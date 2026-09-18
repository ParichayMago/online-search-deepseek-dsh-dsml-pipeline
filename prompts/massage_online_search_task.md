# Final Online Search semantic massage

Independently audit and repair the task at `{TASK_PATH}` for publication. The
seed is `{IDEA}` and the task ID is `{TASK_ID}`. Work in place. Do not create
proposals, traces, logs, manifests, extra deliverables, or a nested task.

You may edit only `instruction.md`, `solution/report.md`,
`solution/evidence_graph.json`, `tests/rubrics.json`, and
`tests/reference/ground_truth.json`. Preserve the task's intended decision and
voice. Make precise, surgical corrections. Prefer supplying a genuinely
missing scenario input or clarifying a boundary over weakening or deleting a
valid decision requirement. Never invent a fact, URL, authority, calculation,
or hidden premise.

Audit instruction coherence, natural domain-appropriate voice, supplied-data
formatting, research openness, answer leakage, cutoff necessity, exact-link
wording, ASCII, commas, paragraphing, and the 350-word cap. Audit the report's
factual accuracy, dates, identities, definitions, units, denominators,
arithmetic, conflicts, uncertainty, decision logic, tables, exact adjacent
URLs, and alignment with the instruction.

Audit every rubric row for binary atomicity, independence, fairness,
judgeability, correct polarity and weight, duplicate credit or punishment,
omission-only penalties, arbitrary exactness, and unsupported requirements.
Check every ground-truth claim and citation against the cited page. Check all
mappings, the rubric hash, every graph node and edge, calculation,
recommendation, conflict, required path, and task-data dependency. Remove
internal task metadata, tier/role fields on graph nodes, decision-log content,
dead placeholders, and evaluator guidance. Keep normalized schemas exact.

Run the validator in capture mode, fix every failure, then rerun it in verify
mode:

```bash
python3 {VALIDATOR_PATH} --task-root {TASK_PATH} --task-id {TASK_ID} --mode capture
python3 {VALIDATOR_PATH} --task-root {TASK_PATH} --task-id {TASK_ID} --mode verify
```

Reread the five edited files after validation. Finish only when the golden
report should satisfy every positive criterion, trigger no negative criterion,
and fairly support more than 0.9 Oracle reward.
