"""Publication telemetry for the current three-trial Online Search contract."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class TrialPublicationMetrics:
    trial: str
    score: float
    peak_call_context: int
    input_tokens: int | None = None
    cached_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    wall_time_seconds: float | None = None


def _number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} is missing or non-numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite")
    return result


def _optional_number(value: object, *, label: str) -> float | None:
    if value is None:
        return None
    return _number(value, label=label)


def _usage_contexts(value: object):
    """Yield input plus output tokens for every individual call-usage object."""
    if isinstance(value, dict):
        input_value = next(
            (value[key] for key in ("input_tokens", "prompt_tokens") if key in value),
            None,
        )
        output_value = next(
            (
                value[key]
                for key in ("output_tokens", "completion_tokens")
                if key in value
            ),
            None,
        )
        if (
            isinstance(input_value, (int, float))
            and not isinstance(input_value, bool)
            and isinstance(output_value, (int, float))
            and not isinstance(output_value, bool)
            and input_value >= 0
            and output_value >= 0
        ):
            yield int(input_value + output_value)
        for child in value.values():
            yield from _usage_contexts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _usage_contexts(child)


def peak_call_context(trajectory_path: Path) -> int:
    """Return the largest single model call found in a Harbor trajectory."""
    payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
    values = list(_usage_contexts(payload))
    if not values:
        raise TypeError(f"trajectory contains no per-call token usage: {trajectory_path}")
    return max(values)


def _gradable_report(trial_dir: Path) -> Path | None:
    candidates = (
        trial_dir / "agent" / "deliverables" / "report.md",
        trial_dir / "deliverables" / "report.md",
        trial_dir / "report.md",
    )
    for path in candidates:
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            continue
        if path.parent.name == "deliverables":
            entries = list(path.parent.iterdir())
            if len(entries) != 1 or entries[0].name != "report.md":
                continue
        return path
    return None


def trial_metrics(trial_dir: Path) -> TrialPublicationMetrics:
    """Read one ordinary Harbor solver trial."""
    result = json.loads((trial_dir / "result.json").read_text(encoding="utf-8"))
    verifier = result.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    if not isinstance(rewards, dict) or "reward" not in rewards:
        raise ValueError(f"trial lacks verifier reward: {trial_dir}")
    if _gradable_report(trial_dir) is None:
        raise ValueError(f"trial lacks a gradable report.md: {trial_dir}")

    agent = result.get("agent_result")
    if not isinstance(agent, dict):
        agent = {}
    started = result.get("started_at")
    finished = result.get("finished_at")
    wall_time = None
    if isinstance(started, str) and isinstance(finished, str):
        wall_time = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()

    return TrialPublicationMetrics(
        trial=trial_dir.name,
        score=_number(rewards["reward"], label="verifier reward"),
        peak_call_context=peak_call_context(trial_dir / "agent" / "trajectory.json"),
        input_tokens=agent.get("n_input_tokens"),
        cached_tokens=agent.get("n_cache_tokens"),
        output_tokens=agent.get("n_output_tokens"),
        cost_usd=agent.get("cost_usd"),
        wall_time_seconds=wall_time,
    )


def muse_trial_metrics(trial_dir: Path) -> TrialPublicationMetrics:
    """Read one miniswe-muse trial without converting it into Harbor format."""
    result = json.loads((trial_dir / "result.json").read_text(encoding="utf-8"))
    if _gradable_report(trial_dir) is None:
        raise ValueError(f"Muse trial lacks a gradable report.md: {trial_dir}")
    status = result.get("status")
    if status not in {"done", "context_goal_reached", "timeout"}:
        raise ValueError(f"Muse trial has non-completing status {status!r}: {trial_dir}")
    score = result.get("verifier_score")
    if score is None:
        raise ValueError(f"Muse trial lacks verifier_score: {trial_dir}")

    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    usage = result.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    peak = metrics.get("peak_call")
    if peak is None:
        raise ValueError(f"Muse trial lacks measured metrics.peak_call: {trial_dir}")

    return TrialPublicationMetrics(
        trial=trial_dir.name,
        score=_number(score, label="Muse verifier score"),
        peak_call_context=int(_number(peak, label="Muse peak call context")),
        input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
        cached_tokens=usage.get("cached_tokens"),
        output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
        cost_usd=_optional_number(metrics.get("cost_usd"), label="Muse cost"),
        wall_time_seconds=_optional_number(metrics.get("elapsed_s"), label="Muse elapsed time"),
    )


def collect_trial_metrics(root: Path, *, expected_trials: int) -> list[TrialPublicationMetrics]:
    directories = sorted(
        result.parent
        for result in root.rglob("result.json")
        if (result.parent / "agent" / "trajectory.json").is_file()
    )
    if len(directories) != expected_trials:
        raise ValueError(
            f"expected {expected_trials} complete solver trials, found {len(directories)}"
        )
    return [trial_metrics(path) for path in directories]


def publication_summary(
    trials: list[TrialPublicationMetrics],
    *,
    maximum_mean_score: float = 0.8,
    minimum_max_peak_call_context: int = 500_000,
    target_peak_call_context: int = 700_000,
) -> dict[str, object]:
    if len(trials) != 3:
        raise ValueError("publication gate requires exactly three solver trials")
    mean_score = sum(item.score for item in trials) / 3
    peaks = [item.peak_call_context for item in trials]
    maximum_peak = max(peaks)
    score_pass = mean_score < maximum_mean_score
    context_pass = maximum_peak >= minimum_max_peak_call_context
    return {
        "accepted": score_pass and context_pass,
        "mean_score": mean_score,
        "maximum_peak_call_context": maximum_peak,
        "mean_peak_call_context": sum(peaks) / 3,
        "score_gate": f"mean < {maximum_mean_score}",
        "peak_call_context_gate": f"at least one trial >= {minimum_max_peak_call_context}",
        "peak_call_context_target": target_peak_call_context,
        "score_pass": score_pass,
        "peak_call_context_pass": context_pass,
        "target_reached": maximum_peak >= target_peak_call_context,
        "total_cost_usd": sum(item.cost_usd or 0 for item in trials),
        "total_input_tokens": sum(item.input_tokens or 0 for item in trials),
        "total_cached_tokens": sum(item.cached_tokens or 0 for item in trials),
        "total_output_tokens": sum(item.output_tokens or 0 for item in trials),
        "total_trial_wall_time_seconds": sum(
            item.wall_time_seconds or 0 for item in trials
        ),
        "trials": [asdict(item) for item in trials],
    }
