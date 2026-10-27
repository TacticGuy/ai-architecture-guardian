"""radon / pylint / hotspot / SonarQube baselines and the resumable output (no network, no Docker)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest

from src.validation_v5.manifest_dev import is_production_python, module_name, pr_number
from src.validation_v5.sonar import (
    SonarClient, SonarError, batch_rows, pr_folder, project_key, scan_batch_side, scan_side, select_sonar_samples,
    sonar_metrics, task_id_from_output,
)
from src.validation_v5.tool_metrics import (
    change_frequency, compact, done, hotspot_metrics, load_rows, parse_pylint, pylint_metrics,
    radon_metrics, read_side,
)

BEFORE = {"pkg/a.py": "def f(x):\n    return x\n"}
AFTER = {"pkg/a.py": ("def f(x):\n    if x:\n        return 1\n    return 2\n\n\n"
                      "class C:\n    def m(self, y):\n        for i in y:\n            if i:\n                return i\n"
                      "        return None\n")}


def test_radon_after_and_delta_with_known_numbers():
    row = radon_metrics(BEFORE, AFTER)
    # after: f has CC 2, C.m has CC 3 (for + if); methods are not counted twice.
    assert row["radon.mean_cc"] == pytest.approx(2.5)
    assert row["radon.max_cc"] == 3
    assert row["radon.sloc"] == 10
    assert row["radon.delta_mean_cc"] == pytest.approx(1.5)
    assert row["radon.delta_max_cc"] == 2
    assert row["radon.delta_sloc"] == 8
    # radon caps the maintainability index at 100; files this small sit at the cap on both sides.
    assert row["radon.mean_mi"] == pytest.approx(100.0) and row["radon.delta_mean_mi"] == pytest.approx(0.0)
    assert row["radon.unparsed_files"] == 0


def test_radon_new_file_and_unparsable_file():
    row = radon_metrics({}, AFTER)
    assert row["radon.delta_sloc"] == 10 and row["radon.delta_max_cc"] == 3
    assert row["radon.delta_mean_cc"] is None  # a mean over nothing is undefined
    broken = radon_metrics({"pkg/a.py": "def (:\n"}, BEFORE)
    assert broken["radon.unparsed_files"] == 1


def test_parse_pylint_counts_categories_and_design_checks():
    report = {"statistics": {"score": 7.5}, "messages": [
        {"type": "convention", "messageId": "C0114"}, {"type": "refactor", "messageId": "R0913"},
        {"type": "refactor", "messageId": "R1705"}, {"type": "warning", "messageId": "W0611"}]}
    row = parse_pylint(report, sloc=500)
    assert row == {"pylint.score": 7.5, "pylint.convention": 1, "pylint.refactor": 2, "pylint.warning": 1,
                   "pylint.error": 0, "pylint.design": 1, "pylint.refactor_per_kloc": 4.0}


@pytest.mark.skipif(importlib.util.find_spec("pylint") is None, reason="pylint not installed")
def test_pylint_on_a_tiny_file():
    code = '"""Doc."""\n\n\ndef many(a, b, c, d, e, f, g):\n    """Doc."""\n    return a + b + c + d + e + f + g\n'
    row = pylint_metrics({"pkg/m.py": code}, sloc=4)
    assert row["pylint.design"] == 2  # R0913 too-many-arguments and R0917 too-many-positional-arguments
    assert row["pylint.error"] == 0 and row["pylint.score"] is not None
    assert pylint_metrics({}, None)["pylint.score"] is None


@pytest.mark.skipif(importlib.util.find_spec("pylint") is None, reason="pylint not installed")
def test_pylint_on_a_module_named_like_the_stdlib_finishes():
    # aiohttp#10038: a touched pkg/abc.py doing `from abc import ABC` used to make pylint import
    # itself and hang until the timeout (null row).
    code = '"""Doc."""\nfrom abc import ABC, abstractmethod\n\n\nclass Base(ABC):\n    """Doc."""\n\n' \
           '    @abstractmethod\n    def run(self):\n        """Doc."""\n'
    row = pylint_metrics({"pkg/abc.py": code}, sloc=8, timeout=60)
    assert row["pylint.score"] is not None


def git(repo: Path, *arguments: str, date: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, env=env,
                          check=True).stdout.strip()


@pytest.fixture
def dated_repo(tmp_path):
    """a.py changed in Jan (outside the window), Mar and May; the PR merges on 2024-06-01; then one more change."""
    git(tmp_path, "init", "-q", "-b", "main")
    shas = {}
    for name, date, text in [("jan", "2023-11-01T00:00:00+00:00", "def f():\n    return 0\n"),
                             ("mar", "2024-03-01T00:00:00+00:00", "def f(x):\n    if x:\n        return 1\n    return 0\n"),
                             ("may", "2024-05-01T00:00:00+00:00", "def f(x):\n    if x:\n        return 2\n    return 0\n")]:
        (tmp_path / "a.py").write_text(text)
        git(tmp_path, "add", "a.py")
        git(tmp_path, "commit", "-q", "-m", name, date=date)
        shas[name] = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "a.py").write_text("def f(x):\n    return x\n")
    git(tmp_path, "commit", "-qam", "pr", date="2024-06-01T00:00:00+00:00")
    shas["merge"] = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "a.py").write_text("def f(x):\n    return -x\n")
    git(tmp_path, "commit", "-qam", "after merge", date="2024-06-10T00:00:00+00:00")
    return tmp_path, shas


def test_hotspot_counts_only_the_182_days_before_the_merge(dated_repo):
    repo, shas = dated_repo
    sample = {"before_commit_sha": shas["may"], "merge_commit_sha": shas["merge"],
              "merged_at": "2024-06-01T00:00:00+00:00", "changed_python_files": ["a.py", "new.py"]}
    assert change_frequency(repo, shas["may"], sample["merged_at"], "a.py") == 2  # mar + may, not jan or later
    before = read_side(repo, shas["may"], sample["changed_python_files"])
    assert set(before) == {"a.py"}  # new.py does not exist before the PR
    row = hotspot_metrics(repo, sample, before)
    assert row == {"hotspot.change_frequency": 2, "hotspot.max_change_frequency": 2, "hotspot.score": 2 * 2}


class FakeSonar:
    """An in-memory SonarQube Web API behind httpx.MockTransport."""

    def __init__(self, measures):
        self.measures, self.deleted, self.task_polls = measures, [], 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ce/task":
            self.task_polls += 1
            return httpx.Response(200, json={"task": {"status": "SUCCESS" if self.task_polls > 1 else "IN_PROGRESS"}})
        if request.url.path == "/api/measures/component":
            key = request.url.params["component"]
            return httpx.Response(200, json={"component": {"measures": [
                {"metric": m, "value": str(v)} for m, v in self.measures[key].items()]}})
        if request.url.path == "/api/projects/delete":
            self.deleted.append(request.content.decode())
            return httpx.Response(204)
        if request.url.path == "/api/server/version":
            return httpx.Response(200, text="25.1.0")
        return httpx.Response(404)


def fake_client(fake: FakeSonar) -> SonarClient:
    return SonarClient("http://sonar", "token", httpx.Client(base_url="http://sonar",
                                                             transport=httpx.MockTransport(fake.handler)))


def test_sonar_metrics_after_delta_and_cleanup():
    before_key, after_key = project_key("o/r#7", "before"), project_key("o/r#7", "after")
    fake = FakeSonar({
        before_key: {"code_smells": 4, "cognitive_complexity": 10, "sqale_index": 30, "duplicated_lines_density": 0},
        after_key: {"code_smells": 6, "cognitive_complexity": 15, "sqale_index": 45, "duplicated_lines_density": 1.5}})
    scanned = []

    def scanner(folder, key, host, token):
        scanned.append((key, sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*.py"))))
        return f"task-{key}"

    client = fake_client(fake)
    client_wait = client.wait_for_task
    client.wait_for_task = lambda task: client_wait(task, sleep=lambda s: None)
    row = sonar_metrics("o/r#7", {"pkg/a.py": "x = 1\n"}, {"pkg/a.py": "x = 2\n"}, client, "http://h", "t", scanner)
    assert row == {"sonar.code_smells": 6.0, "sonar.cognitive_complexity": 15.0, "sonar.sqale_index": 45.0,
                   "sonar.delta_code_smells": 2.0, "sonar.delta_cognitive_complexity": 5.0,
                   "sonar.delta_sqale_index": 15.0, "sonar.duplicated_lines_density": 1.5}
    assert scanned == [(before_key, ["pkg/a.py"]), (after_key, ["pkg/a.py"])]
    assert fake.deleted == [f"project={before_key}", f"project={after_key}"]
    assert client.server_version() == "25.1.0"


def test_sonar_side_without_files_is_zero_and_not_scanned():
    def scanner(*args):
        raise AssertionError("must not scan an empty side")
    measures = scan_side({}, "k", fake_client(FakeSonar({})), "h", "t", scanner)
    assert measures["code_smells"] == 0 and measures["duplicated_lines_density"] is None


def test_project_is_deleted_even_when_the_scan_fails():
    fake = FakeSonar({})

    def scanner(*args):
        raise SonarError("scanner broke")

    with pytest.raises(SonarError):
        scan_side({"a.py": "x = 1\n"}, "v5_k_before", fake_client(fake), "h", "t", scanner)
    assert fake.deleted == ["project=v5_k_before"]


def test_task_id_is_read_from_the_scanner_log():
    log = ("19:07:49.744 INFO  More about the report processing at "
           "http://host.docker.internal:9000/api/ce/task?id=2536e0bc-2daf-4a78-893b-0c89d7a0e639\n"
           "19:07:49.877 INFO  EXECUTION SUCCESS\n")
    assert task_id_from_output(log) == "2536e0bc-2daf-4a78-893b-0c89d7a0e639"
    assert task_id_from_output("EXECUTION FAILURE") is None


def test_sonar_failed_task_raises():
    def handler(request):
        return httpx.Response(200, json={"task": {"status": "FAILED"}})
    client = SonarClient("http://s", "t", httpx.Client(base_url="http://s", transport=httpx.MockTransport(handler)))
    with pytest.raises(SonarError, match="FAILED"):
        client.wait_for_task("abc", sleep=lambda s: None)


class FakeBatchSonar:
    """A server that 'analyses' whatever the fake scanner uploaded: one file-level entry per file,
    code_smells = number of lines, cognitive_complexity = number of 'if', sqale_index = 5 x smells.
    A file named empty.py comes back without measures, as SonarQube does for all-zero files."""

    def __init__(self):
        self.projects, self.deleted = {}, []

    def scanner(self, folder, key, host, token, timeout=None, extra=()):
        assert "-Dsonar.cpd.exclusions=**/*" in extra
        self.projects[key] = {p.relative_to(folder).as_posix(): p.read_text() for p in folder.rglob("*.py")}
        return f"task-{key}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ce/task":
            return httpx.Response(200, json={"task": {"status": "SUCCESS"}})
        if request.url.path == "/api/measures/component_tree":
            assert request.url.params["qualifiers"] == "FIL"
            files = self.projects[request.url.params["component"]]
            components = []
            for path, text in sorted(files.items()):
                lines, ifs = text.count("\n"), text.count("if ")
                measures = [] if path.endswith("empty.py") else [
                    {"metric": "code_smells", "value": str(lines)}, {"metric": "cognitive_complexity", "value": str(ifs)},
                    {"metric": "sqale_index", "value": str(5 * lines)}]
                components.append({"path": path, "measures": measures})
            return httpx.Response(200, json={"paging": {"total": len(components)}, "components": components})
        if request.url.path == "/api/projects/delete":
            self.deleted.append(request.content.decode())
            return httpx.Response(204)
        return httpx.Response(404)


def test_batch_maps_every_pr_folder_to_its_sample_id():
    fake = FakeBatchSonar()
    client = SonarClient("http://s", "t", httpx.Client(base_url="http://s", transport=httpx.MockTransport(fake.handler)))
    # PR 1 edits two files in two folders (SonarQube would collapse these into separate DIRs);
    # PR 2 adds a brand-new file, so its before side is empty.
    before = {"o/r#1": {"src/pkg/a.py": "x = 1\n", "src/pkg/sub/b.py": "if x:\n    y = 2\n"},
              "o/r#2": {}}
    after = {"o/r#1": {"src/pkg/a.py": "x = 1\nif x:\n    z = 3\n", "src/pkg/sub/b.py": "if x:\n    y = 2\n"},
             "o/r#2": {"pkg/new.py": "if a:\n    b = 1\nc = 2\n", "pkg/empty.py": "\n"}}
    old = scan_batch_side(before, "v5_batch_1_before", client, "h", "t", fake.scanner)
    new = scan_batch_side(after, "v5_batch_1_after", client, "h", "t", fake.scanner)
    assert set(fake.projects["v5_batch_1_before"]) == {"o__r__1/src/pkg/a.py", "o__r__1/src/pkg/sub/b.py"}
    rows = {row["sample_id"]: row for row in batch_rows(["o/r#1", "o/r#2"], old, new)}
    # PR 1 after: a.py 3 lines + b.py 2 lines = 5 smells, 2 ifs; before: 1 + 2 = 3 smells, 1 if.
    assert rows["o/r#1"] == {"sample_id": "o/r#1", "sonar.code_smells": 5.0, "sonar.cognitive_complexity": 2.0,
                             "sonar.sqale_index": 25.0, "sonar.delta_code_smells": 2.0,
                             "sonar.delta_cognitive_complexity": 1.0, "sonar.delta_sqale_index": 10.0}
    # PR 2: new.py 3 lines, 1 if; empty.py has no measures (0); before side empty -> 0.
    assert rows["o/r#2"]["sonar.code_smells"] == 3.0 and rows["o/r#2"]["sonar.delta_code_smells"] == 3.0
    assert rows["o/r#2"]["sonar.delta_cognitive_complexity"] == 1.0
    assert fake.deleted == ["project=v5_batch_1_before", "project=v5_batch_1_after"]


def test_batch_row_is_null_when_sonar_returned_nothing_for_a_written_folder():
    rows = batch_rows(["o/r#3"], ({"o__r__3"}, {}), ({"o__r__3"}, {"o__r__3": {"code_smells": 1.0,
                      "cognitive_complexity": 0.0, "sqale_index": 5.0}}))
    assert rows[0]["sonar.code_smells"] == 1.0 and rows[0]["sonar.delta_code_smells"] is None


def test_batches_never_mix_splits_and_respect_the_order():
    spec = importlib.util.spec_from_file_location("sonar_cli", Path(__file__).parents[1] / "scripts/sonar_v5.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    samples = [{"sample_id": f"o/r#{i}", "split": split} for i, split in
               enumerate(["train"] * 3 + ["test"] * 5 + ["val"] * 2)]
    batches = cli.make_batches(samples, ["test", "val", "train"], size=2)
    assert [(split, len(batch)) for split, batch in batches] == [
        ("test", 2), ("test", 2), ("test", 1), ("val", 2), ("train", 2), ("train", 1)]
    assert pr_folder("pallets/flask#5123") == "pallets__flask__5123"


def test_project_key_and_seeded_test_subset():
    assert project_key("pallets/flask#5123", "before") == "v5_pallets_flask_5123_before"
    samples = [{"sample_id": f"o/r#{i}", "split": "test" if i % 2 else "train"} for i in range(40)]
    assert len(select_sonar_samples(samples, None, 0)) == 20
    first, again = select_sonar_samples(samples, 5, 3), select_sonar_samples(samples, 5, 3)
    assert first == again and len(first) == 5 and all(s["split"] == "test" for s in first)


def test_resume_merges_lines_and_compacts(tmp_path):
    out = tmp_path / "m.jsonl"
    out.write_text('{"sample_id": "a", "radon.sloc": 3}\n{"sample_id": "b", "radon.sloc": null}\n'
                   '{"sample_id": "a", "sonar.code_smells": 1}\n')
    rows = load_rows(out)
    assert rows["a"] == {"sample_id": "a", "radon.sloc": 3, "sonar.code_smells": 1}
    assert done(rows["b"], "radon") and not done(rows["b"], "sonar") and not done(None, "radon")
    assert compact(out) == 2 and len(out.read_text().splitlines()) == 2


def test_cli_skips_samples_already_in_the_output(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("tool_metrics_cli", Path(__file__).parents[1] / "scripts/tool_metrics_v5.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    (tmp_path / "repos/o__r/.git").mkdir(parents=True)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(json.dumps({"sample_id": f"o/r#{i}", "repo": "o/r"}) + "\n" for i in range(3)))
    out = tmp_path / "out.jsonl"
    out.write_text('{"sample_id": "o/r#0", "radon.sloc": 1}\n')
    measured = []

    def fake_measure(repository, sample, tools):
        measured.append((sample["sample_id"], sorted(tools)))
        return {"sample_id": sample["sample_id"], **{f"{t}.x": 1 for t in tools}}

    monkeypatch.setattr(cli, "measure_sample", fake_measure)
    monkeypatch.setattr(cli, "local_versions", lambda: {})
    args = ["--manifest", str(manifest), "--repos-dir", str(tmp_path / "repos"), "--out", str(out),
            "--tools", "radon", "--workers", "1"]
    assert cli.main(args) == 0
    assert sorted(measured) == [("o/r#1", ["radon"]), ("o/r#2", ["radon"])]
    measured.clear()
    assert cli.main(args) == 0
    assert measured == []  # everything is done now
    assert json.loads(out.with_suffix(".meta.json").read_text())["rows_with"]["radon"] == 3


def test_manifest_dev_helpers():
    assert pr_number("Merge pull request #5123 from x/y") == 5123
    assert pr_number("fix thing (#42)") == 42 and pr_number("fix #42 later") is None
    assert is_production_python("src/flask/app.py") and not is_production_python("tests/test_app.py")
    assert not is_production_python("docs/conf.py") and not is_production_python("README.md")
    assert module_name("src/flask/app.py") == "flask.app" and module_name("requests/__init__.py") == "requests"
