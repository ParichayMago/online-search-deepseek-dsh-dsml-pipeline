#!/usr/bin/env python3
"""Safely reconcile prepared task payloads onto existing GitHub PR branches.

This command deliberately has no PR-creation path.  It is for repairing an
already-open PR in place, with the PR number and its expected head SHA supplied
by a reviewed manifest.  Dry-run is the default; ``--apply`` is required to
commit, push, or post the optional bot trigger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

TITLE_RE = re.compile(
    r"^\[online-search\] [0-9a-f]{6} ([a-z0-9]+(?:-[a-z0-9]+){2})$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_ALLOWED = ("tests/rubrics.json",)
BOT_COMMENT = "/bot online-search-review"
LEDGER_VERSION = 1
MANIFEST_VERSION = 1


class ReconcileError(RuntimeError):
    """A safe, expected reconciliation refusal."""


class StaleHead(ReconcileError):

    pass


Run = Callable[..., subprocess.CompletedProcess[str]]
Sleep = Callable[[float], None]
POST_PUSH_ATTEMPTS = 12
POST_PUSH_DELAY_SECONDS = 1.0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        rendered = shlex.join(command)
        raise ReconcileError(
            f"command failed ({result.returncode}): {rendered}\n"
            f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
        )
    return result


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcileError(f"cannot load JSON {path}: {exc}") from exc


def tree_digest(root: Path) -> str:
    """Hash a task tree, including relative paths and file contents."""
    if not root.is_dir() or root.is_symlink():
        raise ReconcileError(f"candidate is not a regular directory: {root}")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ReconcileError(f"candidate has no files: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ReconcileError(f"candidate contains a symlink: {path}")
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def require_scoped_changes(
    changed_paths: Iterable[str],
    *,
    task_prefix: str,
    allowed_relative_paths: tuple[str, ...],
) -> list[str]:
    """Reject changes outside the task and outside the explicit allowlist."""
    prefix = PurePosixPath(task_prefix)
    allowed = set()
    for relative in allowed_relative_paths:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
            raise ReconcileError(f"invalid relative allowlist path: {relative!r}")
        allowed.add(prefix / path)
    changed = sorted({PurePosixPath(path) for path in changed_paths if path})
    if not changed:
        return []
    outside = [str(path) for path in changed if path not in allowed]
    if outside:
        raise ReconcileError(
            "diff contains paths outside the repair allowlist: " + ", ".join(outside)
        )
    return [str(path) for path in changed]


def exact_lease_push_command(branch: str, expected_sha: str) -> list[str]:
    if not SHA_RE.fullmatch(expected_sha):
        raise ReconcileError(f"invalid expected head SHA: {expected_sha!r}")
    ref = f"refs/heads/{branch}"
    return [
        "git",
        "push",
        "--porcelain",
        f"--force-with-lease={ref}:{expected_sha}",
        "origin",
        f"HEAD:{ref}",
    ]


@dataclass(frozen=True)
class ManifestEntry:
    pr_number: int
    task_id: str
    title: str
    base_ref: str
    head_ref: str
    expected_head_sha: str
    candidate_digest: str | None = None

    @classmethod
    def parse(cls, raw: Any) -> ManifestEntry:
        if not isinstance(raw, dict):
            raise ReconcileError("manifest entry must be an object")
        try:
            entry = cls(
                pr_number=int(raw["pr_number"]),
                task_id=str(raw["task_id"]),
                title=str(raw["title"]),
                base_ref=str(raw.get("base_ref", "main")),
                head_ref=str(raw["head_ref"]),
                expected_head_sha=str(raw["expected_head_sha"]),
                candidate_digest=(
                    str(raw["candidate_digest"])
                    if raw.get("candidate_digest") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReconcileError(f"malformed manifest entry: {exc}") from exc
        match = TITLE_RE.fullmatch(entry.title)
        if entry.pr_number <= 0:
            raise ReconcileError("pr_number must be positive")
        if match is None or match.group(1) != entry.task_id:
            raise ReconcileError("title and task_id do not match the online-search title format")
        if entry.head_ref != f"online-search/{entry.task_id}":
            raise ReconcileError("head_ref must be online-search/<task_id>")
        if entry.base_ref != "main":
            raise ReconcileError("base_ref must be main")
        if not SHA_RE.fullmatch(entry.expected_head_sha):
            raise ReconcileError("expected_head_sha must be a full lowercase Git SHA")
        if entry.candidate_digest and not DIGEST_RE.fullmatch(entry.candidate_digest):
            raise ReconcileError("candidate_digest must be a lowercase SHA-256")
        return entry


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            data = _load_json(path)
            if not isinstance(data, dict) or data.get("schema_version") != LEDGER_VERSION:
                raise ReconcileError(f"unsupported ledger schema in {path}")
            self.data = data
        else:
            self.data = {
                "schema_version": LEDGER_VERSION,
                "repairs": {},
                "bot_triggers": {},
            }

    def save(self) -> None:
        _atomic_json(self.path, self.data)

    def record_repair(
        self,
        *,
        pr_number: int,
        digest: str,
        old_sha: str,
        new_sha: str,
        state: str,
    ) -> None:
        self.data["repairs"][f"{pr_number}:{digest}"] = {
            "state": state,
            "old_sha": old_sha,
            "new_sha": new_sha,
            "updated_at": _utc_now(),
        }
        self.save()

    def claim_bot_trigger(self, pr_number: int, head_sha: str) -> bool:
        """Atomically claim the one permitted trigger attempt for this SHA."""
        key = f"{pr_number}:{head_sha}"
        if key in self.data["bot_triggers"]:
            return False
        self.data["bot_triggers"][key] = {
            "state": "claimed",
            "claimed_at": _utc_now(),
        }
        self.save()
        return True

    def finish_bot_trigger(self, pr_number: int, head_sha: str, state: str) -> None:
        key = f"{pr_number}:{head_sha}"
        trigger = self.data["bot_triggers"].get(key)
        if trigger is None:
            raise ReconcileError("bot trigger was not claimed")
        trigger.update({"state": state, "finished_at": _utc_now()})
        self.save()


class GitHub:
    def __init__(self, repo: str, runner: Run = _run):
        self.repo = repo
        self.owner = repo.split("/", 1)[0]
        self.runner = runner

    def _json(self, args: list[str]) -> Any:
        result = self.runner(["gh", *args])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ReconcileError(f"GitHub returned invalid JSON: {exc}") from exc

    def get_pr(self, number: int) -> dict[str, Any]:
        value = self._json(["api", f"repos/{self.repo}/pulls/{number}"])
        if not isinstance(value, dict):
            raise ReconcileError("GitHub PR response was not an object")
        return value

    def prs_for_head(self, head_ref: str) -> list[dict[str, Any]]:
        value = self._json(
            [
                "api",
                f"repos/{self.repo}/pulls?state=all&head={self.owner}:{head_ref}&per_page=100",
            ]
        )
        if not isinstance(value, list):
            raise ReconcileError("GitHub head lookup response was not a list")
        return value

    def validate_identity(self, entry: ManifestEntry) -> dict[str, Any]:
        pr = self.get_pr(entry.pr_number)
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_repo = (head.get("repo") or {}).get("full_name")
        errors = []
        if str(pr.get("state", "")).lower() != "open":
            errors.append("PR is not open")
        if pr.get("title") != entry.title:
            errors.append("title changed")
        if base.get("ref") != entry.base_ref:
            errors.append("base branch changed")
        if head.get("ref") != entry.head_ref:
            errors.append("head branch changed")
        if head_repo != self.repo:
            errors.append("head repository is not the target repository")
        matches = self.prs_for_head(entry.head_ref)
        if len(matches) != 1 or int(matches[0].get("number", -1)) != entry.pr_number:
            errors.append("head branch does not map uniquely to the manifest PR")
        if errors:
            raise ReconcileError("; ".join(errors))
        return pr

    def comment(self, pr_number: int, body: str) -> None:
        self.runner(
            [
                "gh",
                "pr",
                "comment",
                str(pr_number),
                "--repo",
                self.repo,
                "--body",
                body,
            ]
        )


class Reconciler:
    def __init__(
        self,
        *,
        repo: str,
        candidate_root: Path,
        ledger: Ledger,
        validator: Path,
        allowed_relative_paths: tuple[str, ...],
        apply: bool,
        trigger_bot: bool,
        runner: Run = _run,
        sleep: Sleep = time.sleep,
    ):
        self.repo = repo
        self.candidate_root = candidate_root
        self.ledger = ledger
        self.validator = validator
        self.allowed_relative_paths = allowed_relative_paths
        self.apply = apply
        self.trigger_bot = trigger_bot
        self.runner = runner
        self.sleep = sleep
        self.github = GitHub(repo, runner)

    def _validate_candidate(self, entry: ManifestEntry) -> tuple[Path, str]:
        candidate = self.candidate_root / entry.task_id
        digest = tree_digest(candidate)
        if entry.candidate_digest and digest != entry.candidate_digest:
            raise ReconcileError(
                f"candidate digest mismatch: manifest={entry.candidate_digest} actual={digest}"
            )
        self.runner(
            [
                sys.executable,
                str(self.validator),
                "--task-root",
                str(candidate),
                "--task-id",
                entry.task_id,
                "--mode",
                "package",
            ]
        )
        return candidate, digest

    def _checkout(self, entry: ManifestEntry, live_sha: str, workspace: Path) -> Path:
        checkout = workspace / "repo"
        checkout.mkdir()
        self.runner(["git", "init", "--quiet", str(checkout)])
        self.runner(
            [
                "git",
                "-C",
                str(checkout),
                "remote",
                "add",
                "origin",
                f"https://github.com/{self.repo}.git",
            ]
        )
        self.runner(
            [
                "git",
                "-C",
                str(checkout),
                "fetch",
                "--quiet",
                "--depth=1",
                "origin",
                f"refs/heads/{entry.head_ref}",
            ]
        )
        fetched = self.runner(
            ["git", "-C", str(checkout), "rev-parse", "FETCH_HEAD"]
        ).stdout.strip()
        if fetched != live_sha:
            raise StaleHead(f"fetched SHA {fetched} differs from GitHub SHA {live_sha}")
        self.runner(
            ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"]
        )
        return checkout

    def _sync_candidate(self, checkout: Path, entry: ManifestEntry, candidate: Path) -> list[str]:
        relative = Path("contributor_tasks") / entry.task_id
        destination = checkout / relative
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(candidate, destination)
        # Stage only this task before inspecting the diff.  Unlike a plain
        # working-tree diff, the cached diff also includes newly added files.
        self.runner(
            ["git", "-C", str(checkout), "add", "-A", "--", str(relative)]
        )
        output = self.runner(
            [
                "git",
                "-C",
                str(checkout),
                "diff",
                "--cached",
                "--name-only",
                "--no-renames",
                "HEAD",
                "--",
            ]
        ).stdout
        return require_scoped_changes(
            output.splitlines(),
            task_prefix=relative.as_posix(),
            allowed_relative_paths=self.allowed_relative_paths,
        )

    def _commit(self, checkout: Path, entry: ManifestEntry, digest: str) -> str:
        relative = Path("contributor_tasks") / entry.task_id
        # Temp clones cannot rely on a host-global Git identity.  Match the
        # identity used by Yggdrasil's original deployment commits and scope it
        # to this isolated checkout only.
        self.runner(
            [
                "git",
                "-C",
                str(checkout),
                "config",
                "user.name",
                "yggdrasil-bot",
            ]
        )
        self.runner(
            [
                "git",
                "-C",
                str(checkout),
                "config",
                "user.email",
                "yggdrasil-bot@parsewave.local",
            ]
        )
        self.runner(["git", "-C", str(checkout), "add", "--", str(relative)])
        message = (
            "Fix online-search rubric balance\n\n"
            f"PR: #{entry.pr_number}\n"
            f"Repair-Base: {entry.expected_head_sha}\n"
            f"Candidate-Digest: {digest}"
        )
        self.runner(["git", "-C", str(checkout), "commit", "-m", message])
        return self.runner(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"]
        ).stdout.strip()

    def _trigger_once(self, entry: ManifestEntry, head_sha: str) -> bool:
        if not self.trigger_bot or not self.apply:
            return False
        if not self.ledger.claim_bot_trigger(entry.pr_number, head_sha):
            return False
        try:
            self.github.comment(entry.pr_number, BOT_COMMENT)
        except Exception:
            self.ledger.finish_bot_trigger(entry.pr_number, head_sha, "failed")
            raise
        self.ledger.finish_bot_trigger(entry.pr_number, head_sha, "posted")
        return True

    def _verify_post_push(self, entry: ManifestEntry, new_sha: str) -> None:
        """Poll through GitHub's brief old-head API cache after a safe push.

        Only the manifest's old SHA is retryable.  A third SHA represents a
        real concurrent update and fails immediately; identity/state changes
        are rejected by ``validate_identity`` on every attempt.
        """
        for attempt in range(POST_PUSH_ATTEMPTS):
            after_push = self.github.validate_identity(entry)
            remote_sha = str((after_push.get("head") or {}).get("sha") or "")
            if remote_sha == new_sha:
                return
            if remote_sha != entry.expected_head_sha:
                raise StaleHead(
                    "post-push head changed unexpectedly: "
                    f"old={entry.expected_head_sha} local={new_sha} remote={remote_sha}"
                )
            if attempt + 1 < POST_PUSH_ATTEMPTS:
                self.sleep(POST_PUSH_DELAY_SECONDS)
        raise ReconcileError(
            "post-push head verification timed out while GitHub still reported "
            f"the old SHA {entry.expected_head_sha}; expected {new_sha}"
        )

    def reconcile(self, entry: ManifestEntry) -> dict[str, Any]:
        candidate, digest = self._validate_candidate(entry)
        pr = self.github.validate_identity(entry)
        live_sha = str((pr.get("head") or {}).get("sha") or "")
        if not SHA_RE.fullmatch(live_sha):
            raise ReconcileError(f"GitHub returned invalid head SHA: {live_sha!r}")

        with tempfile.TemporaryDirectory(prefix=f"pr-reconcile-{entry.pr_number}-") as temp:
            checkout = self._checkout(entry, live_sha, Path(temp))
            current = checkout / "contributor_tasks" / entry.task_id
            if current.is_dir() and tree_digest(current) == digest:
                if self.apply:
                    self.ledger.record_repair(
                        pr_number=entry.pr_number,
                        digest=digest,
                        old_sha=entry.expected_head_sha,
                        new_sha=live_sha,
                        state="noop",
                    )
                triggered = self._trigger_once(entry, live_sha)
                return {
                    "pr_number": entry.pr_number,
                    "state": "noop",
                    "head_sha": live_sha,
                    "candidate_digest": digest,
                    "bot_triggered": triggered,
                }

            if live_sha != entry.expected_head_sha:
                raise StaleHead(
                    f"PR head advanced: expected {entry.expected_head_sha}, found {live_sha}"
                )
            changed = self._sync_candidate(checkout, entry, candidate)
            if not changed:
                raise ReconcileError("candidate digest differs but git found no changed files")
            if not self.apply:
                return {
                    "pr_number": entry.pr_number,
                    "state": "planned",
                    "head_sha": live_sha,
                    "candidate_digest": digest,
                    "changed_paths": changed,
                    "bot_triggered": False,
                }

            new_sha = self._commit(checkout, entry, digest)
            before_push = self.github.validate_identity(entry)
            before_sha = str((before_push.get("head") or {}).get("sha") or "")
            if before_sha != entry.expected_head_sha:
                raise StaleHead(
                    f"PR head advanced before push: expected {entry.expected_head_sha}, found {before_sha}"
                )
            self.runner(exact_lease_push_command(entry.head_ref, entry.expected_head_sha), cwd=checkout)

            self._verify_post_push(entry, new_sha)
            self.ledger.record_repair(
                pr_number=entry.pr_number,
                digest=digest,
                old_sha=entry.expected_head_sha,
                new_sha=new_sha,
                state="updated",
            )
            triggered = self._trigger_once(entry, new_sha)
            return {
                "pr_number": entry.pr_number,
                "state": "updated",
                "old_sha": entry.expected_head_sha,
                "head_sha": new_sha,
                "candidate_digest": digest,
                "changed_paths": changed,
                "bot_triggered": triggered,
            }


def _load_manifest(path: Path) -> tuple[str, list[ManifestEntry]]:
    raw = _load_json(path)
    if not isinstance(raw, dict) or raw.get("schema_version") != MANIFEST_VERSION:
        raise ReconcileError("manifest schema_version must be 1")
    repo = str(raw.get("repo") or "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ReconcileError("manifest repo must be owner/name")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise ReconcileError("manifest entries must be a non-empty list")
    entries = [ManifestEntry.parse(value) for value in entries_raw]
    numbers = [entry.pr_number for entry in entries]
    heads = [entry.head_ref for entry in entries]
    if len(numbers) != len(set(numbers)) or len(heads) != len(set(heads)):
        raise ReconcileError("manifest PR numbers and head refs must be unique")
    return repo, entries


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--results", type=Path)
    parser.add_argument(
        "--validator",
        type=Path,
        default=Path(__file__).with_name("validate_live_task.py"),
    )
    parser.add_argument(
        "--allowed-relative-path",
        action="append",
        dest="allowed_relative_paths",
        help="repeatable path relative to the task root (default: tests/rubrics.json)",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--trigger-bot", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        repo, entries = _load_manifest(args.manifest)
        if not args.validator.is_file():
            raise ReconcileError(f"validator is missing: {args.validator}")
        ledger = Ledger(args.ledger)
        reconciler = Reconciler(
            repo=repo,
            candidate_root=args.candidate_root,
            ledger=ledger,
            validator=args.validator,
            allowed_relative_paths=tuple(args.allowed_relative_paths or DEFAULT_ALLOWED),
            apply=args.apply,
            trigger_bot=args.trigger_bot,
        )
    except ReconcileError as exc:
        print(json.dumps({"state": "invalid", "error": str(exc)}))
        return 1

    results = []
    failed = False
    for entry in entries:
        try:
            result = reconciler.reconcile(entry)
        except StaleHead as exc:
            failed = True
            result = {"pr_number": entry.pr_number, "state": "stale", "error": str(exc)}
        except (ReconcileError, OSError) as exc:
            failed = True
            result = {"pr_number": entry.pr_number, "state": "invalid", "error": str(exc)}
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
    document = {"schema_version": 1, "repo": repo, "results": results}
    if args.results:
        _atomic_json(args.results, document)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
