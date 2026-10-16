"""Read-only Git evidence audit. Findings are not architecture/risk labels.

The first-parent diff is provisional when integration boundaries are ambiguous.
No checkout, repository source execution, graph-schema change or label writing
is performed here. AST import statements are evidence, not resolved graph edges.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
import subprocess
from typing import Any, Callable

from src.dataset.future_refactor_labels import (
    add_calendar_months, is_analysed_python_path, parse_timestamp,
)
from src.dataset.git_snapshots import GitSnapshotError, _validated_sha
from src.dataset.label_protocol import pr_id


def git_bytes(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments], capture_output=True,
        check=False, timeout=60,
    )
    if result.returncode:
        raise GitSnapshotError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def parse_changes(output: bytes) -> list[dict[str, str | None]]:
    """Parse Git's NUL-delimited name/status output including both rename paths."""
    fields = output.decode("utf-8", errors="strict").split("\0")
    if fields[-1] == "":
        fields.pop()
    changes = []
    index = 0
    while index < len(fields):
        status = fields[index]
        width = 3 if status.startswith(("R", "C")) else 2
        if not status or status[0] not in "ACDMRTUXB" or index + width > len(fields):
            raise ValueError("Malformed Git name/status output")
        first = fields[index + 1]
        second = fields[index + 2] if width == 3 else first
        changes.append({
            "status": status,
            "before_path": None if status.startswith("A") else first,
            "after_path": None if status.startswith("D") else second,
        })
        index += width
    return changes


def read_blobs(repository: Path, specifications: list[str]) -> dict[str, bytes]:
    """Read one PR's blobs in one Git process, with NUL-safe input paths."""
    if not specifications:
        return {}
    unique = list(dict.fromkeys(specifications))
    result = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "--batch", "-z"],
        input=("\0".join(unique) + "\0").encode("utf-8"),
        capture_output=True, check=False, timeout=60,
    )
    if result.returncode:
        raise GitSnapshotError(result.stderr.decode("utf-8", errors="replace"))
    output = result.stdout
    offset = 0
    blobs = {}
    for specification in unique:
        newline = output.find(b"\n", offset)
        header = output[offset:newline].split()
        if newline < 0 or len(header) != 3 or header[1] != b"blob":
            raise GitSnapshotError(f"Unable to read source blob: {specification}")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise GitSnapshotError("Invalid Git blob length") from exc
        start, stop = newline + 1, newline + 1 + size
        if size < 0 or output[stop:stop + 1] != b"\n":
            raise GitSnapshotError("Truncated Git blob output")
        blobs[specification] = output[start:stop]
        offset = stop + 1
    if offset != len(output):
        raise GitSnapshotError("Unexpected trailing Git blob output")
    return blobs


def source_facts(source: bytes) -> dict[str, Any]:
    """Parse source bytes (respecting encoding cookies), never import the code."""
    if len(source) > 512 * 1024:
        return {"status": "source_too_large"}
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeError, ValueError) as exc:
        return {"status": "parse_error", "error": f"{type(exc).__name__}: {exc}"}
    imports = sorted({ast.unparse(node) for node in ast.walk(tree)
                      if isinstance(node, (ast.Import, ast.ImportFrom))})
    declarations = []

    def visit(node: ast.AST, scope: tuple[str, ...] = ()) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = (*scope, child.name)
                declarations.append(".".join(name))
                visit(child, name)
            else:
                visit(child, scope)

    visit(tree)
    return {"status": "parsed", "imports": imports, "declarations": sorted(declarations)}


def syntax_delta(before: bytes | None, after: bytes | None) -> dict[str, Any]:
    empty = {"status": "absent", "imports": [], "declarations": []}
    left = source_facts(before) if before is not None else empty
    right = source_facts(after) if after is not None else empty
    result = {"before_status": left["status"], "after_status": right["status"]}
    if left["status"] not in {"parsed", "absent"} or right["status"] not in {"parsed", "absent"}:
        result["status"] = "unresolved"
        result["errors"] = [item.get("error", item["status"]) for item in (left, right)
                            if item["status"] not in {"parsed", "absent"}]
        return result
    result["status"] = "compared"
    for field in ("imports", "declarations"):
        result[f"added_{field}"] = sorted(set(right[field]) - set(left[field]))
        result[f"removed_{field}"] = sorted(set(left[field]) - set(right[field]))
    return result


def reconstruction_status(parents: list[str], head: object, count: object) -> str:
    """Do not infer squash vs multi-commit rebase from one parent or PR titles."""
    if len(parents) == 2 and isinstance(head, str) and parents[1] == head.lower():
        return "merge_head_verified"
    if len(parents) == 1 and type(count) is int and count == 1:
        return "single_commit_boundary"
    if len(parents) == 1:
        return "ambiguous_squash_or_rebase"
    if not parents:
        return "missing_parent"
    return "merge_head_needs_verification"


