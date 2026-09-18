from __future__ import annotations

import json
from pathlib import Path

import pytest

from publication_gate import (
    TrialPublicationMetrics,
    collect_trial_metrics,
    muse_trial_metrics,
    peak_call_context,
    publication_summary,
)


def _trial(root: Path, name: str, *, score: float, calls: list[tuple[int, int]]) -> None:
    trial = root / name
    (trial / "agent/deliverables").mkdir(parents=True)
    (trial / "agent/deliverables/report.md").write_text("gradable", encoding="utf-8")
    (trial / "result.json").write_text(
        json.dumps({"verifier_result": {"rewards": {"reward": score}}}),
        encoding="utf-8",
    )
    (trial / "agent/trajectory.json").write_text(
        json.dumps(
            {
                "events": [
                    {"usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}
                    for input_tokens, output_tokens in calls
                ]
            }
        ),
        encoding="utf-8",
    )


def test_peak_call_context_uses_largest_individual_call(tmp_path: Path) -> None:
    _trial(tmp_path, "one", score=0.4, calls=[(600_000, 2), (10, 1)])
    assert peak_call_context(tmp_path / "one/agent/trajectory.json") == 600_002


def test_publication_gate_uses_three_trials_and_current_thresholds(tmp_path: Path) -> None:
    _trial(tmp_path, "one", score=0.60, calls=[(500_000, 100)])
    _trial(tmp_path, "two", score=0.68, calls=[(300_000, 100)])
    _trial(tmp_path, "three", score=0.70, calls=[(700_000, 100)])
    trials = collect_trial_metrics(tmp_path, expected_trials=3)
    summary = publication_summary(trials)
    assert summary["accepted"] is True
    assert summary["mean_score"] == pytest.approx(0.66)
    assert summary["maximum_peak_call_context"] == 700_100
    assert summary["target_reached"] is True


def test_publication_gate_score_is_strict_but_context_floor_is_inclusive() -> None:
    trials = [
        TrialPublicationMetrics("one", 0.8, 500_000),
        TrialPublicationMetrics("two", 0.8, 10),
        TrialPublicationMetrics("three", 0.8, 10),
    ]
    summary = publication_summary(trials)
    assert summary["score_pass"] is False
    assert summary["peak_call_context_pass"] is True
    assert summary["accepted"] is False


def test_publication_gate_requires_exactly_three_trials() -> None:
    with pytest.raises(ValueError, match="exactly three"):
        publication_summary([TrialPublicationMetrics("one", 0.5, 600_000)])


def test_muse_trial_metrics_accepts_timeout_with_gradable_report(tmp_path: Path) -> None:
    trial = tmp_path / "trial-1"
    (trial / "deliverables").mkdir(parents=True)
    (trial / "deliverables/report.md").write_text("gradable", encoding="utf-8")
    (trial / "result.json").write_text(
        json.dumps(
            {
                "status": "timeout",
                "verifier_score": 0.42,
                "metrics": {"peak_call": 640_000, "elapsed_s": 10800},
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 10_000},
            }
        ),
        encoding="utf-8",
    )
    metrics = muse_trial_metrics(trial)
    assert metrics.score == 0.42
    assert metrics.peak_call_context == 640_000


def test_muse_trial_metrics_rejects_extra_deliverables(tmp_path: Path) -> None:
    trial = tmp_path / "trial-1"
    (trial / "deliverables").mkdir(parents=True)
    (trial / "deliverables/report.md").write_text("gradable", encoding="utf-8")
    (trial / "deliverables/extra.txt").write_text("not allowed", encoding="utf-8")
    (trial / "result.json").write_text(
        json.dumps(
            {
                "verifier_score": 0.42,
                "metrics": {"peak_call": 640_000},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="gradable report"):
        muse_trial_metrics(trial)


def test_muse_trial_metrics_rejects_error_status_even_with_report(tmp_path: Path) -> None:
    trial = tmp_path / "trial-1"
    (trial / "deliverables").mkdir(parents=True)
    (trial / "deliverables/report.md").write_text("gradable", encoding="utf-8")
    (trial / "result.json").write_text(
        json.dumps(
            {
                "status": "error",
                "verifier_score": 0.42,
                "metrics": {"peak_call": 640_000},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-completing status"):
        muse_trial_metrics(trial)


def test_muse_trial_metrics_requires_measured_peak_call(tmp_path: Path) -> None:
    trial = tmp_path / "trial-1"
    (trial / "deliverables").mkdir(parents=True)
    (trial / "deliverables/report.md").write_text("gradable", encoding="utf-8")
    (trial / "result.json").write_text(
        json.dumps(
            {
                "status": "timeout",
                "verifier_score": 0.42,
                "peak_context_tokens": 640_000,
                "metrics": {"calls": 2},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="metrics.peak_call"):
        muse_trial_metrics(trial)


def test_collect_trial_metrics_rejects_incomplete_cohort(tmp_path: Path) -> None:
    _trial(tmp_path, "one", score=0.4, calls=[(600_000, 1)])
    with pytest.raises(ValueError, match="expected 3 complete solver trials"):
        collect_trial_metrics(tmp_path, expected_trials=3)
