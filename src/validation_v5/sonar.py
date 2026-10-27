"""SonarQube Community as a per-PR baseline: scan the touched files before and after, read the measures.

Per PR: write the touched files at each side into a temporary folder (same relative paths),
scan each with ``sonarsource/sonar-scanner-cli`` as its own project, wait for the server to
finish processing, read the measures from the Web API, then delete both projects so the
server stays small. The server and token come from docker/sonarqube/ and .env (SONAR_TOKEN).
"""
from __future__ import annotations

import os
from pathlib import Path
import random
import re
import subprocess
import tempfile
import time
from typing import Any, Callable

import httpx

METRICS = ("code_smells", "cognitive_complexity", "sqale_index", "duplicated_lines_density")
DELTA_METRICS = ("code_smells", "cognitive_complexity", "sqale_index")
SCANNER_IMAGE = "sonarsource/sonar-scanner-cli"


class SonarError(RuntimeError):
    """The scan or the server failed for this PR."""


class SonarClient:
    """The few Web API calls the baseline needs. ``client`` is injectable for tests."""

    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None):
        self.http = client or httpx.Client(base_url=base_url.rstrip("/"), auth=(token, ""), timeout=60)

    def _get(self, path: str, **params: str) -> httpx.Response:
        response = self.http.get(path, params=params)
        if response.status_code != 200:
            raise SonarError(f"GET {path} returned HTTP {response.status_code}: {response.text[:200]}")
        return response

    def server_version(self) -> str:
        return self._get("/api/server/version").text.strip()

    def wait_for_task(self, task_id: str, timeout: float = 600, poll: float = 2,
                      sleep: Callable[[float], None] = time.sleep) -> None:
        """Block until the Compute Engine has processed the scan report."""
        waited = 0.0
        while True:
            status = self._get("/api/ce/task", id=task_id).json()["task"]["status"]
            if status == "SUCCESS":
                return
            if status in {"FAILED", "CANCELED"}:
                raise SonarError(f"SonarQube task {task_id} ended with {status}")
            if waited >= timeout:
                raise SonarError(f"SonarQube task {task_id} still {status} after {timeout:.0f}s")
            sleep(poll)
            waited += poll

    def measures(self, project_key: str) -> dict[str, float | None]:
        payload = self._get("/api/measures/component", component=project_key,
                            metricKeys=",".join(METRICS)).json()
        found = {m["metric"]: float(m["value"]) for m in payload["component"].get("measures", []) if "value" in m}
        return {metric: found.get(metric) for metric in METRICS}

    def delete_project(self, project_key: str) -> None:
        response = self.http.post("/api/projects/delete", data={"project": project_key})
        if response.status_code not in (200, 204, 404):
            raise SonarError(f"Deleting {project_key} returned HTTP {response.status_code}")


def project_key(sample_id: str, side: str) -> str:
    """``pallets/flask#5123`` -> ``v5_pallets_flask_5123_before`` (Sonar keys allow [A-Za-z0-9_.:-])."""
    return f"v5_{re.sub(r'[^A-Za-z0-9]+', '_', sample_id)}_{side}"


def run_scanner(folder: Path, key: str, host_url: str, token: str, image: str = SCANNER_IMAGE,
                timeout: int = 900, extra: tuple[str, ...] = ()) -> str:
    """Scan ``folder`` with the Docker scanner and return the Compute Engine task id."""
    command = ["docker", "run", "--rm", "-e", f"SONAR_HOST_URL={host_url}", "-e", "SONAR_TOKEN",
               "-v", f"{folder.resolve()}:/usr/src", image, *extra,
               f"-Dsonar.projectKey={key}", "-Dsonar.sources=.", "-Dsonar.python.version=3",
               "-Dsonar.scm.disabled=true", "-Dsonar.sourceEncoding=UTF-8"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, "SONAR_TOKEN": token})
    if result.returncode:
        raise SonarError(f"sonar-scanner failed for {key}: {result.stdout[-400:]}{result.stderr[-400:]}")
    task = task_id_from_output(result.stdout + result.stderr)
    report = folder / ".scannerwork" / "report-task.txt"
    if task is None and report.is_file():  # older scanners keep the work folder next to the sources
        task = next((line.split("=", 1)[1].strip() for line in report.read_text(encoding="utf-8").splitlines()
                     if line.startswith("ceTaskId=")), None)
    if task is None:
        raise SonarError(f"sonar-scanner reported no task id for {key}")
    return task


def task_id_from_output(log: str) -> str | None:
    """The Compute Engine task id from the scanner log ("... /api/ce/task?id=<id>").

    Recent scanner images keep their work folder in the container's /tmp, so the log is
    the only place the id survives.
    """
    match = re.search(r"/api/ce/task\?id=([A-Za-z0-9_-]+)", log)
    return match.group(1) if match else None


def scan_side(files: dict[str, str], key: str, client: SonarClient, host_url: str, token: str,
              scanner: Callable[..., str] = run_scanner) -> dict[str, float | None]:
    """Measures for one side. A side with no files (all added/deleted) is zero, not a scan."""
    if not files:
        return {metric: 0.0 for metric in DELTA_METRICS} | {"duplicated_lines_density": None}
    try:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path, text in files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            task = scanner(root, key, host_url, token)
        client.wait_for_task(task)
        return client.measures(key)
    finally:
        # Also after a failed scan: the scanner may have created the project before failing.
        client.delete_project(key)


