"""Prepare and score one public GitHub pull request without creating a training label."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
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
    return {
        "sample_id": reference.sample_id,
        "repo": f"{reference.owner}/{reference.repo}",
        "pr_number": reference.number,
        "url": payload.get("html_url"),
        "title": payload.get("title"),
        "state": payload.get("state"),
        "draft": bool(payload.get("draft")),
        "base_sha": base["sha"].lower(),
        "head_sha": head["sha"].lower(),
        "clone_url": base_repo["clone_url"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def prepare_repository(pr: dict[str, Any], reference: PRReference, cache: Path,
                       repository_path: Path | None = None) -> Path:
    """Fetch GitHub's synthetic merge commit, matching a real pre-merge integration."""
    repository = repository_path.resolve() if repository_path else cache.resolve()
    if repository_path is None and not (repository / ".git").is_dir():
        repository.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--filter=blob:none", "--no-checkout", pr["clone_url"], str(repository)])
    if not repository.is_dir() or not (repository / ".git").is_dir():
        raise LivePRError(f"Not a normal Git clone: {repository}")
    merge_ref = f"refs/remotes/origin/live-merge-{reference.number}"
    _run(["git", "-C", str(repository), "fetch", "--no-tags", "--depth=2", "origin",
          f"+refs/pull/{reference.number}/merge:{merge_ref}"])
    fields = _run(["git", "-C", str(repository), "rev-list", "--parents", "-n", "1", merge_ref]).split()
    if len(fields) != 3:
        raise LivePRError("GitHub PR test merge does not have the expected base and head parents")
    merge_sha, base_parent, head_parent = fields
    if head_parent.lower() != pr["head_sha"]:
        raise LivePRError("GitHub PR test merge head does not match the API head revision")
    if base_parent.lower() != pr["base_sha"]:
        raise LivePRError("GitHub PR test merge base does not match the API base revision")
    pr["analysis_base_sha"] = base_parent.lower()
    pr["analysis_after_sha"] = merge_sha.lower()
    for sha in (pr["analysis_base_sha"], pr["analysis_after_sha"]):
        _run(["git", "-C", str(repository), "cat-file", "-e", f"{sha}^{{commit}}"])
    return repository


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
    graph = prepare_graph(sample_dir / "before/graph.pt", checkpoint).to(target)
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
    if max_hunks:
        result["xai"] = explain_pr(model=fusion, encoder=encoder, analysis_settings=analysis_settings,
                                   diff_text=diff_text, gnn=gnn_vector, stored_diff=diff_vector,
                                   max_hunks=max_hunks)
    result["warning"] = "Prediction for review prioritisation, not proof that the PR causes future debt."
    return result


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
              "split": "live_unlabelled", **result}
    result_path = sample_dir / "live_result.json"
    _write_json(result_path, report)
    return report, result_path


def _run(arguments: list[str]) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise LivePRError(f"{' '.join(arguments[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
