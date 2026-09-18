#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${1:-run-$(date -u +%Y%m%dT%H%M%SZ)-taxonomy-dsh-dsml-target100}"
RUN_ROOT="$ROOT/benchmark-runs/$RUN_ID"
SEED_SOURCE="$ROOT/ideas.yaml"
TARGET_SUCCESSES=100
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
OPENROUTER_ENV_FILE="${OPENROUTER_ENV_FILE:-/home/kerosene/four-lane-experiment/openrouter.env}"

[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]] || {
  echo "pipeline checkout must be clean" >&2
  exit 2
}
[[ ! -e "$RUN_ROOT" ]] || { echo "run already exists: $RUN_ROOT" >&2; exit 2; }
[[ -f "$SEED_SOURCE" ]] || {
  echo "missing taxonomy-balanced seed catalog" >&2
  exit 2
}
[[ -r "$OPENROUTER_ENV_FILE" ]] || {
  echo "missing OpenRouter environment file: $OPENROUTER_ENV_FILE" >&2
  exit 2
}
mkdir -p "$RUN_ROOT"
cp "$SEED_SOURCE" "$RUN_ROOT/seed-set.yaml"
IDEA_COUNT="$(python3 - "$RUN_ROOT/seed-set.yaml" <<'PY'
import sys, yaml
rows = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))["ideas"]
print(len(rows))
PY
)"
(( IDEA_COUNT >= TARGET_SUCCESSES )) || {
  echo "taxonomy catalog has fewer than $TARGET_SUCCESSES seeds" >&2
  exit 2
}

set -a
# shellcheck disable=SC1090
source "$OPENROUTER_ENV_FILE"
set +a
[[ -n "${OPENROUTER_API_KEY:-}" ]] || {
  echo "OpenRouter environment supplied no API key" >&2
  exit 2
}

python3 - "$RUN_ROOT/manifest.json" "$RUN_ID" "$COMMIT" "$IDEA_COUNT" "$TARGET_SUCCESSES" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "schema_version": "online-search-taxonomy-dsh-dsml-v1",
    "run_id": sys.argv[2],
    "pipeline_commit": sys.argv[3],
    "lane": "deepseek-dsh-dsml",
    "model": "deepseek/deepseek-v4.1-flash",
    "reasoning_effort": "xhigh",
    "context_window": 1_000_000,
    "automatic_compaction_disabled": True,
    "max_build_attempts": int(sys.argv[4]),
    "target_build_successes": int(sys.argv[5]),
    "target_qualified_tasks": int(sys.argv[5]),
    "task_concurrency": 4,
    "build_and_oracle_only": False,
    "oracle_gate": "> 0.9",
    "judge_provider": "openrouter",
    "judge_model": "deepseek/deepseek-v4.1-flash",
    "publication_mean_score_gate": "< 0.8",
    "publication_max_peak_call_context_gate": ">= 500000",
    "solver_timeout_seconds": 10800,
    "local_solver_trials_per_task": 3,
    "local_solver_trial_concurrency": 4,
    "deployment_enabled": False,
}
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

export DORAEMON_IDEA_SOURCE="$RUN_ROOT/seed-set.yaml"
export ONLINE_SEARCH_BUILD_ONLY=0
export ONLINE_SEARCH_SERVER_CONTAINERS=1
export ONLINE_SEARCH_BENCHMARK_DIRECT=1
export ONLINE_SEARCH_TASK_COUNT="$IDEA_COUNT"
export ONLINE_SEARCH_TARGET_SUCCESSES="$TARGET_SUCCESSES"
export ONLINE_SEARCH_TASK_CONCURRENCY=4
export ONLINE_SEARCH_TRIAL_CONCURRENCY=12
export ONLINE_SEARCH_JUDGE_PROVIDER=openrouter
export LLM_JUDGE_API_KEY="$OPENROUTER_API_KEY"
export LLM_JUDGE_BASE_URL=https://openrouter.ai/api/v1
export LLM_JUDGE_MODEL=deepseek/deepseek-v4.1-flash
export LLM_JUDGE_REASONING_EFFORT=xhigh
[[ -n "${PARSEWAVE_TOKEN:-${MUSE_API_KEY:-}}" ]] || {
  echo "Muse solver credential missing" >&2
  exit 2
}

exec "$ROOT/scripts/run_online_search_benchmark_lane.sh" \
  deepseek-dsh-dsml "$RUN_ROOT/ygg"
