#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 PIPELINE_DIR STATE_ROOT SERVER_LABEL IDEA_FILE TARGET" >&2
  exit 2
fi

PIPELINE_DIR="$(cd "$1" && pwd)"
STATE_ROOT="$2"
SERVER_LABEL="$3"
IDEA_FILE="$(cd "$(dirname "$4")" && pwd)/$(basename "$4")"
TARGET="$5"
CAMPAIGN="manufacturing-anomaly-verify-${SERVER_LABEL}"
MONITOR="manufacturing-anomaly-storage-${SERVER_LABEL}"
COMMIT="$(git -C "$PIPELINE_DIR" rev-parse HEAD)"
RUNNER="$PIPELINE_DIR/scripts/media_campaign.py"

[[ "$TARGET" =~ ^[1-9][0-9]*$ ]] || { echo "target must be positive" >&2; exit 2; }
[[ -f "$IDEA_FILE" ]] || { echo "missing idea file: $IDEA_FILE" >&2; exit 2; }
[[ -x "$PIPELINE_DIR/run.sh" ]] || { echo "pipeline run.sh is not executable" >&2; exit 2; }
[[ -f "$PIPELINE_DIR/.credentials.yaml" ]] || { echo "pipeline credentials are missing" >&2; exit 2; }
command -v tmux >/dev/null || { echo "tmux is required" >&2; exit 2; }
tmux has-session -t "$CAMPAIGN" 2>/dev/null && { echo "task session already exists: $CAMPAIGN" >&2; exit 2; }
tmux has-session -t "$MONITOR" 2>/dev/null && { echo "monitor session already exists: $MONITOR" >&2; exit 2; }

uv run --project "$PIPELINE_DIR" python "$RUNNER" init \
  --state-root "$STATE_ROOT" --idea-file "$IDEA_FILE" \
  --server "$SERVER_LABEL" --target "$TARGET" --pipeline-commit "$COMMIT" \
  --domain "Manufacturing" --task-mode "anomaly_detection" \
  --config-file "config-manufacturing-anomaly.yaml"

worker_command() {
  local lane="$1"
  printf 'cd %q && exec uv run --project %q python %q worker --state-root %q --pipeline-dir %q --lane %q' \
    "$PIPELINE_DIR" "$PIPELINE_DIR" "$RUNNER" "$STATE_ROOT" "$PIPELINE_DIR" "$lane"
}

tmux new-session -d -s "$CAMPAIGN" -n lane-01 "$(worker_command 1)"
tmux set-option -t "$CAMPAIGN" remain-on-exit on >/dev/null
for lane in 2 3 4 5 6 7; do
  printf -v window 'lane-%02d' "$lane"
  tmux new-window -d -t "$CAMPAIGN" -n "$window" "$(worker_command "$lane")"
done

printf -v monitor_command \
  'cd %q && exec uv run --project %q python %q monitor --state-root %q --path / --interval 60' \
  "$PIPELINE_DIR" "$PIPELINE_DIR" "$RUNNER" "$STATE_ROOT"
tmux new-session -d -s "$MONITOR" -n storage "$monitor_command"
tmux set-option -t "$MONITOR" remain-on-exit on >/dev/null

echo "launched $CAMPAIGN with exactly 7 task windows and $MONITOR"
