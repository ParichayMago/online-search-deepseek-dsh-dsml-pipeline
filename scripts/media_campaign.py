#!/usr/bin/env python3
"""Durable fixed-lane runner for online-search campaigns.

Runtime state lives outside the pipeline checkout so ``run.sh`` can keep its
clean-worktree guarantee.  Seven independent workers share one SQLite ledger;
each worker owns at most one Yggdrasil process, and each process owns one task
with exactly three parallel solver traces.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

TARGET_REPO = "Parsewave-internal/online-search"
PR_BASE = "main"
BRANCH_PREFIX = "online-search/"
PR_TITLE = re.compile(r"^\[online-search\] [0-9a-f]{6} [a-z0-9]+-[a-z0-9]+-[a-z0-9]+$")
DEPLOY_STEPS = ("deploy.gh_push", "deploy.open_pr")
REQUIRED_TASK_FILES = (
    "environment/Dockerfile",
    "instruction.md",
    "solution/evidence_graph.json",
    "solution/report.md",
    "solution/solve.sh",
    "task.toml",
    "tests/Dockerfile",
    "tests/reference/ground_truth.json",
    "tests/rubrics.json",
    "tests/test.sh",
    "tests/test_outputs.py",
    "tests/test_utils.py",
)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(state_root: Path) -> sqlite3.Connection:
    state_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(state_root / "campaign.sqlite3", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def emit(connection: sqlite3.Connection, kind: str, **details: Any) -> None:
    connection.execute(
        "INSERT INTO events(ts, kind, details_json) VALUES (?, ?, ?)",
        (utc_now(), kind, json.dumps(details, sort_keys=True)),
    )


def load_ideas(
    path: Path,
    *,
    expected_domain: str = "Media and journalism",
    expected_task_mode: str = "verification_and_abstention",
) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    ideas = payload.get("ideas") if isinstance(payload, dict) else None
    if not isinstance(ideas, list) or not ideas:
        raise ValueError(f"idea file has no non-empty ideas list: {path}")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in ideas:
        if not isinstance(raw, dict):
            raise TypeError("every idea must be a mapping")
        idea_id = str(raw.get("id", ""))
        if not re.fullmatch(r"[a-z0-9]+-[a-z0-9]+-[a-z0-9]+", idea_id):
            raise ValueError(f"idea ID must be a three-word slug: {idea_id!r}")
        if idea_id in seen:
            raise ValueError(f"duplicate idea ID: {idea_id}")
        if raw.get("domain") != expected_domain:
            raise ValueError(f"wrong domain for {idea_id}")
        if raw.get("task_mode") != expected_task_mode:
            raise ValueError(f"wrong task mode for {idea_id}")
        seen.add(idea_id)
        normalized.append(raw)
    return normalized


def initialize(
    state_root: Path,
    idea_file: Path,
    *,
    server: str,
    target: int,
    pipeline_commit: str,
    domain: str = "Media and journalism",
    task_mode: str = "verification_and_abstention",
    config_file: str = "config-media-journalism.yaml",
) -> None:
    ideas = load_ideas(
        idea_file, expected_domain=domain, expected_task_mode=task_mode
    )
    if target < 1 or target > len(ideas):
        raise ValueError("target must be between one and the idea count")
    connection = connect(state_root)
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ideas (
                position INTEGER PRIMARY KEY,
                idea_id TEXT NOT NULL UNIQUE,
                payload_yaml TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                lane INTEGER,
                attempt INTEGER NOT NULL DEFAULT 0,
                branch TEXT NOT NULL,
                run_dir TEXT,
                child_pid INTEGER,
                started_at TEXT,
                finished_at TEXT,
                pr_number INTEGER,
                pr_url TEXT,
                failure TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            """
        )
        existing = dict(connection.execute("SELECT key, value FROM meta"))
        wanted = {
            "schema_version": "media-campaign-v1",
            "server": server,
            "target": str(target),
            "pipeline_commit": pipeline_commit,
            "idea_source_sha256": hashlib.sha256(idea_file.read_bytes()).hexdigest(),
            "operator_pause": "0",
            "storage_hold": "0",
            "storage_state": "ok",
            "expected_domain": domain,
            "expected_task_mode": task_mode,
            "config_file": config_file,
        }
        if existing:
            immutable = ("schema_version", "server", "target", "pipeline_commit", "idea_source_sha256")
            mismatches = [key for key in immutable if existing.get(key) != wanted[key]]
            if mismatches:
                raise ValueError(f"existing campaign metadata mismatch: {', '.join(mismatches)}")
        else:
            connection.executemany(
                "INSERT INTO meta(key, value) VALUES (?, ?)", wanted.items()
            )
            for position, idea in enumerate(ideas):
                connection.execute(
                    """INSERT INTO ideas(position, idea_id, payload_yaml, branch)
                       VALUES (?, ?, ?, ?)""",
                    (
                        position,
                        idea["id"],
                        yaml.safe_dump(
                            {"version": 1, "ideas": [idea]},
                            sort_keys=False,
                            allow_unicode=True,
                            width=100,
                        ),
                        f"{BRANCH_PREFIX}{idea['id']}",
                    ),
                )
            emit(connection, "campaign_initialized", server=server, target=target, ideas=len(ideas))
        connection.commit()
    finally:
        connection.close()
    for directory in ("inputs", "runs", "worker-logs"):
        (state_root / directory).mkdir(parents=True, exist_ok=True)


