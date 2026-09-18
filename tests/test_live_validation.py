from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "current_online_search_validator", ROOT / "scripts/validate_live_task.py"
)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _task(tmp_path: Path) -> Path:
    task_id = "current-contract-test"
    root = tmp_path / task_id
    shutil.copytree(ROOT / "example-task", root)
    task_toml = (root / "task.toml").read_text(encoding="utf-8")
    (root / "task.toml").write_text(
        task_toml.replace("parsewave/example-task", f"parsewave/{task_id}"),
        encoding="utf-8",
    )
    (root / "instruction.md").write_text(
        "I need a decision memo about a public policy claim. Research the live public "
        "web, test the claim and its strongest counterevidence, and show the important "
        "calculation. Cite the exact URL beside every material factual claim. Explain "
        "what remains uncertain and what new evidence would change the recommendation. "
        "Write only /app/output/report.md.\n",
        encoding="utf-8",
    )
    report = "# Decision memo\n\n" + " ".join(
        [
            (
                "The available record supports a conditional decision, with a clearly stated "
                "limitation and a reversal trigger supported by https://example.org/research."
            )
        ]
        * 55
    )
    (root / "solution/report.md").write_text(report + "\n", encoding="utf-8")

    criteria = []
    claims = []
    mappings = []
    graph_claims = []
    for index in range(1, 18):
        criterion_id = f"P{index:02d}"
        claim_id = f"C{index:02d}"
        criteria.append(
            {
                "id": criterion_id,
                "axis": "analysis",
                "category": "decision",
                "requirement": f"States decision-relevant supported conclusion {index}.",
                "weight": 19,
                "claim_ids": [claim_id],
            }
        )
        claims.append(
            {
                "id": claim_id,
                "kind": "fact",
                "statement": f"Supported conclusion {index}.",
                "basis": "Public evidence in the reference report.",
                "report_location": "Decision memo",
                "accepted_citations": [
                    {
                        "url": "https://example.org/research",
                        "authority_basis": "Public research record",
                    }
                ],
                "rejected_citations": [],
                "conflict_resolution": "No unresolved conflict.",
            }
        )
        mappings.append(
            {
                "criterion_id": criterion_id,
                "claim_ids": [claim_id],
                "justification": "The criterion directly scores the mapped conclusion.",
            }
        )
        graph_claims.append(
            {
                "id": criterion_id,
                "claim_ids": [claim_id],
                "description": "Decision conclusion",
                "basis": "Reference evidence",
                "justification": "Direct mapping",
            }
        )
    criteria.append(
        {
            "id": "N01",
            "axis": "accuracy",
            "category": "material-error",
            "requirement": "Invents a material numerical result not supported by evidence.",
            "weight": -20,
            "claim_ids": ["E01"],
        }
    )
    claims.append(
        {
            "id": "E01",
            "kind": "prohibited_error",
            "statement": "The report must not invent a material number.",
            "basis": "Unsupported precision would change the decision.",
            "report_location": "Throughout",
            "accepted_citations": [],
            "rejected_citations": [],
            "conflict_resolution": "Not applicable.",
        }
    )
    mappings.append(
        {
            "criterion_id": "N01",
            "claim_ids": ["E01"],
            "justification": "The negative criterion maps to the prohibited error.",
        }
    )
    graph_claims.append(
        {
            "id": "N01",
            "claim_ids": ["E01"],
            "description": "Unsupported precision",
            "basis": "Prohibited error",
            "justification": "Direct mapping",
        }
    )
    rubric = {
        "schema_version": "online-search-rubrics",
        "task_id": task_id,
        "scoring": "binary",
        "criteria": criteria,
    }
    _write_json(root / "tests/rubrics.json", rubric)
    _write_json(
        root / "tests/reference/ground_truth.json",
        {
            "schema_version": "online-search-ground-truth",
            "task_id": task_id,
            "rubric_artifact_id": validator.canonical_rubric_hash(rubric),
            "collection_method": "Live public-web research.",
            "source_selection_method": "Decision relevance and authority.",
            "conflict_adjudication_method": "Prefer controlling and current evidence.",
            "known_limitations": ["Public evidence may change."],
            "claims": claims,
            "rubric_mappings": mappings,
        },
    )
    _write_json(
        root / "solution/evidence_graph.json",
        {
            "schema_version": "online-search-evidence-graph",
            "task_id": task_id,
            "rubric_claims": graph_claims,
            "nodes": [
                {
                    "id": "S01",
                    "type": "source",
                    "label": "Public research record",
                    "url": "https://example.org/research",
                    "source_ids": [],
                }
            ],
            "edges": [],
            "required_paths": [],
            "conflicts": [],
            "calculations": [],
            "recommendations": [],
            "decoys": [],
            "task_data": {},
        },
    )
    return root


