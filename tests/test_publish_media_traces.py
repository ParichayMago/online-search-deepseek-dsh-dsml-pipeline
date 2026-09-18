from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "publish_media_traces_test_module", ROOT / "scripts/publish_media_traces.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_trace(root: Path, task_id: str, suffix: str, reward: float) -> None:
    trace = root / "ygg" / "run" / "harbor" / task_id / f"{task_id}__{suffix}"
    (trace / "agent").mkdir(parents=True)
    (trace / "artifacts").mkdir()
    (trace / "verifier").mkdir()
    (trace / "agent" / "trajectory.json").write_text('{"steps": []}\n', encoding="utf-8")
    (trace / "artifacts" / "report.md").write_text("report\n", encoding="utf-8")
    (trace / "verifier" / "judgment.json").write_text('{"ok": true}\n', encoding="utf-8")
    (trace / "verifier" / "score.txt").write_text(f"{reward}\n", encoding="utf-8")
    (trace / "verifier" / "reward.txt").write_text(f"{reward}\n", encoding="utf-8")
    (trace / "result.json").write_text(
        json.dumps(
            {
                "trial_name": f"{task_id}__{suffix}",
                "started_at": "2026-08-14T00:00:00Z",
                "finished_at": "2026-08-14T01:00:00Z",
                "agent_info": {"name": "codex", "version": "1", "model_info": {"name": "gpt"}},
                "agent_result": {
                    "n_input_tokens": 500_001,
                    "n_cache_tokens": 300_000,
                    "n_output_tokens": 10_000,
                    "secret_config_that_must_not_be_copied": "masked",
                },
                "verifier_result": {"rewards": {"reward": reward}},
            }
        ),
        encoding="utf-8",
    )


def make_run(tmp_path: Path, task_id: str, count: int = 3) -> Path:
    run = tmp_path / "campaign-run"
    event = run / "ygg" / "run" / "events.jsonl"
    event.parent.mkdir(parents=True)
    event.write_text("{}\n", encoding="utf-8")
    for index in range(count):
        make_trace(run, task_id, f"trial{index}", 0.1 + index / 10)
    return run


def test_builds_three_curated_trace_folders_and_public_manifest(tmp_path: Path):
    publisher = load_module()
    task_id = "agency-report-revision"
    run = make_run(tmp_path, task_id)
    output = tmp_path / "published" / task_id

    manifest = publisher.build_trace_tree(run, task_id, output)

    assert manifest["trace_count"] == 3
    assert {path.name for path in output.iterdir()} == {
        "agency-report-revision__trial0",
        "agency-report-revision__trial1",
        "agency-report-revision__trial2",
        "manifest.json",
    }
    first = output / "agency-report-revision__trial0"
    assert {path.name for path in first.iterdir()} == {
        "trajectory.json",
        "report.md",
        "judgment.json",
        "score.txt",
        "reward.txt",
        "metrics.json",
    }
    metrics = json.loads((first / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["tokens"]["fresh_input"] == 200_001
    assert "secret_config_that_must_not_be_copied" not in (first / "metrics.json").read_text()


def test_requires_exactly_three_solver_traces(tmp_path: Path):
    publisher = load_module()
    run = make_run(tmp_path, "agency-report-revision", count=2)

    with pytest.raises(ValueError, match="exactly three solver traces"):
        publisher.build_trace_tree(run, "agency-report-revision", tmp_path / "output")


def test_rejects_sensitive_material_in_trace(tmp_path: Path):
    publisher = load_module()
    task_id = "agency-report-revision"
    run = make_run(tmp_path, task_id)
    trace = next((run / "ygg" / "run" / "harbor" / task_id).iterdir())
    (trace / "agent" / "trajectory.json").write_text("github_pat_do_not_publish\n")

    with pytest.raises(ValueError, match="sensitive marker"):
        publisher.build_trace_tree(run, task_id, tmp_path / "output")


def test_post_push_verification_tolerates_old_head_during_api_lag(monkeypatch):
    publisher = load_module()
    old = "a" * 40
    new = "b" * 40
    identities = iter(
        [
            {
                "number": 194,
                "state": "OPEN",
                "headRefName": "online-search/agency-report-revision",
                "headRefOid": old,
                "baseRefName": "main",
            },
            {
                "number": 194,
                "state": "OPEN",
                "headRefName": "online-search/agency-report-revision",
                "headRefOid": new,
                "baseRefName": "main",
            },
        ]
    )
    monkeypatch.setattr(publisher, "pr_identity", lambda *_args: next(identities))
    sleeps = []
    monkeypatch.setattr(publisher.time, "sleep", sleeps.append)

    publisher.verify_pushed_head(
        "owner/repo",
        194,
        "agency-report-revision",
        "online-search/agency-report-revision",
        old,
        new,
    )

    assert sleeps == [1]
