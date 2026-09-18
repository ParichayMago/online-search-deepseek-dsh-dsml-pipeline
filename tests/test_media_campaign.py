from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_campaign_module():
    spec = importlib.util.spec_from_file_location(
        "media_campaign_test_module", ROOT / "scripts/media_campaign.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_resume_module():
    spec = importlib.util.spec_from_file_location(
        "resume_media_package_test_module", ROOT / "scripts/resume_media_package.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def idea(idea_id: str) -> dict:
    return {
        "id": idea_id,
        "idea": "Build an exact verification task.",
        "domain": "Media and journalism",
        "task_mode": "verification_and_abstention",
    }


def write_ideas(path: Path, ideas: list[dict]) -> None:
    path.write_text(
        yaml.safe_dump({"version": 1, "ideas": ideas}, sort_keys=False),
        encoding="utf-8",
    )


def write_complete_task(path: Path) -> None:
    resume = load_resume_module()
    for relative in resume.REQUIRED_TASK_FILES:
        destination = path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("{}\n" if destination.suffix == ".json" else "ok\n")


def test_local_target_reserves_no_more_pr_capable_lanes(tmp_path: Path):
    campaign = load_campaign_module()
    ideas = tmp_path / "ideas.yaml"
    write_ideas(ideas, [idea("one-two-three"), idea("four-five-six")])
    state = tmp_path / "state"

    campaign.initialize(
        state,
        ideas,
        server="test",
        target=1,
        pipeline_commit="a" * 40,
    )
    first = campaign.claim(state, 1)
    second = campaign.claim(state, 2)

    assert first["idea_id"] == "one-two-three"
    assert second is None
    status = campaign.campaign_status(state)
    assert status["running"] == 1
    assert status["pending"] == 1


def test_terminal_failure_releases_lane_for_unused_seed(tmp_path: Path):
    campaign = load_campaign_module()
    ideas = tmp_path / "ideas.yaml"
    write_ideas(ideas, [idea("one-two-three"), idea("four-five-six")])
    state = tmp_path / "state"
    campaign.initialize(
        state,
        ideas,
        server="test",
        target=1,
        pipeline_commit="b" * 40,
    )

    first = campaign.claim(state, 1)
    campaign.finish(state, first["idea_id"], "failed", failure="builder failed")
    second = campaign.claim(state, 1)

    assert second["idea_id"] == "four-five-six"
    assert campaign.campaign_status(state)["failed"] == 1


def test_blocked_deployment_keeps_target_slot_reserved(tmp_path: Path):
    campaign = load_campaign_module()
    ideas = tmp_path / "ideas.yaml"
    write_ideas(ideas, [idea("one-two-three"), idea("four-five-six")])
    state = tmp_path / "state"
    campaign.initialize(
        state,
        ideas,
        server="test",
        target=1,
        pipeline_commit="c" * 40,
    )

    first = campaign.claim(state, 1)
    campaign.finish(
        state,
        first["idea_id"],
        "blocked_deploy",
        failure="push unavailable",
    )

    assert campaign.claim(state, 2) is None
    status = campaign.campaign_status(state)
    assert status["blocked_deploy"] == 1
    assert status["running"] == 1


def test_export_and_import_transfer_disjoint_pending_seeds(tmp_path: Path):
    campaign = load_campaign_module()
    source_file = tmp_path / "source.yaml"
    write_ideas(
        source_file,
        [idea("one-two-three"), idea("four-five-six"), idea("seven-eight-nine")],
    )
    source_state = tmp_path / "source-state"
    campaign.initialize(
        source_state,
        source_file,
        server="source",
        target=1,
        pipeline_commit="d" * 40,
    )
    transfer = tmp_path / "transfer.yaml"
    campaign.export_pending(source_state, transfer, 1)

    destination_file = tmp_path / "destination.yaml"
    write_ideas(destination_file, [idea("alpha-beta-gamma")])
    destination_state = tmp_path / "destination-state"
    campaign.initialize(
        destination_state,
        destination_file,
        server="destination",
        target=1,
        pipeline_commit="d" * 40,
    )
    campaign.add_seeds(destination_state, transfer, 1)

    assert campaign.campaign_status(source_state)["exported"] == 1
    assert campaign.campaign_status(destination_state)["target"] == 2


def test_import_replenishes_exhausted_pool_without_increasing_target(tmp_path: Path):
    campaign = load_campaign_module()
    original = tmp_path / "original.yaml"
    write_ideas(original, [idea("one-two-three")])
    state = tmp_path / "state"
    campaign.initialize(
        state,
        original,
        server="test",
        target=1,
        pipeline_commit="f" * 40,
    )
    first = campaign.claim(state, 1)
    campaign.finish(state, first["idea_id"], "failed", failure="candidate failed")

    replacement = tmp_path / "replacement.yaml"
    write_ideas(replacement, [idea("four-five-six"), idea("seven-eight-nine")])
    campaign.add_seeds(state, replacement, 0)

    status = campaign.campaign_status(state)
    assert status["target"] == 1
    assert status["pending"] == 2
    assert campaign.claim(state, 1)["idea_id"] == "four-five-six"


def test_pre_task_infrastructure_failure_is_safely_requeued(
    tmp_path: Path, monkeypatch
):
    campaign = load_campaign_module()
    ideas = tmp_path / "ideas.yaml"
    write_ideas(ideas, [idea("one-two-three"), idea("four-five-six")])
    state = tmp_path / "state"
    campaign.initialize(
        state,
        ideas,
        server="test",
        target=1,
        pipeline_commit="e" * 40,
    )
    first = campaign.claim(state, 1)
    run_dir = state / "runs" / first["idea_id"] / "bootstrap-failed"
    run_dir.mkdir(parents=True)
    campaign.update_running(
        state, first["idea_id"], run_dir=run_dir, child_pid=99999999
    )
    campaign.finish(
        state,
        first["idea_id"],
        "blocked_deploy",
        failure="infrastructure failure before terminal task event; exit=128",
    )
    monkeypatch.setattr(campaign, "find_open_pr", lambda _branch: None)
    monkeypatch.setattr(campaign, "remote_branch_exists", lambda _branch: False)

    assert campaign.requeue_bootstrap_failures(state) == 1
    claimed = campaign.claim(state, 1)
    assert claimed["idea_id"] == "one-two-three"


def test_same_package_retry_selects_complete_nested_tree(tmp_path: Path):
    campaign = load_campaign_module()
    ideas = tmp_path / "ideas.yaml"
    write_ideas(ideas, [idea("one-two-three")])
    state = tmp_path / "state"
    campaign.initialize(
        state,
        ideas,
        server="test",
        target=1,
        pipeline_commit="f" * 40,
    )
    row = campaign.claim(state, 2)
    run_dir = state / "runs" / row["idea_id"] / "attempt"
    events_root = run_dir / "ygg" / "run-one"
    events_root.mkdir(parents=True)
    candidate = events_root / "tasks" / row["idea_id"]
    nested = candidate / "output" / row["idea_id"]
    write_complete_task(nested)
    (events_root / "events.jsonl").write_text(
        json.dumps(
            {
                "event": "task_failed",
                "error": "Step 'preflight.required_files' failed: missing files",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    campaign.update_running(
        state,
        row["idea_id"],
        run_dir=run_dir,
        child_pid=99999999,
    )
    campaign.finish(
        state,
        row["idea_id"],
        "failed",
        failure="Step 'preflight.required_files' failed: missing files",
    )

    connection = campaign.connect(state)
    failed = connection.execute(
        "SELECT * FROM ideas WHERE idea_id=?", (row["idea_id"],)
    ).fetchone()
    connection.close()
    selected, stage = campaign.same_package_retry_candidate(failed)

    assert selected == nested.resolve()
    assert stage == "preflight"


def test_same_package_retry_refuses_occupied_affinity_lane(tmp_path: Path, monkeypatch):
    campaign = load_campaign_module()
    ideas = tmp_path / "ideas.yaml"
    write_ideas(ideas, [idea("one-two-three"), idea("four-five-six")])
    state = tmp_path / "state"
    campaign.initialize(
        state,
        ideas,
        server="test",
        target=2,
        pipeline_commit="a" * 40,
    )
    first = campaign.claim(state, 5)
    campaign.finish(state, first["idea_id"], "failed", failure="builder failed")
    assert campaign.claim(state, 5)["idea_id"] == "four-five-six"
    campaign.set_pause(state, True)
    monkeypatch.setattr(campaign, "find_open_pr", lambda _branch: None)
    monkeypatch.setattr(campaign, "remote_branch_exists", lambda _branch: False)

    try:
        campaign.prepare_same_package_retry(state, first["idea_id"], expected_lane=5)
    except ValueError as error:
        assert "lane 5 is occupied" in str(error)
    else:
        raise AssertionError("occupied lane unexpectedly admitted a package retry")


def test_resume_plan_starts_after_build_and_setup():
    resume = load_resume_module()
    indexes = resume.resume_step_indexes(ROOT / "config-media-journalism.yaml", "capture")
    items = resume._pipeline_items(ROOT / "config-media-journalism.yaml")
    names = [items[index]["step"] for index in indexes]

    assert names[0] == "doraemon.validate_live_task"
    assert items[indexes[0]]["params"]["mode"] == "capture"
    assert "build.codex" not in names
    assert "setup.instantiate_template" not in names
    assert names[-2:] == ["deploy.gh_push", "deploy.open_pr"]


def test_oracle_resume_never_reinvokes_builder_or_deployment():
    resume = load_resume_module()
    config = ROOT / "config-online-search-build-only-deepseek-dsh-dsml.yaml"
    indexes = resume.resume_step_indexes(config, "oracle")
    items = resume._pipeline_items(config)
    names = [items[index]["step"] for index in indexes]
    assert names[0] == "doraemon.oracle_min_score"
    assert "benchmark.build_lane" not in names
    assert "deploy.gh_push" not in names
    assert "deploy.open_pr" not in names


def test_difficulty_resume_starts_at_solver_and_never_deploys():
    resume = load_resume_module()
    config = ROOT / "config-online-search-pipeline-deepseek-dsh-dsml.yaml"
    indexes = resume.resume_step_indexes(config, "difficulty")
    items = resume._pipeline_items(config)
    names = [items[index]["step"] for index in indexes]
    assert names[0] == "doraemon.muse_solver_lane"
    assert "benchmark.build_lane" not in names
    assert "deploy.gh_push" not in names
    assert "deploy.open_pr" not in names
