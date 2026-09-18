#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${ONLINE_SEARCH_ROOT:-/home/kerosene/online-search-benchmark}"
RUNTIME="$ROOT/benchmark-runtime"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$RUNTIME/preflight/$STAMP"
LANES=(control-proxy-codx deepseek-codex deepseek-codex-dsml deepseek-claude deepseek-dsh deepseek-dsh-dsml)
mkdir -p "$OUT"

container_for() {
  docker ps -q \
    --filter "label=com.docker.compose.project=online-search-bench-$1" \
    --filter "label=com.docker.compose.service=main"
}

run_lane() {
  local lane="$1" container marker work dsh_home rc=0
  container="$(container_for "$lane")"
  marker="ONLINE_SEARCH_READY_${lane^^}"
  marker="${marker//-/_}"
  work="$ROOT/benchmark-runtime/preflight-work/$STAMP/$lane"
  mkdir -p "$work"
  local prompt="Use the shell tool to run exactly: printf '$marker' > '$work/marker.txt' . Do not inspect other files and do not perform any other work. Then reply exactly $marker."
  set +e
  case "$lane" in
    control-proxy-codx)
      timeout 600 docker exec --interactive --workdir "$work" \
        --env HOME=/home/kerosene --env CODEX_HOME=/home/kerosene/.codex-codx-pool-b \
        "$container" /home/kerosene/.local/bin/codx --yolo exec \
        --ignore-user-config --ignore-rules --disable apps --skip-git-repo-check \
        --model gpt-5.6-sol -c 'model_reasoning_effort="xhigh"' \
        -c model_context_window=1000000 -c model_auto_compact_token_limit=2000000000 \
        --json "$prompt" >"$OUT/$lane.trace.jsonl" 2>"$OUT/$lane.stderr.txt" ;;
    deepseek-codex)
      timeout 600 docker exec --interactive --workdir "$work" \
        --env HOME=/home/kerosene --env CODEX_HOME=/home/kerosene/.codex-openrouter \
        "$container" /opt/codex-vendor/bin/codex exec --ignore-rules --disable apps \
        --ephemeral --skip-git-repo-check --model deepseek/deepseek-v4.1-flash \
        -c 'model_reasoning_effort="xhigh"' \
        -c model_context_window=1000000 -c model_auto_compact_token_limit=2000000000 \
        --dangerously-bypass-approvals-and-sandbox --json "$prompt" \
        >"$OUT/$lane.trace.jsonl" 2>"$OUT/$lane.stderr.txt" ;;
    deepseek-codex-dsml)
      timeout 600 docker exec --interactive --workdir "$work" \
        --env HOME=/home/kerosene --env CODEX_HOME=/home/kerosene/.codex-openrouter-dsml-e9ce61d \
        "$container" /opt/codex-vendor/bin/codex exec --ignore-rules --disable apps \
        --ephemeral --skip-git-repo-check --model deepseek/deepseek-v4.1-flash \
        -c 'model_reasoning_effort="xhigh"' \
        -c 'model_catalog_json="/home/kerosene/.codex-openrouter-dsml-e9ce61d/model-catalog.json"' \
        -c model_context_window=1000000 -c model_auto_compact_token_limit=2000000000 \
        --dangerously-bypass-approvals-and-sandbox --json "$prompt" \
        >"$OUT/$lane.trace.jsonl" 2>"$OUT/$lane.stderr.txt" ;;
    deepseek-claude)
      timeout 600 docker exec --interactive --workdir "$work" \
        --env HOME=/home/kerosene --env CLAUDE_CONFIG_DIR=/home/kerosene/.claude-openrouter \
        --env CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0 --env CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000 \
        --env DISABLE_AUTO_COMPACT=1 "$container" \
        /home/kerosene/.local/npm-global/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe --print \
        --model deepseek/deepseek-v4.1-flash --effort xhigh --dangerously-skip-permissions \
        --output-format stream-json --verbose --no-session-persistence "$prompt" \
        >"$OUT/$lane.trace.jsonl" 2>"$OUT/$lane.stderr.txt" ;;
    deepseek-dsh)
      dsh_home="$work/dsh-home"
      PYTHONPATH="$ROOT" python3 -c \
        'from pathlib import Path; from dsh_home_isolation import create_isolated_dsh_home; import sys; create_isolated_dsh_home(Path(sys.argv[1]), Path(sys.argv[2]))' \
        "$HOME/.dsh-openrouter" "$work"
      timeout 600 docker exec --interactive --workdir "$work" \
        --env HOME=/home/kerosene --env DSH_HOME="$dsh_home" \
        --env DSH_REASONING_EFFORT=xhigh --env OPENROUTER_REASONING_EFFORT=xhigh \
        --env DSH_PERMISSION_MODE=danger-full-access --env NODE_OPTIONS=--max-old-space-size=6144 \
        "$container" "$ROOT/scripts/dsh_headless_entrypoint.sh" --profile headless "$prompt" \
        >"$OUT/$lane.trace.txt" 2>"$OUT/$lane.stderr.txt" ;;
    deepseek-dsh-dsml)
      dsh_home="$work/dsh-home"
      PYTHONPATH="$ROOT" python3 -c \
        'from pathlib import Path; from dsh_home_isolation import create_isolated_dsh_home; import sys; create_isolated_dsh_home(Path(sys.argv[1]), Path(sys.argv[2]))' \
        "$HOME/.dsh-openrouter-dsml" "$work"
      timeout 600 docker exec --interactive --workdir "$work" \
        --env HOME=/home/kerosene --env DSH_HOME="$dsh_home" \
        --env DSH_PERMISSION_MODE=danger-full-access --env DSH_TOOLS_MODE=code \
        --env NODE_OPTIONS=--max-old-space-size=6144 "$container" \
        "$ROOT/scripts/dsh_headless_entrypoint.sh" --profile headless "$prompt" \
        >"$OUT/$lane.trace.txt" 2>"$OUT/$lane.stderr.txt" ;;
  esac
  rc=$?
  set -e
  actual="$(cat "$work/marker.txt" 2>/dev/null || true)"
  ready=false
  [[ "$rc" -eq 0 && "$actual" == "$marker" ]] && ready=true
  jq -n --arg lane "$lane" --argjson exit_code "$rc" --arg marker "$marker" \
    --arg actual "$actual" --argjson ready "$ready" \
    '{lane:$lane,exit_code:$exit_code,expected_marker:$marker,actual_marker:$actual,ready:$ready}' \
    >"$OUT/$lane.status.json"
}

for lane in "${LANES[@]}"; do run_lane "$lane" & done
wait
jq -s '{ready:all(.[];.ready),lanes:sort_by(.lane)}' "$OUT"/*.status.json >"$OUT/summary.json"
jq . "$OUT/summary.json"
