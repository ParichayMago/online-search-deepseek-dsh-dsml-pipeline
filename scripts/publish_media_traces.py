#!/usr/bin/env python3
"""Publish three curated solver traces beside each Media campaign task.

The canonical task package remains under ``contributor_tasks``.  Trace artifacts
are committed separately under ``traces/<task-id>/<trial-id>`` on the existing
task PR branch, so package validators continue to see exactly fourteen files.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

TARGET_REPO = "Parsewave-internal/online-search"
PR_BASE = "main"
BRANCH_PREFIX = "online-search/"
TASK_ID = re.compile(r"[a-z0-9]+-[a-z0-9]+-[a-z0-9]+")
SENSITIVE_BYTES = (
    b"github_pat_",
    b"ghp_",
    b"AWS_SECRET_ACCESS_KEY",
    b"LLM_JUDGE_API_KEY",
    b"PWH_GITHUB_TOKEN",
    b"GITHUB_TOKEN=",
)
TRACE_FILES = {
    "agent/trajectory.json": "trajectory.json",
    "artifacts/report.md": "report.md",
    "verifier/judgment.json": "judgment.json",
    "verifier/score.txt": "score.txt",
    "verifier/reward.txt": "reward.txt",
}


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = item.relative_to(path).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256(item)))
    return digest.hexdigest()


def checked_source(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"trace artifact is missing or unsafe: {path}")
    payload = path.read_bytes()
    for marker in SENSITIVE_BYTES:
        if marker.lower() in payload.lower():
            raise ValueError(f"trace artifact contains sensitive marker {marker!r}: {path}")
    return payload


def latest_ygg_run(run_dir: Path) -> Path:
    events = sorted(
        (run_dir / "ygg").glob("*/events.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not events:
        raise ValueError(f"no Yggdrasil event log under {run_dir}")
    return events[0].parent


def solver_trace_dirs(run_dir: Path, task_id: str) -> list[Path]:
    harbor = latest_ygg_run(run_dir) / "harbor" / task_id
    candidates = sorted(
        path
        for path in harbor.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and (path / "agent" / "trajectory.json").is_file()
        and (path / "result.json").is_file()
    )
    if len(candidates) != 3:
        raise ValueError(f"expected exactly three solver traces for {task_id}, found {len(candidates)}")
    return candidates


def public_metrics(result_path: Path) -> dict[str, Any]:
    result = json.loads(checked_source(result_path))
    agent_result = result.get("agent_result") or {}
    agent_info = result.get("agent_info") or {}
    verifier_result = result.get("verifier_result") or {}
    rewards = verifier_result.get("rewards") or {}
    input_tokens = int(agent_result.get("n_input_tokens") or 0)
    cache_tokens = int(agent_result.get("n_cache_tokens") or 0)
    return {
        "trial_id": result.get("trial_name"),
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "agent": {
            "name": agent_info.get("name"),
            "version": agent_info.get("version"),
            "model": (agent_info.get("model_info") or {}).get("name"),
        },
        "tokens": {
            "input": input_tokens,
            "cache": cache_tokens,
            "fresh_input": input_tokens - cache_tokens,
            "output": int(agent_result.get("n_output_tokens") or 0),
        },
        "reward": rewards.get("reward"),
    }


def build_trace_tree(run_dir: Path, task_id: str, output: Path) -> dict[str, Any]:
    if not TASK_ID.fullmatch(task_id):
        raise ValueError(f"invalid task ID: {task_id}")
    if output.exists():
        raise ValueError(f"trace output already exists: {output}")
    output.mkdir(parents=True)
    trials: list[dict[str, Any]] = []
    for source in solver_trace_dirs(run_dir, task_id):
        trial_id = source.name
        if not re.fullmatch(rf"{re.escape(task_id)}__[A-Za-z0-9]+", trial_id):
            raise ValueError(f"unsafe trial ID: {trial_id}")
        destination = output / trial_id
        destination.mkdir()
        files: dict[str, str] = {}
        for source_name, destination_name in TRACE_FILES.items():
            source_file = source / source_name
            if source_name == "artifacts/report.md" and not source_file.exists():
                continue
            payload = checked_source(source_file)
            destination_file = destination / destination_name
            destination_file.write_bytes(payload)
            files[destination_name] = hashlib.sha256(payload).hexdigest()
        metrics = public_metrics(source / "result.json")
        metrics_path = destination / "metrics.json"
        metrics_path.write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        files["metrics.json"] = sha256(metrics_path)
        trials.append(
            {
                "trial_id": trial_id,
                "fresh_input_tokens": metrics["tokens"]["fresh_input"],
                "reward": metrics["reward"],
                "files": files,
            }
        )
    manifest = {
        "schema_version": 1,
        "task_id": task_id,
        "trace_count": len(trials),
        "trials": trials,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def run_json(command: list[str], *, cwd: Path | None = None) -> Any:
    output = subprocess.check_output(command, cwd=cwd, text=True, stderr=subprocess.DEVNULL)
    return json.loads(output)


def pr_identity(repo: str, pr_number: int) -> dict[str, Any]:
    return run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,state,headRefName,headRefOid,baseRefName,url",
        ]
    )


def validate_pr(identity: dict[str, Any], task_id: str, branch: str) -> str:
    if identity.get("state") != "OPEN":
        raise ValueError(f"PR #{identity.get('number')} is not open")
    if identity.get("baseRefName") != PR_BASE or identity.get("headRefName") != branch:
        raise ValueError(f"PR #{identity.get('number')} branch identity changed")
    if branch != f"{BRANCH_PREFIX}{task_id}":
        raise ValueError(f"unexpected task branch: {branch}")
    head = str(identity.get("headRefOid") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError(f"PR #{identity.get('number')} has an invalid head SHA")
    return head


def verify_pushed_head(
    repo: str,
    pr_number: int,
    task_id: str,
    branch: str,
    old_head: str,
    new_head: str,
    *,
    attempts: int = 12,
    delay: float = 1,
) -> None:
    for attempt in range(attempts):
        head = validate_pr(pr_identity(repo, pr_number), task_id, branch)
        if head == new_head:
            return
        if head != old_head:
            raise RuntimeError(f"PR #{pr_number} advanced to an unexpected head {head}")
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise RuntimeError(f"PR #{pr_number} did not expose the trace commit after {attempts} checks")


def publish_one(repo: str, row: dict[str, Any]) -> dict[str, Any]:
    task_id = str(row["idea_id"])
    branch = str(row["branch"])
    pr_number = int(row["pr_number"])
    run_dir = Path(str(row["run_dir"]))
    identity = pr_identity(repo, pr_number)
    old_head = validate_pr(identity, task_id, branch)
    with tempfile.TemporaryDirectory(prefix=f"media-traces-{task_id}-") as temporary:
        temporary_path = Path(temporary)
        prepared = temporary_path / "prepared" / task_id
        manifest = build_trace_tree(run_dir, task_id, prepared)
        prepared_digest = directory_digest(prepared)
        checkout = temporary_path / "repo"
        subprocess.run(
            [
                "gh",
                "repo",
                "clone",
                repo,
                str(checkout),
                "--",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                branch,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip() != old_head:
            raise RuntimeError(f"PR #{pr_number} advanced during trace preparation")
        if not (checkout / "contributor_tasks" / task_id).is_dir():
            raise ValueError(f"PR #{pr_number} does not contain contributor_tasks/{task_id}")
        destination = checkout / "traces" / task_id
        if destination.exists():
            if destination.is_symlink() or directory_digest(destination) != prepared_digest:
                raise ValueError(f"PR #{pr_number} already has different trace artifacts")
            return {
                "task_id": task_id,
                "pr_number": pr_number,
                "state": "noop",
                "commit": old_head,
                "trace_count": manifest["trace_count"],
                "digest": prepared_digest,
            }
        destination.parent.mkdir(exist_ok=True)
        shutil.copytree(prepared, destination)
        subprocess.run(
            ["git", "-C", str(checkout), "add", "--", f"traces/{task_id}"], check=True
        )
        changed = subprocess.check_output(
            ["git", "-C", str(checkout), "diff", "--cached", "--name-only"], text=True
        ).splitlines()
        if not changed or any(not name.startswith(f"traces/{task_id}/") for name in changed):
            raise ValueError(f"out-of-scope trace diff for PR #{pr_number}")
        current = pr_identity(repo, pr_number)
        if validate_pr(current, task_id, branch) != old_head:
            raise RuntimeError(f"PR #{pr_number} advanced before trace commit")
        subprocess.run(
            ["git", "-C", str(checkout), "config", "user.name", "yggdrasil-bot"], check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "config",
                "user.email",
                "yggdrasil-bot@parsewave.local",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "commit", "-m", f"Add solver traces for {task_id}"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        new_head = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
        ).strip()
        subprocess.run(
            ["git", "-C", str(checkout), "push", "origin", f"HEAD:refs/heads/{branch}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        verify_pushed_head(repo, pr_number, task_id, branch, old_head, new_head)
        return {
            "task_id": task_id,
            "pr_number": pr_number,
            "state": "updated",
            "commit": new_head,
            "trace_count": manifest["trace_count"],
            "digest": prepared_digest,
        }


def successful_rows(state_root: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(state_root / "campaign.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        return [
            dict(row)
            for row in connection.execute(
                """SELECT idea_id, branch, run_dir, pr_number, pr_url
                   FROM ideas WHERE status='succeeded' AND run_dir IS NOT NULL
                   AND pr_number IS NOT NULL ORDER BY finished_at"""
            )
        ]
    finally:
        connection.close()


def campaign_complete(state_root: Path) -> bool:
    connection = sqlite3.connect(state_root / "campaign.sqlite3")
    try:
        target = int(connection.execute("SELECT value FROM meta WHERE key='target'").fetchone()[0])
        succeeded = connection.execute(
            "SELECT count(*) FROM ideas WHERE status='succeeded'"
        ).fetchone()[0]
        return succeeded >= target
    finally:
        connection.close()


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "tasks": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("tasks"), dict):
        raise ValueError(f"invalid trace publication ledger: {path}")
    return payload


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sync_once(state_root: Path, repo: str, max_workers: int) -> dict[str, Any]:
    ledger_path = state_root / "trace-publication.json"
    ledger = load_ledger(ledger_path)
    rows = [row for row in successful_rows(state_root) if row["idea_id"] not in ledger["tasks"]]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_rows = {executor.submit(publish_one, repo, row): row for row in rows}
        for future in concurrent.futures.as_completed(future_rows):
            row = future_rows[future]
            try:
                result = future.result()
            except Exception as error:  # noqa: BLE001 - every task must remain retryable
                errors.append({"task_id": str(row["idea_id"]), "error": str(error)})
                continue
            result["published_at"] = utc_now()
            ledger["tasks"][result["task_id"]] = result
            results.append(result)
    save_ledger(ledger_path, ledger)
    return {
        "eligible": len(successful_rows(state_root)),
        "published": len(ledger["tasks"]),
        "updated_this_cycle": len(results),
        "errors": errors,
        "results": sorted(results, key=lambda item: item["task_id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("once", "monitor"))
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--repo", default=TARGET_REPO)
    parser.add_argument("--max-workers", type=int, default=4, choices=range(1, 8))
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")
    args.state_root.mkdir(parents=True, exist_ok=True)
    lock_path = args.state_root / "trace-publisher.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("trace publisher is already running") from None
        while True:
            summary = sync_once(args.state_root, args.repo, args.max_workers)
            print(json.dumps(summary, sort_keys=True), flush=True)
            if args.command == "once" or (
                campaign_complete(args.state_root)
                and summary["published"] >= summary["eligible"]
                and not summary["errors"]
            ):
                return 0 if not summary["errors"] else 1
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