def ancestry_masks(parent_lines: str, sample_shas: list[str]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Topological DAG reachability, using PR-index bits rather than branch names."""
    parents = {}
    for line in parent_lines.splitlines():
        fields = line.split()
        if fields:
            parents[fields[0]] = fields[1:]
    own = {}
    for index, sha in enumerate(sample_shas):
        own[sha] = own.get(sha, 0) | (1 << index)
    masks = {}
    # rev-list --topo-order lists children before their parents.
    for sha, ancestors in reversed(list(parents.items())):
        mask = own.get(sha, 0)
        for ancestor in ancestors:
            if ancestor not in masks:
                raise GitSnapshotError("Incomplete or non-topological Git ancestry")
            mask |= masks[ancestor]
        masks[sha] = mask
    return parents, masks


def overlap_audit(rows: list[dict[str, Any]], masks: dict[str, int]) -> dict[str, Any]:
    """Compare naive six-month path matches with actual commit ancestry.

    These are potential matches between arbitrary changes, not refactor events.
    Renames are included as paths but tracking identities through later renames
    remains unresolved; path overlap alone must not certify negative outcomes.
    """
    totals = Counter()
    for key in ("date_and_path_pairs", "ancestor_pairs", "unrelated_lineage_pairs",
                "ancestry_unknown_pairs", "different_branch_but_ancestor_pairs"):
        totals[key] = 0
    examples = {"unrelated_lineage": [], "different_branch_but_ancestor": []}
    for index, sample in enumerate(rows):
        start = parse_timestamp(sample.get("merged_at"))
        if start is None or not sample.get("production_python_files"):
            continue
        end = add_calendar_months(start, 6)
        files = set(sample["production_python_files"])
        for event in rows:
            timestamp = parse_timestamp(event.get("merged_at"))
            if timestamp is None or not start < timestamp <= end:
                continue
            overlap = sorted(files.intersection(event.get("production_python_files", [])))
            if not overlap:
                continue
            totals["date_and_path_pairs"] += 1
            different = sample.get("base_ref_name") != event.get("base_ref_name")
            mask = masks.get(event.get("after_sha"))
            if mask is None or sample.get("after_sha") not in masks:
                totals["ancestry_unknown_pairs"] += 1
                continue
            ancestor = bool(mask & (1 << index))
            key = "ancestor_pairs" if ancestor else "unrelated_lineage_pairs"
            totals[key] += 1
            kind = "different_branch_but_ancestor" if ancestor and different else (
                "unrelated_lineage" if not ancestor else None
            )
            if kind:
                if kind == "different_branch_but_ancestor":
                    totals["different_branch_but_ancestor_pairs"] += 1
                if len(examples[kind]) < 5:
                    examples[kind].append({"sample_id": sample["sample_id"],
                                           "later_pr": event["sample_id"],
                                           "branches": [sample.get("base_ref_name"), event.get("base_ref_name")],
                                           "overlap": overlap})
    return {"counts": dict(totals), "examples": examples,
            "warning": "Potential change pairs only; no reviewed refactor or risk labels assigned."}


def audit_repository(
    repository: Path, records: list[dict[str, Any]], settings: dict[str, Any],
    observation_end: str, progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ids = [pr_id(row) for row in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate PR IDs: audit requires a unique collection")
    if len({row.get("repo") for row in records}) != 1:
        raise ValueError("Audit one repository at a time")
    end = parse_timestamp(observation_end)
    if end is None:
        raise ValueError("Audit requires timezone-aware observation end")
    shallow = git_bytes(repository, "rev-parse", "--is-shallow-repository").strip() == b"true"
    if shallow:
        raise GitSnapshotError("Shallow clone: ancestry cannot be certified")
    # A non-shallow clone may still be blob-filtered. Detect missing contents
    # locally rather than triggering hundreds of hidden lazy network fetches.
    missing = [line for line in git_bytes(
        repository, "rev-list", "--objects", "--missing=print", "--all",
    ).decode("utf-8", errors="replace").splitlines() if line.startswith("?")]
    if missing:
        raise GitSnapshotError(
            f"Clone lacks {len(missing)} reachable objects. Download historical contents "
            "before auditing (git fetch --refetch --no-filter origin). No labels produced."
        )
    shas = [_validated_sha(row.get("merge_commit_sha")) for row in records]
    parents, masks = ancestry_masks(
        git_bytes(repository, "rev-list", "--topo-order", "--parents", "--all").decode(), shas,
    )
    main = set(git_bytes(repository, "rev-list", "--first-parent", "HEAD").decode().splitlines())
    original_head = git_bytes(repository, "rev-parse", "HEAD").decode().strip()
    rows = []
    for number, (source, sha) in enumerate(zip(records, shas), 1):
        row = {key: source.get(key) for key in (
            "repo", "pr_number", "title", "merged_at", "base_ref_name", "commit_count", "url",
        )}
        merged_at = parse_timestamp(source.get("merged_at"))
        row.update({"sample_id": pr_id(source), "after_sha": sha, "label": None,
                    "on_checkout_first_parent": sha in main,
                    "full_followup_by_date": merged_at is not None and add_calendar_months(merged_at, 6) <= end})
        try:
            if sha not in parents:
                raise GitSnapshotError("Merge SHA not reachable from cloned refs; verify/fetch before use")
            preceding = parents[sha]
            status = reconstruction_status(preceding, source.get("head_ref_sha"), source.get("commit_count"))
            row["reconstruction_status"] = status
            if not preceding:
                raise GitSnapshotError("No first parent")
            before = preceding[0]
            row["before_sha"] = before
            row["diff_is_provisional"] = status not in {"merge_head_verified", "single_commit_boundary"}
            changes = parse_changes(git_bytes(
                repository, "diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z",
                "--find-renames", before, sha, "--",
            ))
            row["git_changed_file_count"] = len(changes)
            row["github_changed_file_count"] = source.get("changed_files")
            row["file_count_matches_metadata"] = len(changes) == source.get("changed_files")
            production = []
            all_paths = set()
            eligible_changes = []
            specifications = []
            for change in changes:
                paths = [p for p in (change["before_path"], change["after_path"]) if p]
                eligible = [p for p in paths if is_analysed_python_path(p, settings)]
                if not eligible:
                    continue
                all_paths.update(eligible)
                eligible_changes.append(change)
                old, new = change["before_path"], change["after_path"]
                if old and old.endswith(".py"):
                    specifications.append(f"{before}:{old}")
                if new and new.endswith(".py"):
                    specifications.append(f"{sha}:{new}")
            blobs = read_blobs(repository, specifications)
            for change in eligible_changes:
                old, new = change["before_path"], change["after_path"]
                left = blobs[f"{before}:{old}"] if old and old.endswith(".py") else None
                right = blobs[f"{sha}:{new}"] if new and new.endswith(".py") else None
                production.append({**change, "syntax": syntax_delta(left, right)})
            row["production_python_files"] = sorted(all_paths)
            row["production_changes"] = production
            row["status"] = "audited"
        except (GitSnapshotError, ValueError, subprocess.TimeoutExpired) as exc:
            row["status"] = "git_or_evidence_error"
            row["error"] = str(exc)
        rows.append(row)
        if progress and number % 25 == 0:
            progress(number, len(records))
    if git_bytes(repository, "rev-parse", "HEAD").decode().strip() != original_head:
        raise GitSnapshotError("Checkout changed during audit")
    counts = Counter(row["status"] for row in rows)
    usable = [row for row in rows if row["status"] == "audited"]
    structural = lambda row: any(
        change["status"].startswith(("A", "D", "R", "C"))
        or change["syntax"].get("added_imports") or change["syntax"].get("removed_imports")
        or change["syntax"].get("added_declarations") or change["syntax"].get("removed_declarations")
        for change in row.get("production_changes", [])
    )
    summary = {
        "schema_version": 1, "repo": records[0].get("repo") if records else None,
        "checkout_head": original_head, "records": len(rows), "statuses": dict(counts),
        "production_python_prs": sum(bool(row.get("production_python_files")) for row in usable),
        "reconstruction_statuses": dict(Counter(row["reconstruction_status"] for row in usable)),
        "file_count_mismatches": sum(not row["file_count_matches_metadata"] for row in usable),
        "production_prs_with_deletions": sum(any(c["status"].startswith("D") for c in row["production_changes"]) for row in usable),
        "production_prs_with_renames": sum(any(c["status"].startswith("R") for c in row["production_changes"]) for row in usable),
        "production_prs_with_parse_errors": sum(any(c["syntax"]["status"] == "unresolved" for c in row["production_changes"]) for row in usable),
        "production_full_followup_prs": sum(bool(row["production_python_files"]) and row["full_followup_by_date"] for row in usable),
        "production_full_followup_basic_checks_passed": sum(
            bool(row["production_python_files"]) and row["full_followup_by_date"]
            and not row["diff_is_provisional"] and row["file_count_matches_metadata"]
            for row in usable
        ),
        "diff_review_candidates": [row["sample_id"] for row in usable if structural(row)],
        "overlap_audit": overlap_audit(rows, masks),
        "warning": "No training labels. Structural changes are review evidence, not proof of refactoring, risk or causation.",
    }
    return rows, summary