def meta(connection: sqlite3.Connection) -> dict[str, str]:
    return dict(connection.execute("SELECT key, value FROM meta"))


def set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def storage_sample(path: Path) -> dict[str, float | int | str]:
    usage = shutil.disk_usage(path)
    stat = os.statvfs(path)
    inode_total = stat.f_files
    inode_free = stat.f_ffree
    inode_used_pct = 0.0 if inode_total == 0 else 100.0 * (inode_total - inode_free) / inode_total
    disk_used_pct = 100.0 * usage.used / usage.total
    free_gib = usage.free / (1024**3)
    if free_gib < 50 or disk_used_pct > 92 or inode_used_pct > 90:
        state = "emergency"
    elif free_gib < 75 or inode_used_pct > 85:
        state = "hold"
    elif free_gib < 100:
        state = "warning"
    else:
        state = "ok"
    return {
        "ts": utc_now(),
        "path": str(path),
        "free_gib": round(free_gib, 2),
        "disk_used_pct": round(disk_used_pct, 2),
        "inode_used_pct": round(inode_used_pct, 2),
        "state": state,
    }


def record_storage(state_root: Path, path: Path) -> dict[str, Any]:
    sample = storage_sample(path)
    connection = connect(state_root)
    try:
        previous = meta(connection).get("storage_state")
        set_meta(connection, "storage_state", str(sample["state"]))
        set_meta(connection, "storage_hold", "1" if sample["state"] in {"hold", "emergency"} else "0")
        set_meta(connection, "last_storage_sample", json.dumps(sample, sort_keys=True))
        if previous != sample["state"]:
            emit(connection, "storage_state_changed", previous=previous, **sample)
        connection.commit()
    finally:
        connection.close()
    return sample


def claim(state_root: Path, lane: int) -> sqlite3.Row | None:
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        campaign = meta(connection)
        if campaign.get("operator_pause") == "1" or campaign.get("storage_hold") == "1":
            connection.rollback()
            return None
        target = int(campaign["target"])
        succeeded = connection.execute(
            "SELECT count(*) FROM ideas WHERE status='succeeded'"
        ).fetchone()[0]
        running = connection.execute(
            "SELECT count(*) FROM ideas WHERE status IN ('running','blocked_deploy')"
        ).fetchone()[0]
        if succeeded >= target or succeeded + running >= target:
            connection.rollback()
            return None
        row = connection.execute(
            "SELECT * FROM ideas WHERE status='pending' ORDER BY position LIMIT 1"
        ).fetchone()
        if row is None:
            connection.rollback()
            return None
        now = utc_now()
        connection.execute(
            """UPDATE ideas SET status='running', lane=?, attempt=attempt+1,
               started_at=?, finished_at=NULL, failure=NULL WHERE idea_id=?""",
            (lane, now, row["idea_id"]),
        )
        emit(connection, "idea_claimed", idea_id=row["idea_id"], lane=lane)
        connection.commit()
        return connection.execute(
            "SELECT * FROM ideas WHERE idea_id=?", (row["idea_id"],)
        ).fetchone()
    finally:
        connection.close()


def update_running(
    state_root: Path,
    idea_id: str,
    *,
    run_dir: Path,
    child_pid: int,
) -> None:
    connection = connect(state_root)
    try:
        connection.execute(
            "UPDATE ideas SET run_dir=?, child_pid=? WHERE idea_id=? AND status='running'",
            (str(run_dir), child_pid, idea_id),
        )
        connection.commit()
    finally:
        connection.close()


def finish(
    state_root: Path,
    idea_id: str,
    status: str,
    *,
    failure: str | None = None,
    pr: dict[str, Any] | None = None,
) -> None:
    if status not in {"succeeded", "failed", "blocked_deploy"}:
        raise ValueError(f"bad terminal status: {status}")
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """UPDATE ideas SET status=?, child_pid=NULL, finished_at=?, failure=?,
               pr_number=?, pr_url=? WHERE idea_id=?""",
            (
                status,
                utc_now(),
                failure,
                None if pr is None else int(pr["number"]),
                None if pr is None else str(pr["url"]),
                idea_id,
            ),
        )
        emit(
            connection,
            "idea_finished",
            idea_id=idea_id,
            status=status,
            failure=failure,
            pr_url=None if pr is None else pr["url"],
        )
        connection.commit()
    finally:
        connection.close()


