#!/usr/bin/env bash
set -euo pipefail

EXPECTED_COMMIT="${ONLINE_SEARCH_DSH_SOURCE_COMMIT:-${ONLINE_SEARCH_DSH_EXPECTED_SHA:-3a224bc69c3a3230272ed5750b30fe90d87b47fc}}"
SOURCE_ROOT="${ONLINE_SEARCH_DSH_SOURCE_ROOT:-$HOME/.local/share/deepseek-harness-builder-search-pipeline-3a224bc}"
ENTRYPOINT="$SOURCE_ROOT/apps/cli/lib/bin.js"

[[ -d "$SOURCE_ROOT/.git" ]] || {
  echo "missing pinned DeepSeek Harness source checkout: $SOURCE_ROOT" >&2
  exit 127
}
ACTUAL_COMMIT="$(git -C "$SOURCE_ROOT" rev-parse HEAD 2>/dev/null || true)"
[[ "$ACTUAL_COMMIT" == "$EXPECTED_COMMIT" ]] || {
  echo "wrong DeepSeek Harness source revision: expected $EXPECTED_COMMIT, got ${ACTUAL_COMMIT:-missing}" >&2
  exit 127
}
[[ -f "$ENTRYPOINT" ]] || {
  echo "pinned DeepSeek Harness is not built: $ENTRYPOINT" >&2
  exit 127
}
command -v node >/dev/null 2>&1 || {
  echo "node is required for the pinned DeepSeek Harness build" >&2
  exit 127
}

exec node "$ENTRYPOINT" "$@"
