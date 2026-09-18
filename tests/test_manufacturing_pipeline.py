from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_campaign():
    spec = importlib.util.spec_from_file_location(
        "manufacturing_campaign_test", ROOT / "scripts/media_campaign.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manufacturing_catalog_and_task_contract():
    shards = [
        yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["ideas"]
        for name in ("manufacturing-anomaly-a.yaml", "manufacturing-anomaly-b.yaml")
    ]
    ideas = shards[0] + shards[1]
    assert [len(shard) for shard in shards] == [100, 100]
    assert len({idea["id"] for idea in ideas}) == 200
    assert all(len(idea["id"].split("-")) == 3 for idea in ideas)
    assert all(idea["domain"] == "Manufacturing" for idea in ideas)
    assert all(idea["task_mode"] == "anomaly_detection" for idea in ideas)
    assert all(
        idea["instruction_shape"] == "task_adaptive_200_to_1800_word_specification"
        for idea in ideas
    )
    assert all(
        all(word in idea["idea"] for word in ("lot", "supplier", "corrective-action"))
        for idea in ideas
    )

    config = yaml.safe_load(
        (ROOT / "config-manufacturing-anomaly.yaml").read_text(encoding="utf-8")
    )
    assert config["domain"] == "manufacturing-anomaly-detection"
    assert config["preflight"]["word_limit"] == 350
    steps = [item.get("step") for item in config["pipeline"]]
    assert "preflight.word_limit" in steps
    assert config["difficulty"]["minimum_fresh_input_tokens"] is None
    assert config["difficulty"]["fresh_input_aggregation"] == "mean"
    assert config["difficulty"]["target_band"] == [0.0, 1.0]
    assert config["difficulty"]["max_number_of_zeros"] is None
    assert config["difficulty"]["lowest_allowed_max_score"] is None
    assert config["difficulty"]["solver_timeout_sec"] == 10800
    assert config["difficulty"]["solver_lane"][0]["model"] == "meta-muse-spark"
    assert config["difficulty"]["solver_lane"][0]["trials"] == 3
    assert "doraemon.oracle_min_score" in steps
    assert "oracle.score_nop" not in steps
    publication = next(
        item for item in config["pipeline"] if item.get("step") == "doraemon.publication_gate"
    )
    assert publication["params"] == {
        "maximum_mean_score": 0.8,
        "minimum_max_peak_call_context": 500000,
    }
    assert "author_online_search_current.md" in json.dumps(config)

    expected_files = {
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
    actual_files = {
        str(path.relative_to(ROOT / "example-task"))
        for path in (ROOT / "example-task").rglob("*")
        if path.is_file()
    }
    assert actual_files == expected_files
    assert (ROOT / "example-task/tests/test_utils.py").read_bytes() == (
        ROOT / "canonical/tests/test_utils.py"
    ).read_bytes()
    assert "COPY . /tests" in (
        ROOT / "canonical/tests/Dockerfile"
    ).read_text(encoding="utf-8")
    task_toml = (ROOT / "canonical/task.toml").read_text(encoding="utf-8")
    judge = (ROOT / "canonical/tests/test_utils.py").read_text(encoding="utf-8")
    vision = (ROOT / "prompts/benchmark_vision_helper.md").read_text(encoding="utf-8")
    launcher = (
        ROOT / "benchmark-runtime/run_server_dsh_dsml_target100.sh"
    ).read_text(encoding="utf-8")
    assert 'LLM_JUDGE_BASE_URL = "${LLM_JUDGE_BASE_URL:-http://127.0.0.1:18099/v1}"' in task_toml
    assert 'LLM_JUDGE_MODEL = "deepseek/deepseek-v4.1-flash"' in task_toml
    assert "judge must be {JUDGE_MODEL}" in judge
    assert "Gemini vision helper" in vision
    assert "google/gemini-3.7-flash" not in judge
    assert "LLM_JUDGE_API_KEY=\"$OPENROUTER_API_KEY\"" in launcher


def test_campaign_loader_accepts_manufacturing_anomaly_mode():
    campaign = load_campaign()
    ideas = ROOT / "manufacturing-anomaly-a.yaml"
    loaded = campaign.load_ideas(
        ideas, expected_domain="Manufacturing", expected_task_mode="anomaly_detection"
    )
    assert len(loaded) == 100


def test_manufacturing_interleave_spreads_first_concurrent_batch():
    spec = importlib.util.spec_from_file_location(
        "manufacturing_interleave_test",
        ROOT / "scripts/interleave_manufacturing_ideas.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    ideas = []
    for name in ("manufacturing-anomaly-a.yaml", "manufacturing-anomaly-b.yaml"):
        ideas.extend(yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["ideas"])
    interleaved = module.interleave(ideas)
    assert len(interleaved) == 200
    assert len({idea["id"].split("-", 1)[0] for idea in interleaved[:8]}) == 8
