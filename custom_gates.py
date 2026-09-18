"""Doraemon-only Yggdrasil steps.

Everything that Yggdrasil already does stays in Yggdrasil. This file contains
only the contracts the engine cannot currently express: exhausting an idea
shard without wrapping, stable task identity plus canonical restoration,
optional staging of a reviewed unpublished candidate, Online-Search-specific
live-source validation, and an isolated Codex review.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import math
import os
import random
import re
import shutil
import signal
import sys
import time
from pathlib import Path

import yaml
from yggdrasil.engine.registry import register_step

from dsh_home_isolation import create_isolated_dsh_home
from publication_gate import muse_trial_metrics, publication_summary, trial_metrics

PUBLICATION_FILES = (
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
TASK_SPECIFIC_FILES = (
    "instruction.md",
    "solution/evidence_graph.json",
    "solution/report.md",
    "tests/reference/ground_truth.json",
    "tests/rubrics.json",
)

CANONICAL_FILES = (
    "environment/Dockerfile",
    "solution/solve.sh",
    "task.toml",
    "tests/Dockerfile",
    "tests/test.sh",
    "tests/test_outputs.py",
    "tests/test_utils.py",
)

BENCHMARK_BUILDER_LANES = {
    "control-native",
    "control-proxy-codx",
    "deepseek-codex",
    "deepseek-codex-dsml",
    "deepseek-claude",
    "deepseek-dsh",
    "deepseek-dsh-dsml",
}
DEEPSEEK_MODEL = "deepseek/deepseek-v4.1-flash"
_ROUTING_ENV = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _configured_executable(
    env_name: str, fallback: str, *, allow_codx: bool = False
) -> str:
    """Resolve a single executable path without permitting shell wrappers."""
    value = os.environ.get(env_name, fallback).strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"{env_name} must name one executable, not a shell command")
    if os.environ.get("ONLINE_SEARCH_BUILDER_CONTAINER"):
        resolved = value
    else:
        resolved = shutil.which(value)
        if resolved is None:
            raise FileNotFoundError(f"builder executable not found: {value} ({env_name})")
    if Path(resolved).name == "codx" and not allow_codx:
        raise ValueError("Launchpad codx is forbidden in benchmark builder lanes")
    return resolved


def _profile_path(env_name: str, fallback: str) -> Path:
    return Path(os.environ.get(env_name, fallback)).expanduser().resolve()


def _configure_isolated_dsh_profile(dsh_home: Path) -> None:
    """Pin the isolated OpenRouter route to the requested xhigh regime."""
    settings_path = dsh_home / "settings.yaml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    providers = settings.setdefault("llm-pi-ai", {}).setdefault("providers", {})
    # Replace this route instead of round-tripping legacy YAML. PyYAML treats
    # the unquoted key `off` as boolean false under YAML 1.1, which invalidates
    # DSH reasoningEfforts and leaves the OpenRouter adapter unregistered.
    providers["openrouter"] = {
        "apiKeyEnv": "OPENROUTER_API_KEY",
        "reasoning": "xhigh",
        "models": [
            {
                "id": DEEPSEEK_MODEL,
                "name": "deepseek-v4.1-flash",
                "contextWindow": 1_000_000,
                "maxTokens": 65_536,
                "reasoningEfforts": {"xhigh": "xhigh"},
            }
        ],
    }
    settings.setdefault("agent-default-model", {}).update(
        {"provider": "openrouter", "model": DEEPSEEK_MODEL}
    )
    settings_path.write_text(
        yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _builder_command(
    lane: str,
    prompt: str,
    trial_root: Path,
) -> tuple[list[str], dict[str, str], str]:
    env = os.environ.copy()
    for name in _ROUTING_ENV:
        env.pop(name, None)

    if lane == "control-native":
        binary = _configured_executable("ONLINE_SEARCH_NATIVE_CODEX_BIN", "codex")
        codex_home = _profile_path(
            "ONLINE_SEARCH_NATIVE_CODEX_HOME",
            os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        )
        if not (codex_home / "auth.json").is_file():
            raise FileNotFoundError(f"native Codex auth is missing: {codex_home / 'auth.json'}")
        env.update({"HOME": str(Path.home()), "CODEX_HOME": str(codex_home)})
        for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY"):
            env.pop(name, None)
        command = [
            binary,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable",
            "apps",
            "--skip-git-repo-check",
            "--model",
            "gpt-5.6-sol",
            "-c",
            'model_provider="openai"',
            "-c",
            'model_reasoning_effort="xhigh"',
            "-c",
            "model_context_window=1000000",
            "-c",
            "model_auto_compact_token_limit=2000000000",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--output-last-message",
            str(trial_root / "final.txt"),
            prompt,
        ]
        return command, env, "gpt-5.6-sol"

    if lane == "control-proxy-codx":
        binary = _configured_executable(
            "ONLINE_SEARCH_CODX_BIN", "codx", allow_codx=True
        )
        codex_home = _profile_path(
            "ONLINE_SEARCH_CODX_HOME", str(Path.home() / ".codex-codx-pool-b")
        )
        if not (codex_home / "auth.json").is_file():
            raise FileNotFoundError(f"Pool-B Codx auth is missing: {codex_home / 'auth.json'}")
        env.update({"HOME": str(Path.home()), "CODEX_HOME": str(codex_home)})
        command = [
            binary,
            "--yolo",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable",
            "apps",
            "--skip-git-repo-check",
            "--model",
            "gpt-5.6-sol",
            "-c",
            'model_reasoning_effort="xhigh"',
            "-c",
            "model_context_window=1000000",
            "-c",
            "model_auto_compact_token_limit=2000000000",
            "--json",
            "--output-last-message",
            str(trial_root / "final.txt"),
            prompt,
        ]
        return command, env, "gpt-5.6-sol"

    if not env.get("OPENROUTER_API_KEY") and not env.get(
        "ONLINE_SEARCH_BUILDER_CONTAINER"
    ):
        raise ValueError(f"{lane} requires OPENROUTER_API_KEY")

    if lane in {"deepseek-codex", "deepseek-codex-dsml"}:
        binary = _configured_executable("ONLINE_SEARCH_CODEX_BIN", "codex")
        home_env = (
            "ONLINE_SEARCH_DEEPSEEK_CODEX_DSML_HOME"
            if lane.endswith("-dsml")
            else "ONLINE_SEARCH_DEEPSEEK_CODEX_HOME"
        )
        fallback = (
            str(Path.home() / ".codex-openrouter-dsml-e9ce61d")
            if lane.endswith("-dsml")
            else str(Path.home() / ".codex-openrouter")
        )
        codex_home = _profile_path(home_env, fallback)
        if not (codex_home / "config.toml").is_file():
            raise FileNotFoundError(f"DeepSeek Codex config is missing: {codex_home / 'config.toml'}")
        env.update({"HOME": str(Path.home()), "CODEX_HOME": str(codex_home)})
        command = [
            binary,
            "exec",
            "--ignore-rules",
            "--disable",
            "apps",
            "--skip-git-repo-check",
            "--model",
            DEEPSEEK_MODEL,
            "-c",
            'model_reasoning_effort="xhigh"',
            "-c",
            "model_context_window=1000000",
            "-c",
            "model_auto_compact_token_limit=2000000000",
        ]
        if lane.endswith("-dsml"):
            catalog = codex_home / "model-catalog.json"
            if not catalog.is_file():
                raise FileNotFoundError(f"Codex DSML catalog is missing: {catalog}")
            command.extend(["-c", f'model_catalog_json="{catalog}"'])
        command.extend(
            [
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                "--output-last-message",
                str(trial_root / "final.txt"),
                prompt,
            ]
        )
        return command, env, DEEPSEEK_MODEL

    if lane == "deepseek-claude":
        binary = _configured_executable("ONLINE_SEARCH_CLAUDE_BIN", "claude")
        config_dir = _profile_path(
            "ONLINE_SEARCH_DEEPSEEK_CLAUDE_HOME",
            str(Path.home() / ".claude-openrouter"),
        )
        if not (config_dir / "settings.json").is_file():
            raise FileNotFoundError(f"DeepSeek Claude settings are missing: {config_dir / 'settings.json'}")
        env.update(
            {
                "CLAUDE_CONFIG_DIR": str(config_dir),
                "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "0",
                "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000",
                "DISABLE_AUTO_COMPACT": "1",
            }
        )
        return (
            [
                binary,
                "--print",
                "--model",
                DEEPSEEK_MODEL,
                "--effort",
                "xhigh",
                "--dangerously-skip-permissions",
                "--output-format",
                "stream-json",
                "--verbose",
                "--no-session-persistence",
                prompt,
            ],
            env,
            DEEPSEEK_MODEL,
        )

    binary = _configured_executable(
        "ONLINE_SEARCH_DSH_BIN",
        str(Path(__file__).resolve().parent / "scripts" / "dsh_headless_entrypoint.sh"),
    )
    dsml = lane == "deepseek-dsh-dsml"
    home_env = "ONLINE_SEARCH_DEEPSEEK_DSH_DSML_HOME" if dsml else "ONLINE_SEARCH_DEEPSEEK_DSH_HOME"
    fallback = str(Path.home() / (".dsh-openrouter-dsml" if dsml else ".dsh-openrouter"))
    dsh_template_home = _profile_path(home_env, fallback)
    if not (dsh_template_home / "settings.yaml").is_file():
        raise FileNotFoundError(
            f"DeepSeek Harness settings are missing: {dsh_template_home / 'settings.yaml'}"
        )
    dsh_home = create_isolated_dsh_home(dsh_template_home, trial_root)
    _configure_isolated_dsh_profile(dsh_home)
    env.update(
        {
            "HOME": str(Path.home()),
            "DSH_HOME": str(dsh_home),
            "DSH_PERMISSION_MODE": "danger-full-access",
            "DSH_REASONING_EFFORT": "xhigh",
            "OPENROUTER_REASONING_EFFORT": "xhigh",
            "NODE_OPTIONS": os.environ.get("NODE_OPTIONS", "--max-old-space-size=6144"),
        }
    )
    if dsml:
        env["DSH_TOOLS_MODE"] = "code"
    else:
        env.pop("DSH_TOOLS_MODE", None)
    return [binary, "--profile", "headless", prompt], env, DEEPSEEK_MODEL


async def _run_builder_process(
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: float,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[int, float]:
    container = env.get("ONLINE_SEARCH_BUILDER_CONTAINER")
    if container:
        docker = shutil.which("docker")
        if docker is None:
            raise FileNotFoundError("docker is required for isolated benchmark builders")
        forwarded = []
        for name in (
            "HOME",
            "CODEX_HOME",
            "CLAUDE_CONFIG_DIR",
            "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
            "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
            "DISABLE_AUTO_COMPACT",
            "DSH_HOME",
            "DSH_PERMISSION_MODE",
            "DSH_TOOLS_MODE",
            "DSH_REASONING_EFFORT",
            "OPENROUTER_REASONING_EFFORT",
            "ONLINE_SEARCH_DSH_SOURCE_ROOT",
            "ONLINE_SEARCH_DSH_SOURCE_COMMIT",
            "NODE_OPTIONS",
        ):
            if name in env:
                forwarded.extend(["--env", f"{name}={env[name]}"])
        command = [
            docker,
            "exec",
            "--interactive",
            "--workdir",
            str(cwd),
            *forwarded,
            container,
            *command,
        ]
    started = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        try:
            return_code = await asyncio.wait_for(process.wait(), timeout=timeout)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            return_code = 124
    return return_code, time.monotonic() - started


async def _wait_for_builder_barrier() -> None:
    raw = os.environ.get("ONLINE_SEARCH_BUILDER_START_NS", "").strip()
    if not raw:
        return
    try:
        target = int(raw)
    except ValueError as exc:
        raise ValueError("ONLINE_SEARCH_BUILDER_START_NS must be an integer") from exc
    while True:
        remaining = (target - time.time_ns()) / 1_000_000_000
        if remaining <= 0:
            return
        await asyncio.sleep(min(remaining, 0.25))


def _stage_builder_output(ctx, output_root: Path) -> None:
    """Give the builder a complete publication tree from its first action."""
    output_root.mkdir(parents=True, exist_ok=False)
    for relative in PUBLICATION_FILES:
        source = ctx.task_dir / relative
        if not source.is_file():
            raise FileNotFoundError(f"builder skeleton is missing: {relative}")
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _builder_output_error(output_root: Path) -> str | None:
    missing = [
        relative
        for relative in PUBLICATION_FILES
        if not (output_root / relative).is_file()
        or (output_root / relative).stat().st_size == 0
    ]
    if missing:
        return f"missing or empty publication files: {missing}"
    if (output_root / "instruction.md").stat().st_size < 500:
        return "instruction.md was not substantively authored"
    if (output_root / "solution/report.md").stat().st_size < 1000:
        return "solution/report.md was not substantively authored"
    for relative in (
        "solution/evidence_graph.json",
        "tests/reference/ground_truth.json",
        "tests/rubrics.json",
    ):
        try:
            value = json.loads((output_root / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"invalid builder JSON {relative}: {exc}"
        if not isinstance(value, dict) or len(value) < 2:
            return f"builder JSON remained a schema-only placeholder: {relative}"
    return None


_RETRYABLE_PROVIDER_ERRORS = (
    "provider finish_reason: error",
    "queued past the",
    "retry after",
    "http 429",
    "http 502",
    "http 503",
    "http 504",
    "connection reset",
    "timed out",
)


def _retryable_provider_error(stderr_path: Path) -> bool:
    if not stderr_path.is_file():
        return False
    text = stderr_path.read_text(encoding="utf-8", errors="replace").casefold()
    return any(pattern in text for pattern in _RETRYABLE_PROVIDER_ERRORS)


async def _run_builder_stage(
    name: str,
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: float,
    trial_root: Path,
    retry_provider_errors: bool,
) -> tuple[int, float, int]:
    total_duration = 0.0
    for attempt in range(1, 3):
        suffix = "" if attempt == 1 else f".attempt-{attempt}"
        stdout_path = trial_root / f"{name}{suffix}.jsonl"
        stderr_path = trial_root / f"{name}{suffix}.stderr.txt"
        return_code, duration = await _run_builder_process(
            command,
            env=env,
            cwd=cwd,
            timeout=timeout,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        total_duration += duration
        if (
            return_code == 0
            or not retry_provider_errors
            or not _retryable_provider_error(stderr_path)
            or attempt == 2
        ):
            return return_code, total_duration, attempt
        await asyncio.sleep(2.0 + random.random() * 2.0)
    raise AssertionError("bounded builder stage loop did not return")


def _checkpoint_prompt(ctx, output_root: Path) -> str:
    checkpoint = ctx.task_dir / "task-planning" / "builder-checkpoint.json"
    return f"""You are the checkpoint author for one Online Search task.
