#!/usr/bin/env bash
set -euo pipefail

if ! command -v wrk >/dev/null 2>&1; then
    echo "Error: wrk is not installed or not in PATH" >&2
    exit 1
fi

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

# Collect median RPS summary lines.
summary_lines=()

for server_port in "${servers[@]}"; do
    server="${server_port%%:*}"
    port="${server_port##*:}"
    for test_spec in "${tests[@]}"; do
        name="${test_spec%%:*}"
        path="${test_spec##*:}"
        path="${path#* }"  # strip HTTP method

        rps_values=()
        for round in 1 2 3; do
            out="$OUTDIR/${server}_${name}_r${round}.txt"
            if [ "$name" = "plaintext" ]; then
                wrk -t $(nproc) -c $CONNECTIONS -d ${DURATION}s \
                    "http://127.0.0.1:$port$path" -s pipeline.lua -- 16 > "$out"
            else
                wrk -t $(nproc) -c $CONNECTIONS -d ${DURATION}s \
                    "http://127.0.0.1:$port$path" > "$out"
            fi
            rps=$(grep 'Requests/sec:' "$out" | awk '{print $2}')
            rps_values+=("$rps")
            echo "Done $server $name round $round"
        done

        median=$(printf '%s\n' "${rps_values[@]}" | sort -n | awk 'NR==2')
        summary_lines+=("${server}_${name}: median ${median} Requests/sec")
    done
done

echo
echo "Summary:"
for line in "${summary_lines[@]}"; do
    echo "  $line"
done

echo "Results in $OUTDIR"
