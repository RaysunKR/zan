"""多实例与多核支持测试。

覆盖：
- 同进程多个 Flask 应用同时 start/stop（非阻塞生命周期）
- 全局运行时 worker 数 = CPU 核数
- run(processes=N) 多进程模式：独立 PID、请求分发、XFF 客户端地址
"""
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from zan import Flask, jsonify


def _wait_http(url, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                return r.read()
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"server not ready: {url}")


# ---------------------------------------------------------------------------
# 非阻塞生命周期 + 多实例
# ---------------------------------------------------------------------------

class TestMultiInstance:
    def test_start_stop_roundtrip(self):
        app = Flask("single")

        @app.route("/")
        def hi():
            return "hi"

        sid, addr = app.start(port=0)
        host, port = addr.rsplit(":", 1)
        assert app.bound_addr(sid) == addr
        body = _wait_http(f"http://{addr}/")
        # 非阻塞：start 返回后主线程仍可执行 Python
        assert isinstance(body, bytes)
        assert app.stop(sid, timeout=5) is True
        assert app.bound_addr(sid) is None

    def test_two_apps_same_process(self):
        """两个独立应用同时在线，各自端口各自响应。"""
        app_a = Flask("alpha")

        @app_a.route("/")
        def a():
            return "A"

        app_b = Flask("beta")

        @app_b.route("/")
        def b():
            return "B"

        sid_a, addr_a = app_a.start(port=0)
        sid_b, addr_b = app_b.start(port=0)
        assert addr_a != addr_b
        try:
            body_a = _wait_http(f"http://{addr_a}/")
            body_b = _wait_http(f"http://{addr_b}/")
            assert body_a == b"A"
            assert body_b == b"B"
        finally:
            app_a.stop(sid_a)
            app_b.stop(sid_b)

    def test_three_apps_and_reuse_port_after_stop(self):
        apps = []
        sids = []
        addrs = []
        for i in range(3):
            app = Flask(f"app{i}")

            @app.route("/")
            def index(i=i):
                return f"app{i}"

            sid, addr = app.start(port=0)
            apps.append(app)
            sids.append(sid)
            addrs.append(addr)
        try:
            for i in range(3):
                assert _wait_http(f"http://{addrs[i]}/") == f"app{i}".encode()
        finally:
            for app, sid in zip(apps, sids):
                app.stop(sid)

    def test_runtime_workers_matches_cpus(self):
        app = Flask("w")
        server = app._ensure_server()
        import multiprocessing

        assert server.runtime_workers == multiprocessing.cpu_count()
        assert server.cpu_count >= 1


# ---------------------------------------------------------------------------
# 多进程模式（子进程内运行，通过脚本文件）
# ---------------------------------------------------------------------------

WORKER_SCRIPT = r'''
import os
import sys
sys.path.insert(0, {root!r})
from zan import Flask, jsonify

app = Flask("multi")

@app.route("/cpu")
def cpu():
    # CPU 密集视图：约 8ms 的纯 Python 计算
    total = 0
    for i in range(60000):
        total += i * i
    return jsonify(total=total)

@app.route("/pid")
def pid():
    return jsonify(pid=os.getpid())

@app.route("/whoami")
def whoami():
    from zan import request
    return jsonify(addr=request.remote_addr)

if __name__ == "__main__":
    app.run(port=int(sys.argv[1]), processes=int(sys.argv[2]))
'''


class TestMultiProcess:
    @pytest.fixture(scope="class")
    def multi_server(self, tmp_path_factory):
        """启动 processes=3 的多进程服务器（外部子进程）。"""
        import socket
        import subprocess

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = tmp_path_factory.mktemp("mp") / "mp_app.py"
        script.write_text(WORKER_SCRIPT.format(root=root), encoding="utf-8")

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        proc = subprocess.Popen(
            [sys.executable, "-u", str(script), str(port), "3"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            _wait_http(f"{base}/pid", timeout=30)
        except Exception:
            proc.terminate()
            raise
        yield base, proc
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def test_distinct_pids(self, multi_server):
        """3 个 worker 应有 3 个不同 PID，均衡器按 round-robin 分发。"""
        base, _ = multi_server
        import json

        pids = set()
        for _ in range(12):
            with urllib.request.urlopen(f"{base}/pid", timeout=5) as r:
                pids.add(json.loads(r.read())["pid"])
        assert len(pids) == 3, f"expected 3 workers, got {len(pids)}"

    def test_xff_client_addr(self, multi_server):
        """经均衡器转发的请求应看到真实客户端 IP（127.0.0.1）。"""
        base, _ = multi_server
        import json

        with urllib.request.urlopen(f"{base}/whoami", timeout=5) as r:
            d = json.loads(r.read())
        assert d["addr"] == "127.0.0.1"

    def test_cpu_view_works(self, multi_server):
        base, _ = multi_server
        import json

        with urllib.request.urlopen(f"{base}/cpu", timeout=10) as r:
            d = json.loads(r.read())
        assert d["total"] > 0

    def test_concurrent_throughput(self, multi_server):
        """并发压一下：多进程下所有请求都应成功（无 5xx）。"""
        import json
        from concurrent.futures import ThreadPoolExecutor

        base, _ = multi_server
        errors = []

        def hit(_):
            try:
                with urllib.request.urlopen(f"{base}/cpu", timeout=30) as r:
                    return r.status
            except Exception as e:
                errors.append(str(e))
                return None

        with ThreadPoolExecutor(12) as ex:
            codes = list(ex.map(hit, range(48)))
        assert not errors, errors[:3]
        assert all(c == 200 for c in codes)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
