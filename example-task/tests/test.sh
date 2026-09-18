#!/usr/bin/env bash
set -euo pipefail

REWARD_FILE="${1:-/logs/verifier/reward.txt}"
mkdir -p "$(dirname "$REWARD_FILE")" /logs/verifier /logs/verifier/deliverables

if [[ ! -f /app/output/report.md ]] || [[ ! -s /app/output/report.md ]]; then
  printf '0.0\n' > /logs/verifier/score.txt
  printf '0.0\n' > "$REWARD_FILE"
  printf '{"status":"missing_or_empty_report","score":0.0}\n' \
    > /logs/verifier/judgment.json
  exit 0
fi

if find /app/output -type l -print -quit | grep -q .; then
  printf '0.0\n' > /logs/verifier/score.txt
  printf '0.0\n' > "$REWARD_FILE"
  printf '{"status":"candidate_output_contains_symlink","score":0.0}\n' \
    > /logs/verifier/judgment.json
  exit 0
fi

if find /app/output -mindepth 1 -maxdepth 1 ! -name report.md -print -quit | grep -q .; then
  printf '0.0\n' > /logs/verifier/score.txt
  printf '0.0\n' > "$REWARD_FILE"
  printf '{"status":"candidate_output_contains_extra_files","score":0.0}\n' \
    > /logs/verifier/judgment.json
  exit 0
fi

install -m 0644 /app/output/report.md /logs/verifier/deliverables/report.md
export OUTPUT_DIR=/logs/verifier/deliverables
if ! python3 /tests/test_outputs.py; then
  printf '0.0\n' > /logs/verifier/score.txt
  printf '0.0\n' > "$REWARD_FILE"
  exit 0
fi
if [[ ! -s /logs/verifier/score.txt ]]; then
  printf '0.0\n' > /logs/verifier/score.txt
fi
cp /logs/verifier/score.txt "$REWARD_FILE"
