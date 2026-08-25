"""Keep-alive benchmark using http.client persistent connections."""
import http.client
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")

from bench_vs_flask import make_flask_app, make_zan_app, run_server


def bench_keepalive(port, path, n=20000, workers=8, method="GET", body=None):
    per = n // workers
    barrier = threading.Barrier(workers + 1)
    errors = []

    def worker():
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        barrier.wait()
        try:
            for _ in range(per):
                try:
                    if method == "GET":
                        conn.request("GET", path)
                    else:
                        conn.request(
                            "POST", path,
                            body=json.dumps(body),
                            headers={"Content-Type": "application/json"},
                        )
                    r = conn.getresponse()
                    r.read()
                except Exception as e:
                    errors.append(str(e))
                    try:
                        conn.close()
                        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                    except Exception:
                        pass
        finally:
            conn.close()

    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(worker) for _ in range(workers)]
        barrier.wait()
        t0 = time.perf_counter()
        for f in futs:
            f.result()
        dt = time.perf_counter() - t0
    if errors:
        print(f"    errors: {errors[:2]} ({len(errors)})")
    return per * workers / dt


def main():
    zan_app = make_zan_app()
    run_server("zan", zan_app, 5103, None)
    flask_app = make_flask_app()
    run_server("flask", flask_app, 5104, None)

    cases = [
        ("plaintext", "/"),
        ("json", "/json"),
        ("param", "/user/42"),
    ]
    print("== keep-alive, 8 connections ==")
    for name, path in cases:
        z = bench_keepalive(5103, path)
        f = bench_keepalive(5104, path, n=8000)
        print(f"  {name:10s} zan {z:9.0f} req/s | flask {f:8.0f} req/s | {z / f:5.1f}x")
    z = bench_keepalive(5103, "/post", n=10000, method="POST", body={"a": 1, "b": [1, 2]})
    f = bench_keepalive(5104, "/post", n=4000, method="POST", body={"a": 1, "b": [1, 2]})
    print(f"  {'post-json':10s} zan {z:9.0f} req/s | flask {f:8.0f} req/s | {z / f:5.1f}x")


if __name__ == "__main__":
    main()
