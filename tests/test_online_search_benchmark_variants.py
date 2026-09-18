from __future__ import annotations

import json
import subprocess
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


def test_seven_named_builder_variants_are_isomorphic_and_non_deploying():
    normalized = []
    for lane in LANES:
        path = ROOT / f"config-online-search-pipeline-{lane}.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert config["name"] == f"{CAMPAIGN}-{lane}"
        assert config["domain"] == "taxonomy-balanced-online-search"
        assert config["build"]["retry_budget"] == 0
        assert config["build"]["reasoning_effort"] == "xhigh"

        steps = [item.get("step") for item in config["pipeline"]]
        assert steps.count("benchmark.build_lane") == 1
        assert "build.codex" not in steps
        assert "deploy.gh_push" not in steps
        assert "deploy.open_pr" not in steps
        assert steps.count("doraemon.oracle_min_score") == 1
        assert steps.count("doraemon.publication_gate") == 1

        build = next(
            item for item in config["pipeline"] if item.get("step") == "benchmark.build_lane"
        )
        assert build["params"]["lane"] == lane
        assert (
            build["params"]["instructions_file"]
            == "prompts/author_online_search_current.md"
        )
        build["params"]["lane"] = "<lane>"
        normalized.append(json.dumps(config["pipeline"], sort_keys=True))

    assert len(set(normalized)) == 1


def test_generated_variants_are_current():
    subprocess.run(
        ["uv", "run", "python", "scripts/generate_online_search_benchmark_configs.py"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    assert len(list(ROOT.glob("config-online-search-pipeline-*.yaml"))) == 7
    assert len(list(ROOT.glob("config-online-search-build-only-*.yaml"))) == 7


def test_build_only_variants_stop_before_every_trial_stage():
    forbidden = {
        "oracle.score_nop",
        "difficulty.solver_lane",
        "doraemon.muse_solver_lane",
        "doraemon.publication_gate",
        "deploy.gh_push",
        "deploy.open_pr",
    }
    for lane in LANES:
        config = yaml.safe_load(
            (ROOT / f"config-online-search-build-only-{lane}.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert config["name"] == f"{CAMPAIGN}-build-only-{lane}"
        steps = [item.get("step") for item in config["pipeline"]]
        assert forbidden.isdisjoint(steps)
        assert steps.count("doraemon.oracle_min_score") == 1
        assert steps.count("benchmark.build_lane") == 1
        assert steps.count("doraemon.validate_live_task") == 4


def test_lane_runner_exposes_exact_task_and_trial_concurrency():
    runner = (ROOT / "scripts/run_online_search_benchmark_lane.sh").read_text(
        encoding="utf-8"
    )
    assert 'export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"' in runner
    assert 'TASK_COUNT="${ONLINE_SEARCH_TASK_COUNT:-3}"' in runner
    assert 'TARGET_SUCCESSES="${ONLINE_SEARCH_TARGET_SUCCESSES:-$TASK_COUNT}"' in runner
    assert 'TASK_CONCURRENCY="${ONLINE_SEARCH_TASK_CONCURRENCY:-1}"' in runner
    assert '--count "$TASK_COUNT"' in runner
    assert '--target-successes "$TARGET_SUCCESSES"' in runner
    assert '--concurrency "$TASK_CONCURRENCY"' in runner
    assert '--conc-trials "${ONLINE_SEARCH_TRIAL_CONCURRENCY:-3}"' in runner
    assert "$ROOT/ideas.yaml" in runner


def test_full_scale_dsh_dsml_launcher_is_pinned_without_starting_a_pilot():
    launcher = (
        ROOT / "benchmark-runtime/run_server_dsh_dsml_target100.sh"
    ).read_text(encoding="utf-8")
    assert 'SEED_SOURCE="$ROOT/ideas.yaml"' in launcher
    assert "TARGET_SUCCESSES=100" in launcher
    assert "ONLINE_SEARCH_TASK_CONCURRENCY=4" in launcher
    assert "ONLINE_SEARCH_BUILD_ONLY=0" in launcher
    assert "ONLINE_SEARCH_TRIAL_CONCURRENCY=12" in launcher
    assert '"oracle_gate": "> 0.9"' in launcher
    assert '"publication_mean_score_gate": "< 0.8"' in launcher
    assert '"publication_max_peak_call_context_gate": ">= 500000"' in launcher
    assert '"target_qualified_tasks": int(sys.argv[5])' in launcher


def test_builder_dispatch_has_context_and_proxy_guards():
    gates = (ROOT / "custom_gates.py").read_text(encoding="utf-8")
    assert '@register_step("benchmark.build_lane")' in gates
    assert 'Path(resolved).name == "codx" and not allow_codx' in gates
    assert '"model_context_window=1000000"' in gates
    assert '"model_auto_compact_token_limit=2000000000"' in gates
    assert 'env["DSH_TOOLS_MODE"] = "code"' in gates
    assert "create_isolated_dsh_home(dsh_template_home, trial_root)" in gates
    assert '"DISABLE_AUTO_COMPACT": "1"' in gates
    assert '"reasoning_effort": "xhigh"' in gates
    assert "_stage_builder_output(ctx, output_root)" in gates
    assert "left an incomplete task" in gates
    assert '@register_step("doraemon.oracle_min_score")' in gates
    assert '@register_step("doraemon.publication_gate")' in gates
    assert "_run_builder_stage" in gates
    assert "no source list or host is" in gates
    assert "_validate_staged_output" in gates
    assert "stage_failure is not None" in gates
    assert "_positive_oracle_feedback" in gates
    assert "_repair_oracle_report" in gates
    assert '"allow_report_repair": False' in gates
    assert "builder-checkpoint.json" in gates
    assert '@register_step("doraemon.muse_solver_lane")' in gates
    assert '"--finish-prompt-tokens"' in gates
    assert '"950000"' in gates

    entrypoint = (ROOT / "scripts/dsh_headless_entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "3a224bc69c3a3230272ed5750b30fe90d87b47fc" in entrypoint
    assert "apps/cli/lib/bin.js" in entrypoint
    assert "npx" not in entrypoint

    for lane in ("deepseek-dsh", "deepseek-dsh-dsml"):
        compose = (
            ROOT / "benchmark-runtime" / f"compose.{lane}.yaml"
        ).read_text(encoding="utf-8")
        home = ".dsh-openrouter-dsml" if lane.endswith("-dsml") else ".dsh-openrouter"
        assert f"${{HOME}}/{home}:${{HOME}}/{home}:ro" in compose
        assert f"${{HOME}}/{home}:${{HOME}}/{home}:rw" not in compose
