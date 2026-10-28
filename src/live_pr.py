"""Prepare and score one public GitHub pull request without creating a training label."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import torch

from src.analysis.pipeline import analyse_repository
from src.dataset.git_snapshots import CommitPair, changed_python_files, detached_snapshot, write_python_diff
from src.fusion.model import FusionModel
from src.ml.gnn_data import attach_touched_masks
from src.ml.gnn_inference import load_gnn_checkpoint, load_gnn_model, prepare_graph
from src.ml.hetero_data import build_hetero_data, save_hetero_data
from src.semantic.diff_encoder import DiffEncoder, EncoderSettings, graph_includes_path
from src.xai.explain import branch_contributions, explain_pr
from src.utils.config import load_settings


_PR_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?$")


class LivePRError(RuntimeError):
    """A live PR could not be prepared or scored safely."""


@dataclass(frozen=True)
class PRReference:
    owner: str
    repo: str
    number: int

    @property
    def sample_id(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


def parse_pr_url(url: str) -> PRReference:
    """Accept only canonical public github.com pull-request URLs."""
    match = _PR_URL.fullmatch(url.strip())
    if not match:
        raise LivePRError("Expected https://github.com/OWNER/REPO/pull/NUMBER")
    return PRReference(match.group(1), match.group(2), int(match.group(3)))


def fetch_pr(reference: PRReference, token: str | None = None,
             opener: Callable[..., Any] = urlopen) -> dict[str, Any]:
    """Read authoritative base/head SHAs and display metadata from GitHub's REST API."""
    endpoint = f"https://api.github.com/repos/{reference.owner}/{reference.repo}/pulls/{reference.number}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-architecture-guardian-live-demo"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with opener(Request(endpoint, headers=headers), timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise LivePRError(f"GitHub API returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LivePRError(f"Could not read the GitHub PR: {exc}") from exc
    base = payload.get("base") or {}
    head = payload.get("head") or {}
    base_repo = base.get("repo") or {}
    if not all(isinstance(value, str) and value for value in
               (base.get("sha"), head.get("sha"), base_repo.get("clone_url"))):
        raise LivePRError("GitHub response lacks the base SHA, head SHA, or clone URL")
    merge_commit_sha = payload.get("merge_commit_sha")
    return {
        "sample_id": reference.sample_id,
        "repo": f"{reference.owner}/{reference.repo}",
        "pr_number": reference.number,
        "url": payload.get("html_url"),
        "title": payload.get("title"),
        "state": payload.get("state"),
        "draft": bool(payload.get("draft")),
        "merged": bool(payload.get("merged")),
        "merge_commit_sha": merge_commit_sha.lower() if isinstance(merge_commit_sha, str) else None,
        "commit_count": payload.get("commits") if type(payload.get("commits")) is int else None,
        "base_ref": base.get("ref") or "main",
        "base_sha": base["sha"].lower(),
        "head_sha": head["sha"].lower(),
        "clone_url": base_repo["clone_url"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def prepare_repository(pr: dict[str, Any], reference: PRReference, cache: Path,
                       repository_path: Path | None = None) -> Path:
    """Choose the before/after commits for the PR's state and record how they were chosen.

    open, merge ref exists      GitHub's test merge (mode "open_test_merge")
    open, no merge ref          a local merge of head into the base branch ("open_local_merge");
                                conflicts raise LivePRError
    merged                      the real merge/squash/rebase commit on the base branch ("merged_pr")
    closed without merging      head against its merge-base with the base branch ("closed_unmerged")
    Sets pr["analysis_base_sha"], pr["analysis_after_sha"] and pr["mode"].
    """
    repository = repository_path.resolve() if repository_path else cache.resolve()
    if repository_path is None and not (repository / ".git").is_dir():
        repository.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--filter=blob:none", "--no-checkout", pr["clone_url"], str(repository)])
    if not repository.is_dir() or not (repository / ".git").is_dir():
        raise LivePRError(f"Not a normal Git clone: {repository}")
    git = _Git(repository)
    base_ref = f"refs/remotes/origin/live-base-{reference.number}"
    head_ref = f"refs/remotes/origin/live-head-{reference.number}"
    git("fetch", "--no-tags", "origin", f"+refs/heads/{pr['base_ref']}:{base_ref}")
    git("fetch", "--no-tags", "origin", f"+refs/pull/{reference.number}/head:{head_ref}")
    if git.sha(head_ref) != pr["head_sha"]:
        raise LivePRError("GitHub's PR head ref does not match the API head revision; retry in a minute")
    if pr.get("merged"):
        _prepare_merged(pr, git, base_ref)
    elif pr.get("state") == "closed":
        _prepare_closed_unmerged(pr, git, base_ref)
    elif git("ls-remote", "origin", f"refs/pull/{reference.number}/merge").strip():
        _prepare_test_merge(pr, git, reference.number)
    else:
        _prepare_local_merge(pr, git, base_ref, reference.number)
    for sha in (pr["analysis_base_sha"], pr["analysis_after_sha"]):
        git("cat-file", "-e", f"{sha}^{{commit}}")
    return repository


def _prepare_test_merge(pr: dict[str, Any], git: _Git, number: int) -> None:
    merge_ref = f"refs/remotes/origin/live-merge-{number}"
    git("fetch", "--no-tags", "origin", f"+refs/pull/{number}/merge:{merge_ref}")
    fields = git.parents(merge_ref)
    if len(fields) != 3:
        raise LivePRError("GitHub PR test merge does not have the expected base and head parents")
    merge_sha, base_parent, head_parent = fields
    if head_parent != pr["head_sha"]:
        raise LivePRError("GitHub's test merge is older than the PR head; GitHub is still recomputing it, "
                          "retry in a minute")
    # GitHub builds the test merge against the base branch as it was when it last computed it.
    # The API's base.sha can be newer; the merge commit's own first parent is the honest base.
    if base_parent != pr["base_sha"]:
        pr["api_base_sha"] = pr["base_sha"]
        pr["test_merge_base_sha"] = base_parent
        pr["base_note"] = "GitHub test merge was computed against an older base"
    pr.update(mode="open_test_merge", analysis_base_sha=base_parent, analysis_after_sha=merge_sha)


def _prepare_merged(pr: dict[str, Any], git: _Git, base_ref: str) -> None:
    merge_sha = pr.get("merge_commit_sha")
    if not merge_sha:
        raise LivePRError("GitHub says the PR is merged but gives no merge commit")
    if not git.ok("cat-file", "-e", f"{merge_sha}^{{commit}}") or \
            not git.ok("merge-base", "--is-ancestor", merge_sha, base_ref):
        raise LivePRError(f"Merge commit {merge_sha[:12]} is not on the base branch {pr['base_ref']}")
    fields = git.parents(merge_sha)
    if len(fields) == 3:
        if fields[2] != pr["head_sha"]:
            raise LivePRError("The merge commit's second parent is not the PR head")
        method, before = "merge", fields[1]
    elif len(fields) == 2:
        # A rebase merge keeps each commit's author and author date; a squash commit gets new ones.
        if git.author(merge_sha) == git.author(pr["head_sha"]) and (pr.get("commit_count") or 1) > 1:
            count = pr["commit_count"]
            chain = git("rev-list", "--first-parent", "--parents", f"-n{count}", merge_sha).splitlines()
            if len(chain) != count or any(len(line.split()) != 2 for line in chain):
                raise LivePRError("Could not walk back over the rebased PR commits")
            method, before = "rebase", chain[-1].split()[1]
        else:
            method, before = "squash", fields[1]
    else:
        raise LivePRError("The merge commit has an unexpected number of parents")
    pr.update(mode="merged_pr", merge_method=method, analysis_base_sha=before, analysis_after_sha=merge_sha)


def _prepare_closed_unmerged(pr: dict[str, Any], git: _Git, base_ref: str) -> None:
    before = git("merge-base", base_ref, pr["head_sha"]).strip().lower()
    if not before:
        raise LivePRError("The PR head shares no history with the base branch")
    pr.update(mode="closed_unmerged", analysis_base_sha=before, analysis_after_sha=pr["head_sha"],
              mode_warning="This PR was closed without merging; it is analysed as its head against its "
                           "merge-base with the base branch.")


def _prepare_local_merge(pr: dict[str, Any], git: _Git, base_ref: str, number: int) -> None:
    """GitHub has no test merge (usually conflicts): try the merge locally, never guess."""
    base_tip = git.sha(base_ref)
    worktree = Path(tempfile.mkdtemp(prefix="live-merge-")) / "tree"
    git("worktree", "add", "--detach", str(worktree), base_tip)
    try:
        inside = _Git(worktree)
        if not inside.ok("-c", "user.name=AI Guardian", "-c", "user.email=live@ai-guardian.invalid",
                         "merge", "--no-commit", "--no-ff", pr["head_sha"]):
            inside.ok("merge", "--abort")
            raise LivePRError(f"This PR has merge conflicts with {pr['base_ref']}; GitHub cannot build a "
                              "pre-merge state, so it cannot be analysed until the conflicts are resolved.")
        # Fixed identity and the head's date make the merge commit (and so its SHA) reproducible.
        date = git("log", "-1", "--format=%cI", pr["head_sha"]).strip()
        inside("-c", "user.name=AI Guardian", "-c", "user.email=live@ai-guardian.invalid", "commit",
               "--no-verify", "-m", f"Local test merge of PR #{number}",
               env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
        merge_sha = inside.sha("HEAD")
        git("update-ref", f"refs/live/merge-{number}", merge_sha)
    finally:
        git.ok("worktree", "remove", "--force", str(worktree))
        shutil.rmtree(worktree.parent, ignore_errors=True)
        git.ok("worktree", "prune")
    if base_tip != pr["base_sha"]:
        pr["api_base_sha"] = pr["base_sha"]
    pr.update(mode="open_local_merge", analysis_base_sha=base_tip, analysis_after_sha=merge_sha,
              base_note="GitHub had no test merge; the PR head was merged into the base branch locally")


def prepare_live_sample(pr: dict[str, Any], repository: Path, output_root: Path,
                        analysis_settings: dict[str, Any]) -> dict[str, Any]:
    """Reuse locked Steps 2-5 on the PR base and save an explicitly unlabeled sample."""
    pair = CommitPair(pr["analysis_base_sha"], pr["analysis_after_sha"])
    all_python = changed_python_files(repository, pair)
    analysed = [path for path in all_python if graph_includes_path(path, analysis_settings)]
    if not analysed:
        raise LivePRError("PR changes no production Python files analysed by the graph pipeline")
    sample_dir = output_root / pr["repo"].replace("/", "__") / str(pr["pr_number"])
    if sample_dir.exists():
        metadata_path = sample_dir / "metadata.json"
        existing = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        if (existing.get("head_commit_sha") == pr["head_sha"]
                and existing.get("integration_commit_sha") == pr["analysis_after_sha"]
                and existing.get("before_commit_sha") == pr["analysis_base_sha"]
                and (sample_dir / "before/graph.pt").is_file()):
            return existing
        raise LivePRError(f"Live sample already exists for another PR revision: {sample_dir}")
    staging_root = output_root / ".staging" / uuid4().hex
    staging = staging_root / "sample"
    staging.mkdir(parents=True)
    try:
        write_python_diff(repository, pair, staging / "diff.patch")
        worktree = output_root / ".worktrees" / uuid4().hex / "before"
        with detached_snapshot(repository, pair.before_sha, worktree) as snapshot:
            analysis = analyse_repository(snapshot, staging / "before", analysis_settings)
        graph = attach_touched_masks(build_hetero_data(analysis["graph"], analysis["features"]), analysed)
        touched = sum(int(graph[node_type].touched_mask.sum()) for node_type in graph.node_types)
        if touched == 0:
            raise LivePRError("No changed file exists in the base graph; choose a PR modifying existing Python files")
        save_hetero_data(graph, staging / "before/graph.pt")
        metadata = {**pr, "schema_version": 1, "label": None, "split": "live_unlabelled",
                    "before_commit_sha": pair.before_sha, "head_commit_sha": pr["head_sha"],
                    "integration_commit_sha": pair.after_sha,
                    "changed_python_files": analysed, "all_changed_python_files": all_python,
                    "diff_path": "diff.patch", "before_graph_path": "before/graph.pt",
                    "touched_node_count": touched,
                    "note": "Live inference only; no historical outcome label is assigned."}
        _write_json(staging / "metadata.json", metadata)
        sample_dir.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(sample_dir)
        return metadata
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def score_live_sample(sample_dir: Path, manifest_path: Path, diff_store_path: Path,
                      fusion_path: Path, *, device: str = "cpu", max_hunks: int = 0,
                      encoder_factory: Callable[..., DiffEncoder] | None = None,
                      analysis_settings: dict[str, Any]) -> dict[str, Any]:
    """Run V4 GNN + CodeReviewer + fusion on one unlabeled prepared sample."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint_path = manifest_path.parent / manifest["checkpoint_name"]
    checkpoint = load_gnn_checkpoint(checkpoint_path)
    target = "cuda" if device == "auto" and torch.cuda.is_available() else ("cpu" if device == "auto" else device)
    gnn = load_gnn_model(checkpoint, target)
    graph, dropped_types = _fit_to_checkpoint_schema(prepare_graph(sample_dir / "before/graph.pt", checkpoint),
                                                     checkpoint)
    graph = graph.to(target)
    with torch.no_grad():
        gnn_vector = gnn.encode(graph).cpu().float()
        gnn_probability = float(torch.sigmoid(gnn(graph)).cpu().item())

    store = torch.load(diff_store_path, map_location="cpu", weights_only=True)
    saved_settings = store["encoder"]
    settings = EncoderSettings(max_tokens=int(saved_settings["max_tokens"]),
                               stride=int(saved_settings["stride"]),
                               max_chunks=int(saved_settings["max_chunks"]),
                               graph_files_only=bool(saved_settings["graph_files_only"]))
    if encoder_factory is None:
        # The encoder intentionally tokenizes the full diff before applying its own
        # overlapping 512-token windows. Silence Hugging Face's misleading warning
        # that the unwindowed token count would overflow a model call.
        from transformers.utils import logging as transformers_logging
        transformers_logging.set_verbosity_error()
    encoder = (encoder_factory or DiffEncoder.from_pretrained)(saved_settings["model_name"], settings, target)
    if encoder.describe() != saved_settings:
        raise LivePRError("Live CodeReviewer settings do not match the V4 training embeddings")
    diff_text = (sample_dir / "diff.patch").read_text(encoding="utf-8", errors="replace")
    encoded = encoder.encode_diff(diff_text, analysis_settings, allow_fallback=False)
    diff_vector = encoded.vector.reshape(1, -1)

    saved_fusion = torch.load(fusion_path, map_location="cpu", weights_only=True)
    fusion = FusionModel.from_state(saved_fusion["models"][saved_fusion["main"]])
    matrices = {"gnn": gnn_vector, "diff": diff_vector}
    probability = float(fusion.predict_proba(matrices)[0])
    contributions = branch_contributions(fusion, gnn_vector, diff_vector)
    result: dict[str, Any] = {
        "risk_probability": probability,
        "risk_percent": round(probability * 100, 2),
        "threshold": fusion.threshold,
        "prediction": int(probability >= fusion.threshold),
        "classification": "high_risk" if probability >= fusion.threshold else "low_risk",
        "gnn_probability": gnn_probability,
        "contributions": contributions,
        "diff": {"num_tokens": encoded.num_tokens, "num_chunks": encoded.num_chunks,
                 "truncated": encoded.truncated, "files_used": encoded.files_used,
                 "files_dropped": encoded.files_dropped},
    }
    if dropped_types:
        result["schema_note"] = ("The graph builder now adds " + ", ".join(dropped_types) + ", which this model "
                                 "was not trained on; they were removed before scoring.")
    if max_hunks:
        result["xai"] = explain_pr(model=fusion, encoder=encoder, analysis_settings=analysis_settings,
                                   diff_text=diff_text, gnn=gnn_vector, stored_diff=diff_vector,
                                   max_hunks=max_hunks)
    result["warning"] = "Prediction for review prioritisation, not proof that the PR causes future debt."
    return result


def _fit_to_checkpoint_schema(graph: Any, checkpoint: dict[str, Any]) -> tuple[Any, list[str]]:
    """Remove node and edge types the checkpoint was not trained on (e.g. v5's global_variable).

    A model only has weights for the relations in its metadata; anything else would crash
    the forward pass. Returns the graph and the sorted names of what was removed.
    """
    node_types, edge_types = checkpoint["metadata"]
    known_nodes, known_edges = set(node_types), {tuple(edge) for edge in edge_types}
    known_relations = {edge[1] for edge in known_edges}
    dropped = set()
    for edge_type in list(graph.edge_types):
        if tuple(edge_type) not in known_edges:
            del graph[edge_type]
            if edge_type[1] not in known_relations:
                dropped.add(edge_type[1])
    for node_type in list(graph.node_types):
        if node_type not in known_nodes:
            del graph[node_type]
            dropped.add(node_type)
    return graph, sorted(dropped)


def analyze_live_pr(url: str, root: Path, *, manifest_path: Path | None = None,
                    output_root: Path | None = None, repository_path: Path | None = None,
                    token: str | None = None, device: str = "cpu", max_hunks: int = 0,
                    encoder_factory: Callable[..., DiffEncoder] | None = None) -> tuple[dict[str, Any], Path]:
    """Run the complete live adapter and return its unlabeled report and saved path."""
    reference = parse_pr_url(url)
    manifest_path = manifest_path or root / "artifacts/gnn_embeddings_v4.json"
    output_root = output_root or root / "data/live"
    pr = fetch_pr(reference, token)
    version = manifest_path.stem.rsplit("_", 1)[-1]
    diff_store = root / "data/embeddings" / f"microsoft__codereviewer__{manifest_path.stem}" / "embeddings.pt"
    fusion_path = root / "data/fusion" / version / "fusion_model.pt"
    checkpoint_name = json.loads(manifest_path.read_text(encoding="utf-8")).get("checkpoint_name") \
        if manifest_path.is_file() else None
    required = [("manifest", manifest_path), ("CodeReviewer store", diff_store),
                ("fusion model", fusion_path)]
    if isinstance(checkpoint_name, str):
        required.append(("GNN checkpoint", manifest_path.parent / checkpoint_name))
    for name, path in required:
        if not path.is_file():
            raise LivePRError(f"Missing {name}: {path}")
    settings = load_settings(root / "config/settings.json")["static_analysis"]
    cache = output_root / ".repositories" / f"{reference.owner}__{reference.repo}"
    repository = prepare_repository(pr, reference, cache, repository_path)
    metadata = prepare_live_sample(pr, repository, output_root, settings)
    sample_dir = output_root / pr["repo"].replace("/", "__") / str(pr["pr_number"])
    result = score_live_sample(sample_dir, manifest_path, diff_store, fusion_path, device=device,
                               max_hunks=max_hunks, encoder_factory=encoder_factory,
                               analysis_settings=settings)
    report = {"schema_version": 1, "sample_id": metadata["sample_id"], "url": metadata["url"],
              "title": metadata["title"], "state": metadata["state"], "label": None,
              "split": "live_unlabelled", "mode": metadata.get("mode"),
              "before_commit_sha": metadata["before_commit_sha"],
              "integration_commit_sha": metadata["integration_commit_sha"],
              **{key: metadata[key] for key in ("merge_method", "base_note", "api_base_sha", "mode_warning")
                 if key in metadata},
              **result}
    result_path = sample_dir / "live_result.json"
    _write_json(result_path, report)
    return report, result_path


def _run(arguments: list[str], env: dict[str, str] | None = None) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            env={**os.environ, **env} if env else None)
    if result.returncode:
        shown = [argument for argument in arguments if argument != "-C"][:4]
        raise LivePRError(f"{' '.join(shown)} failed: {result.stderr.strip()}")
    return result.stdout


class _Git:
    """``git -C <repository>`` with small helpers; every SHA it returns is lower case."""

    def __init__(self, repository: Path):
        self.repository = repository

    def __call__(self, *arguments: str, env: dict[str, str] | None = None) -> str:
        return _run(["git", "-C", str(self.repository), *arguments], env)

    def ok(self, *arguments: str) -> bool:
        try:
            self(*arguments)
            return True
        except LivePRError:
            return False

    def sha(self, revision: str) -> str:
        return self("rev-parse", "--verify", f"{revision}^{{commit}}").strip().lower()

    def parents(self, revision: str) -> list[str]:
        return self("rev-list", "--parents", "-n", "1", revision).lower().split()

    def author(self, revision: str) -> str:
        return self("log", "-1", "--format=%ae %aI", revision).strip()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
