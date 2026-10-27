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
                timeout: int = 900) -> str:
    """Scan ``folder`` with the Docker scanner and return the Compute Engine task id."""
    command = ["docker", "run", "--rm", "-e", f"SONAR_HOST_URL={host_url}", "-e", "SONAR_TOKEN",
               "-v", f"{folder.resolve()}:/usr/src", image,
               f"-Dsonar.projectKey={key}", "-Dsonar.sources=.", "-Dsonar.python.version=3",
               "-Dsonar.scm.disabled=true", "-Dsonar.sourceEncoding=UTF-8"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, "SONAR_TOKEN": token})
    if result.returncode:
        raise SonarError(f"sonar-scanner failed for {key}: {result.stdout[-400:]}{result.stderr[-400:]}")
    report = folder / ".scannerwork" / "report-task.txt"
    for line in report.read_text(encoding="utf-8").splitlines() if report.is_file() else []:
        if line.startswith("ceTaskId="):
            return line.split("=", 1)[1].strip()
    raise SonarError(f"sonar-scanner wrote no task id for {key}")


def scan_side(files: dict[str, str], key: str, client: SonarClient, host_url: str, token: str,
              scanner: Callable[..., str] = run_scanner) -> dict[str, float | None]:
    """Measures for one side. A side with no files (all added/deleted) is zero, not a scan."""
    if not files:
        return {metric: 0.0 for metric in DELTA_METRICS} | {"duplicated_lines_density": None}
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for path, text in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        task = scanner(root, key, host_url, token)
    try:
        client.wait_for_task(task)
        return client.measures(key)
    finally:
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
