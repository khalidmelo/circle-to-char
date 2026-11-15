#!/bin/zsh
# Run the region pipeline for the N largest regions with W parallel workers.
# Regions that fail (usually a dropped connection) are retried in later passes; cached
# Sentinel-2 composites and radar crops are reused, so a retry only redoes what is missing.
# Usage: scripts/run_national.sh 60 4 [passes]
N=${1:-60}
W=${2:-4}
PASSES=${3:-3}
cd "$(dirname "$0")/.."
mkdir -p logs
FILTER="warn|shp_transform"
ids=($(.venv/bin/python -c "import json;R=json.load(open('data/national/regions.json'));print(' '.join(r['id'] for r in R[:$N]))"))
for pass in $(seq 1 $PASSES); do
  todo=()
  for rid in $ids; do
    [[ " $SKIP " == *" $rid "* ]] && continue
    # skip regions already finished, or with no NISAR coverage
    if [[ -f data/regions/$rid/meta.json ]] && grep -q -E '"status": "(ok|no radar|no fields)"' data/regions/$rid/meta.json; then continue; fi
    todo+=($rid)
  done
  echo "pass $pass: ${#todo} regions to run"
  (( ${#todo} )) || break
  for w in $(seq 0 $((W-1))); do
    (( w + 1 > ${#todo} )) && continue  # fewer regions than workers (macOS seq rejects an empty range)
    mine=()
    for i in $(seq $((w+1)) $W ${#todo}); do mine+=(${todo[$i]}); done
    if (( ${#mine} )); then
      # fields + radar, then the Sentinel-2 spring check (wheat rotation vs perennial) for the same regions
      ({ .venv/bin/python -u scripts/region_pipeline.py ${mine[@]}; .venv/bin/python -u scripts/s2_spring.py ${mine[@]}; } 2>&1 \
        | grep --line-buffered -v -i -E "$FILTER" >> logs/worker_$w.log) &
    fi
  done
  wait
done
# spring check for any finished region still missing it (e.g. ones done in an earlier run); quick for the rest
.venv/bin/python -u scripts/s2_spring.py all 2>&1 | grep --line-buffered -v -i -E "$FILTER" >> logs/spring_all.log
echo "all workers finished"
