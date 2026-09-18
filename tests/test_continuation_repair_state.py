from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).parents[1] / "scripts" / "continuation_repair_state.py"
REQUIRED_PRIOR_FILES = (
    "instruction.md",
    "solution/evidence_graph.json",
    "solution/report.md",
    "tests/rubrics.json",
    "tests/reference/ground_truth.json",
)


def _complete_candidate(path: Path) -> None:
    for relative in REQUIRED_PRIOR_FILES:
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("candidate\n", encoding="utf-8")


def test_failed_candidates_are_rendered_with_latest_artifacts_and_feedback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ideas.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "ideas": [
                    {"id": "repair-me", "idea": "repair"},
                    {"id": "already-done", "idea": "done"},
                    {
                        "id": "fresh-repair",
                        "idea": "fresh",
                        "prior_task_path": "/older/candidate",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    _complete_candidate(run_dir / "tasks" / "repair-me")
    events = run_dir / "events.jsonl"
    events.parent.mkdir(parents=True, exist_ok=True)
    events.write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "event": "task_failed",
                    "task_id": "000-aaaaaa",
                    "error": "fix the source boundary",
                },
                {"event": "task_done", "task_id": "001-bbbbbb"},
                {
                    "event": "task_failed",
                    "task_id": "002-cccccc",
                    "error": "raise solver signal",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    state = tmp_path / "repair-state.json"
    subprocess.run(
        [sys.executable, SCRIPT, "update", source, events, run_dir, state],
        check=True,
    )

    accepted = tmp_path / "accepted.txt"
    accepted.write_text("", encoding="utf-8")
    prior = tmp_path / "prior.txt"
    prior.write_text("already-done\n", encoding="utf-8")
    rendered = tmp_path / "rendered.yaml"
    subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "render",
            source,
            accepted,
            prior,
            state,
            rendered,
        ],
        check=True,
    )

    ideas = yaml.safe_load(rendered.read_text(encoding="utf-8"))["ideas"]
    assert [idea["id"] for idea in ideas] == ["repair-me", "fresh-repair"]
    assert ideas[0]["continuation_feedback"] == "fix the source boundary"
    assert ideas[0]["prior_task_path"] == str(
        (run_dir / "tasks" / "repair-me").resolve()
    )
    assert ideas[1]["continuation_feedback"] == "raise solver signal"
    assert ideas[1]["prior_task_path"] == "/older/candidate"


def _fake_runtime_commands(tmp_path: Path, monkeypatch, open_prs: int = 1) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    docker = binaries / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    docker.chmod(0o755)
    gh = binaries / "gh"
    rows = [
        {"title": f"[online-search] {index:06x} task-name-here", "headRefName": f"online-search/task-{index}"}
        for index in range(open_prs)
    ]
    gh.write_text(
        "#!/bin/sh\nprintf '%s\\n' '" + json.dumps(rows) + "'\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binaries}:{os.environ['PATH']}")


