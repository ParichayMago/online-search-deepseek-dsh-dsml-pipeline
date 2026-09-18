#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 LANE [LOGS_DIR]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
LANE="$1"
if [[ "${ONLINE_SEARCH_BUILD_ONLY:-0}" == "1" ]]; then
  CONFIG="$ROOT/config-online-search-build-only-${LANE}.yaml"
else
  CONFIG="$ROOT/config-online-search-pipeline-${LANE}.yaml"
fi
LOGS_DIR="${2:-$ROOT/benchmark-runs/${LANE}}"
TASK_COUNT="${ONLINE_SEARCH_TASK_COUNT:-3}"
TARGET_SUCCESSES="${ONLINE_SEARCH_TARGET_SUCCESSES:-$TASK_COUNT}"
TASK_CONCURRENCY="${ONLINE_SEARCH_TASK_CONCURRENCY:-1}"

case "$LANE" in
  control-native|control-proxy-codx|deepseek-codex|deepseek-codex-dsml|deepseek-claude|deepseek-dsh|deepseek-dsh-dsml) ;;
  *) echo "unsupported lane: $LANE" >&2; exit 2 ;;
esac

[[ -f "$CONFIG" ]] || { echo "missing lane config: $CONFIG" >&2; exit 2; }
export DORAEMON_IDEA_SOURCE="${DORAEMON_IDEA_SOURCE:-$ROOT/ideas.yaml}"
[[ -f "$DORAEMON_IDEA_SOURCE" ]] || {
  echo "missing immutable idea source: $DORAEMON_IDEA_SOURCE" >&2
  exit 2
}

if [[ "${ONLINE_SEARCH_SERVER_CONTAINERS:-0}" == "1" ]]; then
  [[ "$LANE" != "control-native" ]] || {
    echo "control-native must run locally without a server container" >&2
    exit 2
  }
  ONLINE_SEARCH_BUILDER_CONTAINER="$(
    docker ps -q \
      --filter "label=com.docker.compose.project=online-search-bench-$LANE" \
      --filter "label=com.docker.compose.service=main"
  )"
  [[ -n "$ONLINE_SEARCH_BUILDER_CONTAINER" ]] || {
    echo "no ready builder container for $LANE" >&2
    exit 2
  }
  export ONLINE_SEARCH_BUILDER_CONTAINER
  case "$LANE" in
    control-proxy-codx)
      export ONLINE_SEARCH_CODX_BIN=/home/kerosene/.local/bin/codx
      export ONLINE_SEARCH_CODX_HOME=/home/kerosene/.codex-codx-pool-b ;;
    deepseek-codex)
      export ONLINE_SEARCH_CODEX_BIN=/opt/codex-vendor/bin/codex
      export ONLINE_SEARCH_DEEPSEEK_CODEX_HOME=/home/kerosene/.codex-openrouter ;;
    deepseek-codex-dsml)
      export ONLINE_SEARCH_CODEX_BIN=/opt/codex-vendor/bin/codex
      export ONLINE_SEARCH_DEEPSEEK_CODEX_DSML_HOME=/home/kerosene/.codex-openrouter-dsml-e9ce61d ;;
    deepseek-claude)
      ONLINE_SEARCH_CLAUDE_BIN=/home/kerosene/.local/npm-global/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
      export ONLINE_SEARCH_CLAUDE_BIN
      export ONLINE_SEARCH_DEEPSEEK_CLAUDE_HOME=/home/kerosene/.claude-openrouter ;;
    deepseek-dsh)
      export ONLINE_SEARCH_DSH_BIN="$ROOT/scripts/dsh_headless_entrypoint.sh"
      export ONLINE_SEARCH_DEEPSEEK_DSH_HOME=/home/kerosene/.dsh-openrouter ;;
    deepseek-dsh-dsml)
      export ONLINE_SEARCH_DSH_BIN="$ROOT/scripts/dsh_headless_entrypoint.sh"
      export ONLINE_SEARCH_DEEPSEEK_DSH_DSML_HOME=/home/kerosene/.dsh-openrouter-dsml ;;
  esac
fi

# Exactly three fixed seed indices, sequentially within each lane. Six server
# lanes can run concurrently while the native control runs on the local host.
RUN_ARGS=(
  --config "$CONFIG"
  --count "$TASK_COUNT"
  --target-successes "$TARGET_SUCCESSES"
  --concurrency "$TASK_CONCURRENCY"
  --conc-trials "${ONLINE_SEARCH_TRIAL_CONCURRENCY:-3}"
  --logs-dir "$LOGS_DIR"
)

if [[ "${ONLINE_SEARCH_BENCHMARK_DIRECT:-0}" == "1" ]]; then
  YGG_DIR="${ONLINE_SEARCH_YGGDRASIL_DIR:-$HOME/yggdrasil-online-benchmark}"
  PWH_PATH="${PWH_PATH:-$HOME/pw-harness}"
  [[ -d "$YGG_DIR/.git" ]] || { echo "missing pinned Yggdrasil: $YGG_DIR" >&2; exit 2; }
  [[ -e "$PWH_PATH/.git" ]] || { echo "missing pinned pw-harness: $PWH_PATH" >&2; exit 2; }
  [[ -f "$ROOT/.credentials.yaml" ]] || {
    echo "missing secure benchmark credentials: $ROOT/.credentials.yaml" >&2
    exit 2
  }
  export PWH_PATH HARBOR_ALLOW_INTERNET=1
  [[ -n "${OPENROUTER_API_KEY:-}" ]] || {
    echo "OpenRouter judge requires OPENROUTER_API_KEY" >&2
    exit 2
  }
  export LLM_JUDGE_API_KEY="$OPENROUTER_API_KEY"
  export LLM_JUDGE_BASE_URL=https://openrouter.ai/api/v1
  export LLM_JUDGE_MODEL=deepseek/deepseek-v4.1-flash
  export LLM_JUDGE_REASONING_EFFORT=xhigh
  export VERIFIER_REASONING_EFFORT=xhigh
  export VERIFIER_SEARCH_URL="${VERIFIER_SEARCH_URL:-http://127.0.0.1:18120}"
  export ONLINE_SEARCH_AGENTIC_VERIFIER_BIN
  ONLINE_SEARCH_AGENTIC_VERIFIER_BIN="$($ROOT/scripts/setup_agentic_verifier.sh)"
  if [[ "${ONLINE_SEARCH_BUILD_ONLY:-0}" != "1" ]] \
    && [[ -z "${PARSEWAVE_TOKEN:-${MUSE_API_KEY:-}}" ]]; then
    echo "full pipeline requires PARSEWAVE_TOKEN or MUSE_API_KEY for Muse" >&2
    exit 2
  fi
  exec uv run --project "$PWH_PATH" \
    --with-editable "$YGG_DIR" \
    --with boto3 --with httpx --with beautifulsoup4 --with pypdf --with pyyaml \
    python -m yggdrasil.cli run "${RUN_ARGS[@]}"
fi

exec "$ROOT/run.sh" "${RUN_ARGS[@]}"
