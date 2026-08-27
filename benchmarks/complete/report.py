import glob
import os
import re
import sys
from pathlib import Path
from statistics import median


# Valid server and test names as produced by benchmarks/complete/benchmark.sh.
SERVERS = ["zan", "flask", "zan_multi"]
TESTS = ["plaintext", "json", "db", "queries", "updates", "fortunes"]

# Filename pattern: <server>_<test>_r<round>.txt
FILE_RE = re.compile(r"^(.+)_(.+)_r(\d+)$")


def parse_wrk(path):
    text = Path(path).read_text()

    m = re.search(r"Requests/sec:\s+([0-9.]+)", text)
    rps = float(m.group(1)) if m else 0.0

    m = re.search(r"Latency\s+([0-9.]+)(us|ms|s)", text)
    if m:
        lat = f"{m.group(1)}{m.group(2)}"
        lat_ms = _latency_to_ms(m.group(1), m.group(2))
    else:
        lat = "-"
        lat_ms = None

    m = re.search(
        r"Socket errors.*connect\s+(\d+),\s*read\s+(\d+),\s*write\s+(\d+),\s*timeout\s+(\d+)",
        text,
    )
    errors = tuple(int(g) for g in m.groups()) if m else (0, 0, 0, 0)

    return {"rps": rps, "latency": lat, "latency_ms": lat_ms, "errors": errors}


def _latency_to_ms(value, unit):
    value = float(value)
    if unit == "us":
        return value / 1000.0
    if unit == "ms":
        return value
    if unit == "s":
        return value * 1000.0
    return value


def _median_round(values):
    """Return the run whose RPS is closest to the median (used for latency/error details)."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    sorted_vals = sorted(values, key=lambda r: r["rps"])
    n = len(sorted_vals)
    mid = n // 2
    if n % 2:
        return sorted_vals[mid]
    # For even counts return the lower-middle value to keep determinism.
    return sorted_vals[mid - 1]


def main(outdir):
    outdir = Path(outdir)
    if not outdir.is_dir():
        raise SystemExit(f"Error: {outdir} is not a directory")

    files = sorted(glob.glob(str(outdir / "*_r*.txt")))
    if not files:
        raise SystemExit(f"No *_r*.txt wrk output files found in {outdir}")

    # Collect parsed results grouped by (server, test).
    grouped = {}
    for f in files:
        stem = Path(f).stem
        m = FILE_RE.match(stem)
        if not m:
            continue
        raw_server, raw_test, _round = m.groups()

        # Resolve server/test against known names to handle underscores correctly.
        server = raw_server if raw_server in SERVERS else None
        test = raw_test if raw_test in TESTS else None
        if server is None or test is None:
            # Fallback: try longest matching server prefix.
            for s in SERVERS:
                if raw_server.startswith(s + "_"):
                    server = s
                    test = raw_server[len(s) + 1:]
                    break
            if server is None or test is None:
                print(f"Warning: skipping unrecognized file {f}", file=sys.stderr)
                continue

        data = parse_wrk(f)
        grouped.setdefault((server, test), []).append(data)

    if not grouped:
        raise SystemExit(f"No recognizable wrk results in {outdir}")

    rows = []
    for test in TESTS:
        for server in SERVERS:
            runs = grouped.get((server, test), [])
            if not runs:
                rows.append(
                    {
                        "server": server,
                        "test": test,
                        "rps": 0.0,
                        "latency": "-",
                        "latency_ms": None,
                        "errors": (0, 0, 0, 0),
                    }
                )
                continue

            rps_values = [r["rps"] for r in runs]
            median_rps = median(rps_values)
            median_run = _median_round(runs)
            rows.append(
                {
                    "server": server,
                    "test": test,
                    "rps": median_rps,
                    "latency": median_run["latency"],
                    "latency_ms": median_run["latency_ms"],
                    "errors": median_run["errors"],
                }
            )

    def rps(server, test):
        for r in rows:
            if r["server"] == server and r["test"] == test:
                return r["rps"]
        return 0.0

    def latency(server, test):
        for r in rows:
            if r["server"] == server and r["test"] == test:
                return r["latency"]
        return "-"

    def errors(server, test):
        for r in rows:
            if r["server"] == server and r["test"] == test:
                return r["errors"]
        return (0, 0, 0, 0)

    # Build markdown table.
    md = [
        "| Test | zan | flask | zan_multi | zan vs flask |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for test in TESTS:
        zan_rps = rps("zan", test)
        flask_rps = rps("flask", test)
        speedup = zan_rps / flask_rps if flask_rps else 0.0
        md.append(
            f"| {test} | {zan_rps:.0f} | {flask_rps:.0f} | {rps('zan_multi', test):.0f} | {speedup:.1f}x |"
        )

    md.append("")
    md.append("### Latency (median round)")
    md.append("")
    md.append("| Test | zan | flask | zan_multi |")
    md.append("| --- | --- | --- | --- |")
    for test in TESTS:
        md.append(
            f"| {test} | {latency('zan', test)} | {latency('flask', test)} | {latency('zan_multi', test)} |"
        )

    md.append("")
    md.append("### Errors (median round)")
    md.append("")
    md.append("| Test | zan (connect/read/write/timeout) | flask (connect/read/write/timeout) | zan_multi (connect/read/write/timeout) |")
    md.append("| --- | --- | --- | --- |")
    for test in TESTS:
        zan_err = errors("zan", test)
        flask_err = errors("flask", test)
        multi_err = errors("zan_multi", test)
        md.append(
            f"| {test} | {'/'.join(str(e) for e in zan_err)} | {'/'.join(str(e) for e in flask_err)} | {'/'.join(str(e) for e in multi_err)} |"
        )

    # Build CSV.
    csv_lines = [
        "test,zan_rps,flask_rps,zan_multi_rps,zan_vs_flask,zan_latency,flask_latency,zan_multi_latency,zan_errors,flask_errors,zan_multi_errors"
    ]
    for test in TESTS:
        zan_rps = rps("zan", test)
        flask_rps = rps("flask", test)
        multi_rps = rps("zan_multi", test)
        speedup = zan_rps / flask_rps if flask_rps else 0.0
        csv_lines.append(
            f"{test},"
            f"{zan_rps:.2f},{flask_rps:.2f},{multi_rps:.2f},{speedup:.2f},"
            f"{latency('zan', test)},{latency('flask', test)},{latency('zan_multi', test)},"
            f"{'/'.join(str(e) for e in errors('zan', test))},"
            f"{'/'.join(str(e) for e in errors('flask', test))},"
            f"{'/'.join(str(e) for e in errors('zan_multi', test))}"
        )

    (outdir / "results.md").write_text("\n".join(md) + "\n")
    (outdir / "results.csv").write_text("\n".join(csv_lines) + "\n")
    print(f"Wrote {outdir}/results.md and {outdir}/results.csv")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python report.py <results-dir>")
    main(sys.argv[1])
