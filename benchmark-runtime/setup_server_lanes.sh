#!/usr/bin/env bash
set -euo pipefail

ROOT="${ONLINE_SEARCH_ROOT:-/home/kerosene/online-search-benchmark}"
ONLINE_SEARCH_ROOT="$ROOT"
RUNTIME="$ROOT/benchmark-runtime"
VISION_RUNTIME_ROOT="${VISION_RUNTIME_ROOT:-/home/kerosene/six-lane-experiment/0d3229-supplier-recovery-forum-evidence-reset/runtime}"
OPENROUTER_ENV_FILE="${OPENROUTER_ENV_FILE:-/home/kerosene/four-lane-experiment/openrouter.env}"
CODEX_VENDOR_ROOT="${CODEX_VENDOR_ROOT:-/home/kerosene/.local/npm-global/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl}"
ONLINE_SEARCH_DSH_SOURCE_COMMIT="${ONLINE_SEARCH_DSH_SOURCE_COMMIT:-3a224bc69c3a3230272ed5750b30fe90d87b47fc}"
ONLINE_SEARCH_DSH_SOURCE_ROOT="${ONLINE_SEARCH_DSH_SOURCE_ROOT:-/home/kerosene/.local/share/deepseek-harness-builder-search-pipeline-3a224bc}"
BENCH_UID="$(id -u)"
BENCH_GID="$(id -g)"
LANES=(control-proxy-codx deepseek-codex deepseek-codex-dsml deepseek-claude deepseek-dsh deepseek-dsh-dsml)

export ONLINE_SEARCH_ROOT VISION_RUNTIME_ROOT OPENROUTER_ENV_FILE CODEX_VENDOR_ROOT BENCH_UID BENCH_GID
export ONLINE_SEARCH_DSH_SOURCE_COMMIT ONLINE_SEARCH_DSH_SOURCE_ROOT
[[ -d "$ROOT/.git" ]] || { echo "missing clean pipeline checkout: $ROOT" >&2; exit 2; }
[[ -f "$OPENROUTER_ENV_FILE" ]] || { echo "missing OpenRouter env file" >&2; exit 2; }
[[ -f "$VISION_RUNTIME_ROOT/vision_inspect.py" ]] || { echo "missing vision client" >&2; exit 2; }
[[ -f "$VISION_RUNTIME_ROOT/vision_sidecar.py" ]] || { echo "missing vision sidecar" >&2; exit 2; }
[[ "$(git -C "$ONLINE_SEARCH_DSH_SOURCE_ROOT" rev-parse HEAD 2>/dev/null || true)" == "$ONLINE_SEARCH_DSH_SOURCE_COMMIT" ]] || {
  echo "pinned DeepSeek Harness source revision is missing or wrong" >&2
  exit 2
}
[[ -f "$ONLINE_SEARCH_DSH_SOURCE_ROOT/apps/cli/lib/bin.js" ]] || {
  echo "pinned DeepSeek Harness source build is missing apps/cli/lib/bin.js" >&2
  exit 2
}

lp self-update --force
lp pool codx set pool-b
lp proxy restart
lp refresh-env codx
lp pool codx status

install -d -m 700 "$HOME/.codex-codx-pool-b"
install -m 600 "$HOME/.codex/auth.json" "$HOME/.codex-codx-pool-b/auth.json"

docker compose -f "$RUNTIME/compose.base.yaml" build main
for lane in "${LANES[@]}"; do
  files=(-f "$RUNTIME/compose.base.yaml")
  if [[ "$lane" == deepseek-* ]]; then
    files+=(-f "$RUNTIME/compose.vision.yaml")
  fi
  files+=(-f "$RUNTIME/compose.${lane}.yaml")
  docker compose -p "online-search-bench-${lane}" "${files[@]}" up -d
done

map="$RUNTIME/server-lanes.env"
: >"$map"
for lane in "${LANES[@]}"; do
  files=(-f "$RUNTIME/compose.base.yaml")
  [[ "$lane" == deepseek-* ]] && files+=(-f "$RUNTIME/compose.vision.yaml")
  files+=(-f "$RUNTIME/compose.${lane}.yaml")
  container=$(docker compose -p "online-search-bench-${lane}" "${files[@]}" ps -q main)
  [[ -n "$container" ]] || { echo "missing container for $lane" >&2; exit 1; }
  printf 'ONLINE_SEARCH_CONTAINER_%s=%s\n' "${lane^^}" "$container" | tr '-' '_' >>"$map"
done
chmod 600 "$map"
echo "server lane containers ready; map=$map"
