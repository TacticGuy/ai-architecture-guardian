"""Verified integration and file-lineage context for future PR outcomes."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import re
from typing import Any

from src.dataset.future_refactor_labels import is_analysed_python_path
from src.dataset.git_snapshots import (
    CommitPair, GitSnapshotError, changed_file_records, parse_changed_files, verified_boundary,
)
from src.dataset.history_audit import ancestry_masks, git_bytes, read_blobs
from src.dataset.label_protocol import pr_id


HISTORY_VALIDATION_VERSION = 1


def structural_history(output: bytes) -> dict[str, list[dict[str, str | None]]]:
    """Read Git's first-parent A/D/R/C history, consuming path tokens by status.

    No dates or PR titles decide lineage. Full Git history includes direct pushes
    as well as PR merges, so an intervening rename cannot silently hide an outcome.
    """
    fields = output.decode("utf-8", errors="strict").split("\0")
    result = {}
    current = None
    index = 0
    while index < len(fields):
        token = fields[index].lstrip("\n")
        if not token:
            index += 1
            continue
        if re.fullmatch("[0-9a-f]{40}", token):
            current = token
            result[current] = []
            index += 1
            continue
        width = 3 if token.startswith(("R", "C")) else 2
        if current is None or not re.fullmatch("[ADRC][0-9]*", token) or index + width > len(fields):
            raise GitSnapshotError("Malformed structural Git history")
        segment = [token, *fields[index + 1:index + width]]
        result[current].extend(parse_changed_files("\0".join(segment) + "\0"))
        index += width
    return result


class HistoryMatcher:
    """Match only verifiable target-branch history; ambiguous file identities stay unknown."""
    def __init__(self, repository: Path, records: list[dict[str, Any]], settings: dict[str, Any]):
        self.repository = repository
        if git_bytes(repository, "rev-parse", "--is-shallow-repository").strip() != b"false":
            raise GitSnapshotError("Use a non-shallow clone for outcome matching")
        missing = git_bytes(repository, "rev-list", "--objects", "--missing=print", "--all")
        if any(line.startswith(b"?") for line in missing.splitlines()):
            raise GitSnapshotError("Clone has missing source objects; fetch --refetch --no-filter first")
        self.ids = {pr_id(row): index for index, row in enumerate(records)}
        if len(self.ids) != len(records):
            raise ValueError("Duplicate PR IDs in history context")
        shas = [row.get("merge_commit_sha", "") for row in records]
        self.parents, self.masks = ancestry_masks(
            git_bytes(repository, "rev-list", "--topo-order", "--parents", "--all").decode(), shas,
        )
        self.structural = structural_history(git_bytes(
            repository, "log", "--all", "--format=%H", "-z", "--name-status", "--no-ext-diff",
            "--no-textconv", "--diff-merges=first-parent", "--find-renames", "--diff-filter=ADRC",
        ))
        self.records = {}
        self.changes = {}
        self.files = {}
        self.settings = settings
        self._chains = {}
        for source in records:
            identifier = pr_id(source)
            row = {**source, "history_validation_version": None, "history_status": "unverified_boundary"}
            sha = source.get("merge_commit_sha")
            try:
                parents = self.parents.get(sha)
                if parents is None:
                    raise GitSnapshotError("Merge commit is not reachable from the clone")
                status = verified_boundary(parents, source.get("head_ref_sha"), source.get("commit_count"))
                changes = changed_file_records(repository, CommitPair(parents[0], sha))
                self.changes[identifier] = changes
                self.files[identifier] = sorted({path for change in changes
                    for path in (change["before_path"], change["after_path"])
                    if path and is_analysed_python_path(path, settings)})
                if len(changes) != source.get("changed_files"):
                    raise GitSnapshotError("Integrated changed-file count differs from GitHub PR metadata")
                row.update({"history_validation_version": HISTORY_VALIDATION_VERSION,
                            "history_status": "verified", "before_commit_sha": parents[0],
                            "reconstruction_status": status})
            except (GitSnapshotError, ValueError) as exc:
                row["history_error"] = str(exc)
            self.records[identifier] = row

    def _chain(self, sha: str) -> list[str]:
        if sha not in self._chains:
            chain = []
            current = sha
            while current in self.parents:
                chain.append(current)
                parents = self.parents[current]
                if not parents:
                    break
                current = parents[0]
            self._chains[sha] = chain
        return self._chains[sha]

    def match(self, sample: dict, event: dict, sample_files: set[str], event_files: set[str]) -> dict:
        identifier, event_id = pr_id(sample), pr_id(event)
        left, right = self.records[identifier], self.records[event_id]
        # Even an unresolved integration has a known target parent when its
        # commit exists. Use ancestry to exclude unrelated release branches.
        parents = self.parents.get(event.get("merge_commit_sha"), [])
        before = parents[0] if parents else None
        index = self.ids[identifier]
        mask = self.masks.get(before)
        if mask is None or sample.get("merge_commit_sha") not in self.masks:
            return {"status": "unknown_lineage"}
        if not mask & (1 << index):
            return {"status": "unrelated_lineage", "history_evidence": {
                "sample_after_sha": sample["merge_commit_sha"],
                "event_before_sha": before,
                "event_after_sha": event["merge_commit_sha"],
                "history_validation_version": HISTORY_VALIDATION_VERSION,
                "ancestry_verified": True, "same_target_history": False,
            }}
        if left["history_status"] != "verified" or right["history_status"] != "verified":
            return {"status": "unverified_boundary"}
        chain = self._chain(before)
        sha = sample["merge_commit_sha"]
        if sha not in chain:
            return {"status": "nonlinear_file_history"}
        # Start at files surviving this PR. An old name deleted/renamed by the
        # sample is not the identity of a later recreated file at that same name.
        surviving = {change["after_path"] for change in self.changes[identifier]
                     if change["after_path"] in sample_files}
        for commit in chain[:chain.index(sha)]:
            for change in self.structural.get(commit, []):
                paths = {change["before_path"], change["after_path"]}
                if paths & surviving:
                    return {"status": "uncertain_file_identity", "identity_change_commit": commit}
        overlap = sorted(surviving & event_files)
        return {"status": "verified", "matched_python_files": overlap,
                "history_evidence": {"sample_after_sha": sha, "event_before_sha": before,
                                     "event_after_sha": event["merge_commit_sha"],
                                     "sample_boundary": left["reconstruction_status"],
                                     "event_boundary": right["reconstruction_status"],
                                     "history_validation_version": HISTORY_VALIDATION_VERSION,
                                     "same_target_history": True,
                                     "ancestry_verified": True, "file_identity": "unchanged_paths"}}

    def non_executable_reviews(self) -> list[dict[str, Any]]:
        """Certify only exact AST equivalence after removing literal docstrings.

        This does not classify executable edits, even if imports/classes remain
        unchanged. Machine checks are explicitly not human-expert reviews.
        """
        reviews = []
        for identifier, row in self.records.items():
            if row["history_status"] != "verified" or not self.files.get(identifier):
                continue
            changes = [c for c in self.changes[identifier]
                       if any(p and is_analysed_python_path(p, self.settings)
                              for p in (c["before_path"], c["after_path"]))]
            if any(c["status"] != "M" or c["before_path"] != c["after_path"] for c in changes):
                continue
            before, after = row["before_commit_sha"], row["merge_commit_sha"]
            blobs = read_blobs(self.repository, [f"{sha}:{c['before_path']}"
                              for c in changes for sha in (before, after)])
            evidence = []
            for change in changes:
                path = change["before_path"]
                left = executable_ast(blobs[f"{before}:{path}"])
                right = executable_ast(blobs[f"{after}:{path}"])
                if left is None or left != right:
                    break
                evidence.append({"path": path, "executable_ast_sha256": hashlib.sha256(left.encode()).hexdigest()})
            else:
                reviews.append({"sample_id": identifier, "merge_commit_sha": after,
                    "decision": "non_architectural", "reviewer": "automated-executable-ast-equivalence-v1",
                    "review_kind": "machine_check_not_human_expert",
                    "rationale": "All changed production Python sources have identical executable ASTs after literal docstrings are removed. No executable restructuring inferred.",
                    "evidence_refs": [f"https://github.com/{row['repo']}/commit/{after}"],
                    "machine_evidence": evidence})
        return reviews


def executable_ast(source: bytes) -> str | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeError, ValueError):
        return None
    tree = deepcopy(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                node.body = body[1:]
    return ast.dump(tree, include_attributes=False)
