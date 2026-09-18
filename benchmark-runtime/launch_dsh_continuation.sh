#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: $0 ORIGINAL_RUN SEED_FILE TARGET_SUCCESSES [CONCURRENCY]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORIGINAL_RUN="$(cd "$1" && pwd)"
SEED_FILE="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
TARGET="$3"
CONCURRENCY="${4:-4}"
OPENROUTER_ENV_FILE="${OPENROUTER_ENV_FILE:-/home/kerosene/four-lane-experiment/openrouter.env}"

[[ "$ORIGINAL_RUN" == "$ROOT"/benchmark-runs/* ]] || {
  echo "original run must be beneath $ROOT/benchmark-runs" >&2
  exit 2
}
[[ -f "$ORIGINAL_RUN/manifest.json" && -f "$SEED_FILE" ]] || {
  echo "missing original manifest or continuation seed file" >&2
  exit 2
}
[[ "$TARGET" =~ ^[1-9][0-9]*$ ]] || { echo "target must be positive" >&2; exit 2; }
[[ "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]] || {
  echo "concurrency must be positive" >&2
  exit 2
}

IDEA_COUNT="$(uv run --project "$ROOT" python - "$SEED_FILE" <<'PY'
import sys
from pathlib import Path
import yaml
ideas = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))["ideas"]
ids = [item["id"] for item in ideas]
if not ideas or len(ids) != len(set(ids)):
    raise SystemExit("continuation ideas must be nonempty and unique")
print(len(ideas))
PY
)"
(( TARGET <= IDEA_COUNT )) || { echo "target exceeds idea count" >&2; exit 2; }

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
CONTINUATION="$ORIGINAL_RUN/continuations/$stamp"
mkdir -p "$CONTINUATION"
cp "$SEED_FILE" "$CONTINUATION/seed-set.yaml"

set -a
# shellcheck disable=SC1090
source "$OPENROUTER_ENV_FILE"
set +a
[[ -n "${OPENROUTER_API_KEY:-}" ]] || { echo "OpenRouter key missing" >&2; exit 2; }
[[ -n "${PARSEWAVE_TOKEN:-${MUSE_API_KEY:-}}" ]] || {
  echo "Muse solver credential missing" >&2
  exit 2
}

export DORAEMON_IDEA_SOURCE="$CONTINUATION/seed-set.yaml"
export ONLINE_SEARCH_BUILD_ONLY=0
export ONLINE_SEARCH_SERVER_CONTAINERS=1
export ONLINE_SEARCH_BENCHMARK_DIRECT=1
export ONLINE_SEARCH_TASK_COUNT="$IDEA_COUNT"
export ONLINE_SEARCH_TARGET_SUCCESSES="$TARGET"
export ONLINE_SEARCH_TASK_CONCURRENCY="$CONCURRENCY"
export ONLINE_SEARCH_TRIAL_CONCURRENCY="$((CONCURRENCY * 3))"
export ONLINE_SEARCH_JUDGE_PROVIDER=openrouter
export LLM_JUDGE_API_KEY="$OPENROUTER_API_KEY"
export LLM_JUDGE_BASE_URL=https://openrouter.ai/api/v1
export LLM_JUDGE_MODEL=deepseek/deepseek-v4.1-flash
export LLM_JUDGE_REASONING_EFFORT=xhigh

nohup "$ROOT/scripts/run_online_search_benchmark_lane.sh" \
  deepseek-dsh-dsml "$CONTINUATION/ygg" \
  >"$CONTINUATION/launcher.log" 2>&1 </dev/null &
pid=$!
python3 - "$CONTINUATION/supervisor.json" "$pid" <<'PY'
import json, sys, time
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(json.dumps({
    "pid": int(sys.argv[2]),
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "launcher_log": str(path.parent / "launcher.log"),
}, indent=2) + "\n", encoding="utf-8")
PY
echo "$CONTINUATION"
