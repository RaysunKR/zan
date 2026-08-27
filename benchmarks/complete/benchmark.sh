#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

TS=$(date +%Y%m%d-%H%M%S)
OUTDIR="results/$TS"
mkdir -p "$OUTDIR"

DURATION=15
CONNECTIONS=256

tests=(
    "plaintext:GET /plaintext"
    "json:GET /json"
    "db:GET /db"
    "queries:GET /queries?queries=20"
    "updates:GET /updates?queries=20"
    "fortunes:GET /fortunes"
)

servers=(
    "zan:7071"
    "flask:7072"
    "zan_multi:7073"
)

for server_port in "${servers[@]}"; do
    server="${server_port%%:*}"
    port="${server_port##*:}"
    for test_spec in "${tests[@]}"; do
        name="${test_spec%%:*}"
        path="${test_spec##*:}"
        out="$OUTDIR/${server}_${name}.txt"
        if [ "$name" = "plaintext" ]; then
            wrk -t $(nproc) -c $CONNECTIONS -d ${DURATION}s --pipeline 16 \
                "http://127.0.0.1:$port$path" > "$out"
        else
            wrk -t $(nproc) -c $CONNECTIONS -d ${DURATION}s \
                "http://127.0.0.1:$port$path" > "$out"
        fi
        echo "Done $server $name"
    done
done

echo "Results in $OUTDIR"
