from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = {
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
}
BASE_CONFIGS = (
    "config.yaml",
    "config-consumer-safety.yaml",
    "config-emergency.yaml",
    "config-manufacturing-anomaly.yaml",
    "config-media-journalism.yaml",
)


def _steps(config: dict) -> list[dict]:
    result = []
    for item in config["pipeline"]:
        if "retry_block" in item:
            result.extend(_steps({"pipeline": item["retry_block"]["steps"]}))
        else:
            result.append(item)
    return result


def test_every_base_config_uses_current_massaged_contract() -> None:
    for name in BASE_CONFIGS:
        config = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        assert config["yggdrasil_ref"] == "codex/rolling-success-target"
        assert config["build"]["model"] == "deepseek/deepseek-v4.1-flash"
        assert config["build"]["reasoning_effort"] == "xhigh"
        assert config["preflight"] == {
            "word_limit": 350,
            "required_files": list(config["preflight"]["required_files"]),
        }
        assert set(config["preflight"]["required_files"]) == PACKAGE_FILES
        assert config["oracle"]["expected_score"] == 0.9
        assert config["difficulty"]["solver_timeout_sec"] == 10800
        assert config["difficulty"]["solver_lane"] == [
            {
                "agent": "codex",
                "model": "meta-muse-spark",
                "reasoning_effort": "xhigh",
                "trials": 3,
            }
        ]
        steps = _steps(config)
        names = [item["step"] for item in steps]
        builder = next(item for item in steps if item["step"] == "benchmark.build_lane")
        assert builder["params"] == {
            "instructions_file": "prompts/author_online_search_current.md",
            "timeout_sec": 5400,
            "lane": "deepseek-dsh-dsml",
        }
        massage = next(item for item in steps if item["step"] == "doraemon.semantic_massage")
        assert massage["params"] == {
            "instructions_file": "prompts/massage_online_search_task.md",
            "timeout_sec": 3600,
        }
        required = next(item for item in steps if item["step"] == "preflight.required_files")
        assert set(required["params"]["files"]) == PACKAGE_FILES
        word_limit = next(item for item in steps if item["step"] == "preflight.word_limit")
        assert word_limit["params"] == {"file": "instruction.md", "limit": 350}
        oracle = next(item for item in steps if item["step"] == "doraemon.oracle_min_score")
        assert oracle["params"] == {"minimum": 0.9}
        muse = next(item for item in steps if item["step"] == "doraemon.muse_solver_lane")
        assert muse["params"] == {"trials": 3, "max_attempts": 4}
        publication = next(item for item in steps if item["step"] == "doraemon.publication_gate")
        assert publication["params"] == {
            "maximum_mean_score": 0.8,
            "minimum_max_peak_call_context": 500000,
        }
        taxonomy = next(item for item in steps if item["step"] == "doraemon.domain_taxonomy")
        assert taxonomy["params"] == {"taxonomy_file": "domain-taxonomy.yaml"}
        assert names.index("doraemon.idea_file_pick_no_wrap") < names.index("doraemon.domain_taxonomy")
        assert names.index("doraemon.domain_taxonomy") < names.index("doraemon.semantic_identity")
        assert names.index("benchmark.build_lane") < names.index("doraemon.semantic_massage")
        assert names.index("doraemon.semantic_massage") < names.index("doraemon.oracle_min_score")
        assert names.index("doraemon.oracle_min_score") < names.index("doraemon.muse_solver_lane")
        deploy = [item for item in steps if item["step"] == "deploy.open_pr"]
        if deploy and deploy[0].get("enabled", True):
            assert deploy[0]["params"]["title_pattern"] == (
                "[online-search] {token} {id}"
            )


def test_template_is_exact_and_shared_files_are_identical() -> None:
    files = {
        str(path.relative_to(ROOT / "example-task"))
        for path in (ROOT / "example-task").rglob("*")
        if path.is_file()
    }
    assert files == PACKAGE_FILES
    for relative in (
        "environment/Dockerfile",
        "solution/solve.sh",
        "tests/Dockerfile",
        "tests/test.sh",
        "tests/test_outputs.py",
        "tests/test_utils.py",
    ):
        assert (ROOT / "example-task" / relative).read_bytes() == (
            ROOT / "canonical" / relative
        ).read_bytes()
    assert "def test_report()" in (
        ROOT / "canonical/tests/test_outputs.py"
    ).read_text(encoding="utf-8")


def test_task_toml_and_muse_command_match_production_regime() -> None:
    task = tomllib.loads((ROOT / "canonical/task.toml").read_text(encoding="utf-8"))
    assert task["artifacts"] == ["/app/output/report.md"]
    assert task["agent"]["timeout_sec"] == 10800
    assert task["verifier"]["timeout_sec"] == 1600
    assert task["verifier"]["env"]["LLM_JUDGE_MODEL"] == (
        "deepseek/deepseek-v4.1-flash"
    )
    assert task["verifier"]["env"]["LLM_JUDGE_REASONING_EFFORT"] == "xhigh"

    gates = (ROOT / "custom_gates.py").read_text(encoding="utf-8")
    for required in (
        '"--model",\n            "meta-muse-spark"',
        '"--agent-timeout-sec",\n            "10800"',
        '"--context-goal-tokens",\n            "700000"',
        '"--finish-prompt-tokens",\n            "950000"',
        '"--context-hard-limit-tokens",\n            "1048576"',
        '"--reasoning-effort",\n            "xhigh"',
    ):
        assert required in gates
    assert "ctx.harbor_trials.append(path)" in gates
    assert "ctx.artifacts.upload(path, relative_to=output_root)" in gates
    assert "await _grade_muse_deliverables(ctx, run_dir)" in gates
    assert 'verifier_harness="agentic-verifier-harness"' in gates


def test_no_legacy_task_contract_artifacts_remain() -> None:
    tracked_tree = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and ".venv" not in path.parts and ".git" not in path.parts
    ]
    assert not [path for path in tracked_tree if path.name == "source_manifest.json"]
    assert not [path for path in tracked_tree if path.name.startswith("docker-compose")]
    assert not [path for path in tracked_tree if path.suffix in {".pyc", ".pyo"}]
    for forbidden_path in (
        "config-environment-regulatory-compliance.yaml",
        "config-groundwater.yaml",
        "config-groundwater-fast.yaml",
        "environment-regulatory-compliance-a.yaml",
        "environment-regulatory-compliance-b.yaml",
    ):
        assert not (ROOT / forbidden_path).exists()


def test_dsh_builder_is_pinned_to_validated_source_build() -> None:
    script = (ROOT / "scripts/dsh_headless_entrypoint.sh").read_text(encoding="utf-8")
    compose = (ROOT / "benchmark-runtime/compose.base.yaml").read_text(encoding="utf-8")
    setup = (ROOT / "benchmark-runtime/setup_server_lanes.sh").read_text(encoding="utf-8")
    commit = "3a224bc69c3a3230272ed5750b30fe90d87b47fc"
    assert commit in script and commit in setup
    assert "apps/cli/lib/bin.js" in script and "apps/cli/lib/bin.js" in setup
    assert "npx" not in script
    assert "ONLINE_SEARCH_DSH_SOURCE_ROOT" in compose
    assert "ONLINE_SEARCH_DSH_SOURCE_COMMIT" in compose
