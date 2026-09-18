#!/usr/bin/env python3
"""Static preflight for taxonomy-balanced Online Search builder variants."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = "online-search-taxonomy-balanced"
LANES = (
    "control-native",
    "control-proxy-codx",
    "deepseek-codex",
    "deepseek-codex-dsml",
    "deepseek-claude",
    "deepseek-dsh",
    "deepseek-dsh-dsml",
)


def normalized_pipeline(config: dict) -> list[dict]:
    pipeline = []
    for item in config["pipeline"]:
        copy = json.loads(json.dumps(item))
        if copy.get("step") == "benchmark.build_lane":
            copy["params"]["lane"] = "<lane>"
        pipeline.append(copy)
    return pipeline


def main() -> None:
    taxonomy = yaml.safe_load((ROOT / "domain-taxonomy.yaml").read_text(encoding="utf-8"))
    assert taxonomy["schema_version"] == "online-search-domain-taxonomy-v1"
    forbidden = {str(value).casefold() for value in taxonomy["forbidden_domains"]}
    for required in ("law", "public policy", "environment", "climate"):
        assert required in forbidden
    default_ideas = yaml.safe_load((ROOT / "ideas.yaml").read_text(encoding="utf-8"))[
        "ideas"
    ]
    configs = {}
    build_only_configs = {}
    for lane in LANES:
        path = ROOT / f"config-online-search-pipeline-{lane}.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        expected_name = f"{CAMPAIGN}-{lane}"
        assert config["name"] == expected_name, (path, config["name"])
        assert config["domain"] == "taxonomy-balanced-online-search", path
        steps = [item.get("step") for item in config["pipeline"]]
        assert steps.count("benchmark.build_lane") == 1, path
        assert steps.count("doraemon.domain_taxonomy") == 1, path
        assert "build.codex" not in steps, path
        assert "deploy.gh_push" not in steps, path
        assert "deploy.open_pr" not in steps, path
        build = next(
            item for item in config["pipeline"] if item.get("step") == "benchmark.build_lane"
        )
        assert build["params"]["lane"] == lane, path
        assert (
            build["params"]["instructions_file"]
            == "prompts/author_online_search_current.md"
        ), path
        assert config["build"]["retry_budget"] == 0, path
        assert config["build"]["reasoning_effort"] == "xhigh", path
        assert steps.count("doraemon.semantic_massage") == 1, path
        assert steps.count("doraemon.muse_solver_lane") == 1, path
        assert steps.count("doraemon.publication_gate") == 1, path
        configs[lane] = config

        build_path = ROOT / f"config-online-search-build-only-{lane}.yaml"
        build_config = yaml.safe_load(build_path.read_text(encoding="utf-8"))
        assert build_config["name"] == f"{CAMPAIGN}-build-only-{lane}", build_path
        build_steps = [item.get("step") for item in build_config["pipeline"]]
        for forbidden in (
            "oracle.score_nop",
            "difficulty.solver_lane",
            "doraemon.muse_solver_lane",
            "doraemon.publication_gate",
            "deploy.gh_push",
            "deploy.open_pr",
        ):
            assert forbidden not in build_steps, (build_path, forbidden)
        assert build_steps.count("doraemon.oracle_min_score") == 1, build_path
        assert build_steps.count("benchmark.build_lane") == 1, build_path
        build_only_configs[lane] = build_config

    reference = normalized_pipeline(configs[LANES[0]])
    for lane in LANES[1:]:
        assert normalized_pipeline(configs[lane]) == reference, lane

    print(
        json.dumps(
            {
                "ready": True,
                "full_variants": len(configs),
                "build_only_variants": len(build_only_configs),
                "prepared_full_scale": {
                    "lane": "deepseek-dsh-dsml",
                    "max_build_attempts": len(default_ideas),
                    "target_build_successes": 100,
                    "target_qualified_tasks": 100,
                    "task_concurrency": 4,
                    "muse_solver_trials_per_task": 3,
                    "muse_solver_timeout_seconds": 10800,
                    "muse_solver_trial_concurrency": 12,
                },
                "deployment_enabled": False,
                "oracle_enabled_in_build_only": True,
                "nop_solver_deploy_enabled_in_build_only": False,
                "quality_targets_blocking": True,
                "oracle_gate": "score > 0.9",
                "publication_gates": {
                    "mean_score": "< 0.8",
                    "max_peak_call_context": ">= 500000 (700000 target)",
                },
                "domain_taxonomy": {
                    "allowed": taxonomy["allowed_domains"],
                    "forbidden": taxonomy["forbidden_domains"],
                },
                "builder_step": "benchmark.build_lane",
                "lanes": list(LANES),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
