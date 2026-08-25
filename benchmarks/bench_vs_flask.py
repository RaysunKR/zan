"""Benchmark: zan vs Flask (dev server) vs zan fast-path internals.

Runs each server on 127.0.0.1, hammers it with concurrent HTTP requests from
a thread pool (urllib, keep-alive not available in urllib so this measures
connection setup too), reports req/s.
"""
import json
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")


def make_zan_app():
    from zan import Flask, jsonify, request

    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Hello, World!"

    @app.route("/json")
    def json_view():
        return jsonify(hello="world", n=42, list=[1, 2, 3])

    @app.route("/user/<int:uid>")
    def user(uid):
        return jsonify(uid=uid, name=f"user{uid}")

    @app.route("/post", methods=["POST"])
    def post():
        return jsonify(got=request.get_json(silent=True))

    return app


def make_flask_app():
    from flask import Flask, jsonify, request

    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Hello, World!"

    @app.route("/json")
    def json_view():
        return jsonify(hello="world", n=42, list=[1, 2, 3])

    @app.route("/user/<int:uid>")
    def user(uid):
        return jsonify(uid=uid, name=f"user{uid}")

    @app.route("/post", methods=["POST"])
    def post():
        return jsonify(got=request.get_json(silent=True))

    return app


def bench(port, path, n=5000, workers=16, method="GET", body=None):
    url = f"http://127.0.0.1:{port}{path}"
    barrier = threading.Barrier(workers + 1)
    per = n // workers
    errors = []

    def worker():
        barrier.wait()
        for _ in range(per):
            try:
                if method == "GET":
                    req = urllib.request.Request(url)
                else:
                    data = json.dumps(body).encode()
                    req = urllib.request.Request(
                        url, data=data, headers={"Content-Type": "application/json"}
                    )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    resp.read()
            except Exception as e:
                errors.append(str(e))

    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(worker) for _ in range(workers)]
        barrier.wait()
        t0 = time.perf_counter()
        for f in futs:
            f.result()
        dt = time.perf_counter() - t0
    if errors:
        print(f"    errors: {errors[:3]} ({len(errors)} total)")
    return per * workers / dt


def run_server(name, app, port, target):
    if name == "zan":
        t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port), daemon=True)
    else:
        t = threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, threaded=True),
            daemon=True,
        )
    t.start()
    # wait for readiness
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"{name} server did not start")


def main():
    results = {}

    zan_app = make_zan_app()
    run_server("zan", zan_app, 5101, None)
    print("== zan ==")
    results["zan"] = {
        "plaintext": bench(5101, "/", n=5000),
        "json": bench(5101, "/json", n=5000),
        "param": bench(5101, "/user/42", n=5000),
        "post-json": bench(5101, "/post", n=3000, method="POST", body={"a": 1, "b": [1, 2]}),
    }
    for k, v in results["zan"].items():
        print(f"  {k:12s} {v:10.0f} req/s")

    flask_app = make_flask_app()
    run_server("flask", flask_app, 5102, None)
    print("== flask (dev server) ==")
    results["flask"] = {
        "plaintext": bench(5102, "/", n=2000),
        "json": bench(5102, "/json", n=2000),
        "param": bench(5102, "/user/42", n=2000),
        "post-json": bench(5102, "/post", n=1000, method="POST", body={"a": 1, "b": [1, 2]}),
    }
    for k, v in results["flask"].items():
        print(f"  {k:12s} {v:10.0f} req/s")

    print()
    print("== speedup (zan / flask) ==")
    for k in results["zan"]:
        f = results["flask"][k]
        z = results["zan"][k]
        print(f"  {k:12s} {z / f:6.1f}x")


if __name__ == "__main__":
    main()