def _aborted_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "ideas.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "ideas": [
                    {"id": "already-done"},
                    {"id": "failed-one"},
                    {"id": "paused-one"},
                    {"id": "paused-two"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    run = tmp_path / "run"
    for idea_id in ("failed-one", "paused-one", "paused-two"):
        _complete_candidate(run / "tasks" / idea_id)
    events = run / "events.jsonl"
    payload = [
        {"event": "task_start", "task_id": "000-aaaaaa"},
        {"event": "task_done", "task_id": "000-aaaaaa"},
        {"event": "task_start", "task_id": "001-bbbbbb"},
        {"event": "task_failed", "task_id": "001-bbbbbb", "error": "repair"},
        {"event": "task_start", "task_id": "002-cccccc"},
        {"event": "task_start", "task_id": "003-dddddd"},
    ]
    events.parent.mkdir(parents=True, exist_ok=True)
    events.write_text("".join(json.dumps(event) + "\n" for event in payload), encoding="utf-8")
    return source, run, events


def test_aborted_marker_enqueues_nonterminal_candidates_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    _fake_runtime_commands(tmp_path, monkeypatch, open_prs=1)
    source, run, events = _aborted_fixture(tmp_path)
    inspection = subprocess.run(
        [sys.executable, SCRIPT, "inspect-prior", source, events, run],
        check=True,
        capture_output=True,
        text=True,
    )
    inspected = json.loads(inspection.stdout)
    assert inspected["counts"]["nonterminal"] == 2
    assert all(task["complete"] for task in inspected["nonterminal_tasks"])
    marker = tmp_path / "aborted.json"
    state = tmp_path / "repair.json"
    state.write_text(
        json.dumps({"failed-one": {"continuation_feedback": "repair"}}) + "\n",
        encoding="utf-8",
    )
    event_hash = hashlib.sha256(events.read_bytes()).hexdigest()
    command = [
        sys.executable,
        SCRIPT,
        "finalize-aborted",
        source,
        events,
        run,
        state,
        marker,
        "--expect-events-sha256",
        event_hash,
        "--expect-started",
        "4",
        "--expect-done",
        "1",
        "--expect-failed",
        "1",
        "--expect-nonterminal",
        "2",
        "--reason",
        "operator pause",
        "--guard-pid",
        "999999999",
        "--guard-container",
        "removed-container",
        "--github-repo",
        "example/tasks",
        "--pr-title-regex",
        r"\[online-search\] [0-9a-f]{6} [a-z-]+",
        "--pr-head-prefix",
        "online-search/",
        "--expected-open-prs",
        "1",
    ]
    subprocess.run(command, check=True)
    subprocess.run(command, check=True)

    repair = json.loads(state.read_text(encoding="utf-8"))
    assert set(repair) == {"failed-one", "paused-one", "paused-two"}
    assert "positive-only rubric-axis" in repair["paused-one"]["continuation_feedback"]
    assert repair["paused-two"]["prior_task_path"] == str(
        (run / "tasks" / "paused-two").resolve()
    )
    marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_payload["nonterminal_indexes"] == [2, 3]
    assert marker_payload["counts"] == {
        "started": 4,
        "done": 1,
        "failed": 1,
        "nonterminal": 2,
    }

    accepted = tmp_path / "accepted.txt"
    accepted.write_text("", encoding="utf-8")
    prior = tmp_path / "prior.txt"
    subprocess.run(
        [sys.executable, SCRIPT, "write-prior-ids", marker, events, prior],
        check=True,
    )
    assert prior.read_text(encoding="utf-8") == "already-done\n"
    audit = subprocess.run(
        [sys.executable, SCRIPT, "audit", source, accepted, prior, state, "4"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(audit.stdout)["remaining"] == 3


def test_aborted_marker_rejects_live_pid_and_event_drift(tmp_path: Path, monkeypatch) -> None:
    _fake_runtime_commands(tmp_path, monkeypatch, open_prs=1)
    source, run, events = _aborted_fixture(tmp_path)
    state = tmp_path / "repair.json"
    marker = tmp_path / "aborted.json"
    digest = hashlib.sha256(events.read_bytes()).hexdigest()
    base = [
        sys.executable, SCRIPT, "finalize-aborted", source, events, run, state, marker,
        "--expect-events-sha256", digest,
        "--expect-started", "4", "--expect-done", "1", "--expect-failed", "1",
        "--expect-nonterminal", "2", "--reason", "pause",
        "--github-repo", "example/tasks", "--pr-title-regex", r"\[online-search\] [0-9a-f]{6} [a-z-]+",
        "--expected-open-prs", "1",
    ]
    live = subprocess.run(
        base + ["--guard-pid", str(os.getpid())],
        check=False,
        capture_output=True,
        text=True,
    )
    assert live.returncode != 0
    assert "guarded PIDs" in live.stderr

    subprocess.run(base + ["--guard-pid", "999999999"], check=True)
    events.write_text(events.read_text(encoding="utf-8") + json.dumps({"event": "note"}) + "\n", encoding="utf-8")
    drift = subprocess.run(
        [sys.executable, SCRIPT, "verify-aborted", marker, events],
        check=False,
        capture_output=True,
        text=True,
    )
    assert drift.returncode != 0
    assert "events changed" in drift.stderr


def test_audit_rejects_overlapping_ledgers(tmp_path: Path) -> None:
    source = tmp_path / "ideas.yaml"
    source.write_text(yaml.safe_dump({"ideas": [{"id": "same"}]}), encoding="utf-8")
    accepted = tmp_path / "accepted"
    accepted.write_text("same\n", encoding="utf-8")
    prior = tmp_path / "prior"
    prior.write_text("", encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"same": {}}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, SCRIPT, "audit", source, accepted, prior, state, "2"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "overlap" in result.stderr