Use the available DSH tools in Code Mode. Do not browse, delegate, or explain a
plan. Work immediately and durably.

First read the five existing task-specific files under:
{output_root}

Then overwrite each one with a substantive task-specific scaffold derived from
this seed:
{json.dumps(ctx.seed, ensure_ascii=False)}

Required now:
- instruction.md: at least 500 bytes with a concrete supplied scenario;
- solution/report.md: at least 1000 bytes with section outlines and provisional analysis;
- evidence_graph.json, ground_truth.json, and rubrics.json: valid normalized
  Online Search JSON objects using task id {ctx.task_id}. Do not create a source
  manifest, approved-domain list, tier/role fields, or evaluator metadata.
- write {checkpoint} as JSON containing task_id, scenario, research_questions,
  source_queries, and files_written.

Use small sequential read/write calls, one file per write. Do not emit literal
<invoke> markup. Finish only after rereading every written file and confirming
it is nonempty. This is a checkpoint, not the final validator stage."""


def _repair_prompt(ctx, output_root: Path, output_error: str) -> str:
    return f"""Complete an interrupted Online Search task in place at:
{output_root}

The prior authoring pass ended with: {output_error}

Read and preserve every substantive existing file. Finish only the missing,
placeholder, invalid, or inconsistent portions. Use the seed at
{ctx.task_dir / 'task-planning' / 'seed.json'} and the checkpoint at
{ctx.task_dir / 'task-planning' / 'builder-checkpoint.json'}. Do not restart
research from scratch, delegate, create a nested output directory, or return a
plan. Use small sequential Code Mode calls and write one file at a time. Then
reread all five task-specific files, reconcile their IDs and URLs, and run the
exact validator command already given in the original authoring instructions.
Stop after the validator succeeds."""


async def _validate_staged_output(ctx, output_root: Path) -> tuple[bool, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ctx.pipeline_dir / "scripts" / "validate_live_task.py"),
        "--task-root",
        str(output_root),
        "--task-id",
        str(ctx.task_id),
        "--mode",
        "capture",
        cwd=ctx.task_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=480)
    except TimeoutError:
        process.kill()
        await process.wait()
        return False, "staged task validation exceeded 480 seconds"
    message = output.decode("utf-8", "replace")[-6000:]
    return process.returncode == 0, message


@register_step("benchmark.build_lane")
async def benchmark_build_lane(ctx, params):
    """Build one task with the selected benchmark harness, never with codx."""
    # Imported lazily so the pipeline's small custom-gate unit harness does not
    # need to recreate Yggdrasil's full built-in step package.
    from yggdrasil.steps.build import _promote_task_output, render_instructions

    lane = str(params.get("lane", ""))
    if lane not in BENCHMARK_BUILDER_LANES:
        return False, f"unknown benchmark builder lane: {lane!r}"

    instructions = ctx.pipeline_dir / str(params["instructions_file"])
    if not instructions.is_file():
        return False, f"builder instructions are missing: {instructions}"
    output_root = ctx.task_dir / "output" / ctx.task_id
    try:
        _stage_builder_output(ctx, output_root)
    except (FileExistsError, FileNotFoundError, OSError) as exc:
        return False, f"builder output staging failed: {exc}"
    rendered_params = {
        **params,
        "task_path": str(output_root),
        "template_path": str(ctx.task_dir),
    }
    instruction_text = instructions.read_text(encoding="utf-8").replace(
        "{VALIDATOR_PATH}",
        str(ctx.pipeline_dir / "scripts" / "validate_live_task.py"),
    )
    prompt = render_instructions(instruction_text, ctx, rendered_params)
    if lane != "control-native":
        vision_contract = ctx.pipeline_dir / "prompts" / "benchmark_vision_helper.md"
        if vision_contract.is_file():
            prompt = vision_contract.read_text(encoding="utf-8") + "\n\n" + prompt

    trial_root = ctx.task_dir.parent / ".builder-traces" / ctx.task_id
    trial_root.mkdir(parents=True, exist_ok=False)
    (trial_root / "artifacts").mkdir()
    (trial_root / "prompt.md").write_text(prompt, encoding="utf-8")
    started_at = dt.datetime.now(dt.UTC).isoformat()
    stage_results: list[dict[str, object]] = []
    stage_failure: str | None = None
    try:
        await _wait_for_builder_barrier()
        started_at = dt.datetime.now(dt.UTC).isoformat()
        command, env, model = _builder_command(lane, prompt, trial_root)
        timeout = float(params.get("timeout_sec", 5400))
        duration = 0.0
        builder_attempts = 0

        if lane == "deepseek-dsh-dsml":
            checkpoint_prompt = _checkpoint_prompt(ctx, output_root)
            (trial_root / "checkpoint-prompt.md").write_text(
                checkpoint_prompt,
                encoding="utf-8",
            )
            checkpoint_code, checkpoint_duration, checkpoint_attempts = (
                await _run_builder_stage(
                    "checkpoint",
                    [*command[:-1], checkpoint_prompt],
                    env=env,
                    cwd=ctx.task_dir,
                    timeout=min(timeout, 1200.0),
                    trial_root=trial_root,
                    retry_provider_errors=True,
                )
            )
            duration += checkpoint_duration
            builder_attempts += checkpoint_attempts
            checkpoint_error = _builder_output_error(output_root)
            stage_results.append(
                {
                    "stage": "checkpoint",
                    "exit_code": checkpoint_code,
                    "duration_sec": round(checkpoint_duration, 6),
                    "attempts": checkpoint_attempts,
                    "output_error": checkpoint_error,
                }
            )
            if checkpoint_code != 0 or checkpoint_error is not None:
                return_code = checkpoint_code
                stage_failure = (
                    f"checkpoint exited {checkpoint_code}"
                    if checkpoint_code != 0
                    else f"checkpoint incomplete: {checkpoint_error}"
                )
            else:
                author_prompt = (
                    "Continue from the completed checkpoint. Research the live public "
                    "web as broadly as the task requires; no source list or host is "
                    "preapproved. Finish the five task-specific files and validate them.\n\n"
                    + prompt
                )
                (trial_root / "author-prompt.md").write_text(
                    author_prompt,
                    encoding="utf-8",
                )
                return_code, full_duration, full_attempts = await _run_builder_stage(
                    "trace",
                    [*command[:-1], author_prompt],
                    env=env,
                    cwd=ctx.task_dir,
                    timeout=timeout,
                    trial_root=trial_root,
                    retry_provider_errors=True,
                )
                duration += full_duration
                builder_attempts += full_attempts
                stage_results.append(
                    {
                        "stage": "author",
                        "exit_code": return_code,
                        "duration_sec": round(full_duration, 6),
                        "attempts": full_attempts,
                    }
                )
                output_error = _builder_output_error(output_root)
                validation_ok = False
                validation_message = ""
                if return_code == 0 and output_error is None:
                    validation_ok, validation_message = await _validate_staged_output(
                        ctx,
                        output_root,
                    )
                repair_reason = output_error or (
                    None if validation_ok else validation_message
                )
                stage_results[-1].update(
                    {
                        "output_error": output_error,
                        "validation_ok": validation_ok,
                        "validation_message": validation_message,
                    }
                )
                if return_code == 0 and repair_reason:
                    repair_prompt = _repair_prompt(ctx, output_root, repair_reason)
                    (trial_root / "repair-prompt.md").write_text(
                        repair_prompt,
                        encoding="utf-8",
                    )
                    repair_code, repair_duration, repair_attempts = (
                        await _run_builder_stage(
                            "repair",
                            [*command[:-1], repair_prompt],
                            env=env,
                            cwd=ctx.task_dir,
                            timeout=min(timeout, 2400.0),
                            trial_root=trial_root,
                            retry_provider_errors=True,
                        )
                    )
                    duration += repair_duration
                    builder_attempts += repair_attempts
                    return_code = repair_code
                    stage_results.append(
                        {
                            "stage": "repair",
                            "exit_code": repair_code,
                            "duration_sec": round(repair_duration, 6),
                            "attempts": repair_attempts,
                            "initial_failure": repair_reason,
                        }
                    )
                    if return_code == 0:
                        output_error = _builder_output_error(output_root)
                        if output_error is None:
                            validation_ok, validation_message = (
                                await _validate_staged_output(ctx, output_root)
                            )
                        else:
                            validation_ok = False
                            validation_message = output_error
                        stage_results[-1].update(
                            {
                                "output_error": output_error,
                                "validation_ok": validation_ok,
                                "validation_message": validation_message,
                            }
                        )
                        if not validation_ok:
                            stage_failure = (
                                "repair did not produce a valid task: "
                                + validation_message
                            )
                elif return_code == 0 and not validation_ok:
                    stage_failure = "authoring validation failed: " + validation_message
        else:
            return_code, duration, builder_attempts = await _run_builder_stage(
                "trace",
                command,
                env=env,
                cwd=ctx.task_dir,
                timeout=timeout,
                trial_root=trial_root,
                retry_provider_errors=lane in {"deepseek-dsh", "deepseek-dsh-dsml"},
            )
            stage_results.append(
                {
                    "stage": "author",
                    "exit_code": return_code,
                    "duration_sec": round(duration, 6),
                    "attempts": builder_attempts,
                }
            )
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        (trial_root / "status.json").write_text(
            json.dumps(
                {
                    "schema_version": "online-search-builder-v1",
                    "lane": lane,
                    "started_at": started_at,
                    "preflight_error": str(exc),
                    "exit_code": None,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return False, f"benchmark builder preflight failed for {lane}: {exc}"

    output_error = (
        _builder_output_error(output_root) if output_root.is_dir() else "output directory missing"
    )
    status = {
        "schema_version": "online-search-builder-v1",
        "lane": lane,
        "model": model,
        "started_at": started_at,
        "duration_sec": round(duration, 6),
        "builder_attempts": builder_attempts,
        "stages": stage_results,
        "stage_failure": stage_failure,
        "exit_code": return_code,
        "output_present": output_root.is_dir(),
        "output_complete": output_error is None,
        "context_window": 1_000_000,
        "compaction_disabled": True,
        "reasoning_effort": "xhigh",
        "dsh_home_isolated": lane in {"deepseek-dsh", "deepseek-dsh-dsml"},
    }
    (trial_root / "status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if stage_failure is not None:
        ctx.harbor_trials.append(trial_root)
        return False, f"benchmark builder {lane} stage failed: {stage_failure}"
    if return_code != 0:
        ctx.harbor_trials.append(trial_root)
        return False, (
            f"benchmark builder {lane} exited {return_code} after {duration:.1f}s; "
            f"trace: {trial_root}"
        )
    if not output_root.is_dir():
        ctx.harbor_trials.append(trial_root)
        return False, f"benchmark builder {lane} produced no task at {output_root}"
    if output_error is not None:
        ctx.harbor_trials.append(trial_root)
        return False, f"benchmark builder {lane} left an incomplete task: {output_error}"

    shutil.copytree(
        output_root,
        trial_root / "artifacts" / "output" / ctx.task_id,
        dirs_exist_ok=True,
    )
    ctx.harbor_trials.append(trial_root)
    try:
        _promote_task_output(output_root, ctx.task_dir)
    except (OSError, shutil.Error, ValueError) as exc:
        return False, f"benchmark builder {lane} output promotion failed: {exc}"
    return True, f"{lane} builder completed in {duration:.3f}s"


def _positive_oracle_feedback(task_root: Path, oracle_trial: Path) -> list[dict[str, str]]:
    judgment_path = oracle_trial / "agentic-deepseek" / "judgment.json"
    if not judgment_path.is_file():
        return []
    judgment = json.loads(judgment_path.read_text(encoding="utf-8"))
    rubric = json.loads((task_root / "tests" / "rubrics.json").read_text(encoding="utf-8"))
    positive_ids = {
        str(item.get("id"))
        for item in rubric.get("criteria") or []
        if float(item.get("weight") or 0) > 0
    }
    return [
        {
            "id": str(row.get("criterion_id") or row.get("id")),
            "reason": str(row.get("rationale") or row.get("reason") or ""),
        }
        for row in judgment.get("judgments") or judgment.get("criteria") or []
        if row.get("verdict") == "UNMET"
        and str(row.get("criterion_id") or row.get("id")) in positive_ids
    ]


async def _repair_oracle_report(ctx, feedback: list[dict[str, str]]) -> tuple[bool, str]:
    if not feedback:
        return False, "Oracle supplied no actionable unmet positive criteria"
    trace_root = ctx.task_dir.parent / ".oracle-repair-traces" / ctx.task_id
    trace_root.mkdir(parents=True, exist_ok=False)
    (trace_root / "artifacts").mkdir()
    prompt = f"""Repair only the golden report at {ctx.task_dir / 'solution' / 'report.md'}.
