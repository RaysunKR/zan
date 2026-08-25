"""TFB 对照测试（修正版）：httpx 串行 keep-alive 客户端。

原因：autocannon 20 并发连接下 Windows 的 waitress（asyncore 模型）
退化到 ~8 rps，无法代表 Flask 真实吞吐；改用「单连接串行」消除
连接层实现差异，纯比框架每请求开销。同时报告 zan 的 autocannon
并发数据作为吞吐上限参考。
"""
import json
import os
import subprocess
import sys
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "..", ".venv", "Scripts", "python.exe")

TESTS = [
    ("plaintext", "/plaintext"),
    ("json", "/json"),
    ("db", "/db"),
    ("queries×20", "/queries?queries=20"),
    ("updates×20", "/updates?queries=20"),
    ("fortunes", "/fortunes"),
]

SERVERS = [
    ("zan", os.path.join(HERE, "zan_app.py"), 7071),
    ("flask+waitress", os.path.join(HERE, "flask_app.py"), 7072),
]

# 每端点的串行请求数（重的端点少测些）
NREQ = {"plaintext": 2000, "json": 2000, "db": 500, "queries×20": 300,
        "updates×20": 150, "fortunes": 300}


def wait_ready(base, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(base + "/plaintext", timeout=1)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def bench_serial(base, path, n):
    ok = 0
    t0 = None
    with httpx.Client(timeout=120) as c:
        c.get(base + path)  # 预热
        t0 = time.perf_counter()
        for _ in range(n):
            r = c.get(base + path)
            if r.status_code == 200:
                ok += 1
        dt = time.perf_counter() - t0
    return ok / dt, ok


def main():
    results = {}
    for name, script, port in SERVERS:
        base = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env["TFB_PORT"] = str(port)
        proc = subprocess.Popen([PY, "-u", script], env=env, cwd=HERE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not wait_ready(base):
            print(f"{name}: 启动失败")
            proc.terminate()
            continue
        print(f"== {name} ==")
        for tname, path in TESTS:
            rps, ok = bench_serial(base, path, NREQ[tname])
            results[(name, tname)] = rps
            print(f"  {tname:12s} {rps:9.0f} req/s ({ok}/{NREQ[tname]} ok)")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(1)

    lines = ["| 测试 | zan req/s | Flask+waitress req/s | 加速 |",
             "| --- | ---: | ---: | ---: |"]
    for tname, _ in TESTS:
        z = results.get(("zan", tname), 0)
        f = results.get(("flask+waitress", tname), 0)
        sp = f"{z / f:.1f}x" if f else "-"
        lines.append(f"| {tname} | {z:,.0f} | {f:,.0f} | {sp} |")
    table = "\n".join(lines)
    print()
    print(table)
    with open(os.path.join(HERE, "results.md"), "w", encoding="utf-8") as fh:
        fh.write(HEAD + table + "\n")
    print("已写入 benchmarks/tfb/results.md")


HEAD = """# TechEmpower 风格基准 · 本机结果

方法：TFB 六类标准端点，httpx 单连接串行 keep-alive（消除 Windows 上
waitress 高并发连接退化与 Werkzeug 无 keep-alive 的连接层差异，纯比
框架每请求开销）。zan 另有 autocannon 20 并发数据作吞吐参考。

环境：2 核 Windows / Python 3.13 / SQLite（非官方 PostgreSQL）/
压测客户端同机。绝对值偏低是环境使然，两框架条件完全相同。

"""

if __name__ == "__main__":
    main()
