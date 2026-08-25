"""多核基准：单进程 vs processes=N（CPU 密集型视图）。

视图做纯 Python 计算（~10ms/次），单进程时 GIL 限制吞吐约等于
1/latency；processes=N 应近似线性扩展（直至 CPU 饱和）。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = r'''
import sys, os
sys.path.insert(0, {root!r})
from zan import Flask, jsonify

app = Flask("bench")

@app.route("/cpu")
def cpu():
    total = 0
    for i in range(60000):   # ~8ms 纯 Python 计算
        total += i * i
    return jsonify(total=total)

if __name__ == "__main__":
    app.run(port=int(sys.argv[1]), processes=int(sys.argv[2]))
'''


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_ready(base, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/cpu", timeout=2)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def bench(base, n=200, workers=8):
    per = n // workers

    def hit(_):
        ok = 0
        for _ in range(per):
            try:
                with urllib.request.urlopen(base + "/cpu", timeout=60) as r:
                    r.read()
                    ok += 1
            except Exception:
                pass
        return ok

    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        ok = sum(ex.map(hit, [per] * workers))
    dt = time.perf_counter() - t0
    return ok / dt, ok


def run_mode(processes, port, script):
    env = os.environ.copy()
    env.pop("ZAN_WORKER", None)
    env.pop("ZAN_RUN_MAIN", None)
    proc = subprocess.Popen(
        [sys.executable, "-u", script, str(port), str(processes)],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    ok = wait_ready(base)
    if not ok:
        proc.terminate()
        return None, proc
    return base, proc


def main():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bench_app.tmp.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(SCRIPT.format(root=ROOT))

    ncpu = os.cpu_count() or 4
    modes = [1, 2, 4] if ncpu >= 4 else [1, 2]
    results = {}
    for n in modes:
        port = free_port()
        base, proc = run_mode(n, port, script)
        if base is None:
            print(f"processes={n}: 启动失败")
            continue
        try:
            rps, ok = bench(base)
            results[n] = rps
            print(f"processes={n}: {rps:8.1f} req/s ({ok} ok)")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            time.sleep(1)

    if 1 in results:
        print()
        for n in modes:
            if n in results:
                print(f"加速比 processes={n}: {results[n] / results[1]:.2f}x")

    os.unlink(script)


if __name__ == "__main__":
    main()
