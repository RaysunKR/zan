# zan

**A Flask-compatible Python web framework powered by a Rust HTTP core.**

```python
from zan import Flask, jsonify, request

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello, World!"

@app.route("/user/<int:uid>")
def user(uid):
    return jsonify(uid=uid, name=f"user{uid}")

@app.route("/post", methods=["POST"])
def post():
    return jsonify(echo=request.get_json())

if __name__ == "__main__":
    app.run()   # zan/0.1.0 — Rust HTTP server
```

Replace `from flask import ...` with `from zan import ...` and the rest of your code stays the same.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/zan.svg)](https://pypi.org/project/zan/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Rust 1.75+](https://img.shields.io/badge/rust-1.75%2B-orange.svg)](https://www.rust-lang.org/)

[中文 README](README.zh-CN.md)

## Install

zan provides pre-built wheels for Windows, macOS, and Linux. No Rust toolchain is required:

```bash
pip install zan
```

Optional template support:

```bash
pip install zan[templates]
```

To build from source, see [Building from source](#building-from-source) below.

## Building from source

You need the Rust toolchain (`rustc` 1.75+) and Python 3.8+:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install maturin pytest jinja2
maturin develop --release
pytest tests/ -q
```

## Features

- **Drop-in Flask replacement** — same `Flask`, `request`, `session`, `g`, `current_app`, `jsonify`, `url_for`, `abort`, `Blueprint`, `render_template`, and `send_file` APIs.
- **Rust HTTP core** — multi-threaded Tokio server with keep-alive, chunked transfer, pipelining, `100-continue`, and size/timeouts enforced in Rust.
- **Trie router** — Werkzeug-compatible converters (`<int>`, `<float>`, `<path>`, `<uuid>`, `<any(a,b)>`), strict-slash and merge-slash redirects, automatic `HEAD`/`OPTIONS` handling.
- **Static files served in Rust** — no GIL contention; includes `Last-Modified`/304, MIME inference, and path-traversal protection.
- **Sessions & flashes** — signed cookie sessions (HMAC-SHA256, itsdangerous semantics) and `flash`/`get_flashed_messages`.
- **Signals & hooks** — `before_request`, `after_request`, `teardown_request`, `teardown_appcontext`, context processors, and a full signal implementation.
- **Multiple apps & multi-core** — run several apps in the same process (`start`/`stop`) and scale beyond the GIL with `run(processes=N)` plus a Rust TCP load balancer.

## Installation & Build

You need the Rust toolchain (`rustc` 1.75+) and Python 3.8+:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install maturin pytest jinja2
maturin develop --release
pytest tests/ -q
```

Templates are optional and require `jinja2` (`pip install jinja2`). If `jinja2` is not installed, `render_template*` will raise a clear error.

## Flask Compatibility

API surface already implemented and tested (91 test cases):

| Category | Coverage |
| --- | --- |
| Application | `Flask(import_name)`, `route/add_url_rule`, `run`, `start/stop` (non-blocking multi-instance), `test_client`, `config`, `debug`, `secret_key`, `logger`, `cli`, `extensions`, `name` |
| Routing | `<string>`, `<int>`, `<float>`, `<path>`, `<uuid>`, `<any(a,b)>` converters, `methods`, `endpoint`, strict-slash 308 redirect, merge-slashes redirect, automatic `HEAD`/`OPTIONS`, 405 + `Allow` |
| Request | `request.args/form/values/json/data/get_json/headers/cookies/method/path/url/endpoint/view_args/blueprint/remote_addr/user_agent/authorization`, multipart file uploads |
| Response | `str`/`bytes`/`dict`/`list`/`Response`/`(body, status, headers)` tuples, generators, `make_response`, `jsonify` (sorted keys + `ensure_ascii`), `redirect`, `send_file`, `set_cookie/delete_cookie` |
| Hooks | `before_request`, `after_request`, `teardown_request`, `teardown_appcontext`, `context_processor` |
| Errors | Full `HTTPException` family, `abort`, `errorhandler` (status codes and exception classes), debug traceback page |
| Context | `request`/`session`/`g`/`current_app` proxies, `app_context`/`request_context`/`test_request_context`, `RuntimeError` when accessed outside context |
| Session | Signed-cookie sessions (HMAC-SHA256, itsdangerous semantics), `flash`/`get_flashed_messages` |
| Blueprints | `Blueprint`, `url_prefix`, blueprint-level routes/hooks/error handlers, `bp.endpoint` naming |
| Templates | `render_template`, `render_template_string`, blueprint template folders, `url_for`/`get_flashed_messages` context injection |
| URL building | `url_for` (args, `_anchor`, `_external`, blueprint defaults) |
| Static files | `/static/` served directly from Rust (`Last-Modified`/304, MIME inference, path-traversal protection) |
| Signals | Full signal support (uses `blinker` if available, otherwise a built-in compatible implementation) |
| Multi-instance | Multiple apps can `start()`/`stop()` in the same process, sharing the Rust runtime |
| Multi-core | `run(processes=N)` multi-process + Rust TCP load balancer (round-robin, `X-Forwarded-For`) |

Known differences (intentional or not yet implemented):

- No Werkzeug reloader — in debug mode you must restart manually after code changes (a warning is printed).
- Not WSGI-based — apps run on the built-in Rust server, not `werkzeug.serving` or gunicorn.
- `request.scheme` is always `http` (TLS is on the roadmap).

## Performance

### Local micro-benchmark (Windows, Python 3.13, 8 keep-alive connections, pure Python views)

| Scenario | zan | Flask dev server | Speedup |
| --- | --- | --- | --- |
| Plain text | 3205 req/s | 291 req/s | **11.0x** |
| JSON | 2941 req/s | 423 req/s | **6.9x** |
| Route params | 3077 req/s | 419 req/s | **7.4x** |
| POST JSON | 2375 req/s | 422 req/s | **5.6x** |

### TechEmpower-style benchmark

Six canonical endpoints (`/plaintext`, `/json`, `/db`, `/queries`, `/updates`, `/fortunes`) on an Ubuntu server (8 cores, PostgreSQL 16), strict TechEmpower wrk methodology: 256 connections, 15 s per round, median of 3 rounds. Flask served by gunicorn + gevent. zan uses native Rust handlers for the DB endpoints with no API change to application code.

| Test | zan | flask | zan_multi | zan vs flask |
| --- | ---: | ---: | ---: | ---: |
| plaintext | 65 141 | 40 372 | 98 613 | 1.6x |
| json | 67 144 | 37 966 | 110 427 | 1.8x |
| db | 43 937 | 15 122 | 40 832 | 2.9x |
| queries | 36 587 | 11 377 | 29 150 | 3.2x |
| updates | 16 614 | 4 297 | 13 909 | 3.9x |
| fortunes | 43 108 | 14 270 | 40 519 | 3.0x |

All zan endpoints completed the benchmark with zero socket/read/write/timeout errors. DB-bound numbers are constrained by PostgreSQL single-machine throughput.

Multi-core: `run(processes=N)` breaks through the GIL; CPU-bound views scale almost linearly (2 cores measured at ~1.9x).

To reproduce:

```bash
cd benchmarks/complete
bash deploy.sh        # installs deps, builds zan, starts services
bash benchmark.sh     # runs wrk and writes results/<timestamp>
python3 report.py results/<timestamp>
```

Note that the Flask dev server (Werkzeug) does not enable keep-alive by default; the local micro-benchmark uses the same client and workload for both frameworks.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Your code (written exactly like Flask)               │
├─────────────────────────────────────────────────────┤
│ zan Python layer (app/wrappers/ctx/session/...)     │  ← compatibility: Flask API aligned one-to-one
├──────────────────────── PyO3 ───────────────────────┤
│ zan Rust core (_zan)                                 │
│  • Process-wide shared Tokio runtime                 │
│    (workers = CPU cores, reused across instances)    │
│  • Multi-threaded Tokio HTTP/1.1 server              │
│    (keep-alive, chunked, pipelining, 100-continue,   │
│     timeouts and size limits)                        │
│  • Trie router (Werkzeug converter semantics,        │
│    static-first, strict/merge-slash redirects)       │
│  • Static file serving (fully in Rust, no GIL)       │
│  • Native Rust JSON serialization                    │
│    (output aligned with json.dumps)                  │
│  • TCP load balancer (multi-process mode,            │
│    round-robin + X-Forwarded-For)                    │
│  • Fast error paths: 404/405/413/431 skip Python     │
└─────────────────────────────────────────────────────┘
```

- Each request is parsed by a Tokio worker; after routing it crosses into Python via `spawn_blocking` (releasing the GIL via `allow_threads`), with full app/request context pushed so hooks, signals, and sessions behave like Flask.
- When a view returns `str`/`bytes`/`dict`/`tuple`, serialization happens in Rust; `Response` objects pass through FFI as a `(status, headers, body)` tuple via `_fast()`, with no intermediate `environ`.
- Uncaught exceptions fall back to the Python error chain (`errorhandler` → `HTTPException` → 500); debug mode renders a traceback page.

## Project Structure

```
src/            Rust core
  router.rs     Trie router + converters
  http.rs       Connection/parsing/static files/dispatch
  json.rs       Native JSON serialization
  pyapi.rs      PyO3 Server class (shared runtime/lifecycle/load-balancer entry)
  balancer.rs   Multi-process TCP load balancer
zan/            Python compatibility layer (16 modules)
tests/          91 test cases (compatibility 62 / features 18 / multi-method rules 3 / multi-instance & multi-core 8)
blog/           Full blog example (zan backend + React/shadcn frontend served in one process)
benchmarks/     Benchmarks: keep-alive comparison / multi-core scaling / TechEmpower standard (tfb/)
```

## Documentation

Full documentation is currently available in Chinese under [`docs/`](docs/index.md):

- [Index](docs/index.md) — overview, feature table, quick start
- [Quick start](docs/quickstart.md) — routes, requests, responses, templates, sessions, blueprints, error handling
- [Routing](docs/routing.md) — all converters, methods, strict-slash 308, 405, OPTIONS/HEAD
- [Request object](docs/request.md) — all `request` attributes and methods
- [Response object](docs/response.md) — view return values, `jsonify`, `redirect`, `send_file`, cookies
- [Context & hooks](docs/context.md) — `request/session/g/current_app`, hooks, signals
- [Sessions & flashes](docs/session.md) — signed cookie internals, permanent sessions, `flash`
- [Blueprints](docs/blueprints.md) — registration, `url_prefix`, blueprint hooks/static/template folders
- [Error handling](docs/errors.md) — `HTTPException` family, `abort`, `errorhandler`
- [Debugging](docs/debugging.md) — debug page, reloader, colored output
- [CLI](docs/cli.md) — `python -m zan run/shell/routes`
- [Config reference](docs/config.md) — all configuration keys
- [Multi-instance & multi-core](docs/multi.md) — `start/stop`, `processes=N`, load balancer
- [Architecture](docs/architecture.md) — Rust core, PyO3 boundary, request lifecycle, performance data
- [Testing](docs/testing.md) — `test_client`, `test_request_context`, pytest integration
- [FAQ](docs/faq.md) — differences from Flask, deployment advice, performance tuning

English translations of the docs are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- HTTPS/TLS (rustls) and HTTP/2
- WebSocket support
- More edge-case behavior for `url_for` with `external` and `SERVER_NAME`
- CI matrix for platforms other than Windows and abi3 wheel publishing

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on bug reports, feature requests, and pull requests.

## License

[MIT](LICENSE) © 2026 RaysunKR
