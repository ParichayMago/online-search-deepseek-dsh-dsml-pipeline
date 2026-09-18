#!/usr/bin/env python3
"""Carry failed or deliberately interrupted tasks into continuation cycles."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

import yaml

REQUIRED_PRIOR_FILES = (
    "instruction.md",
    "solution/evidence_graph.json",
    "solution/report.md",
    "tests/rubrics.json",
    "tests/reference/ground_truth.json",
)
ABORT_SCHEMA = "doraemon-aborted-prior-v1"
PAUSE_FEEDBACK = (
    "The prior campaign was intentionally stopped before this task emitted a "
    "terminal event. Re-audit the preserved candidate under every current rule, "
    "including positive-only rubric-axis count and weight balance, and rerun all "
    "deterministic, review, oracle, difficulty, and deployment gates."
)


def _read_ideas(path: pathlib.Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    ideas = payload.get("ideas") if isinstance(payload, dict) else None
    if not isinstance(ideas, list):
        raise SystemExit(f"idea source has no ideas list: {path}")
    ids = [str(idea.get("id") or "") for idea in ideas]
    if any(not idea_id for idea_id in ids) or len(ids) != len(set(ids)):
        raise SystemExit(f"idea source IDs must be unique and nonempty: {path}")
    return ideas


def _read_id_lines(path: pathlib.Path) -> list[str]:
    if not path.exists():
        return []
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(values) != len(set(values)):
        raise SystemExit(f"ID ledger contains duplicates: {path}")
    return values


def _read_ids(path: pathlib.Path) -> set[str]:
    return set(_read_id_lines(path))


def _read_state(path: pathlib.Path) -> dict[str, dict[str, str]]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or any(not isinstance(item, dict) for item in value.values()):
        raise SystemExit(f"repair state must be an object of objects: {path}")
    return value


def _write_json_atomic(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_lines_atomic(path: pathlib.Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(f"{value}\n" for value in values), encoding="utf-8")
    temporary.replace(path)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event_index(event: dict[str, Any]) -> int:
    match = re.match(r"^(\d+)-", str(event.get("task_id", "")))
    if match is None:
        raise SystemExit(f"task event has no sequential index: {event}")
    return int(match.group(1))


def _read_events(path: pathlib.Path) -> list[dict[str, Any]]:
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid event JSON at {path}:{number}: {exc}") from exc
        if not isinstance(event, dict):
            raise SystemExit(f"event must be an object at {path}:{number}")
        events.append(event)
    return events


def _classify_events(events: list[dict[str, Any]], idea_count: int) -> dict[str, Any]:
    starts: dict[int, str] = {}
    terminals: dict[int, str] = {}
    done: list[int] = []
    failed: list[int] = []
    engine_done = 0
    for event in events:
        kind = event.get("event")
        if kind == "engine_done":
            engine_done += 1
            continue
        if kind not in {"task_start", "task_done", "task_failed"}:
            continue
        index = _event_index(event)
        if not 0 <= index < idea_count:
            raise SystemExit(f"task index {index} exceeds the {idea_count}-idea source")
        task_id = str(event["task_id"])
        if kind == "task_start":
            if index in starts:
                raise SystemExit(f"duplicate task_start index {index}")
            starts[index] = task_id
            continue
        if index not in starts:
            raise SystemExit(f"terminal event for index {index} has no task_start")
        if starts[index] != task_id:
            raise SystemExit(f"task ID changed for index {index}: {starts[index]} != {task_id}")
        if index in terminals:
            raise SystemExit(f"duplicate terminal event for index {index}")
        terminals[index] = str(kind)
        (done if kind == "task_done" else failed).append(index)
    nonterminal = sorted(set(starts) - set(terminals))
    return {
        "started": len(starts),
        "done": sorted(done),
        "failed": sorted(failed),
        "nonterminal": nonterminal,
        "engine_done": engine_done,
    }


def _assert_candidate_complete(path: pathlib.Path) -> None:
    missing = [relative for relative in REQUIRED_PRIOR_FILES if not (path / relative).is_file()]
    if missing:
        raise SystemExit(f"prior candidate is incomplete at {path}: {', '.join(missing)}")


def update_state(
    source_path: pathlib.Path,
    events_path: pathlib.Path,
    run_dir: pathlib.Path,
    state_path: pathlib.Path,
) -> None:
    ideas = _read_ideas(source_path)
    state = _read_state(state_path)

    for event in _read_events(events_path):
        if event.get("event") not in {"task_done", "task_failed"}:
            continue
        index = _event_index(event)
        if index >= len(ideas):
            raise SystemExit(f"task index {index} exceeds {len(ideas)} ideas in {source_path}")
        idea_id = str(ideas[index]["id"])
        if event["event"] == "task_done":
            state.pop(idea_id, None)
            continue

        repair: dict[str, str] = {}
        feedback = str(event.get("error") or event.get("message") or "").strip()
        if feedback:
            repair["continuation_feedback"] = feedback
        candidate = (run_dir / "tasks" / idea_id).resolve()
        if candidate.is_dir() and all((candidate / relative).is_file() for relative in REQUIRED_PRIOR_FILES):
            repair["prior_task_path"] = str(candidate)
        state[idea_id] = repair
    _write_json_atomic(state_path, state)


def _github_open_count(guard: dict[str, Any]) -> int:
    command = [
        "gh", "pr", "list", "--repo", str(guard["repo"]), "--state", "open",
        "--limit", "500", "--json", "title,headRefName",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    rows = json.loads(result.stdout)
    title = re.compile(str(guard["title_regex"]))
    head_prefix = str(guard.get("head_prefix") or "")
    return sum(
        1 for row in rows
        if title.fullmatch(str(row.get("title") or ""))
        and str(row.get("headRefName") or "").startswith(head_prefix)
    )


def _assert_runtime_guards(guards: dict[str, Any], accepted_count: int) -> None:
    active_pids = [pid for pid in guards.get("pids", []) if pathlib.Path(f"/proc/{int(pid)}").exists()]
    if active_pids:
        raise SystemExit(f"aborted prior still has guarded PIDs: {active_pids}")
    active_cwds: list[dict[str, object]] = []
    prefixes = [pathlib.Path(value).resolve() for value in guards.get("cwd_prefixes", [])]
    if prefixes:
        for proc in pathlib.Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cwd = (proc / "cwd").resolve(strict=True)
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if any(cwd == prefix or prefix in cwd.parents for prefix in prefixes):
                active_cwds.append({"pid": int(proc.name), "cwd": str(cwd)})
    if active_cwds:
        raise SystemExit(f"aborted prior still has processes inside its run directory: {active_cwds}")
    engines: list[int] = []
    if guards.get("forbid_yggdrasil_run"):
        for proc in pathlib.Path("/proc").iterdir():
            if not proc.name.isdigit() or int(proc.name) == os.getpid():
                continue
            try:
                command = (proc / "cmdline").read_bytes().replace(b"\0", b" ")
            except (FileNotFoundError, PermissionError, OSError):
                continue
            if b"-m yggdrasil.cli run " in command:
                engines.append(int(proc.name))
    if engines:
        raise SystemExit(f"another Yggdrasil run engine is active: {engines}")
    present_containers = []
    for name in guards.get("containers", []):
        result = subprocess.run(
            ["docker", "container", "inspect", str(name)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            present_containers.append(name)
    if present_containers:
        raise SystemExit(f"aborted prior still has guarded containers: {present_containers}")
    github = guards.get("github")
    if github:
        observed = _github_open_count(github)
        expected = int(github["baseline_open_prs"]) + accepted_count
        if observed != expected:
            raise SystemExit(f"campaign open-PR count is {observed}; expected exactly {expected}")


def _load_marker(path: pathlib.Path) -> dict[str, Any]:
    marker = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(marker, dict) or marker.get("schema_version") != ABORT_SCHEMA:
        raise SystemExit(f"invalid aborted-prior marker: {path}")
    return marker


def _validate_marker(
    marker_path: pathlib.Path,
    events_path: pathlib.Path,
    accepted_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    marker = _load_marker(marker_path)
    if pathlib.Path(marker["events_path"]).resolve() != events_path.resolve():
        raise SystemExit("aborted marker is bound to a different events file")
    if _sha256(events_path) != marker["events_sha256"]:
        raise SystemExit("aborted prior events changed after finalization")
    source = pathlib.Path(marker["source_path"])
    if _sha256(source) != marker["source_sha256"]:
        raise SystemExit("aborted prior idea source changed after finalization")
    summary = _classify_events(_read_events(events_path), len(_read_ideas(source)))
    observed = {
        "started": summary["started"],
        "done": len(summary["done"]),
        "failed": len(summary["failed"]),
        "nonterminal": len(summary["nonterminal"]),
    }
    if observed != marker["counts"] or summary["nonterminal"] != marker["nonterminal_indexes"]:
        raise SystemExit("aborted prior event counts or nonterminal indexes changed")
    accepted_count = len(_read_id_lines(accepted_path)) if accepted_path else 0
    _assert_runtime_guards(marker.get("guards", {}), accepted_count)
    return marker


def finalize_aborted(
    args: argparse.Namespace,
) -> None:
    ideas = _read_ideas(args.source)
    events = _read_events(args.events)
    summary = _classify_events(events, len(ideas))
    if summary["engine_done"]:
        raise SystemExit("cannot finalize an aborted prior that emitted engine_done")
    expected = {
        "started": args.expect_started,
        "done": args.expect_done,
        "failed": args.expect_failed,
        "nonterminal": args.expect_nonterminal,
    }
    observed = {
        "started": summary["started"],
        "done": len(summary["done"]),
        "failed": len(summary["failed"]),
        "nonterminal": len(summary["nonterminal"]),
    }
    if observed != expected:
        raise SystemExit(f"aborted prior counts changed: {observed} != {expected}")
    event_hash = _sha256(args.events)
    if event_hash != args.expect_events_sha256:
        raise SystemExit(f"events SHA-256 changed: {event_hash} != {args.expect_events_sha256}")
    nonterminal = []
    for index in summary["nonterminal"]:
        idea_id = str(ideas[index]["id"])
        candidate = (args.run_dir / "tasks" / idea_id).resolve()
        _assert_candidate_complete(candidate)
        nonterminal.append({"index": index, "idea_id": idea_id, "prior_task_path": str(candidate)})
    guards: dict[str, Any] = {
        "pids": sorted(set(args.guard_pid or [])),
        "containers": sorted(set(args.guard_container or [])),
        "cwd_prefixes": [str(args.run_dir.resolve())],
        "forbid_yggdrasil_run": True,
    }
    if args.github_repo:
        if args.expected_open_prs is None or not args.pr_title_regex:
            raise SystemExit("GitHub guard requires repo, title regex, and expected open-PR count")
        guards["github"] = {
            "repo": args.github_repo,
            "title_regex": args.pr_title_regex,
            "head_prefix": args.pr_head_prefix or "",
            "baseline_open_prs": args.expected_open_prs,
        }
    _assert_runtime_guards(guards, 0)
    marker = {
        "schema_version": ABORT_SCHEMA,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "reason": args.reason,
        "run_dir": str(args.run_dir.resolve()),
        "events_path": str(args.events.resolve()),
        "events_sha256": event_hash,
        "source_path": str(args.source.resolve()),
        "source_sha256": _sha256(args.source),
        "counts": observed,
        "done_indexes": summary["done"],
        "failed_indexes": summary["failed"],
        "nonterminal_indexes": summary["nonterminal"],
        "nonterminal_tasks": nonterminal,
        "guards": guards,
    }
    if args.marker.exists():
        existing = _load_marker(args.marker)
        stable_keys = set(marker) - {"created_at"}
        if any(existing.get(key) != marker.get(key) for key in stable_keys):
            raise SystemExit("existing aborted marker does not match this finalization")
    else:
        _write_json_atomic(args.marker, marker)
    enqueue_nonterminal(args.marker, args.events, args.state)


def enqueue_nonterminal(marker_path: pathlib.Path, events_path: pathlib.Path, state_path: pathlib.Path) -> None:
    marker = _validate_marker(marker_path, events_path)
    state = _read_state(state_path)
    for task in marker["nonterminal_tasks"]:
        idea_id = str(task["idea_id"])
        candidate = pathlib.Path(task["prior_task_path"])
        _assert_candidate_complete(candidate)
        repair = dict(state.get(idea_id, {}))
        prior = repair.get("prior_task_path")
        if prior and pathlib.Path(prior).resolve() != candidate.resolve():
            raise SystemExit(f"repair state has a conflicting prior path for {idea_id}")
        repair["prior_task_path"] = str(candidate.resolve())
        repair.setdefault("continuation_feedback", PAUSE_FEEDBACK)
        state[idea_id] = repair
    _write_json_atomic(state_path, state)


def write_prior_ids(marker_path: pathlib.Path, events_path: pathlib.Path, output_path: pathlib.Path) -> None:
    marker = _validate_marker(marker_path, events_path)
    ideas = _read_ideas(pathlib.Path(marker["source_path"]))
    _write_lines_atomic(output_path, [str(ideas[index]["id"]) for index in marker["done_indexes"]])


def audit_state(
    source_path: pathlib.Path,
    accepted_path: pathlib.Path,
    prior_path: pathlib.Path,
    state_path: pathlib.Path,
    target_total: int,
) -> dict[str, Any]:
    idea_ids = [str(idea["id"]) for idea in _read_ideas(source_path)]
    known = set(idea_ids)
    accepted = set(_read_id_lines(accepted_path))
    prior = set(_read_id_lines(prior_path))
    repair = set(_read_state(state_path))
    for label, values in (("accepted", accepted), ("prior", prior), ("repair", repair)):
        unknown = sorted(values - known)
        if unknown:
            raise SystemExit(f"{label} ledger has unknown idea IDs: {unknown}")
    overlaps = {
        "accepted/prior": accepted & prior,
        "accepted/repair": accepted & repair,
        "prior/repair": prior & repair,
    }
    bad = {name: sorted(values) for name, values in overlaps.items() if values}
    if bad:
        raise SystemExit(f"continuation ledgers overlap: {bad}")
    total_success = len(prior) + len(accepted)
    if total_success > target_total:
        raise SystemExit(f"success ledgers exceed target: {total_success} > {target_total}")
    candidates = [idea_id for idea_id in idea_ids if idea_id not in prior | accepted]
    remaining = target_total - total_success
    if len(candidates) < remaining:
        raise SystemExit(f"only {len(candidates)} candidates remain for {remaining} successes")
    result = {
        "prior_successes": len(prior),
        "continuation_successes": len(accepted),
        "repair_pending": len(repair),
        "candidates": len(candidates),
        "remaining": remaining,
        "target_total": target_total,
    }
    print(json.dumps(result, sort_keys=True))
    return result


def inspect_prior(source_path: pathlib.Path, events_path: pathlib.Path, run_dir: pathlib.Path) -> None:
    ideas = _read_ideas(source_path)
    summary = _classify_events(_read_events(events_path), len(ideas))
    tasks = []
    for index in summary["nonterminal"]:
        idea_id = str(ideas[index]["id"])
        candidate = (run_dir / "tasks" / idea_id).resolve()
        missing = [relative for relative in REQUIRED_PRIOR_FILES if not (candidate / relative).is_file()]
        tasks.append(
            {
                "index": index,
                "idea_id": idea_id,
                "prior_task_path": str(candidate),
                "complete": not missing,
                "missing": missing,
            }
        )
    print(
        json.dumps(
            {
                "events_sha256": _sha256(events_path),
                "source_sha256": _sha256(source_path),
                "counts": {
                    "started": summary["started"],
                    "done": len(summary["done"]),
                    "failed": len(summary["failed"]),
                    "nonterminal": len(summary["nonterminal"]),
                    "engine_done": summary["engine_done"],
                },
                "nonterminal_tasks": tasks,
            },
            indent=2,
            sort_keys=True,
        )
    )


def render_source(
    source_path: pathlib.Path,
    accepted_path: pathlib.Path,
    prior_path: pathlib.Path,
    state_path: pathlib.Path,
    output_path: pathlib.Path,
) -> None:
    payload = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    ideas = _read_ideas(source_path)
    excluded = _read_ids(accepted_path) | _read_ids(prior_path)
    state = _read_state(state_path)
    rendered = []
    for original in ideas:
        idea_id = str(original["id"])
        if idea_id in excluded:
            continue
        idea = dict(original)
        idea.update(state.get(idea_id, {}))
        rendered.append(idea)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        yaml.safe_dump({"version": payload.get("version", 1), "ideas": rendered}, sort_keys=False, width=100),
        encoding="utf-8",
    )
    temporary.replace(output_path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    update = subparsers.add_parser("update")
    update.add_argument("source", type=pathlib.Path)
    update.add_argument("events", type=pathlib.Path)
    update.add_argument("run_dir", type=pathlib.Path)
    update.add_argument("state", type=pathlib.Path)
    render = subparsers.add_parser("render")
    render.add_argument("source", type=pathlib.Path)
    render.add_argument("accepted", type=pathlib.Path)
    render.add_argument("prior", type=pathlib.Path)
    render.add_argument("state", type=pathlib.Path)
    render.add_argument("output", type=pathlib.Path)
    finalize = subparsers.add_parser("finalize-aborted")
    finalize.add_argument("source", type=pathlib.Path)
    finalize.add_argument("events", type=pathlib.Path)
    finalize.add_argument("run_dir", type=pathlib.Path)
    finalize.add_argument("state", type=pathlib.Path)
    finalize.add_argument("marker", type=pathlib.Path)
    finalize.add_argument("--expect-events-sha256", required=True)
    finalize.add_argument("--expect-started", type=int, required=True)
    finalize.add_argument("--expect-done", type=int, required=True)
    finalize.add_argument("--expect-failed", type=int, required=True)
    finalize.add_argument("--expect-nonterminal", type=int, required=True)
    finalize.add_argument("--reason", required=True)
    finalize.add_argument("--guard-pid", type=int, action="append")
    finalize.add_argument("--guard-container", action="append")
    finalize.add_argument("--github-repo")
    finalize.add_argument("--pr-title-regex")
    finalize.add_argument("--pr-head-prefix")
    finalize.add_argument("--expected-open-prs", type=int)
    enqueue = subparsers.add_parser("enqueue-nonterminal")
    enqueue.add_argument("marker", type=pathlib.Path)
    enqueue.add_argument("events", type=pathlib.Path)
    enqueue.add_argument("state", type=pathlib.Path)
    verify = subparsers.add_parser("verify-aborted")
    verify.add_argument("marker", type=pathlib.Path)
    verify.add_argument("events", type=pathlib.Path)
    verify.add_argument("--accepted", type=pathlib.Path)
    prior = subparsers.add_parser("write-prior-ids")
    prior.add_argument("marker", type=pathlib.Path)
    prior.add_argument("events", type=pathlib.Path)
    prior.add_argument("output", type=pathlib.Path)
    audit = subparsers.add_parser("audit")
    audit.add_argument("source", type=pathlib.Path)
    audit.add_argument("accepted", type=pathlib.Path)
    audit.add_argument("prior", type=pathlib.Path)
    audit.add_argument("state", type=pathlib.Path)
    audit.add_argument("target_total", type=int)
    inspect = subparsers.add_parser("inspect-prior")
    inspect.add_argument("source", type=pathlib.Path)
    inspect.add_argument("events", type=pathlib.Path)
    inspect.add_argument("run_dir", type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "update":
        update_state(args.source, args.events, args.run_dir, args.state)
    elif args.command == "render":
        render_source(args.source, args.accepted, args.prior, args.state, args.output)
    elif args.command == "finalize-aborted":
        finalize_aborted(args)
    elif args.command == "enqueue-nonterminal":
        enqueue_nonterminal(args.marker, args.events, args.state)
    elif args.command == "verify-aborted":
        marker = _validate_marker(args.marker, args.events, args.accepted)
        print(json.dumps({"valid": True, "counts": marker["counts"]}, sort_keys=True))
    elif args.command == "write-prior-ids":
        write_prior_ids(args.marker, args.events, args.output)
    elif args.command == "audit":
        audit_state(args.source, args.accepted, args.prior, args.state, args.target_total)
    else:
        inspect_prior(args.source, args.events, args.run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
