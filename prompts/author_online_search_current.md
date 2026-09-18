# Current Online Search task authoring contract

Task ID: `{TASK_ID}`

Seed brief:

`{IDEA}`

Build one publication-ready task directly in `{TASK_PATH}`. The complete staged
template is already there. Work only in that tree. Do not create another task
directory, source manifest, decision log, trace, marker file, or extra
deliverable.

## Publication package

The package must contain exactly these twelve files:

1. `instruction.md`
2. `task.toml`
3. `environment/Dockerfile`
4. `solution/evidence_graph.json`
5. `solution/report.md`
6. `solution/solve.sh`
7. `tests/Dockerfile`
8. `tests/rubrics.json`
9. `tests/test.sh`
10. `tests/test_outputs.py`
11. `tests/test_utils.py`
12. `tests/reference/ground_truth.json`

The pipeline owns the seven invariant runtime files. Do not edit them. Author
only `instruction.md`, the three solution/reference artifacts, and the rubric.
`/app/output/report.md` is the solver's sole deliverable.

## Instruction

Write a coherent request from a believable person whose voice fits the domain.
It should feel spoken rather than like benchmark metadata or a mechanical
checklist. Keep it at or below 350 words, use ASCII outside URLs, avoid em
dashes, and use no more than 13 commas. Use no more than four short paragraphs
unless a compact Markdown table or bullets materially clarify supplied facts.
Do not overload the task with a large artificial data table.

Require research of the live public web and exact inline URLs beside material
claims. Do not name approved sites, restrict research to domains, disclose
canonical sources, identify the expected answer, mention schemas/rubrics/models,
set report length, request a decision log, or coach the solver around scoring.
Avoid research and decision cutoff dates unless the question genuinely breaks
without a historical boundary. Keep facts supplied by the requester distinct
from claims the solver must verify. Preserve meaningful uncertainty.

Difficulty must come from real research: identity and scope joins, conflicting
authority or versions, boundary and exception analysis, unit normalization,
population reconstruction, calculations, counterevidence, and a conditional
decision. Do not manufacture difficulty with missing inputs, arbitrary format
requirements, hidden facts, or source hints.

## Reference report

Create a thorough, decision-ready `solution/report.md` that actually answers
the instruction. Use exact adjacent URLs from sources you opened. Reconcile
dates, identities, definitions, units, totals, and denominators. Show important
arithmetic. Distinguish supplied facts, verified facts, assumptions, inference,
uncertainty, and recommendation naturally. Use well-formed Markdown tables for
structured comparisons. Do not include task IDs, schema names, rubric terms,
source tiers/roles, decision logs, evaluator language, model names, or context
targets. Do not assert precision the evidence does not support.

Every URL in the ground truth and report must be a real public HTTP(S) URL. A
repeat 404/410 is unacceptable. A 401/403/429 or transient timeout is not proof
that a source is dead. Never use `example.com`, prose placeholders, or invented
URLs. Do not limit the evidence to any predetermined host list.

## Normalized rubric

`tests/rubrics.json` has exactly:

```json
{"schema_version":"online-search-rubrics","task_id":"<task-id>","scoring":"binary","criteria":[]}
```

Every criterion has exactly `id`, `axis`, `category`, `requirement`, `weight`,
and `claim_ids`. Criteria are binary, atomic, independent, integer weighted,
and visibly judgeable from the report. Positive IDs are `P...`, weights are
`1..20`; negative IDs are `N...`, weights are `-1..-100`.

Requirements:

- total criteria at most 50;
- at least one positive and one negative;
- positive count strictly greater than negative count;
- positive weight sum strictly greater than 300;
- positive weight sum strictly greater than total negative magnitude;
- no duplicate requirements, double rewards, or double punishment;
- omission loses positive credit and is not itself a negative trigger unless
  the instruction directly requires the omitted item;
- negatives describe distinct affirmative, material errors;
- positives score decision-relevant results, not generic workflow or headings;
- equivalent evidence-supported recommendations can earn credit when the
  instruction does not lock one option.

Aim for a useful distribution near 30 positives and 8-15 negatives when the
task genuinely supports it. Do not add filler to reach a count.

## Ground truth

Use exactly the normalized `online-search-ground-truth` top-level keys already
present in the template. Each claim has exactly:

`id`, `kind`, `statement`, `basis`, `report_location`, `accepted_citations`,
`rejected_citations`, and `conflict_resolution`.

Kinds are `fact`, `report_requirement`, or `prohibited_error`. Claims must be
atomic, concrete, supported, and consistent with the instruction and report.
Accepted citations use exact URLs and a concise `authority_basis`; rejected
citations need an exact URL and reason. Never create a citation entry with a
null, blank, or prose URL. `rubric_mappings` covers every criterion exactly once
with identical claim IDs and a nonempty justification.

Set `rubric_artifact_id` to SHA-256 of the canonical compact, sorted-key JSON
serialization of `tests/rubrics.json`:

```python
hashlib.sha256(json.dumps(rubric, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
```

## Evidence graph

Use exactly these top-level keys:

`schema_version`, `task_id`, `rubric_claims`, `nodes`, `edges`,
`required_paths`, `conflicts`, `calculations`, `recommendations`, `decoys`, and
`task_data`.

The schema version is `online-search-evidence-graph`. Every node has only `id`,
`type`, `label`, `url`, and `source_ids`; never add tier, role, capture, or
evaluator fields. IDs are unique and all edges resolve. `rubric_claims` covers
every rubric criterion exactly once with the same claim IDs. Represent genuine
source-to-claim support, conflict resolution, calculations, and downstream
decisions rather than padding empty or decorative nodes.

## Final checks

Run this exact command in capture mode, fix every failure, then rerun it with
`--mode verify`:

```bash
python3 {VALIDATOR_PATH} --task-root {TASK_PATH} --task-id {TASK_ID} --mode capture
```

Reread the five task-specific files. Confirm exact alignment
among instruction, report, rubric, ground truth, and graph. The golden report
must satisfy every positive criterion and trigger no negative criterion. Finish
only with a complete, fair, citation-grounded task.
