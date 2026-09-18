from __future__ import annotations

import asyncio
import collections
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_gates():
    registry_module = ModuleType("yggdrasil.engine.registry")
    registered = {}

    def register_step(name):
        def decorate(function):
            registered[name] = function
            return function

        return decorate

    registry_module.register_step = register_step
    engine_module = ModuleType("yggdrasil.engine")
    yggdrasil_module = ModuleType("yggdrasil")
    old = {
        name: sys.modules.get(name)
        for name in ("yggdrasil", "yggdrasil.engine", "yggdrasil.engine.registry")
    }
    sys.modules["yggdrasil"] = yggdrasil_module
    sys.modules["yggdrasil.engine"] = engine_module
    sys.modules["yggdrasil.engine.registry"] = registry_module
    try:
        spec = importlib.util.spec_from_file_location(
            "doraemon_test_gates",
            ROOT / "custom_gates.py",
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module._test_registry = registered
        return module
    finally:
        for name, value in old.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_idea_shard_never_wraps(tmp_path: Path):
    gates = _load_gates()
    ideas = tmp_path / "ideas.yaml"
    ideas.write_text(
        yaml.safe_dump({"ideas": [{"id": "one"}, {"id": "two"}]}),
        encoding="utf-8",
    )
    ctx = SimpleNamespace(
        pipeline_dir=tmp_path,
        task_id="001-abcdef",
        config=SimpleNamespace(ideation=SimpleNamespace(source=str(ideas))),
        seed={},
    )
    assert asyncio.run(gates.idea_file_pick_no_wrap(ctx, {})) == (True, None)
    assert ctx.seed == {"id": "two"}
    ctx.task_id = "002-abcdef"
    ok, error = asyncio.run(gates.idea_file_pick_no_wrap(ctx, {}))
    assert not ok
    assert "will not wrap" in error


def test_domain_taxonomy_accepts_allowed_and_rejects_excluded_domains(tmp_path: Path):
    gates = _load_gates()
    shutil.copy2(ROOT / "domain-taxonomy.yaml", tmp_path / "domain-taxonomy.yaml")
    ctx = SimpleNamespace(
        pipeline_dir=tmp_path,
        seed={"domain": "Technology", "authoritative_domains": ["example.gov"]},
    )
    assert asyncio.run(gates.domain_taxonomy(ctx, {})) == (
        True,
        "domain accepted: Technology",
    )
    assert "authoritative_domains" not in ctx.seed
    for domain in (
        "Law",
        "Public Policy",
        "Environment and Climate",
        "Energy and Environment",
        "Climate policy",
    ):
        ctx.seed = {"domain": domain}
        ok, error = asyncio.run(gates.domain_taxonomy(ctx, {}))
        assert not ok
        assert "excluded" in error
    ctx.seed = {"domain": "Unrecognized Vertical"}
    ok, error = asyncio.run(gates.domain_taxonomy(ctx, {}))
    assert not ok
    assert "outside the approved taxonomy" in error


def test_taxonomy_catalog_and_reserve_are_disjoint_and_use_allowed_domains():
    catalog = yaml.safe_load((ROOT / "ideas.yaml").read_text(encoding="utf-8"))
    reserve = yaml.safe_load(
        (ROOT / "ideas-reserve.yaml").read_text(encoding="utf-8")
    )
    ids = [idea["id"] for idea in catalog["ideas"]]
    reserve_ids = [idea["id"] for idea in reserve["ideas"]]

    assert len(ids) == len(set(ids))
    assert all(len(task_id.split("-")) == 3 for task_id in ids)
    assert set(ids).isdisjoint(reserve_ids)
    taxonomy = yaml.safe_load((ROOT / "domain-taxonomy.yaml").read_text())
    allowed = set(taxonomy["allowed_domains"])
    forbidden = {value.casefold() for value in taxonomy["forbidden_domains"]}
    rows = [*catalog["ideas"], *reserve["ideas"]]
    assert rows
    assert {row["domain"] for row in rows} <= allowed
    assert not ({row["domain"].casefold() for row in rows} & forbidden)
    assert all("authoritative_domains" not in row and "as_of" not in row for row in rows)
    counts = collections.Counter(row["domain"] for row in rows)
    assert max(counts.values()) <= taxonomy["default_catalog"]["max_tasks_per_domain"]
    assert len(counts) >= 8


def test_no_prior_candidate_staging_gate_is_registered():
    gates = _load_gates()
    assert "doraemon.stage_seed_prior" not in gates._test_registry


def test_builder_starts_with_complete_tree_and_rejects_placeholders(tmp_path: Path):
    gates = _load_gates()
    task = tmp_path / "task"
    shutil.copytree(ROOT / "example-task", task)
    output = task / "output" / "sample-task-id"
    gates._stage_builder_output(SimpleNamespace(task_dir=task), output)

    files = {
        str(path.relative_to(output))
        for path in output.rglob("*")
        if path.is_file()
    }
    assert files == set(gates.PUBLICATION_FILES)
    assert "instruction.md was not substantively authored" in gates._builder_output_error(output)


def test_isolated_dsh_profile_is_pinned_to_v41_xhigh(tmp_path: Path):
    gates = _load_gates()
    home = tmp_path / "dsh"
    home.mkdir()
    (home / "settings.yaml").write_text(
        "llm-pi-ai:\n"
        "  providers:\n"
        "    openrouter:\n"
        "      apiKeyEnv: OPENROUTER_API_KEY\n"
        "      models:\n"
        "        - id: legacy/model\n"
        "          reasoningEfforts:\n"
        "            off:\n"
        "            high: high\n",
        encoding="utf-8",
    )
    gates._configure_isolated_dsh_profile(home)
    settings = yaml.safe_load((home / "settings.yaml").read_text(encoding="utf-8"))
    route = settings["llm-pi-ai"]["providers"]["openrouter"]
    assert route["reasoning"] == "xhigh"
    assert route["models"] == [
        {
            "id": "deepseek/deepseek-v4.1-flash",
            "name": "deepseek-v4.1-flash",
            "contextWindow": 1_000_000,
            "maxTokens": 65_536,
            "reasoningEfforts": {"xhigh": "xhigh"},
        }
    ]


def test_online_search_runner_opts_out_of_model_only_egress_sandbox():
    runner = (ROOT / "run.sh").read_text(encoding="utf-8")

    assert 'export HARBOR_ALLOW_INTERNET="${HARBOR_ALLOW_INTERNET:-1}"' in runner
    assert "[environment].allow_internet=true" in runner
    assert 'BOOTSTRAP_LOCK="$HOME/.cache/doraemon/bootstrap.lock"' in runner
    assert "flock 8" in runner
    assert "flock -u 8" in runner


def test_runner_fails_fast_when_openrouter_judge_is_unavailable():
    runner = (ROOT / "run.sh").read_text(encoding="utf-8")

    assert 'JUDGE_MODELS_URL="${LLM_JUDGE_BASE_URL%/}/models"' in runner
    assert "OpenRouter judge preflight failed" in runner
    assert "athena-judge.env" not in runner


def test_author_must_finish_with_exact_pipeline_validator():
    prompt = (ROOT / "prompts/author_online_search_current.md").read_text(encoding="utf-8")
    assert "exactly these twelve files" in prompt
    assert "Task ID: `{TASK_ID}`" in prompt
    assert "`{IDEA}`" in prompt
    assert "directly in `{TASK_PATH}`" in prompt
    assert "at or below 350 words" in prompt
    assert "live public web" in prompt
    assert "exact inline URLs" in prompt
    assert "positive count strictly greater than negative count" in prompt
    assert "positive weight sum strictly greater than 300" in prompt
    assert "python3 {VALIDATOR_PATH} --task-root {TASK_PATH}" in prompt


def test_author_and_reviewer_forbid_domain_guidance():
    author = (ROOT / "prompts/author_online_search_current.md").read_text(encoding="utf-8")
    reviewer = (ROOT / "prompts/review_live_task.md").read_text(encoding="utf-8")
    assert "Do not name approved sites" in author
    assert "Do not limit the evidence to any predetermined host list" in author
    assert "source hints" in reviewer


def test_source_manifests_are_absent_from_current_contract():
    author = (ROOT / "prompts/author_online_search_current.md").read_text(encoding="utf-8")
    files = {str(path.relative_to(ROOT / "example-task")) for path in (ROOT / "example-task").rglob("*") if path.is_file()}
    assert "source_manifest.json" not in files
    assert "source manifest" in author


def test_builder_quality_audit_is_single_pass_without_retries():
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    pipeline = config["pipeline"]
    retry_blocks = [item for item in pipeline if "retry_block" in item]
    assert retry_blocks == []
    steps = [item["step"] for item in pipeline if "step" in item]
    assert steps.index("benchmark.build_lane") < steps.index("doraemon.oracle_min_score")
    assert "doraemon.codex_review" not in steps
    assert "oracle.score_nop" not in steps
    assert steps.index("doraemon.muse_solver_lane") < steps.index("postbuild.cleanup")
    difficulty = next(item for item in pipeline if item.get("step") == "doraemon.muse_solver_lane")
    assert difficulty["params"] == {"trials": 3, "max_attempts": 4}


def test_task_producing_configs_do_not_launch_independent_reviewers():
    for name in (
        "config.yaml",
        "config-consumer-safety.yaml",
        "config-media-journalism.yaml",
        "config-emergency.yaml",
    ):
        config = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        serialized = json.dumps(config)
        assert "doraemon.codex_review" not in serialized
        assert "doraemon.stage_seed_prior" not in serialized


def test_media_journalism_pipeline_contract():
    config = yaml.safe_load((ROOT / "config-media-journalism.yaml").read_text(encoding="utf-8"))
    prompt = (ROOT / "prompts/author_online_search_current.md").read_text(
        encoding="utf-8"
    )

    assert config["domain"] == "media-journalism-verification"
    assert config["preflight"]["word_limit"] == 350
    assert config["difficulty"]["minimum_fresh_input_tokens"] is None
    assert config["difficulty"]["fresh_input_aggregation"] == "mean"
    assert config["difficulty"]["solver_lane"][0]["trials"] == 3
    build = next(
        item for item in config["pipeline"] if item.get("step") == "benchmark.build_lane"
    )
    assert build["params"]["lane"] == "deepseek-dsh-dsml"
    assert build["params"]["instructions_file"].endswith(
        "author_online_search_current.md"
    )
    assert "at or below 350 words" in prompt
    assert "binary, atomic, independent" in prompt

    runner = (ROOT / "run.sh").read_text(encoding="utf-8")
    assert 'CONFIG="$ROOT/config.yaml"' in runner
    assert '$ROOT/ideas.yaml' in runner


def test_media_journalism_catalog_has_100_disjoint_verification_tasks():
    first = yaml.safe_load((ROOT / "media-journalism-a.yaml").read_text(encoding="utf-8"))
    second = yaml.safe_load((ROOT / "media-journalism-b.yaml").read_text(encoding="utf-8"))
    ideas = first["ideas"] + second["ideas"]
    ids = [idea["id"] for idea in ideas]

    assert len(first["ideas"]) == 50
    assert len(second["ideas"]) == 50
    assert len(ids) == len(set(ids)) == 100
    assert all(len(task_id.split("-")) == 3 for task_id in ids)
    assert all(idea["domain"] == "Media and journalism" for idea in ideas)
    assert all(idea["task_mode"] == "verification_and_abstention" for idea in ideas)
    assert all(idea["instruction_shape"] == "exact_120_word_micro_contract" for idea in ideas)


def test_media_campaign_launcher_uses_seven_fixed_single_task_lanes():
    launcher = (ROOT / "scripts/launch_media_campaign.sh").read_text(encoding="utf-8")
    campaign = (ROOT / "scripts/media_campaign.py").read_text(encoding="utf-8")

    assert "for lane in 2 3 4 5 6 7" in launcher
    assert "--concurrency\", \"1\"" in campaign
    assert "--conc-trials\", \"3\"" in campaign
    assert "succeeded + running >= target" in campaign
    assert "blocked_deploy" in campaign
    assert "blocked_for_lane" in campaign
    assert "--max-candidates" in campaign
    assert "storage_hold" in campaign


def test_author_uses_cutoffs_only_when_semantically_required():
    prompt = (ROOT / "prompts/author_online_search_current.md").read_text(encoding="utf-8")
    assert "Avoid research and decision cutoff dates unless" in prompt
    assert "question genuinely breaks" in prompt


def test_semantic_identity_renames_task_and_artifact_prefix(tmp_path: Path):
    gates = _load_gates()
    old_task = tmp_path / "tasks" / "001-random"
    old_task.mkdir(parents=True)
    ctx = SimpleNamespace(
        seed={"id": "Grid Heat Readiness"},
        task_id="001-random",
        task_dir=old_task,
        artifacts=SimpleNamespace(key_prefix="runs/001-random"),
    )

    assert asyncio.run(gates.semantic_identity(ctx, {})) == (
        True,
        "grid-heat-readiness",
    )
    assert ctx.task_id == "grid-heat-readiness"
    assert ctx.task_dir == tmp_path / "tasks" / "grid-heat-readiness"
    assert ctx.task_dir.is_dir()
    assert ctx.artifacts.key_prefix == "runs/grid-heat-readiness"


def test_restore_canonical_binds_task_and_seed(tmp_path: Path):
    gates = _load_gates()
    canonical = tmp_path / "canonical"
    task = tmp_path / "task"
    for relative in gates.CANONICAL_FILES:
        path = canonical / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            'name = "parsewave/example-task"\n'
            if relative == "task.toml"
            else f"{relative}\n",
            encoding="utf-8",
        )
    task.mkdir()
    (task / "instruction.md").write_text("Please research this.\n", encoding="utf-8")
    ctx = SimpleNamespace(
        pipeline_dir=tmp_path,
        task_dir=task,
        task_id="live-source-test",
        seed={"id": "live-source-test", "scope": "example"},
    )

    assert asyncio.run(gates.restore_canonical(ctx, {})) == (True, None)
    assert "parsewave/live-source-test" in (task / "task.toml").read_text()
    assert not (task / "tests/instruction.md").exists()
    assert json.loads((task / "task-planning/seed.json").read_text()) == ctx.seed
