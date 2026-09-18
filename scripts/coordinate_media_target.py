#!/usr/bin/env python3
"""Coordinate an exact success target across two remote Media campaign ledgers."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Server:
    label: str
    host: str
    port: int
    state_root: str


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_server(value: str) -> Server:
    parts = value.split(",", 3)
    if len(parts) != 4 or parts[0] not in {"a", "b"}:
        raise argparse.ArgumentTypeError("server must be LABEL,HOST,PORT,STATE_ROOT")
    return Server(parts[0], parts[1], int(parts[2]), parts[3])


def remote(server: Server, script: str) -> str:
    payload = base64.b64encode(script.encode()).decode()
    return subprocess.check_output(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-p",
            str(server.port),
            f"ubuntu@{server.host}",
            f"echo {payload} | base64 -d | bash -l",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=30,
    ).strip()


def snapshot(server: Server) -> dict[str, Any]:
    script = f"""python3 - {server.state_root}/campaign.sqlite3 {server.state_root}/trace-publication.json <<'PY'
import json,sqlite3,sys
c=sqlite3.connect(sys.argv[1]); c.row_factory=sqlite3.Row
counts={{row[0]:row[1] for row in c.execute('select status,count(*) from ideas group by status')}}
meta=dict(c.execute('select key,value from meta'))
active=[dict(row) for row in c.execute("select idea_id,status,lane,child_pid,run_dir from ideas where status in ('running','blocked_deploy') order by lane")]
try:
    published=len(json.load(open(sys.argv[2]))['tasks'])
except FileNotFoundError:
    published=0
print(json.dumps({{
 'label':meta['server'], 'target':int(meta['target']),
 'paused':meta.get('operator_pause')=='1', 'succeeded':counts.get('succeeded',0),
 'failed':counts.get('failed',0), 'running':counts.get('running',0)+counts.get('blocked_deploy',0),
 'blocked':counts.get('blocked_deploy',0), 'pending':counts.get('pending',0),
 'traces_published':published, 'active':active,
}},sort_keys=True))
PY"""
    return json.loads(remote(server, script))


def resume_reserve(server: Server, task_id: str, pid: int) -> None:
    script = f"""set -euo pipefail
STATE={server.state_root}
python3 - "$STATE/campaign.sqlite3" {task_id} {pid} <<'PY'
import os,signal,sqlite3,sys
c=sqlite3.connect(sys.argv[1])
r=c.execute("select child_pid,status from ideas where idea_id=?",(sys.argv[2],)).fetchone()
if r != (int(sys.argv[3]),'running'): raise SystemExit('reserve identity changed')
os.killpg(int(sys.argv[3]),signal.SIGCONT)
PY"""
    remote(server, script)


def cancel_reserve(server: Server, task_id: str, pid: int) -> None:
    script = f"""set -euo pipefail
STATE={server.state_root}
python3 - "$STATE/campaign.sqlite3" {task_id} {pid} <<'PY'
import os,signal,sqlite3,sys,time
db,task,pid=sys.argv[1],sys.argv[2],int(sys.argv[3])
c=sqlite3.connect(db)
r=c.execute("select child_pid,status,lane,pr_number from ideas where idea_id=?",(task,)).fetchone()
if r != (pid,'running',5,None): raise SystemExit('reserve identity changed or was published')
try: os.killpg(pid,signal.SIGCONT)
except ProcessLookupError: pass
try: os.killpg(pid,signal.SIGTERM)
except ProcessLookupError: pass
for _ in range(20):
    try: os.killpg(pid,0)
    except ProcessLookupError: break
    time.sleep(.5)
else:
    os.killpg(pid,signal.SIGKILL)
PY
tmux kill-window -t media-journalism-verify-a:lane-05 2>/dev/null || true
python3 - "$STATE/campaign.sqlite3" {task_id} <<'PY'
import datetime,json,sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=30)
c.execute('begin immediate')
r=c.execute("select status,pr_number from ideas where idea_id=?",(sys.argv[2],)).fetchone()
if r[1] is not None: raise SystemExit('reserve unexpectedly has a PR')
now=datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
c.execute("update ideas set status='failed',child_pid=NULL,finished_at=?,failure=? where idea_id=?",(now,'operator canceled held reserve after exact global target was reached',sys.argv[2]))
c.execute("insert into events(ts,kind,details_json) values(?,?,?)",(now,'global_target_reserve_canceled',json.dumps({{'idea_id':sys.argv[2],'previous_status':r[0]}},sort_keys=True)))
c.commit()
PY"""
    remote(server, script)


def allocate(remaining: int, pending_a: int, pending_b: int) -> tuple[int, int]:
    if remaining < 0 or remaining > pending_a + pending_b:
        raise ValueError("remaining target cannot fit pending candidates")
    a = min((remaining + 1) // 2, pending_a)
    b = remaining - a
    if b > pending_b:
        shift = b - pending_b
        a += shift
        b -= shift
    return a, b


def set_local_target(server: Server, target: int, global_target: int) -> None:
    script = f"""python3 - {server.state_root}/campaign.sqlite3 {target} {global_target} <<'PY'