def sonar_metrics(sample_id: str, before: dict[str, str], after: dict[str, str], client: SonarClient,
                  host_url: str, token: str, scanner: Callable[..., str] = run_scanner) -> dict[str, Any]:
    """The brief's sonar.* keys: after-state measures, after - before deltas, after duplication."""
    old = scan_side(before, project_key(sample_id, "before"), client, host_url, token, scanner)
    new = scan_side(after, project_key(sample_id, "after"), client, host_url, token, scanner)
    row: dict[str, Any] = {f"sonar.{metric}": new[metric] for metric in DELTA_METRICS}
    for metric in DELTA_METRICS:
        row[f"sonar.delta_{metric}"] = (new[metric] - old[metric]
                                        if new[metric] is not None and old[metric] is not None else None)
    row["sonar.duplicated_lines_density"] = new["duplicated_lines_density"]
    return row


def select_sonar_samples(samples: list[dict[str, Any]], limit: int | None, seed: int) -> list[dict[str, Any]]:
    """The test split, or a seeded random subset of it when it does not fit the time budget."""
    test = [sample for sample in samples if sample.get("split") == "test"]
    if limit is None or limit >= len(test):
        return test
    chosen = set(s["sample_id"] for s in random.Random(seed).sample(test, limit))
    return [sample for sample in test if sample["sample_id"] in chosen]


# ---------------------------------------------------------------- batch mode
# Scanner start-up and server processing are paid per scan, not per file, so many PRs share
# one project: one folder per PR (<owner>__<repo>__<number>/<path>), one scan per side.

BATCH_METRICS = ("code_smells", "cognitive_complexity", "sqale_index")
# Duplication off: in a batch it would compare code across unrelated PRs.
BATCH_SCANNER_ARGS = ("-Dsonar.cpd.exclusions=**/*",)
TREE_LIMIT = 10_000  # component_tree cannot page past 10,000 results


def pr_folder(sample_id: str) -> str:
    """``pallets/flask#5123`` -> ``pallets__flask__5123``."""
    repo, number = sample_id.rsplit("#", 1)
    return f"{repo.replace('/', '__')}__{number}"


def write_batch(root: Path, files_by_sample: dict[str, dict[str, str]]) -> set[str]:
    """Write each PR's files under root/<pr folder>/<path>; return the PR folders that got a file."""
    written = set()
    for sample_id, files in files_by_sample.items():
        for path, text in files.items():
            target = root / pr_folder(sample_id) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            written.add(pr_folder(sample_id))
    return written


def read_tree(client: SonarClient, project_key: str) -> dict[str, dict[str, float]]:
    """Per-PR-folder totals of BATCH_METRICS, summed over the folder's files.

    Files, not directories: SonarQube collapses folder chains (``o__r__1/src/pkg`` is one DIR,
    and a PR touching two folders has two DIRs), so summing files by the first path segment is
    the only exact mapping. The three metrics are additive; a file without a value has 0.
    """
    totals: dict[str, dict[str, float]] = {}
    page = 1
    while True:
        payload = client._get("/api/measures/component_tree", component=project_key, qualifiers="FIL",
                              strategy="all", metricKeys=",".join(BATCH_METRICS), ps="500", p=str(page)).json()
        if payload["paging"]["total"] > TREE_LIMIT:
            raise SonarError(f"{project_key} has {payload['paging']['total']} files; use a smaller batch")
        for component in payload["components"]:
            folder = component["path"].replace("\\", "/").split("/", 1)[0]
            row = totals.setdefault(folder, {metric: 0.0 for metric in BATCH_METRICS})
            for measure in component.get("measures", []):
                if measure["metric"] in row and "value" in measure:
                    row[measure["metric"]] += float(measure["value"])
        if page * 500 >= payload["paging"]["total"]:
            return totals
        page += 1


def scan_batch_side(files_by_sample: dict[str, dict[str, str]], key: str, client: SonarClient, host_url: str,
                    token: str, scanner: Callable[..., str] = run_scanner,
                    timeout: int = 3600) -> tuple[set[str], dict[str, dict[str, float]]]:
    """Scan one side of a batch as one project; return (folders written, totals per folder)."""
    try:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            written = write_batch(root, files_by_sample)
            if not written:
                return written, {}
            task = scanner(root, key, host_url, token, timeout=timeout, extra=BATCH_SCANNER_ARGS)
        client.wait_for_task(task, timeout=timeout)
        return written, read_tree(client, key)
    finally:
        client.delete_project(key)


def batch_rows(sample_ids: list[str], before: tuple[set[str], dict], after: tuple[set[str], dict]) -> list[dict[str, Any]]:
    """sonar.<metric> (after) and sonar.delta_<metric> (after - before) per sample_id.

    A side with no files (the PR added or deleted all of them) counts as 0. A side whose files
    were written but that SonarQube returned nothing for is unknown (null), not 0.
    """
    rows = []
    for sample_id in sample_ids:
        folder = pr_folder(sample_id)
        sides = []
        for written, totals in (before, after):
            if folder not in written:
                sides.append({metric: 0.0 for metric in BATCH_METRICS})
            else:
                sides.append(totals.get(folder))
        old, new = sides
        row: dict[str, Any] = {"sample_id": sample_id}
        for metric in BATCH_METRICS:
            row[f"sonar.{metric}"] = new[metric] if new else None
        for metric in BATCH_METRICS:
            row[f"sonar.delta_{metric}"] = new[metric] - old[metric] if new and old else None
        rows.append(row)
    return rows
