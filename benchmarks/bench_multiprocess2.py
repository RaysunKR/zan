"""多核基准（httpx keep-alive 客户端 + 多客户端进程，消除客户端瓶颈）。

之前的 urllib 版基准被客户端限制在 ~200 req/s（每请求新建连接 + GIL）。
本脚本用：
- httpx.Client（HTTP keep-alive）
- 多个客户端进程（各自独立 GIL）
确保瓶颈只出现在服务端。
"""
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = r'''
import sys
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

CLIENT = r'''
import sys, time
import httpx
url, n = sys.argv[1], int(sys.argv[2])
ok = 0
with httpx.Client(timeout=120) as c:
    t0 = time.perf_counter()
    for _ in range(n):
        try:
            r = c.get(url)
            if r.status_code == 200:
                ok += 1
        except Exception:
            pass
    dt = time.perf_counter() - t0
print(ok / dt)
'''


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_ready(base, timeout=30):
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(base + "/cpu", timeout=2)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def run_mode(processes, port, script, clients=4, per_client=100):
    env = os.environ.copy()
    env.pop("ZAN_WORKER", None)
    env.pop("ZAN_RUN_MAIN", None)
    proc = subprocess.Popen(
        [sys.executable, "-u", script, str(port), str(processes)],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    if not wait_ready(base):
        proc.terminate()
        return None
    # 先杀可能残留的 httpx 预热连接影响
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CLIENT, base + "/cpu", str(per_client)],
            stdout=subprocess.PIPE, text=True,
        )
        for _ in range(clients)
    ]
    total = 0.0
    t0 = time.time()
    rps_list = []
    for p in procs:
        out, _ = p.communicate(timeout=600)
        rps_list.append(float(out.strip()))
    wall = time.time() - t0
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    # 总吞吐 = 总成功数 / 最长客户端耗时；此处用各客户端 rps 之和近似
    return sum(rps_list), len(rps_list)


def main():
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bench2.tmp.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(SCRIPT.format(root=ROOT))

    results = {}
    for n in (1, 2, 4):
        port = free_port()
        r = run_mode(n, port, script, clients=8)
        if r is None:
            print(f"processes={n}: 启动失败")
            continue
        total, cnt = r
        results[n] = total
        print(f"processes={n}: {total:8.1f} req/s ({cnt} clients)")
        time.sleep(1)

    if 1 in results:
        print()
        for n in results:
            print(f"加速比 processes={n}: {results[n] / results[1]:.2f}x")

    os.unlink(script)


if __name__ == "__main__":
    main()