import datetime,json,sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=30)
c.execute('begin immediate')
counts={{row[0]:row[1] for row in c.execute('select status,count(*) from ideas group by status')}}
running=counts.get('running',0)+counts.get('blocked_deploy',0)
target=int(sys.argv[2]); succeeded=counts.get('succeeded',0); pending=counts.get('pending',0)
if target < succeeded+running or target > succeeded+running+pending: raise SystemExit('unsafe local target')
now=datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
c.execute("update meta set value=? where key='target'",(str(target),))
c.execute("update meta set value='0' where key='operator_pause'")
c.execute("insert into events(ts,kind,details_json) values(?,?,?)",(now,'global_target_allocated',json.dumps({{'global_target':int(sys.argv[3]),'local_target':target}},sort_keys=True)))
c.commit()
PY"""
    remote(server, script)


def save(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def log(path: Path, event: str, **details: Any) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"ts": utc_now(), "event": event, **details}, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="append", type=parse_server, required=True)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--reserve-label", choices=("a", "b"), required=True)
    parser.add_argument("--reserve-task", required=True)
    parser.add_argument("--reserve-pid", type=int, required=True)
    parser.add_argument("--baseline-failed", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()
    servers = {server.label: server for server in args.server}
    if set(servers) != {"a", "b"} or args.target < 1 or args.interval < 5:
        parser.error("exactly servers a and b, a positive target, and interval >=5 are required")
    args.state.parent.mkdir(parents=True, exist_ok=True)
    lock_path = args.state.with_suffix(".lock")
    log_path = args.state.with_suffix(".jsonl")
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = (
            json.loads(args.state.read_text(encoding="utf-8"))
            if args.state.exists()
            else {
                "schema_version": 1,
                "phase": "reserve_held",
                "target": args.target,
                "reserve": {
                    "label": args.reserve_label,
                    "task_id": args.reserve_task,
                    "pid": args.reserve_pid,
                },
                "baseline_failed": args.baseline_failed,
                "servers": {label: asdict(server) for label, server in servers.items()},
            }
        )
        save(args.state, state)
        while True:
            snapshots = {label: snapshot(server) for label, server in servers.items()}
            succeeded = sum(item["succeeded"] for item in snapshots.values())
            failed = sum(item["failed"] for item in snapshots.values())
            running = sum(item["running"] for item in snapshots.values())
            log(log_path, "sample", phase=state["phase"], succeeded=succeeded, failed=failed, running=running)
            if succeeded > args.target:
                raise RuntimeError(f"global target exceeded: {succeeded}>{args.target}")
            reserve = state["reserve"]
            reserve_server = servers[reserve["label"]]
            if state["phase"] == "reserve_held" and succeeded == args.target:
                cancel_reserve(reserve_server, reserve["task_id"], reserve["pid"])
                state["phase"] = "reserve_canceled"
                save(args.state, state)
                log(log_path, "reserve_canceled", **reserve)
                time.sleep(args.interval)
                continue
            if state["phase"] == "reserve_held" and failed > state["baseline_failed"]:
                resume_reserve(reserve_server, reserve["task_id"], reserve["pid"])
                state["phase"] = "reserve_running"
                save(args.state, state)
                log(log_path, "reserve_resumed", **reserve)
                time.sleep(args.interval)
                continue
            if state["phase"] == "reserve_running":
                deficit = args.target - succeeded - running
                if deficit < 0:
                    raise RuntimeError("active tasks exceed the remaining global target")
                add_a, add_b = allocate(
                    deficit, snapshots["a"]["pending"], snapshots["b"]["pending"]
                )
                target_a = snapshots["a"]["succeeded"] + snapshots["a"]["running"] + add_a
                target_b = snapshots["b"]["succeeded"] + snapshots["b"]["running"] + add_b
                set_local_target(servers["a"], target_a, args.target)
                set_local_target(servers["b"], target_b, args.target)
                state["phase"] = "targets_allocated"
                state["local_targets"] = {"a": target_a, "b": target_b}
                save(args.state, state)
                log(log_path, "targets_allocated", **state["local_targets"])
                time.sleep(args.interval)
                continue
            if running == 0 and succeeded < args.target and state["phase"] != "targets_allocated":
                remaining = args.target - succeeded
                add_a, add_b = allocate(remaining, snapshots["a"]["pending"], snapshots["b"]["pending"])
                set_local_target(servers["a"], snapshots["a"]["succeeded"] + add_a, args.target)
                set_local_target(servers["b"], snapshots["b"]["succeeded"] + add_b, args.target)
                state["phase"] = "targets_allocated"
                state["local_targets"] = {
                    "a": snapshots["a"]["succeeded"] + add_a,
                    "b": snapshots["b"]["succeeded"] + add_b,
                }
                save(args.state, state)
                log(log_path, "targets_allocated", **state["local_targets"])
                time.sleep(args.interval)
                continue
            traces_ready = all(
                item["traces_published"] == item["succeeded"] for item in snapshots.values()
            )
            if succeeded == args.target and running == 0 and traces_ready:
                state["phase"] = "complete"
                state["completed_at"] = utc_now()
                save(args.state, state)
                log(log_path, "complete", succeeded=succeeded)
                return 0
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
