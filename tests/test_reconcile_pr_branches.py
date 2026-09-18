import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reconcile_pr_branches", ROOT / "scripts/reconcile_pr_branches.py"
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


OLD_SHA = "1" * 40
NEW_SHA = "2" * 40
TITLE = "[online-search] abcdef alpha-beta-gamma"


def entry(**updates):
    raw = {
        "pr_number": 75,
        "task_id": "alpha-beta-gamma",
        "title": TITLE,
        "base_ref": "main",
        "head_ref": "online-search/alpha-beta-gamma",
        "expected_head_sha": OLD_SHA,
    }
    raw.update(updates)
    return module.ManifestEntry.parse(raw)


def completed(command, stdout="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout, "")


def pr_payload(head_sha=OLD_SHA):
    return {
        "number": 75,
        "state": "open",
        "title": TITLE,
        "base": {"ref": "main"},
        "head": {
            "ref": "online-search/alpha-beta-gamma",
            "sha": head_sha,
            "repo": {"full_name": "Parsewave-internal/online-search"},
        },
    }


def test_manifest_entry_requires_matching_title_branch_and_full_digest():
    parsed = entry(candidate_digest="a" * 64)
    assert parsed.task_id == "alpha-beta-gamma"
    with pytest.raises(module.ReconcileError, match="title and task_id"):
        entry(title="[online-search] abcdef wrong-task-name")
    with pytest.raises(module.ReconcileError, match="head_ref"):
        entry(head_ref="online-search/some-other-task")
    with pytest.raises(module.ReconcileError, match="candidate_digest"):
        entry(candidate_digest="a" * 40)


def test_exact_lease_push_is_atomic_and_sha_guarded():
    command = module.exact_lease_push_command(
        "online-search/alpha-beta-gamma", OLD_SHA
    )
    assert command == [
        "git",
        "push",
        "--porcelain",
        f"--force-with-lease=refs/heads/online-search/alpha-beta-gamma:{OLD_SHA}",
        "origin",
        "HEAD:refs/heads/online-search/alpha-beta-gamma",
    ]
    with pytest.raises(module.ReconcileError, match="invalid expected"):
        module.exact_lease_push_command("online-search/x", "short")


def test_scoped_diff_rejects_sibling_and_non_allowlisted_files():
    prefix = "contributor_tasks/alpha-beta-gamma"
    assert module.require_scoped_changes(
        [f"{prefix}/tests/rubrics.json"],
        task_prefix=prefix,
        allowed_relative_paths=("tests/rubrics.json",),
    ) == [f"{prefix}/tests/rubrics.json"]
    with pytest.raises(module.ReconcileError, match="outside"):
        module.require_scoped_changes(
            [f"{prefix}/instruction.md"],
            task_prefix=prefix,
            allowed_relative_paths=("tests/rubrics.json",),
        )
    with pytest.raises(module.ReconcileError, match="invalid relative"):
        module.require_scoped_changes(
            [],
            task_prefix=prefix,
            allowed_relative_paths=("../sibling/rubrics.json",),
        )
    with pytest.raises(module.ReconcileError, match="outside"):
        module.require_scoped_changes(
            ["contributor_tasks/a-different-task/tests/rubrics.json"],
            task_prefix=prefix,
            allowed_relative_paths=("tests/rubrics.json",),
        )


def test_ledger_claims_bot_trigger_at_most_once_per_pr_sha(tmp_path):
    ledger = module.Ledger(tmp_path / "ledger.json")
    assert ledger.claim_bot_trigger(75, NEW_SHA) is True
    assert ledger.claim_bot_trigger(75, NEW_SHA) is False
    assert ledger.claim_bot_trigger(75, OLD_SHA) is True
    reloaded = module.Ledger(tmp_path / "ledger.json")
    assert reloaded.claim_bot_trigger(75, NEW_SHA) is False


def test_github_identity_rejects_duplicate_pr_mapping():
    responses = [pr_payload(), [{"number": 75}, {"number": 99}]]

    def runner(command, **kwargs):
        return completed(command, json.dumps(responses.pop(0)))

    github = module.GitHub("Parsewave-internal/online-search", runner)
    with pytest.raises(module.ReconcileError, match="uniquely"):
        github.validate_identity(entry())


class FakeGitHub:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.comments = []

    def validate_identity(self, ignored_entry):
        return self.payloads.pop(0)

    def comment(self, pr_number, body):
        self.comments.append((pr_number, body))


def reconciler(tmp_path, *, apply=False, trigger_bot=False, runner=None, sleep=None):
    validator = tmp_path / "validator.py"
    validator.write_text("# fake validator\n")
    kwargs = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    return module.Reconciler(
        repo="Parsewave-internal/online-search",
        candidate_root=tmp_path / "candidates",
        ledger=module.Ledger(tmp_path / "ledger.json"),
        validator=validator,
        allowed_relative_paths=("tests/rubrics.json",),
        apply=apply,
        trigger_bot=trigger_bot,
        runner=runner or (lambda command, **kwargs: completed(command)),
        **kwargs,
    )


def create_tree(root, content):
    path = root / "tests"
    path.mkdir(parents=True)
    (path / "rubrics.json").write_text(content)


def test_advanced_head_with_identical_candidate_is_idempotent_noop(tmp_path, monkeypatch):
    candidate = tmp_path / "candidates" / "alpha-beta-gamma"
    create_tree(candidate, "same")
    checkout = tmp_path / "checkout"
    create_tree(checkout / "contributor_tasks" / "alpha-beta-gamma", "same")
    digest = module.tree_digest(candidate)
    reconcile = reconciler(tmp_path)
    reconcile.github = FakeGitHub([pr_payload(NEW_SHA)])
    monkeypatch.setattr(reconcile, "_validate_candidate", lambda ignored: (candidate, digest))
    monkeypatch.setattr(reconcile, "_checkout", lambda *args: checkout)

    result = reconcile.reconcile(entry())

    assert result["state"] == "noop"
    assert result["head_sha"] == NEW_SHA


def test_advanced_head_with_different_candidate_is_stale(tmp_path, monkeypatch):
    candidate = tmp_path / "candidates" / "alpha-beta-gamma"
    create_tree(candidate, "new")
    checkout = tmp_path / "checkout"
    create_tree(checkout / "contributor_tasks" / "alpha-beta-gamma", "old")
    digest = module.tree_digest(candidate)
    reconcile = reconciler(tmp_path)
    reconcile.github = FakeGitHub([pr_payload(NEW_SHA)])
    monkeypatch.setattr(reconcile, "_validate_candidate", lambda ignored: (candidate, digest))
    monkeypatch.setattr(reconcile, "_checkout", lambda *args: checkout)

    with pytest.raises(module.StaleHead, match="head advanced"):
        reconcile.reconcile(entry())


def test_apply_pushes_existing_branch_and_never_creates_pr(tmp_path, monkeypatch):
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        return completed(command)

    candidate = tmp_path / "candidates" / "alpha-beta-gamma"
    create_tree(candidate, "new")
    checkout = tmp_path / "checkout"
    create_tree(checkout / "contributor_tasks" / "alpha-beta-gamma", "old")
    digest = module.tree_digest(candidate)
    reconcile = reconciler(tmp_path, apply=True, trigger_bot=True, runner=runner)
    reconcile.github = FakeGitHub(
        [pr_payload(OLD_SHA), pr_payload(OLD_SHA), pr_payload(NEW_SHA)]
    )
    monkeypatch.setattr(reconcile, "_validate_candidate", lambda ignored: (candidate, digest))
    monkeypatch.setattr(reconcile, "_checkout", lambda *args: checkout)
    monkeypatch.setattr(
        reconcile,
        "_sync_candidate",
        lambda *args: ["contributor_tasks/alpha-beta-gamma/tests/rubrics.json"],
    )
    monkeypatch.setattr(reconcile, "_commit", lambda *args: NEW_SHA)

    result = reconcile.reconcile(entry())

    assert result["state"] == "updated"
    assert result["bot_triggered"] is True
    assert (exact := [command for command in commands if "push" in command])
    assert exact[0] == module.exact_lease_push_command(
        "online-search/alpha-beta-gamma", OLD_SHA
    )
    assert not any(command[:3] == ["gh", "pr", "create"] for command in commands)
    assert reconcile.github.comments == [(75, module.BOT_COMMENT)]


def test_second_trigger_for_same_head_is_skipped(tmp_path):
    reconcile = reconciler(tmp_path, apply=True, trigger_bot=True)
    github = FakeGitHub([])
    reconcile.github = github
    assert reconcile._trigger_once(entry(), NEW_SHA) is True
    assert reconcile._trigger_once(entry(), NEW_SHA) is False
    assert github.comments == [(75, module.BOT_COMMENT)]


def test_commit_sets_repo_local_yggdrasil_identity(tmp_path):
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        stdout = NEW_SHA + "\n" if command[-2:] == ["rev-parse", "HEAD"] else ""
        return completed(command, stdout)

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    reconcile = reconciler(tmp_path, runner=runner)

    assert reconcile._commit(checkout, entry(), "a" * 64) == NEW_SHA
    assert [
        "git",
        "-C",
        str(checkout),
        "config",
        "user.name",
        "yggdrasil-bot",
    ] in commands
    assert [
        "git",
        "-C",
        str(checkout),
        "config",
        "user.email",
        "yggdrasil-bot@parsewave.local",
    ] in commands
    commit_index = next(index for index, command in enumerate(commands) if "commit" in command)
    name_index = next(index for index, command in enumerate(commands) if "user.name" in command)
    email_index = next(index for index, command in enumerate(commands) if "user.email" in command)
    assert name_index < commit_index
    assert email_index < commit_index


def test_post_push_verification_polls_through_old_sha_lag(tmp_path):
    sleeps = []
    reconcile = reconciler(tmp_path, sleep=sleeps.append)
    reconcile.github = FakeGitHub(
        [pr_payload(OLD_SHA), pr_payload(OLD_SHA), pr_payload(NEW_SHA)]
    )

    reconcile._verify_post_push(entry(), NEW_SHA)

    assert sleeps == [1.0, 1.0]


def test_post_push_verification_times_out_on_persistently_old_sha(tmp_path):
    sleeps = []
    reconcile = reconciler(tmp_path, sleep=sleeps.append)
    reconcile.github = FakeGitHub(
        [pr_payload(OLD_SHA) for _ in range(module.POST_PUSH_ATTEMPTS)]
    )

    with pytest.raises(module.ReconcileError, match="timed out"):
        reconcile._verify_post_push(entry(), NEW_SHA)

    assert sleeps == [1.0] * (module.POST_PUSH_ATTEMPTS - 1)


def test_post_push_verification_rejects_third_sha_without_retry(tmp_path):
    third_sha = "3" * 40
    sleeps = []
    reconcile = reconciler(tmp_path, sleep=sleeps.append)
    reconcile.github = FakeGitHub([pr_payload(third_sha)])

    with pytest.raises(module.StaleHead, match="changed unexpectedly"):
        reconcile._verify_post_push(entry(), NEW_SHA)

    assert sleeps == []
