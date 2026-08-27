import os
import sys

import requests

BASE = os.environ.get("BASE", "http://127.0.0.1:7071")


def check(path, expected_status=200, content_type=None, contains=None):
    r = requests.get(BASE + path, timeout=10)
    assert r.status_code == expected_status, f"{path}: {r.status_code}"
    if content_type:
        assert content_type in r.headers.get("Content-Type", ""), r.headers
    if contains:
        assert contains in r.text, f"{path}: missing {contains}"
    print(f"OK {path}")


def main():
    check("/plaintext", content_type="text/plain", contains="Hello, World!")
    check("/json", content_type="json", contains='"message"')
    check("/db", content_type="json", contains='"randomNumber"')
    check("/queries?queries=20", content_type="json")
    check("/updates?queries=20", content_type="json")
    check("/fortunes", content_type="html", contains="Additional fortune")
    check("/", content_type="html", contains="Benchmark Service")
    check("/demo/session", content_type="json", contains="not set")
    check("/api/ping", content_type="json", contains="pong")
    check("/api/user/42", content_type="json", contains="user42")
    check("/error/404", expected_status=404)
    print("All checks passed.")


if __name__ == "__main__":
    main()
