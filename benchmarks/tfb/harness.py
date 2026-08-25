"""TFB 本机压测 harness：autocannon（wrk 的 Node 等价物）× 6 类测试 × 2 框架。

方法：
- 每端点先 3s 预热，再 10s 计时（-c 20 并发连接，无 pipelining）
- 依次测 plaintext / json / db / queries(20) / updates(20) / fortunes
- 输出 req/s、平均延迟、p99 延迟、错误数对比表，并存 results.md

局限（如实声明，与官方 TFB rig 的差异）：
- 本机为 2 核，压测客户端与服务端同机竞争 CPU，绝对值偏低
- 数据库是 SQLite 而非 PostgreSQL/MySQL
- Flask 侧用 Werkzeug dev server（Windows 下无 gunicorn），不支持 keep-alive
- 无官方 rig 的裸机隔离与多轮取中位数
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

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
    ("flask", os.path.join(HERE, "flask_app.py"), 7072),
]


def wait_ready(base, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/plaintext", timeout=1)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def run_autocannon(url, duration, warmup_first=True):
    # Windows: npx 是 .cmd，必须经 shell 解析
    cmd = ["npx", "-y", "autocannon", "-c", "20"]
    if warmup_first:
        subprocess.run(
            [*cmd, "-d", "3", url], capture_output=True, shell=True
        )
    out = subprocess.run(
        [*cmd, "-d", str(duration), "-j", url],
        capture_output=True, text=True, shell=True,
    )
    # JSON 在 stdout（可能混有 npx 输出），取第一个 { 到最后一个 }
    text = out.stdout
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def main():
    results = {}  # (server, test) -> dict
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
        print(f"\n== {name} ==")
        for tname, path in TESTS:
            r = run_autocannon(base + path, duration=10)
            req = r.get("requests", {})
            lat = r.get("latency", {})
            results[(name, tname)] = {
                "rps": req.get("average", 0),
                "p99": lat.get("p99", 0) or lat.get("p99.0", 0),
                "avg_latency": lat.get("average", 0),
                "errors": r.get("errors", 0) + r.get("non2xx", 0),
            }
            print(
                f"  {tname:12s} {results[(name, tname)]['rps']:9.0f} req/s"
                f"  avg {results[(name, tname)]['avg_latency']:7.2f}ms"
                f"  p99 {results[(name, tname)]['p99']:8.2f}ms"
                f"  err {results[(name, tname)]['errors']}"
            )
            time.sleep(1)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(1)

    # 汇总表
    lines = []
    lines.append("\n## 结果对比\n")
    lines.append("| 测试 | zan req/s | Flask req/s | 加速 | zan p99 | Flask p99 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for tname, _ in TESTS:
        z = results.get(("zan", tname), {})
        f = results.get(("flask", tname), {})
        zr, fr = z.get("rps", 0), f.get("rps", 0)
        speed = f"{zr / fr:.1f}x" if fr else "-"
        lines.append(
            f"| {tname} | {zr:,.0f} | {fr:,.0f} | {speed}"
            f" | {z.get('p99', 0):.1f}ms | {f.get('p99', 0):.1f}ms |"
        )
    table = "\n".join(lines)
    print(table)

    with open(os.path.join(HERE, "results.md"), "w", encoding="utf-8") as fh:
        fh.write("# TechEmpower 本机测试结果\n\n" + __doc__ + "\n" + table + "\n")
    print("\n已写入 benchmarks/tfb/results.md")


if __name__ == "__main__":
    main()
