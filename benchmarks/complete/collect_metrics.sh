#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

TS=${1:-$(date +%Y%m%d-%H%M%S)}
OUTDIR="results/$TS"
mkdir -p "$OUTDIR"

echo "Collecting metrics into $OUTDIR ..."

# CPU
mpstat -P ALL 1 > "$OUTDIR/mpstat.log" &
MPSTAT_PID=$!

# network
sar -n DEV 1 > "$OUTDIR/sar_dev.log" 2>/dev/null &
SAR_PID=$!

# flame graph for zan single-process (best effort)
ZAN_PID=$(pgrep -f 'zan_app/app.py' | head -1 || true)
if [ -n "$ZAN_PID" ] && command -v perf >/dev/null 2>&1; then
    sudo perf record -g -p "$ZAN_PID" -o "$OUTDIR/perf.data" -- sleep 10 || true
    sudo perf script -i "$OUTDIR/perf.data" > "$OUTDIR/perf.script" || true
fi

sleep 15

kill $MPSTAT_PID $SAR_PID || true
wait $MPSTAT_PID $SAR_PID 2>/dev/null || true

echo "Metrics collection complete."