def run_json(command: list[str], *, cwd: Path | None = None) -> Any:
    output = subprocess.check_output(command, cwd=cwd, text=True, stderr=subprocess.DEVNULL)
    return json.loads(output)


def find_open_pr(branch: str) -> dict[str, Any] | None:
    try:
        rows = run_json(
            [
                "gh", "pr", "list", "--repo", TARGET_REPO, "--state", "open",
                "--head", branch, "--json", "number,url,title,headRefName,baseRefName",
            ]
        )
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    exact = [
        row for row in rows
        if row.get("headRefName") == branch and row.get("baseRefName") == PR_BASE
    ]
    if len(exact) != 1:
        return None
    if not PR_TITLE.fullmatch(str(exact[0].get("title", ""))):
        return None
    return exact[0]


def poll_open_pr(branch: str, attempts: int = 12, delay: int = 5) -> dict[str, Any] | None:
    for attempt in range(attempts):
        found = find_open_pr(branch)
        if found is not None:
            return found
        if attempt + 1 < attempts:
            time.sleep(delay)
    return None


def remote_branch_exists(branch: str) -> bool:
    encoded = branch.replace("/", "%2F")
    result = subprocess.run(
        ["gh", "api", f"repos/{TARGET_REPO}/git/ref/heads/{encoded}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def deterministic_title(idea_id: str) -> str:
    for nonce in range(1000):
        token = hashlib.sha256(f"online-search:{idea_id}:{nonce}".encode()).hexdigest()[:6]
        prefix = f"[online-search] {token}"
        result = subprocess.run(
            [
                "gh", "pr", "list", "--repo", TARGET_REPO, "--state", "all",
                "--search", f"{prefix} in:title", "--limit", "1", "--json", "number",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "[]":
            return f"{prefix} {idea_id}"
    raise RuntimeError("could not allocate a collision-free PR title")


def create_pr(branch: str, idea_id: str, *, cwd: Path | None = None) -> dict[str, Any] | None:
    title = deterministic_title(idea_id)
    result = subprocess.run(
        [
            "gh", "pr", "create", "--repo", TARGET_REPO, "--head", branch,
            "--base", PR_BASE, "--title", title,
            "--body", "Online-search task generated by the one-pass pipeline.",
        ],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return None
    return poll_open_pr(branch)


def latest_events(run_dir: Path) -> tuple[list[dict[str, Any]], Path | None]:
    files = sorted(
        (run_dir / "ygg").glob("*/events.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return [], None
    events: list[dict[str, Any]] = []
    for line in files[0].read_text(encoding="utf-8", errors="replace").splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            events.append(json.loads(line))
    return events, files[0]


def task_failure(events: list[dict[str, Any]]) -> str | None:
    failures = [event for event in events if event.get("event") == "task_failed"]
    return None if not failures else str(failures[-1].get("error") or failures[-1].get("message") or "task failed")


def completed_task_dir(events_path: Path | None, idea_id: str) -> Path | None:
    if events_path is None:
        return None
    candidate = events_path.parent / "tasks" / idea_id
    return candidate if candidate.is_dir() else None


def push_completed_task(task_dir: Path, branch: str, idea_id: str) -> bool:
    if remote_branch_exists(branch):
        return True
    with tempfile.TemporaryDirectory(prefix=f"media-deploy-{idea_id}-") as temporary:
        checkout = Path(temporary) / "repo"
        clone = subprocess.run(
            ["gh", "repo", "clone", TARGET_REPO, str(checkout), "--", "--depth", "1", "--branch", PR_BASE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if clone.returncode != 0:
            return False
        subprocess.check_call(["git", "-C", str(checkout), "checkout", "-b", branch])
        destination = checkout / "contributor_tasks" / idea_id
        if destination.exists():
            return False
        shutil.copytree(task_dir, destination)
        subprocess.check_call(
            ["git", "-C", str(checkout), "add", "--", f"contributor_tasks/{idea_id}"]
        )
        subprocess.check_call(
            ["git", "-C", str(checkout), "config", "user.name", "yggdrasil-bot"]
        )
        subprocess.check_call(
            ["git", "-C", str(checkout), "config", "user.email", "yggdrasil-bot@parsewave.local"]
        )
        subprocess.check_call(
            ["git", "-C", str(checkout), "commit", "-m", f"Add task {idea_id}"]
        )
        pushed = subprocess.run(
            ["git", "-C", str(checkout), "push", "origin", f"HEAD:refs/heads/{branch}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return pushed.returncode == 0


def recover_deployment(
    task_dir: Path | None,
    branch: str,
    idea_id: str,
    *,
    attempts: int = 12,
) -> dict[str, Any] | None:
    for attempt in range(attempts):
        existing = find_open_pr(branch)
        if existing is not None:
            return existing
        try:
            if not remote_branch_exists(branch) and (
                task_dir is None or not push_completed_task(task_dir, branch, idea_id)
            ):
                raise RuntimeError("task branch is not yet available")
            created = create_pr(branch, idea_id)
            if created is not None:
                return created
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        time.sleep(min(300, 5 * (2**attempt)))
    return None


def blocked_for_lane(state_root: Path, lane: int) -> sqlite3.Row | None:
    connection = connect(state_root)
    try:
        return connection.execute(
            """SELECT * FROM ideas WHERE status='blocked_deploy' AND lane=?
               ORDER BY started_at LIMIT 1""",
            (lane,),
        ).fetchone()
    finally:
        connection.close()


def running_for_lane(state_root: Path, lane: int) -> sqlite3.Row | None:
    connection = connect(state_root)
    try:
        return connection.execute(
            "SELECT * FROM ideas WHERE status='running' AND lane=? ORDER BY started_at LIMIT 1",
            (lane,),
        ).fetchone()
    finally:
        connection.close()


def pid_is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def reconcile_interrupted_run(state_root: Path, row: sqlite3.Row) -> None:
    idea_id = str(row["idea_id"])
    branch = str(row["branch"])
    pr = find_open_pr(branch)
    if pr is not None:
        finish(state_root, idea_id, "succeeded", pr=pr)
        return
    run_dir = Path(str(row["run_dir"])) if row["run_dir"] else None
    events, _ = latest_events(run_dir) if run_dir is not None else ([], None)
    failure = task_failure(events)
    if remote_branch_exists(branch) or (
        failure is not None and any(step in failure for step in DEPLOY_STEPS)
    ):
        finish(
            state_root,
            idea_id,
            "blocked_deploy",
            failure=failure or "remote branch exists without a verified open PR",
        )
        return
    if failure is not None:
        finish(state_root, idea_id, "failed", failure=failure[-4000:])
        return
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """UPDATE ideas SET status='pending', lane=NULL, child_pid=NULL,
               finished_at=NULL, failure='interrupted before a terminal task event'
               WHERE idea_id=? AND status='running'""",
            (idea_id,),
        )
        emit(connection, "interrupted_run_requeued", idea_id=idea_id)
        connection.commit()
    finally:
        connection.close()


def retry_blocked_deployment(state_root: Path, row: sqlite3.Row) -> bool:
    run_dir = Path(str(row["run_dir"]))
    _, events_path = latest_events(run_dir)
    pr = recover_deployment(
        completed_task_dir(events_path, str(row["idea_id"])),
        str(row["branch"]),
        str(row["idea_id"]),
        attempts=1,
    )
    if pr is None:
        return False
    finish(state_root, str(row["idea_id"]), "succeeded", pr=pr)
    return True


def worker(
    state_root: Path,
    pipeline_dir: Path,
    *,
    lane: int,
    poll_seconds: int,
    max_candidates: int = 0,
) -> int:
    worker_log = state_root / "worker-logs" / f"lane-{lane:02d}.log"
    processed = 0
    while True:
        record_storage(state_root, Path("/"))
        snapshot = campaign_status(state_root)
        if snapshot["succeeded"] >= snapshot["target"]:
            return 0
        if snapshot["operator_pause"] or snapshot["storage_state"] in {"hold", "emergency"}:
            time.sleep(poll_seconds)
            continue
        interrupted = running_for_lane(state_root, lane)
        if interrupted is not None:
            if pid_is_alive(interrupted["child_pid"]):
                time.sleep(poll_seconds)
                continue
            reconcile_interrupted_run(state_root, interrupted)
            continue
        blocked = blocked_for_lane(state_root, lane)
        if blocked is not None:
            if retry_blocked_deployment(state_root, blocked):
                processed += 1
                if max_candidates and processed >= max_candidates:
                    return 0
                continue
            time.sleep(poll_seconds)
            continue
        row = claim(state_root, lane)
        if row is None:
            snapshot = campaign_status(state_root)
            if snapshot["succeeded"] >= snapshot["target"]:
                return 0
            if snapshot["pending"] == 0 and snapshot["running"] == 0:
                return 1
            time.sleep(poll_seconds)
            continue

        idea_id = str(row["idea_id"])
        branch = str(row["branch"])
        input_path = state_root / "inputs" / f"{idea_id}.yaml"
        input_path.write_text(str(row["payload_yaml"]), encoding="utf-8")
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
        run_dir = state_root / "runs" / idea_id / f"{stamp}-lane-{lane:02d}"
        run_dir.mkdir(parents=True, exist_ok=False)
        environment = os.environ.copy()
        environment["DORAEMON_IDEA_SOURCE"] = str(input_path)
        connection = connect(state_root)
        try:
            environment["DORAEMON_EXPECTED_PIPELINE_COMMIT"] = meta(connection)["pipeline_commit"]
        finally:
            connection.close()
        connection = connect(state_root)
        try:
            config_file = meta(connection).get(
                "config_file", "config-media-journalism.yaml"
            )
        finally:
            connection.close()
        command = [
            str(pipeline_dir / "run.sh"), "--config", str(pipeline_dir / config_file),
            "--count", "1", "--target-successes", "1", "--concurrency", "1",
            "--conc-trials", "3", "--logs-dir", str(run_dir / "ygg"),
        ]
        with (run_dir / "runner.log").open("ab", buffering=0) as output:
            process = subprocess.Popen(
                command,
                cwd=pipeline_dir,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            update_running(state_root, idea_id, run_dir=run_dir, child_pid=process.pid)
            return_code = process.wait()
        events, events_path = latest_events(run_dir)
        pr = poll_open_pr(branch)
        if pr is not None:
            finish(state_root, idea_id, "succeeded", pr=pr)
            processed += 1
            if max_candidates and processed >= max_candidates:
                return 0
            continue
        failure = task_failure(events)
        deploy_failure = failure is not None and any(step in failure for step in DEPLOY_STEPS)
        if deploy_failure or (return_code == 0 and failure is None):
            pr = recover_deployment(completed_task_dir(events_path, idea_id), branch, idea_id)
            if pr is not None:
                finish(state_root, idea_id, "succeeded", pr=pr)
                processed += 1
                if max_candidates and processed >= max_candidates:
                    return 0
                continue
            finish(
                state_root,
                idea_id,
                "blocked_deploy",
                failure=failure or "pipeline exited without a verifiable open PR",
            )
            with worker_log.open("a", encoding="utf-8") as log:
                log.write(f"{utc_now()} blocked deployment for {idea_id}; lane remains occupied\n")
            time.sleep(poll_seconds)
            continue
        if failure is not None:
            finish(state_root, idea_id, "failed", failure=failure[-4000:])
            processed += 1
            if max_candidates and processed >= max_candidates:
                return 1
            continue
        finish(
            state_root,
            idea_id,
            "blocked_deploy",
            failure=f"infrastructure failure before terminal task event; exit={return_code}",
        )
        return 2


def campaign_status(state_root: Path) -> dict[str, Any]:
    connection = connect(state_root)
    try:
        campaign = meta(connection)
        counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                "SELECT status, count(*) AS count FROM ideas GROUP BY status"
            )
        }
        active = [
            dict(row)
            for row in connection.execute(
                """SELECT idea_id, status, lane, started_at, run_dir, failure
                   FROM ideas WHERE status IN ('running','blocked_deploy') ORDER BY lane"""
            )
        ]
        return {
            "server": campaign.get("server"),
            "target": int(campaign.get("target", "0")),
            "pipeline_commit": campaign.get("pipeline_commit"),
            "succeeded": counts.get("succeeded", 0),
            "failed": counts.get("failed", 0),
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0) + counts.get("blocked_deploy", 0),
            "blocked_deploy": counts.get("blocked_deploy", 0),
            "exported": counts.get("exported", 0),
            "operator_pause": campaign.get("operator_pause") == "1",
            "storage_state": campaign.get("storage_state"),
            "last_storage_sample": json.loads(campaign.get("last_storage_sample", "null")),
            "active": active,
        }
    finally:
        connection.close()


def set_pause(state_root: Path, paused: bool) -> None:
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        set_meta(connection, "operator_pause", "1" if paused else "0")
        emit(connection, "operator_pause_changed", paused=paused)
        connection.commit()
    finally:
        connection.close()


def monitor(state_root: Path, path: Path, interval: int) -> None:
    while True:
        sample = record_storage(state_root, path)
        print(json.dumps(sample, sort_keys=True), flush=True)
        time.sleep(interval)


def export_pending(state_root: Path, output: Path, count: int) -> None:
    if count < 1:
        raise ValueError("export count must be positive")
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT idea_id, payload_yaml FROM ideas WHERE status='pending' ORDER BY position LIMIT ?",
            (count,),
        ).fetchall()
        if len(rows) != count:
            raise ValueError(f"requested {count} exports but only {len(rows)} pending ideas remain")
        ideas = [yaml.safe_load(row["payload_yaml"])["ideas"][0] for row in rows]
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            yaml.safe_dump({"version": 1, "ideas": ideas}, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        os.replace(temporary, output)
        connection.executemany(
            "UPDATE ideas SET status='exported', finished_at=? WHERE idea_id=?",
            [(utc_now(), row["idea_id"]) for row in rows],
        )
        emit(connection, "pending_exported", count=count, output=str(output))
        connection.commit()
    finally:
        connection.close()


def add_seeds(state_root: Path, idea_file: Path, target_increment: int) -> None:
    connection = connect(state_root)
    try:
        campaign = meta(connection)
    finally:
        connection.close()
    ideas = load_ideas(
        idea_file,
        expected_domain=campaign.get("expected_domain", "Media and journalism"),
        expected_task_mode=campaign.get(
            "expected_task_mode", "verification_and_abstention"
        ),
    )
    if target_increment < 0 or target_increment > len(ideas):
        raise ValueError("target increment must be nonnegative and fit imported seed count")
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = {row[0] for row in connection.execute("SELECT idea_id FROM ideas")}
        duplicate = existing.intersection(idea["id"] for idea in ideas)
        if duplicate:
            raise ValueError(f"import duplicates existing ideas: {sorted(duplicate)}")
        position = connection.execute("SELECT coalesce(max(position), -1) + 1 FROM ideas").fetchone()[0]
        for offset, idea in enumerate(ideas):
            connection.execute(
                "INSERT INTO ideas(position, idea_id, payload_yaml, branch) VALUES (?, ?, ?, ?)",
                (
                    position + offset,
                    idea["id"],
                    yaml.safe_dump({"version": 1, "ideas": [idea]}, sort_keys=False, allow_unicode=True, width=100),
                    f"{BRANCH_PREFIX}{idea['id']}",
                ),
            )
        campaign = meta(connection)
        set_meta(connection, "target", str(int(campaign["target"]) + target_increment))
        emit(connection, "seeds_imported", count=len(ideas), target_increment=target_increment)
        connection.commit()
    finally:
        connection.close()


def requeue_bootstrap_failures(state_root: Path) -> int:
    connection = connect(state_root)
    requeued = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """SELECT * FROM ideas WHERE status='blocked_deploy'
               AND failure LIKE 'infrastructure failure before terminal task event%'"""
        ).fetchall()
        for row in rows:
            run_dir = Path(str(row["run_dir"])) if row["run_dir"] else None
            events, _ = latest_events(run_dir) if run_dir is not None else ([], None)
            if any(event.get("event") == "task_start" for event in events):
                continue
            if find_open_pr(str(row["branch"])) is not None or remote_branch_exists(
                str(row["branch"])
            ):
                continue
            connection.execute(
                """UPDATE ideas SET status='pending', lane=NULL, child_pid=NULL,
                   run_dir=NULL, started_at=NULL, finished_at=NULL,
                   failure='bootstrap failure requeued without task execution'
                   WHERE idea_id=? AND status='blocked_deploy'""",
                (row["idea_id"],),
            )
            emit(
                connection,
                "bootstrap_failure_requeued",
                idea_id=row["idea_id"],
                previous_run_dir=row["run_dir"],
            )
            requeued += 1
        connection.commit()
    finally:
        connection.close()
    return requeued


def _complete_task_tree(path: Path) -> bool:
    return path.is_dir() and all((path / relative).is_file() for relative in REQUIRED_TASK_FILES)


def same_package_retry_candidate(row: sqlite3.Row) -> tuple[Path, str]:
    """Resolve a terminal candidate and the earliest safe downstream stage.

    A local Codex build can leave the complete package one level below the
    promoted task root.  Accept that exact preserved tree, but never repair,
    merge, or rebuild it here.
    """
    run_dir = Path(str(row["run_dir"] or ""))
    events, events_path = latest_events(run_dir)
    failure = task_failure(events) or str(row["failure"] or "")
    candidate = completed_task_dir(events_path, str(row["idea_id"]))
    if candidate is None:
        raise ValueError("failed row has no preserved task directory")
    if not _complete_task_tree(candidate):
        nested = candidate / "output" / str(row["idea_id"])
        if not _complete_task_tree(nested):
            raise ValueError("failed row has no complete preserved task package")
        candidate = nested

    if "Step 'preflight.required_files' failed" in failure or (
        "Step 'preflight.word_limit' failed" in failure
    ):
        return candidate.resolve(), "preflight"
    if any(
        marker in failure
        for marker in (
            "Step 'doraemon.validate_live_task' failed",
            "Step 'oracle.score_golden' failed",
            "Step 'oracle.score_nop' failed",
            "Step 'difficulty.solver_lane' failed",
            "Step 'postbuild.cleanup' failed",
        )
    ):
        return candidate.resolve(), "capture"
    raise ValueError("failure is not eligible for downstream-only package retry")


def prepare_same_package_retry(
    state_root: Path,
    idea_id: str,
    *,
    expected_lane: int,
) -> tuple[sqlite3.Row, Path, str]:
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        campaign = meta(connection)
        if campaign.get("operator_pause") != "1":
            raise ValueError("campaign must be operator-paused")
        if campaign.get("storage_hold") == "1" or campaign.get("storage_state") in {
            "hold",
            "emergency",
        }:
            raise ValueError("campaign storage hold prevents package retry")
        row = connection.execute(
            "SELECT * FROM ideas WHERE idea_id=?", (idea_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown campaign idea: {idea_id}")
        if row["status"] != "failed":
            raise ValueError(f"idea is not terminally failed: {row['status']}")
        if int(row["lane"] or 0) != expected_lane:
            raise ValueError(
                f"lane affinity changed: expected {expected_lane}, found {row['lane']}"
            )
        if pid_is_alive(row["child_pid"]):
            raise ValueError("failed idea still has a live child process")
        occupied = connection.execute(
            """SELECT idea_id FROM ideas
               WHERE lane=? AND status IN ('running', 'blocked_deploy')""",
            (expected_lane,),
        ).fetchall()
        if occupied:
            raise ValueError(
                f"lane {expected_lane} is occupied by "
                f"{', '.join(str(item['idea_id']) for item in occupied)}"
            )
        candidate, from_stage = same_package_retry_candidate(row)
        if find_open_pr(str(row["branch"])) is not None or remote_branch_exists(
            str(row["branch"])
        ):
            raise ValueError("task already has a remote branch or open PR")
        return row, candidate, from_stage
    finally:
        connection.rollback()
        connection.close()


def retry_failed_package(
    state_root: Path,
    pipeline_dir: Path,
    idea_id: str,
    *,
    expected_lane: int,
) -> bool:
    """Run current downstream gates on one exact preserved task package."""
    row, candidate, from_stage = prepare_same_package_retry(
        state_root,
        idea_id,
        expected_lane=expected_lane,
    )
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    logs_dir = Path(str(row["run_dir"])) / "same-package-retries" / stamp
    logs_dir.mkdir(parents=True, exist_ok=False)
    connection = connect(state_root)
    try:
        config_file = meta(connection).get("config_file", "config-media-journalism.yaml")
    finally:
        connection.close()
    command = [
        str(pipeline_dir / "run.sh"),
        "--config",
        str(pipeline_dir / config_file),
        "--resume-package",
        str(candidate),
        "--resume-task-id",
        idea_id,
        "--resume-from-stage",
        from_stage,
        "--logs-dir",
        str(logs_dir),
    ]
    environment = os.environ.copy()
    connection = connect(state_root)
    try:
        environment["DORAEMON_EXPECTED_PIPELINE_COMMIT"] = meta(connection)[
            "pipeline_commit"
        ]
    finally:
        connection.close()

    with (logs_dir / "runner.log").open("ab", buffering=0) as output:
        process = subprocess.Popen(
            command,
            cwd=pipeline_dir,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        connection = connect(state_root)
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT status, lane FROM ideas WHERE idea_id=?", (idea_id,)
            ).fetchone()
            if current is None or current["status"] != "failed" or current["lane"] != expected_lane:
                process.terminate()
                raise ValueError("failed idea changed before package retry could start")
            connection.execute(
                """UPDATE ideas SET status='running', child_pid=?, failure=NULL,
                   finished_at=NULL WHERE idea_id=? AND status='failed'""",
                (process.pid, idea_id),
            )
            emit(
                connection,
                "same_package_retry_started",
                idea_id=idea_id,
                lane=expected_lane,
                candidate=str(candidate),
                from_stage=from_stage,
                child_pid=process.pid,
            )
            connection.commit()
        finally:
            connection.close()
        return_code = process.wait()

    pr = poll_open_pr(str(row["branch"]))
    if pr is not None:
        finish(state_root, idea_id, "succeeded", pr=pr)
        return True
    failure = f"same-package downstream retry exited {return_code}; see {logs_dir / 'runner.log'}"
    if remote_branch_exists(str(row["branch"])):
        finish(state_root, idea_id, "blocked_deploy", failure=failure)
    else:
        finish(state_root, idea_id, "failed", failure=failure)
    return False


def update_pipeline_commit(
    state_root: Path,
    pipeline_dir: Path,
    *,
    expected_old: str,
) -> str:
    actual = subprocess.check_output(
        ["git", "-C", str(pipeline_dir), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.check_output(
        ["git", "-C", str(pipeline_dir), "status", "--porcelain"], text=True
    ).strip():
        raise ValueError("pipeline worktree must be clean before updating campaign commit")
    connection = connect(state_root)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = meta(connection).get("pipeline_commit")
        if current != expected_old:
            raise ValueError(
                f"campaign commit changed: expected {expected_old}, found {current}"
            )
        set_meta(connection, "pipeline_commit", actual)
        emit(
            connection,
            "pipeline_commit_updated",
            previous=expected_old,
            current=actual,
        )
        connection.commit()
    finally:
        connection.close()
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--state-root", type=Path, required=True)
    init_parser.add_argument("--idea-file", type=Path, required=True)
    init_parser.add_argument("--server", required=True)
    init_parser.add_argument("--target", type=int, required=True)
    init_parser.add_argument("--pipeline-commit", required=True)
    init_parser.add_argument("--domain", default="Media and journalism")
    init_parser.add_argument("--task-mode", default="verification_and_abstention")
    init_parser.add_argument("--config-file", default="config-media-journalism.yaml")

    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--state-root", type=Path, required=True)
    worker_parser.add_argument("--pipeline-dir", type=Path, required=True)
    worker_parser.add_argument("--lane", type=int, choices=range(1, 8), required=True)
    worker_parser.add_argument("--poll-seconds", type=int, default=60)
    worker_parser.add_argument("--max-candidates", type=int, default=0)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state-root", type=Path, required=True)

    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--state-root", type=Path, required=True)
    monitor_parser.add_argument("--path", type=Path, default=Path("/"))
    monitor_parser.add_argument("--interval", type=int, default=60)

    for name, paused in (("pause", True), ("resume", False)):
        pause_parser = subparsers.add_parser(name)
        pause_parser.add_argument("--state-root", type=Path, required=True)
        pause_parser.set_defaults(paused=paused)

    export_parser = subparsers.add_parser("export-pending")
    export_parser.add_argument("--state-root", type=Path, required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    export_parser.add_argument("--count", type=int, required=True)

    import_parser = subparsers.add_parser("add-seeds")
    import_parser.add_argument("--state-root", type=Path, required=True)
    import_parser.add_argument("--idea-file", type=Path, required=True)
    import_parser.add_argument("--target-increment", type=int, required=True)

    requeue_parser = subparsers.add_parser("requeue-bootstrap")
    requeue_parser.add_argument("--state-root", type=Path, required=True)

    package_retry_parser = subparsers.add_parser("retry-failed-package")
    package_retry_parser.add_argument("--state-root", type=Path, required=True)
    package_retry_parser.add_argument("--pipeline-dir", type=Path, required=True)
    package_retry_parser.add_argument("--idea-id", required=True)
    package_retry_parser.add_argument(
        "--expected-lane", type=int, choices=range(1, 8), required=True
    )

    commit_parser = subparsers.add_parser("update-commit")
    commit_parser.add_argument("--state-root", type=Path, required=True)
    commit_parser.add_argument("--pipeline-dir", type=Path, required=True)
    commit_parser.add_argument("--expected-old", required=True)

    args = parser.parse_args()
    if args.command == "init":
        initialize(
            args.state_root,
            args.idea_file,
            server=args.server,
            target=args.target,
            pipeline_commit=args.pipeline_commit,
            domain=args.domain,
            task_mode=args.task_mode,
            config_file=args.config_file,
        )
    elif args.command == "worker":
        return worker(
            args.state_root,
            args.pipeline_dir.resolve(),
            lane=args.lane,
            poll_seconds=args.poll_seconds,
            max_candidates=args.max_candidates,
        )
    elif args.command == "status":
        print(json.dumps(campaign_status(args.state_root), indent=2, sort_keys=True))
    elif args.command == "monitor":
        monitor(args.state_root, args.path, args.interval)
    elif args.command in {"pause", "resume"}:
        set_pause(args.state_root, args.paused)
    elif args.command == "export-pending":
        export_pending(args.state_root, args.output, args.count)
    elif args.command == "add-seeds":
        add_seeds(args.state_root, args.idea_file, args.target_increment)
    elif args.command == "requeue-bootstrap":
        print(requeue_bootstrap_failures(args.state_root))
    elif args.command == "retry-failed-package":
        return 0 if retry_failed_package(
            args.state_root,
            args.pipeline_dir.resolve(),
            args.idea_id,
            expected_lane=args.expected_lane,
        ) else 1
    elif args.command == "update-commit":
        print(
            update_pipeline_commit(
                args.state_root,
                args.pipeline_dir.resolve(),
                expected_old=args.expected_old,
            )
        )
    return 0


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
    sys.exit(130)
