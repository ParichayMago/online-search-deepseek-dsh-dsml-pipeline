#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${ONLINE_SEARCH_ROOT:-/home/kerosene/online-search-benchmark}"
RUNTIME="$ROOT/benchmark-runtime"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$RUNTIME/concurrency-preflight/$STAMP"
LANES=(control-proxy-codx deepseek-codex deepseek-codex-dsml deepseek-claude deepseek-dsh deepseek-dsh-dsml)
mkdir -p "$OUT/work"

[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || { echo "pipeline checkout is dirty" >&2; exit 2; }
if pgrep -af 'yggdrasil.cli run|run_online_search_benchmark_lane' | grep -v 'pgrep -af' >/dev/null; then
  echo "pipeline process already active" >&2
  exit 2
fi

python3 - "$ROOT" <<'PY'
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1])
lanes = (
    "control-proxy-codx",
    "deepseek-codex",
    "deepseek-codex-dsml",
    "deepseek-claude",
    "deepseek-dsh",
    "deepseek-dsh-dsml",
)
for lane in lanes:
    path = root / f"config-online-search-build-only-{lane}.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = [item.get("step") for item in config["pipeline"]]
    assert steps.count("benchmark.build_lane") == 1
    assert steps.count("oracle.score_golden") == 1
    for forbidden in (
        "oracle.score_nop",
        "difficulty.solver_lane",
        "deploy.gh_push",
        "deploy.open_pr",
    ):
        assert forbidden not in steps, (lane, forbidden)
PY

available_kib=$(awk '/MemAvailable:/{print $2}' /proc/meminfo)
free_kib=$(df -Pk / | awk 'NR==2{print $4}')
(( available_kib >= 45 * 1024 * 1024 )) || { echo "insufficient available RAM" >&2; exit 2; }
(( free_kib >= 250 * 1024 * 1024 )) || { echo "insufficient free disk" >&2; exit 2; }

declare -A CONTAINERS
for lane in "${LANES[@]}"; do
  container=$(docker ps -q \
    --filter "label=com.docker.compose.project=online-search-bench-$lane" \
    --filter "label=com.docker.compose.service=main")
  [[ -n "$container" ]] || { echo "missing main container: $lane" >&2; exit 2; }
  memory=$(docker inspect --format '{{.HostConfig.Memory}}' "$container")
  cpus=$(docker inspect --format '{{.HostConfig.NanoCpus}}' "$container")
  (( memory == 12 * 1024 * 1024 * 1024 )) || { echo "wrong memory cap: $lane" >&2; exit 2; }
  (( cpus == 3000000000 )) || { echo "wrong CPU cap: $lane" >&2; exit 2; }
  CONTAINERS[$lane]="$container"
done

# Prove all 30 slots can execute concurrently without invoking any model or
# producing a benchmark task.
barrier=$(( $(date +%s) + 3 ))
pids=()
for lane in "${LANES[@]}"; do
  for slot in 1 2 3 4 5; do
    marker="$OUT/work/$lane-$slot.ready"
    docker exec --workdir "$ROOT" "${CONTAINERS[$lane]}" sh -c \
      "while [ \$(date +%s) -lt $barrier ]; do sleep 0.05; done; sleep 1; printf ready > '$marker'" &
    pids+=("$!")
  done
done
for pid in "${pids[@]}"; do wait "$pid"; done
count=$(find "$OUT/work" -type f -name '*.ready' | wc -l)
[[ "$count" -eq 30 ]] || { echo "only $count/30 task slots completed" >&2; exit 1; }

jq -n --argjson total_slots "$count" --argjson lane_count "${#LANES[@]}" \
  --argjson tasks_per_lane 5 --argjson available_kib "$available_kib" \
  --argjson free_kib "$free_kib" \
  '{ready:($total_slots==30),lane_count:$lane_count,tasks_per_lane:$tasks_per_lane,total_slots:$total_slots,oracle_enabled:true,nop_enabled:false,solver_enabled:false,deployment_enabled:false,available_memory_kib:$available_kib,free_disk_kib:$free_kib}' \
  >"$OUT/summary.json"
jq . "$OUT/summary.json"

