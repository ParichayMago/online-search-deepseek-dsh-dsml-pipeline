#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_ID="${1:-bearing-deviation-closure}"
RUN_ID="${2:-canary-$(date -u +%Y%m%dT%H%M%SZ)-dsh-dsml}"
RUN_ROOT="$ROOT/benchmark-runs/$RUN_ID"
OPENROUTER_ENV_FILE="${OPENROUTER_ENV_FILE:-/home/kerosene/four-lane-experiment/openrouter.env}"

[[ ! -e "$RUN_ROOT" ]] || { echo "canary run already exists" >&2; exit 2; }
[[ -r "$OPENROUTER_ENV_FILE" ]] || { echo "OpenRouter environment missing" >&2; exit 2; }
mkdir -p "$RUN_ROOT"
uv run --project "$ROOT" python - "$ROOT" "$TASK_ID" "$RUN_ROOT/seed.yaml" <<'PY'
import sys
from pathlib import Path
import yaml
root, task_id, output = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
ideas = []
for name in ("manufacturing-anomaly-a.yaml", "manufacturing-anomaly-b.yaml"):
    ideas.extend(yaml.safe_load((root / name).read_text(encoding="utf-8"))["ideas"])
matches = [idea for idea in ideas if idea["id"] == task_id]
if len(matches) != 1:
    raise SystemExit(f"expected one seed for {task_id}, found {len(matches)}")
output.write_text(yaml.safe_dump({"version": 1, "ideas": matches}, sort_keys=False), encoding="utf-8")
PY

set -a
# shellcheck disable=SC1090
source "$OPENROUTER_ENV_FILE"
set +a
[[ -n "${OPENROUTER_API_KEY:-}" ]] || { echo "OpenRouter key missing" >&2; exit 2; }

export DORAEMON_IDEA_SOURCE="$RUN_ROOT/seed.yaml"
export ONLINE_SEARCH_BUILD_ONLY=1
export ONLINE_SEARCH_SERVER_CONTAINERS=1
export ONLINE_SEARCH_BENCHMARK_DIRECT=1
export ONLINE_SEARCH_TASK_COUNT=1
export ONLINE_SEARCH_TARGET_SUCCESSES=1
export ONLINE_SEARCH_TASK_CONCURRENCY=1
export ONLINE_SEARCH_TRIAL_CONCURRENCY=1
export ONLINE_SEARCH_JUDGE_PROVIDER=openrouter
export LLM_JUDGE_API_KEY="$OPENROUTER_API_KEY"
export LLM_JUDGE_BASE_URL=https://openrouter.ai/api/v1
export LLM_JUDGE_MODEL=deepseek/deepseek-v4.1-flash
export LLM_JUDGE_REASONING_EFFORT=xhigh

python3 - "$RUN_ROOT/manifest.json" "$RUN_ID" "$TASK_ID" "$(git -C "$ROOT" rev-parse HEAD)" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": "online-search-dsh-dsml-canary-v1",
    "run_id": sys.argv[2],
    "task_id": sys.argv[3],
    "pipeline_commit": sys.argv[4],
    "builder": "deepseek-dsh-dsml",
    "builder_model": "deepseek/deepseek-v4.1-flash",
    "judge_model": "deepseek/deepseek-v4.1-flash",
    "vision_model": "google/gemini-3.7-flash",
    "build_concurrency": 1,
    "deployment_enabled": False,
}, indent=2) + "\n", encoding="utf-8")
PY

exec "$ROOT/scripts/run_online_search_benchmark_lane.sh" \
  deepseek-dsh-dsml "$RUN_ROOT/ygg"