Read it first. Preserve all correct content, citations, verdict labels, and safe
abstentions. Add the smallest explicit statements needed to satisfy these unmet
positive Oracle criteria:
{json.dumps(feedback, indent=2, ensure_ascii=False)}

Use only canonical sources already present in ground_truth.json and cite exact
adjacent URLs. Do not change the instruction, rubric, evidence graph,
or ground truth. Do not browse, delegate, or return a plan. Write the report
once, reread it, and stop."""
    (trace_root / "prompt.md").write_text(prompt, encoding="utf-8")
    try:
        command, env, model = _builder_command(
            "deepseek-dsh-dsml",
            prompt,
            trace_root,
        )
        code, duration, attempts = await _run_builder_stage(
            "trace",
            command,
            env=env,
            cwd=ctx.task_dir,
            timeout=1800,
            trial_root=trace_root,
            retry_provider_errors=True,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        return False, f"Oracle report repair could not start: {exc}"
    validation_ok = False
    validation_message = "repair process failed"
    if code == 0:
        validation_ok, validation_message = await _validate_staged_output(
            ctx,
            ctx.task_dir,
        )
    status = {
        "schema_version": "online-search-oracle-report-repair-v1",
        "model": model,
        "exit_code": code,
        "duration_sec": round(duration, 6),
        "attempts": attempts,
        "feedback": feedback,
        "validation_ok": validation_ok,
        "validation_message": validation_message,
    }
    (trace_root / "status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ctx.harbor_trials.append(trace_root)
    if code != 0:
        return False, f"Oracle report repair exited {code}"
    return validation_ok, validation_message


@register_step("doraemon.oracle_min_score")
async def oracle_min_score(ctx, params):
    """Require a real golden-path Oracle score strictly above a floor."""
    from yggdrasil.engine.context import StepResult

    minimum = float(params.get("minimum", 0.9))
    trial_root = ctx.task_dir.parent / ".oracle-traces" / ctx.task_id / str(time.time_ns())
    (trial_root / "deliverables").mkdir(parents=True, exist_ok=False)
    shutil.copy2(ctx.task_dir / "solution/report.md", trial_root / "deliverables/report.md")
    (trial_root / "result.json").write_text(
        json.dumps({"task": ctx.task_id, "status": "done", "role": "oracle"}) + "\n",
        encoding="utf-8",
    )
    score = None
    infrastructure_errors = []
    for attempt in range(1, 3):
        try:
            await _grade_muse_deliverables(ctx, trial_root, role="oracle")
            summary = json.loads((trial_root / "result.json").read_text(encoding="utf-8"))
            raw_score = summary.get("verifier_score")
            score = float(raw_score)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            infrastructure_errors.append(f"{type(exc).__name__}: {exc}")
            if attempt == 1:
                await asyncio.sleep(2)
                continue
            break
        if score is not None and math.isfinite(score):
            break
        infrastructure_errors.append(f"missing real Oracle reward (attempt {attempt})")
        if attempt == 1:
            await asyncio.sleep(2)
    if score is None or not math.isfinite(score):
        return False, "oracle infrastructure failed: " + " | ".join(infrastructure_errors)
    ctx.harbor_trials.append(trial_root)
    if ctx.artifacts is not None:
        try:
            ctx.artifacts.upload(trial_root, relative_to=trial_root.parent)
        except FileNotFoundError:
            pass
    ctx.step_results["doraemon.oracle_min_score"] = StepResult(
        name="doraemon.oracle_min_score",
        success=True,
        score=score,
        artifacts={
            "score": score,
            "required": f"> {minimum}",
            "trial_dir": str(trial_root),
            "infrastructure_errors": infrastructure_errors,
        },
    )
    if (
        score <= minimum
        and params.get("allow_report_repair", True)
        and trial_root is not None
    ):
        feedback = _positive_oracle_feedback(ctx.task_dir, trial_root)
        repaired, repair_message = await _repair_oracle_report(ctx, feedback)
        if not repaired:
            return False, f"oracle score {score:.3f}; report repair failed: {repair_message}"
        return await oracle_min_score(
            ctx,
            {**params, "allow_report_repair": False},
        )
    if score <= minimum:
        return False, f"oracle score {score:.3f} must be > {minimum:.3f}"
    return True, f"oracle score {score:.3f} > {minimum:.3f}"


@register_step("doraemon.semantic_massage")
async def semantic_massage(ctx, params):
    """Run one independent xhigh semantic/fairness repair before Oracle."""
    from yggdrasil.steps.build import render_instructions

    prompt_path = ctx.pipeline_dir / str(
        params.get("instructions_file", "prompts/massage_online_search_task.md")
    )
    if not prompt_path.is_file():
        return False, f"semantic massage prompt is missing: {prompt_path}"
    rendered = prompt_path.read_text(encoding="utf-8").replace(
        "{VALIDATOR_PATH}",
        str(ctx.pipeline_dir / "scripts" / "validate_live_task.py"),
    )
    prompt = render_instructions(
        rendered,
        ctx,
        {"task_path": str(ctx.task_dir), "template_path": str(ctx.task_dir)},
    )
    trace_root = ctx.task_dir.parent / ".massage-traces" / ctx.task_id
    if trace_root.exists():
        return False, f"semantic massage trace already exists: {trace_root}"
    trace_root.mkdir(parents=True)
    (trace_root / "prompt.md").write_text(prompt, encoding="utf-8")
    try:
        command, env, model = _builder_command(
            "deepseek-dsh-dsml",
            prompt,
            trace_root,
        )
        code, duration, attempts = await _run_builder_stage(
            "trace",
            command,
            env=env,
            cwd=ctx.task_dir,
            timeout=float(params.get("timeout_sec", 3600)),
            trial_root=trace_root,
            retry_provider_errors=True,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        return False, f"semantic massage could not start: {exc}"
    validation_ok = False
    validation_message = "massage process failed"
    if code == 0:
        validation_ok, validation_message = await _validate_staged_output(
            ctx,
            ctx.task_dir,
        )
    status = {
        "schema_version": "online-search-semantic-massage-v1",
        "model": model,
        "reasoning_effort": "xhigh",
        "exit_code": code,
        "duration_sec": round(duration, 6),
        "attempts": attempts,
        "validation_ok": validation_ok,
        "validation_message": validation_message,
    }
    (trace_root / "status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    ctx.harbor_trials.append(trace_root)
    if ctx.artifacts is not None:
        try:
            ctx.artifacts.upload(trace_root, relative_to=trace_root.parent)
        except FileNotFoundError:
            pass
    if code != 0:
        return False, f"semantic massage exited {code}; trace: {trace_root}"
    return validation_ok, validation_message


def _muse_harness_path() -> Path:
    configured = os.environ.get("ONLINE_SEARCH_MUSE_HARNESS", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path.home() / "miniswe-muse-fleet",
        Path.home() / ".cache" / "doraemon" / "miniswe-muse",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "muse_agent" / "__main__.py").is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "miniswe-muse harness not found; set ONLINE_SEARCH_MUSE_HARNESS"
    )


async def _run_one_muse_slot(ctx, output_root: Path, logical_trial: int, max_attempts: int):
    harness = _muse_harness_path()
    entrypoint = harness / "muse_agent" / "__main__.py"
    if "finish-prompt-tokens" not in entrypoint.read_text(encoding="utf-8"):
        raise RuntimeError(
            "miniswe-muse is missing --finish-prompt-tokens; use the current fleet harness"
        )
    launchpad_token = (
        os.environ.get("PARSEWAVE_TOKEN")
        or os.environ.get("MUSE_API_KEY")
        or ""
    ).strip()
    if not launchpad_token:
        raise RuntimeError("PARSEWAVE_TOKEN or MUSE_API_KEY is required for Muse trials")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(harness)
    env["OPENROUTER_API_KEY"] = launchpad_token
    env["MUSE_VERIFIER_TIMEOUT_SEC"] = "1600"
    last_error = "no attempt ran"
    for attempt in range(1, max_attempts + 1):
        run_name = f"trial-{logical_trial}-attempt-{attempt}"
        run_dir = output_root / ctx.task_id / run_name
        log_path = output_root / ctx.task_id / f"{run_name}.log"
        command = [
            sys.executable,
            "-m",
            "muse_agent",
            "--task-dir",
            str(ctx.task_dir),
            "--provider",
            "openrouter",
            "--base-url",
            "https://console.parsewave.ai/api/launchpad/muse/prod/v1",
            "--model",
            "meta-muse-spark",
            "--out",
            str(output_root),
            "--run-name",
            run_name,
            "--max-steps",
            "0",
            "--min-tool-calls",
            "1",
            "--agent-timeout-sec",
            "10800",
            "--call-timeout-sec",
            "1800",
            "--model-timeout-sec",
            "1800",
            "--max-tokens",
            "65536",
            "--max-output-chars",
            "0",
            "--context-goal-tokens",
            "700000",
            "--context-hard-limit-tokens",
            "1048576",
            "--finish-prompt-tokens",
            "950000",
            "--reasoning-effort",
            "xhigh",
            "--max-retries",
            "7",
            "--empty-response-retries",
            "2",
            "--retry-initial-sec",
            "5",
            "--retry-max-sec",
            "60",
            "--agent-user",
            "agent",
            "--observer-port",
            "0",
        ]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=harness,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                # The agent itself is hard-capped at 10,800 seconds. This outer
                # allowance leaves time for image setup and the separate
                # 1,600-second verifier without extending solver work.
                await asyncio.wait_for(process.wait(), timeout=12_900)
            except TimeoutError:
                process.kill()
                await process.wait()
        deliverables = run_dir / "deliverables"
        report = deliverables / "report.md"
        if report.is_file() and report.stat().st_size > 0:
            try:
                await _grade_muse_deliverables(ctx, run_dir)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                last_error = f"attempt {attempt}: grading failed: {exc}"
                continue
        try:
            metrics = muse_trial_metrics(run_dir)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            last_error = f"attempt {attempt}: {exc}"
            continue
        return run_dir, metrics
    raise RuntimeError(
        f"Muse logical trial {logical_trial} exhausted {max_attempts} attempts: {last_error}"
    )


async def _grade_muse_deliverables(ctx, run_dir: Path, *, role: str = "verifier") -> None:
    """Judge the preserved solver report with the real Agentic Verifier Harness."""
    cli = os.environ.get("ONLINE_SEARCH_AGENTIC_VERIFIER_BIN", "").strip()
    if not cli or not Path(cli).is_file():
        raise RuntimeError(
            "Agentic Verifier CLI is missing; run scripts/setup_agentic_verifier.sh"
        )
    search_url = os.environ.get("VERIFIER_SEARCH_URL", "").strip()
    if not search_url:
        raise RuntimeError("online Agentic Verifier requires VERIFIER_SEARCH_URL")
    env = os.environ.copy()
    env.update(
        {
            "VERIFIER_MODEL": DEEPSEEK_MODEL,
            "VERIFIER_BASE_URL": env.get("LLM_JUDGE_BASE_URL", "https://openrouter.ai/api/v1"),
            "VERIFIER_API_KEY": env.get("LLM_JUDGE_API_KEY", ""),
            "VERIFIER_REASONING_EFFORT": "xhigh",
            "VERIFIER_MAX_DURATION": "1500",
            "VERIFIER_MODEL_TIMEOUT": "600",
            "VERIFIER_MODEL_RETRIES": "5",
            "VERIFIER_MAX_TURNS": "16",
            "VERIFIER_MAX_TOOL_CALLS": "128",
            "VERIFIER_CONTEXT_WINDOW_TOKENS": "800000",
        }
    )
    grade_root = run_dir / "agentic-deepseek"
    command = [
        cli,
        "verify",
        "--task-root",
        str(ctx.task_dir),
        "--candidate-root",
        str(run_dir / "deliverables"),
        "--mode",
        "online",
        "--role",
        role,
        "--log-root",
        str(grade_root),
        "--batch-size",
        "50",
        "--parallel-batches",
        "1",
        "--oracle-threshold",
        "0.9",
    ]
    grade_root.mkdir(parents=True, exist_ok=True)
    with (grade_root / "runner.log").open("ab") as log:
        process = await asyncio.create_subprocess_exec(
            *command,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=log,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=1600)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("Agentic Verifier exceeded 1600 seconds") from None
    judgment = json.loads((grade_root / "judgment.json").read_text(encoding="utf-8"))
    if judgment.get("status") != "graded":
        raise RuntimeError(f"Agentic Verifier status is {judgment.get('status')!r}")
    raw_score = judgment.get("score")
    score = raw_score.get("score") if isinstance(raw_score, dict) else raw_score
    if not isinstance(score, (int, float)) or not math.isfinite(score):
        raise RuntimeError("Agentic Verifier did not return a finite score")
    result_path = run_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.update(
        verifier_score=float(score),
        verifier_error=None,
        verifier_pending=False,
        verifier_model=DEEPSEEK_MODEL,
        verifier_harness="agentic-verifier-harness",
        verifier_reasoning_effort="xhigh",
    )
    temporary = result_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(result_path)


@register_step("doraemon.muse_solver_lane")
async def muse_solver_lane(ctx, params):
    """Run the exact three-trial meta-muse-spark production configuration."""
    from yggdrasil.engine.context import StepResult

    trials = int(params.get("trials", 3))
    max_attempts = int(params.get("max_attempts", 4))
    if trials != 3:
        return False, "Online Search requires exactly three logical Muse trials"
    if max_attempts < 1 or max_attempts > 4:
        return False, "max_attempts must be between 1 and 4"
    output_root = (
        ctx.logger.log_path.parent / "muse"
        if ctx.logger is not None
        else ctx.task_dir.parent / ".muse-traces"
    )
    output_root = output_root / f"cohort-{time.time_ns()}"
    output_root.mkdir(parents=True, exist_ok=False)

    async def bounded_slot(index):
        semaphore = getattr(ctx, "trial_semaphore", None)
        if semaphore is not None:
            async with semaphore:
                return await _run_one_muse_slot(ctx, output_root, index, max_attempts)
        return await _run_one_muse_slot(ctx, output_root, index, max_attempts)

    # Await every slot even if one fails; never advance the task while sibling
    # solver processes are still using its package.
    outcomes = await asyncio.gather(
        *(bounded_slot(index) for index in range(1, trials + 1)),
        return_exceptions=True,
    )
    errors = [
        {"logical_trial": index, "error": str(outcome)}
        for index, outcome in enumerate(outcomes, 1)
        if isinstance(outcome, BaseException)
    ]
    completed = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]

    directories = [str(path) for path, _metrics in completed]
    scores = [metrics.score for _path, metrics in completed]
    for path, _metrics in completed:
        ctx.harbor_trials.append(path)
        if ctx.artifacts is not None:
            try:
                ctx.artifacts.upload(path, relative_to=output_root)
            except FileNotFoundError:
                pass
    artifacts = {
        "model": "meta-muse-spark",
        "reasoning_effort": "xhigh",
        "solver_timeout_sec": 10800,
        "context_goal_tokens": 700_000,
        "finish_prompt_tokens": 950_000,
        "context_hard_limit_tokens": 1_048_576,
        "n_trials": 3,
        "n_valid_trials": len(completed),
        "invalid_trials": errors,
        "scores": scores,
        "trial_dirs": directories,
        "trials": [
            {
                "agent": "miniswe-muse",
                "model": "meta-muse-spark",
                "lane_trial_idx": index,
                "reward": metrics.score,
                "valid": True,
                "peak_call_context": metrics.peak_call_context,
                "trial_dir": str(path),
            }
            for index, (path, metrics) in enumerate(completed, 1)
        ],
    }
    result = StepResult(
        name="doraemon.muse_solver_lane",
        success=not errors,
        artifacts=artifacts,
    )
    ctx.step_results["doraemon.muse_solver_lane"] = result
    ctx.step_results["difficulty.solver_lane"] = result
    if errors:
        return False, f"Muse solver cohort has {len(errors)} invalid slot(s): {errors}"
    return True, "three gradable Muse trials completed"


@register_step("doraemon.publication_gate")
async def publication_gate(ctx, params):
    """Apply the calibrated solver-score and peak-call-context gates."""
    from yggdrasil.engine.context import StepResult

    difficulty = ctx.step_results.get("doraemon.muse_solver_lane")
    if difficulty is None:
        difficulty = ctx.step_results.get("difficulty.solver_lane")
    artifacts = getattr(difficulty, "artifacts", {}) if difficulty is not None else {}
    expected = int(artifacts.get("n_valid_trials") or 0)
    scores = [float(value) for value in artifacts.get("scores") or []]
    if expected < 1 or len(scores) != expected:
        return False, "publication gate requires a complete valid solver cohort"
    muse_directories = [Path(value) for value in artifacts.get("trial_dirs") or []]
    if muse_directories:
        if len(muse_directories) != expected:
            return False, (
                "publication gate found "
                f"{len(muse_directories)}/{expected} Muse trial directories"
            )
        try:
            trials = [muse_trial_metrics(path) for path in muse_directories]
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"Muse publication telemetry is invalid: {exc}"
    else:
        if ctx.logger is None:
            return False, "publication gate cannot resolve the Harbor trial directory"
        harbor_root = ctx.logger.log_path.parent / "harbor" / ctx.task_id
        solver_names = [
            entry["name"]
            for entry in ctx.trace_uris
            if entry.get("role") == "solver" and entry.get("name")
        ][-expected:]
        if len(solver_names) == expected:
            trial_dirs = [harbor_root / name for name in solver_names]
        else:
            candidates = [
                result.parent
                for result in harbor_root.glob("*/result.json")
                if (result.parent / "agent" / "trajectory.json").is_file()
            ]
            trial_dirs = sorted(
                candidates,
                key=lambda path: (path / "result.json").stat().st_mtime_ns,
            )[-expected:]
        if len(trial_dirs) != expected:
            return False, f"publication gate found {len(trial_dirs)}/{expected} solver traces"
        try:
            trials = [trial_metrics(path) for path in trial_dirs]
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"publication telemetry is invalid: {exc}"
    try:
        summary = publication_summary(
            trials,
            maximum_mean_score=float(params.get("maximum_mean_score", 0.8)),
            minimum_max_peak_call_context=int(
                params.get("minimum_max_peak_call_context", 500_000)
            ),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return False, f"publication telemetry is invalid: {exc}"
    observed_scores = sorted(item.score for item in trials)
    if observed_scores != sorted(scores):
        return False, "publication trace rewards do not match difficulty results"
    ctx.step_results["doraemon.publication_gate"] = StepResult(
        name="doraemon.publication_gate",
        success=True,
        artifacts=summary,
    )
    if not summary["accepted"]:
        return False, (
            f"publication gate failed: mean_score={summary['mean_score']:.3f}, "
            f"maximum_peak_call_context={summary['maximum_peak_call_context']}"
        )
    return True, (
        f"publication gate passed: mean_score={summary['mean_score']:.3f}, "
        f"maximum_peak_call_context={summary['maximum_peak_call_context']}"
    )


def _runtime_path(ctx, value: object, *, label: str) -> tuple[Path | None, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, f"{label} is required"
    expanded = os.path.expandvars(raw)
    if re.search(r"\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)", expanded):
        return None, f"{label} references an unset environment variable: {raw}"
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = ctx.pipeline_dir / path
    return path, None


@register_step("doraemon.idea_file_pick_no_wrap")
async def idea_file_pick_no_wrap(ctx, params):
    """Select a sequential shard entry once; fail instead of wrapping."""
    configured = getattr(
        getattr(getattr(ctx, "config", None), "ideation", None),
        "source",
        None,
    )
    path, error = _runtime_path(
        ctx,
        params.get("file") or configured or "ideas.yaml",
        label="ideas file",
    )
    if path is None:
        return False, error
    if not path.is_file():
        return False, f"ideas file not found: {path}"

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    ideas = payload.get("ideas") if isinstance(payload, dict) else payload
    if not isinstance(ideas, list) or not ideas:
        return False, f"ideas file {path} must contain a non-empty list"

    if "index" in params:
        index = int(params["index"])
    else:
        match = re.match(r"^(\d+)-", str(ctx.task_id))
        if match is None:
            return False, f"task id has no sequential index: {ctx.task_id}"
        index = int(match.group(1))
    if index < 0 or index >= len(ideas):
        return False, (
            f"idea shard exhausted at index {index}; {path.name} contains "
            f"{len(ideas)} ideas and will not wrap"
        )

    seed = ideas[index]
    ctx.seed = seed if isinstance(seed, dict) else {"idea": seed}
    return True, None


def _normalized_domain(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


@register_step("doraemon.domain_taxonomy")
async def domain_taxonomy(ctx, params):
    """Reject unknown or excluded domains before any model or template work."""
    taxonomy_path = ctx.pipeline_dir / str(
        params.get("taxonomy_file", "domain-taxonomy.yaml")
    )
    if not taxonomy_path.is_file():
        return False, f"domain taxonomy is missing: {taxonomy_path}"
    payload = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != (
        "online-search-domain-taxonomy-v1"
    ):
        return False, "domain taxonomy schema mismatch"
    allowed_values = payload.get("allowed_domains")
    forbidden_values = payload.get("forbidden_domains")
    if not isinstance(allowed_values, list) or not isinstance(forbidden_values, list):
        return False, "domain taxonomy lists are malformed"
    allowed = {_normalized_domain(value): str(value) for value in allowed_values}
    forbidden = {_normalized_domain(value) for value in forbidden_values}
    domain = str(ctx.seed.get("domain") or "").strip()
    normalized = _normalized_domain(domain)
    blocked = any(
        normalized == value
        or normalized.startswith(value + " ")
        or normalized.endswith(" " + value)
        for value in forbidden
        if value
    )
    if blocked:
        return False, f"seed domain is explicitly excluded: {domain!r}"
    if normalized not in allowed:
        return False, f"seed domain is outside the approved taxonomy: {domain!r}"
    ctx.seed["domain"] = allowed[normalized]
    for source_hint_field in (
        "allowed_domains",
        "approved_domains",
        "authoritative_domains",
        "source_domains",
        "source_whitelist",
    ):
        ctx.seed.pop(source_hint_field, None)
    return True, f"domain accepted: {ctx.seed['domain']}"


@register_step("doraemon.semantic_identity")
async def semantic_identity(ctx, params):
    """Use the idea ID as the stable task ID and task-directory name."""
    idea_id = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(ctx.seed.get("id") or ctx.seed.get("idea") or "").casefold(),
    ).strip("-")
    if not idea_id:
        return False, "idea has no usable semantic identifier"
    task_id = idea_id[:80].rstrip("-")
    required_words = params.get("words")
    if required_words is not None and len(task_id.split("-")) != int(required_words):
        return False, (
            f"semantic task ID must contain exactly {int(required_words)} "
            f"hyphen-separated words: {task_id}"
        )
    old_dir = ctx.task_dir
    new_dir = old_dir.parent / task_id
    if new_dir.exists() and new_dir != old_dir:
        return False, f"semantic task directory already exists: {new_dir}"
    if old_dir.exists() and old_dir != new_dir:
        old_dir.rename(new_dir)
    ctx.task_id = task_id
    ctx.task_dir = new_dir
    if ctx.artifacts is not None:
        prefix = str(getattr(ctx.artifacts, "key_prefix", "") or "")
        if prefix:
            ctx.artifacts.key_prefix = f"{prefix.rsplit('/', 1)[0]}/{task_id}"
    return True, task_id


@register_step("doraemon.restore_canonical")
async def restore_canonical(ctx, _params):
    """Restore invariant live-web runtime and verifier files byte-for-byte."""
    canonical = ctx.pipeline_dir / "canonical"
    if not canonical.is_dir():
        return False, f"canonical directory is missing: {canonical}"
    for relative in CANONICAL_FILES:
        source = canonical / relative
        destination = ctx.task_dir / relative
        if not source.is_file():
            return False, f"canonical file is missing: {relative}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    # Legacy templates contained verifier-only metadata that is forbidden by
    # the current twelve-file Online Search publication contract.
    for relative in (
        "tests/reference/source_manifest.json",
        "tests/reference/evidence_graph.json",
        "tests/evidence_graph.json",
        "tests/docker-compose.yaml",
        "tests/docker-compose.yml",
    ):
        path = ctx.task_dir / relative
        if path.is_file():
            path.unlink()

    task_toml = (canonical / "task.toml").read_text(encoding="utf-8")
    (ctx.task_dir / "task.toml").write_text(
        task_toml.replace("parsewave/example-task", f"parsewave/{ctx.task_id}"),
        encoding="utf-8",
    )
    planning = ctx.task_dir / "task-planning"
    planning.mkdir(parents=True, exist_ok=True)
    (planning / "seed.json").write_text(
        json.dumps(ctx.seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for relative in (
        "solution/solve.sh",
        "tests/test.sh",
        "tests/test_outputs.py",
        "tests/test_utils.py",
    ):
        (ctx.task_dir / relative).chmod(0o755)
    return True, None


async def _run(command: list[str], *, cwd: Path, timeout: float) -> tuple[bool, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        return False, f"command timed out after {timeout:.0f}s"
    text = output.decode("utf-8", errors="replace")
    return process.returncode == 0, text


@register_step("doraemon.validate_live_task")
async def validate_live_task(ctx, params):
    """Run the deterministic task/source validator in capture, verify, or package mode."""
    mode = str(params.get("mode", "capture"))
    if mode not in {"capture", "verify", "package"}:
        return False, f"unsupported validation mode: {mode}"
    script = ctx.pipeline_dir / "scripts/validate_live_task.py"
    if not script.is_file():
        return False, f"live validator is missing: {script}"
    command = [
        sys.executable,
        str(script),
        "--task-root",
        str(ctx.task_dir),
        "--task-id",
        str(ctx.task_id),
        "--mode",
        mode,
    ]
    ok, output = await _run(
        command,
        cwd=ctx.task_dir,
        timeout=float(params.get("timeout_sec", 300)),
    )
    if not ok:
        return False, f"Doraemon {mode} validation failed:\n{output[-12000:]}"
    return True, output[-4000:] or None