def test_current_package_passes_offline_contract(tmp_path: Path) -> None:
    root = _task(tmp_path)
    result = validator.validate(root, root.name, "package")
    assert result["status"] == "pass"
    assert result["files"] == 12


@pytest.mark.parametrize(
    "extra",
    (
        "tests/reference/source_manifest.json",
        "tests/docker-compose.yaml",
        "solution/decision-log.md",
    ),
)
def test_forbidden_or_extra_files_fail_package(tmp_path: Path, extra: str) -> None:
    root = _task(tmp_path)
    path = root / extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(validator.ValidationFailure):
        validator.validate(root, root.name, "package")


def test_instruction_rules_are_enforced(tmp_path: Path) -> None:
    root = _task(tmp_path)
    path = root / "instruction.md"
    path.write_text(path.read_text().replace("live public web", "approved domains"))
    with pytest.raises(validator.ValidationFailure):
        validator.validate(root, root.name, "package")


def test_shared_files_must_match_canonical(tmp_path: Path) -> None:
    root = _task(tmp_path)
    (root / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    with pytest.raises(validator.ValidationFailure, match="differs from canonical"):
        validator.validate(root, root.name, "package")


def test_stale_rubric_hash_fails(tmp_path: Path) -> None:
    root = _task(tmp_path)
    path = root / "tests/reference/ground_truth.json"
    value = json.loads(path.read_text())
    value["rubric_artifact_id"] = hashlib.sha256(b"stale").hexdigest()
    _write_json(path, value)
    with pytest.raises(validator.ValidationFailure, match="stale rubric_artifact_id"):
        validator.validate(root, root.name, "package")


def test_tier_or_role_graph_fields_fail(tmp_path: Path) -> None:
    root = _task(tmp_path)
    path = root / "solution/evidence_graph.json"
    value = json.loads(path.read_text())
    value["nodes"][0]["tier"] = 1
    _write_json(path, value)
    with pytest.raises(validator.ValidationFailure, match="node schema"):
        validator.validate(root, root.name, "package")


def test_rubric_balance_and_mapping_are_enforced(tmp_path: Path) -> None:
    root = _task(tmp_path)
    rubric_path = root / "tests/rubrics.json"
    rubric = json.loads(rubric_path.read_text())
    for criterion in rubric["criteria"]:
        if criterion["weight"] > 0:
            criterion["weight"] = 17
    _write_json(rubric_path, rubric)
    ground_truth_path = root / "tests/reference/ground_truth.json"
    ground_truth = json.loads(ground_truth_path.read_text())
    ground_truth["rubric_artifact_id"] = validator.canonical_rubric_hash(rubric)
    _write_json(ground_truth_path, ground_truth)
    with pytest.raises(validator.ValidationFailure, match="weight balance"):
        validator.validate(root, root.name, "package")


def test_repeated_404_is_hard_dead_but_403_is_not(monkeypatch) -> None:
    class Response:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.url = "https://example.org/final"

    statuses = [404, 404]

    class Client:

        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _url):
            return Response(statuses.pop(0))

    monkeypatch.setattr(validator.httpx, "Client", Client)
    assert validator.verify_url("https://example.org/missing")[1] == "hard_dead"
    statuses[:] = [403]
    assert validator.verify_url("https://example.org/blocked")[1] == "reachable_or_blocked"


def test_current_task_toml_contract(tmp_path: Path) -> None:
    root = _task(tmp_path)
    validator.validate_task_toml(root, root.name)
    text = (root / "task.toml").read_text()
    assert 'LLM_JUDGE_MODEL = "deepseek/deepseek-v4.1-flash"' in text
    assert 'LLM_JUDGE_REASONING_EFFORT = "xhigh"' in text
    assert "timeout_sec = 1600.0" in text
    assert "timeout_sec = 10800.0" in text
