#!/usr/bin/env python3
"""Resume a preserved Media and journalism package after its build step.

This command deliberately cannot instantiate a template or invoke a builder.
It accepts an existing complete task tree and runs only the configured gates
at or after a narrow, named checkpoint.  The campaign runner owns ledger and
lane transitions; this module owns the downstream Yggdrasil context.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import yaml

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

STAGE_START = {
    "preflight": ("preflight.required_files", None),
    "capture": ("doraemon.validate_live_task", "capture"),
    "oracle": ("doraemon.oracle_min_score", None),
    "difficulty": ("doraemon.muse_solver_lane", None),
}

FORBIDDEN_RESUME_STEPS = {
    "doraemon.idea_file_pick_no_wrap",
    "doraemon.semantic_identity",
    "setup.instantiate_template",
    "doraemon.restore_canonical",
    "build.codex",
    "build",
}


def _pipeline_items(config_path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    pipeline = payload.get("pipeline") if isinstance(payload, dict) else None
    if not isinstance(pipeline, list) or not pipeline:
        raise ValueError(f"config has no pipeline: {config_path}")
    if any(not isinstance(item, dict) for item in pipeline):
        raise ValueError("every pipeline item must be an object")
    return pipeline


def resume_step_indexes(config_path: Path, from_stage: str) -> list[int]:
    """Return the exact downstream suffix for a supported resume stage."""
    if from_stage not in STAGE_START:
        raise ValueError(f"unsupported resume stage: {from_stage}")
    wanted_step, wanted_mode = STAGE_START[from_stage]
    items = _pipeline_items(config_path)
    start: int | None = None
    for index, item in enumerate(items):
        if "retry_block" in item:
            raise ValueError("same-package resume does not support retry blocks")
        if item.get("step") != wanted_step:
            continue
        if wanted_mode is not None and (item.get("params") or {}).get("mode") != wanted_mode:
            continue
        start = index
        break
    if start is None:
        raise ValueError(f"resume stage {from_stage!r} is absent from config")
    suffix = items[start:]
    forbidden = sorted(
        str(item.get("step")) for item in suffix if item.get("step") in FORBIDDEN_RESUME_STEPS
    )
    if forbidden:
        raise ValueError(f"resume suffix contains build/setup steps: {forbidden}")
    return list(range(start, len(items)))


def validate_task_root(task_root: Path, task_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2}", task_id):
        raise ValueError(f"invalid three-word task ID: {task_id!r}")
    root = task_root.resolve(strict=True)
    if root.name != task_id:
        raise ValueError(f"task root name {root.name!r} does not match task ID {task_id!r}")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError(f"task root contains a symbolic link: {root}")
    missing = [relative for relative in REQUIRED_TASK_FILES if not (root / relative).is_file()]
    if missing:
        raise ValueError(f"preserved package is incomplete: {', '.join(missing)}")
    return root


def _load_seed(task_root: Path, task_id: str) -> dict[str, Any]:
    seed_path = task_root / "task-planning" / "seed.json"
    if seed_path.is_file():
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        if not isinstance(seed, dict):
            raise ValueError(f"seed must be an object: {seed_path}")
        return seed
    return {"id": task_id}


async def resume_package(
    config_path: Path,
    task_root: Path,
    task_id: str,
    from_stage: str,
    logs_dir: Path,
) -> bool:
    # Imports are intentionally deferred so planning/guard tests do not need a
    # locally installed Yggdrasil checkout. run.sh supplies the pinned package.
    import yggdrasil.steps  # noqa: F401
    from yggdrasil.artifacts import make_artifact_uploader
    from yggdrasil.config import load_config
    from yggdrasil.credentials import load_credentials
    from yggdrasil.engine.context import BuildContext
    from yggdrasil.engine.custom_loader import load_custom_gates
    from yggdrasil.engine.executor import _execute_step
    from yggdrasil.logging.logger import setup_logger

    config_path = config_path.resolve(strict=True)
    pipeline_dir = config_path.parent
    task_root = validate_task_root(task_root, task_id)
    indexes = resume_step_indexes(config_path, from_stage)
    config = load_config(config_path)
    load_custom_gates(pipeline_dir)

    run_id = f"resume-{time.strftime('%Y%m%d-%H%M%S')}-{task_id}"
    logs_dir = logs_dir.resolve()
    logger = setup_logger(run_id, logs_dir)
    credentials = load_credentials(pipeline_dir)
    artifacts = make_artifact_uploader(
        config.traces,
        credentials,
        run_id=run_id,
        task_id=task_id,
    )
    ctx = BuildContext(
        run_id=run_id,
        task_id=task_id,
        task_dir=task_root,
        pipeline_dir=pipeline_dir,
        domain=config.domain,
        seed=_load_seed(task_root, task_id),
        config=config,
        credentials=credentials,
        logger=logger,
        artifacts=artifacts,
    )
    logger.info(
        "same_package_resume_start",
        task_id=task_id,
        task_root=str(task_root),
        from_stage=from_stage,
    )
    for index in indexes:
        step_cfg = config.pipeline[index]
        ok, error = await _execute_step(ctx, step_cfg)
        if not ok and step_cfg.blocking:
            logger.error(
                "same_package_resume_failed",
                task_id=task_id,
                step=step_cfg.step,
                error=error,
            )
            return False
        if not ok:
            logger.warning(
                "non_blocking_step_failed",
                task_id=task_id,
                step=step_cfg.step,
                error=error,
            )
    logger.info("same_package_resume_done", task_id=task_id)
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--from-stage", choices=sorted(STAGE_START), required=True)
    parser.add_argument("--logs-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        ok = asyncio.run(
            resume_package(
                args.config,
                args.task_root,
                args.task_id,
                args.from_stage,
                args.logs_dir,
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
