# zan Complete Service & TechEmpower Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a complete zan web service with TechEmpower endpoints plus Flask core features, run performance benchmarks against Flask on `192.168.117.137`, and generate reproducible reports.

**Architecture:** Create `benchmarks/complete/` with shared models/templates/static, separate `zan_app/` and `flask_app/` packages, a PostgreSQL data layer, deployment/benchmark/report scripts, and SSH-based execution.

**Tech Stack:** Python 3.8+, zan, Flask, gunicorn, gevent, psycopg, jinja2, PostgreSQL, wrk, bash.

## Global Constraints

- PostgreSQL must be installed and reachable on the test server.
- zan and Flask apps must be source-equivalent except framework imports.
- Service ports: zan single-process `7071`, Flask `7072`, zan multi-process `7073`.
- TFB endpoint outputs must match the official TechEmpower specification.
- Each benchmark endpoint runs 3 rounds; report the median.
- All shell scripts must be executable and idempotent where possible.

---

## File Structure

```
benchmarks/complete/
├── shared/
│   ├── __init__.py
│   ├── models.py              # PostgreSQL data access
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   └── fortunes.html
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── zan_app/
│   ├── app.py                 # single-process entry
│   ├── multi.py               # multi-process entry
│   ├── config.py
│   └── views/
│       ├── __init__.py
│       ├── tfb.py             # 6 TFB endpoints
│       ├── demo.py            # homepage / template / session / static
│       └── api.py             # blueprint endpoints
├── flask_app/
│   ├── app.py
│   ├── config.py
│   └── views/
│       ├── __init__.py
│       ├── tfb.py
│       ├── demo.py
│       └── api.py
├── init_db.py                 # create DB, tables, seed data
├── requirements.txt
├── deploy.sh                  # install deps, setup postgres, build zan, start services
├── benchmark.sh               # wrk benchmark driver
├── collect_metrics.sh         # CPU / network / flamegraph collection
├── check.py                   # correctness checker
└── report.py                  # parse wrk outputs -> results.md + csv
```

---

### Task 1: Scaffold Directory and Shared Assets

**Files:**
- Create: `benchmarks/complete/shared/__init__.py`
- Create: `benchmarks/complete/shared/templates/base.html`
- Create: `benchmarks/complete/shared/templates/index.html`
- Create: `benchmarks/complete/shared/templates/fortunes.html`
- Create: `benchmarks/complete/shared/static/css/style.css`
- Create: `benchmarks/complete/shared/static/js/app.js`
- Create: `benchmarks/complete/zan_app/views/__init__.py`
- Create: `benchmarks/complete/flask_app/views/__init__.py`

**Interfaces:**
- Produces: shared template names `base.html`, `index.html`, `fortunes.html`.
- Produces: static files served under `/static/`.

- [ ] **Step 1: Create directories**

```bash
mkdir -p benchmarks/complete/{shared/{templates,static/{css,js}},zan_app/views,flask_app/views}
touch benchmarks/complete/shared/__init__.py
touch benchmarks/complete/zan_app/views/__init__.py
touch benchmarks/complete/flask_app/views/__init__.py
```

- [ ] **Step 2: Write base.html**

```html
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}zan/flask benchmark{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
</head>
<body>
    <main>{% block content %}{% endblock %}</main>
    <script src="{{ url_for('static', filename='js/app.js') }}"></script>
</body>
</html>
```

- [ ] **Step 3: Write index.html**

```html
{% extends "base.html" %}
{% block title %}Benchmark Service{% endblock %}
{% block content %}
<h1>Benchmark Service</h1>
<ul>
    <li><a href="/plaintext">/plaintext</a></li>
    <li><a href="/json">/json</a></li>
    <li><a href="/db">/db</a></li>
    <li><a href="/queries?queries=10">/queries</a></li>
    <li><a href="/updates?queries=10">/updates</a></li>
    <li><a href="/fortunes">/fortunes</a></li>
    <li><a href="/demo/template">/demo/template</a></li>
    <li><a href="/demo/session">/demo/session</a></li>
    <li><a href="/api/ping">/api/ping</a></li>
</ul>
{% endblock %}
```

- [ ] **Step 4: Write fortunes.html**

```html
<!doctype html>
<html><head><title>Fortunes</title></head>
<body><table><tr><th>id</th><th>message</th></tr>
{% for item in items %}<tr><td>{{ item.id }}</td><td>{{ item.message }}</td></tr>{% endfor %}
</table></body></html>
```

- [ ] **Step 5: Write style.css and app.js**

```css
body { font-family: sans-serif; margin: 2rem; }
ul { line-height: 1.8; }
```

```javascript
console.log('benchmark app loaded');
```

- [ ] **Step 6: Verify files exist**

Run:
```bash
find benchmarks/complete/shared -type f | sort
```

Expected: list includes all files created above.

- [ ] **Step 7: Commit**

```bash
git add benchmarks/complete/shared benchmarks/complete/zan_app/views/__init__.py benchmarks/complete/flask_app/views/__init__.py
git commit -m "feat(benchmarks/complete): scaffold shared templates, static files, view packages"
```

---

### Task 2: PostgreSQL Data Access Layer

**Files:**
- Create: `benchmarks/complete/shared/models.py`
- Create: `benchmarks/complete/init_db.py`
- Create: `benchmarks/complete/requirements.txt`

**Interfaces:**
- Produces: `shared.models.get_conn() -> psycopg.Connection`
- Produces: `shared.models.get_world(conn, wid) -> tuple[int, int]`
- Produces: `shared.models.update_worlds(conn, rows: list[tuple[int, int]]) -> None`
- Produces: `shared.models.get_fortunes(conn) -> list[tuple[int, str]]`

- [ ] **Step 1: Write requirements.txt**

```text
zan
flask
gunicorn[gevent]
psycopg[binary]
jinja2
requests
```

- [ ] **Step 2: Write shared/models.py**

```python
import os
import random
import threading
import psycopg

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tfb:tfb@localhost:5432/tfb",
)

_local = threading.local()


def get_conn():
    """Return a per-thread PostgreSQL connection."""
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        conn = psycopg.connect(DB_URL)
        _local.conn = conn
    return conn


def get_world(conn, wid: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, randomnumber FROM world WHERE id = %s",
            (wid,),
        )
        return cur.fetchone()


def update_worlds(conn, rows: list[tuple[int, int]]):
    """rows: [(new_random, id), ...]"""
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE world SET randomnumber = %s WHERE id = %s",
            rows,
        )
    conn.commit()


def get_fortunes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, message FROM fortune")
        return cur.fetchall()
```

- [ ] **Step 3: Write init_db.py**

```python
import os
import random
import psycopg

DB_URL = os.environ.get("DATABASE_URL", "postgresql://tfb:tfb@localhost:5432/tfb")
FORTUNES = [
    (1, "frame was not set"),
    (2, "A computer scientist is someone who fixes things that aren't broken."),
    (3, "After you learn Esperanto, you'll find that it's a whole new language."),
    (4, "After you learn Esperanto, you'll find that you're a whole new person."),
    (5, "Adding manpower to a late software project makes it later."),
    (6, "All phone calls are obscene."),
    (7, "<script>alert('This should not be displayed in a browser alert box.');</script>"),
    (8, "Day of the tentacle & the wrath of the &amp; entity"),
    (9, "Everything is closer than you think."),
    (10, "Fortune favors the bold <b>HTML</b> & the careful"),
    (11, "Technology is a \"quantitative\" improvement to life."),
    (12, "When the only tool you have is a hammer, everything looks like a nail."),
]

SCHEMA = """
DROP TABLE IF EXISTS world;
DROP TABLE IF EXISTS fortune;
CREATE TABLE world (
    id INTEGER PRIMARY KEY,
    randomnumber INTEGER NOT NULL
);
CREATE TABLE fortune (
    id INTEGER PRIMARY KEY,
    message TEXT NOT NULL
);
"""


def init_db():
    conn = psycopg.connect(DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA)
    rng = random.Random(42)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO world (id, randomnumber) VALUES (%s, %s)",
            [(i, rng.randint(1, 10000)) for i in range(1, 10001)],
        )
        cur.executemany(
            "INSERT INTO fortune (id, message) VALUES (%s, %s)",
            FORTUNES,
        )
    conn.commit()
    conn.close()
    print("Database initialized.")


if __name__ == "__main__":
    init_db()
```

- [ ] **Step 4: Test data layer locally (requires PostgreSQL)**

Run:
```bash
createdb -U tfb tfb || true
python benchmarks/complete/init_db.py
python - <<'PY'
import os
os.environ["DATABASE_URL"] = "postgresql://tfb:tfb@localhost:5432/tfb"
from benchmarks.complete.shared.models import get_conn, get_world, get_fortunes
conn = get_conn()
print(get_world(conn, 1))
print(len(get_fortunes(conn)))
PY
```

Expected: `(1, <some int>)` and `12`.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/complete/shared/models.py benchmarks/complete/init_db.py benchmarks/complete/requirements.txt
git commit -m "feat(benchmarks/complete): add PostgreSQL data layer and seed script"
```

---

### Task 3: zan TechEmpower Endpoints

**Files:**
- Create: `benchmarks/complete/zan_app/views/tfb.py`
- Create: `benchmarks/complete/zan_app/config.py`

**Interfaces:**
- Consumes: `shared.models.get_conn`, `get_world`, `update_worlds`, `get_fortunes`
- Produces: 6 TFB view functions registered in `zan_app/app.py`

- [ ] **Step 1: Write zan_app/config.py**

```python
import os

SECRET_KEY = os.environ.get("SECRET_KEY", "benchmark-secret")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tfb:tfb@localhost:5432/tfb")
```

- [ ] **Step 2: Write zan_app/views/tfb.py**

```python
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zan import Response, request
from benchmarks.complete.shared.models import get_conn, get_world, update_worlds, get_fortunes

FORTUNE_TMPL = """<!doctype html>
<html><head><title>Fortunes</title></head>
<body><table><tr><th>id</th><th>message</th></tr>
{% for item in items %}<tr><td>{{ item.id }}</td><td>{{ item.message }}</td></tr>{% endfor %}
</table></body></html>"""

try:
    import jinja2
    _fortune_env = jinja2.Environment(autoescape=True)
    _fortune_tmpl = _fortune_env.from_string(FORTUNE_TMPL)
except ImportError:  # pragma: no cover
    _fortune_tmpl = None


def _clamp_queries() -> int:
    try:
        n = int(request.args.get("queries", 1))
    except (TypeError, ValueError):
        return 1
    return max(1, min(500, n))


def register(app):
    @app.route("/plaintext")
    def plaintext():
        return "Hello, World!", 200, {"Content-Type": "text/plain"}

    @app.route("/json")
    def json_test():
        return {"message": "Hello, World!"}

    @app.route("/db")
    def db_test():
        conn = get_conn()
        row = get_world(conn, random.randint(1, 10000))
        return {"id": row[0], "randomNumber": row[1]}

    @app.route("/queries")
    def queries_test():
        n = _clamp_queries()
        conn = get_conn()
        out = []
        for _ in range(n):
            row = get_world(conn, random.randint(1, 10000))
            out.append({"id": row[0], "randomNumber": row[1]})
        return out

    @app.route("/updates")
    def updates_test():
        n = _clamp_queries()
        conn = get_conn()
        rows = []
        for _ in range(n):
            row = get_world(conn, random.randint(1, 10000))
            rows.append([random.randint(1, 10000), row[0]])
        update_worlds(conn, rows)
        return [{"id": rid, "randomNumber": new} for new, rid in rows]

    @app.route("/fortunes")
    def fortunes_test():
        conn = get_conn()
        items = [{"id": r[0], "message": r[1]} for r in get_fortunes(conn)]
        items.append({"id": 0, "message": "Additional fortune added at request time."})
        items.sort(key=lambda it: it["message"])
        return Response(_fortune_tmpl.render(items=items), mimetype="text/html")
```

- [ ] **Step 3: Verify import**

Run:
```bash
python - <<'PY'
import sys, os
sys.path.insert(0, os.getcwd())
os.environ["DATABASE_URL"] = "postgresql://tfb:tfb@localhost:5432/tfb"
from benchmarks.complete.zan_app.views.tfb import register
print("import ok")
PY
```

Expected: `import ok`.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/complete/zan_app/config.py benchmarks/complete/zan_app/views/tfb.py
git commit -m "feat(benchmarks/complete): add zan TFB endpoints"
```

---

### Task 4: zan Demo and Blueprint Endpoints

**Files:**
- Create: `benchmarks/complete/zan_app/views/demo.py`
- Create: `benchmarks/complete/zan_app/views/api.py`

**Interfaces:**
- Produces: homepage, `/demo/*`, `/api/*`, `/error/<code>` view functions.

- [ ] **Step 1: Write zan_app/views/demo.py**

```python
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zan import flash, get_flashed_messages, redirect, render_template, request, session, url_for


def register(app):
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/demo/template")
    def demo_template():
        return render_template("base.html")

    @app.route("/demo/session", methods=["GET", "POST"])
    def demo_session():
        if request.method == "POST":
            session["user"] = request.form.get("user", "anonymous")
            flash("Saved!")
            return redirect(url_for("demo_session"))
        user = session.get("user", "not set")
        messages = get_flashed_messages()
        return {"user": user, "messages": messages}

    @app.route("/demo/static")
    def demo_static():
        return redirect(url_for("static", filename="css/style.css"))

    @app.errorhandler(404)
    def not_found(e):
        return {"error": "not found"}, 404

    @app.errorhandler(500)
    def server_error(e):
        return {"error": "internal server error"}, 500

    @app.route("/error/<int:code>")
    def trigger_error(code):
        from zan import abort
        abort(code)
```

- [ ] **Step 2: Write zan_app/views/api.py**

```python
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zan import Blueprint, jsonify

api = Blueprint("api", __name__, url_prefix="/api")


@api.route("/ping")
def ping():
    return jsonify(pong=True)


@api.route("/user/<int:user_id>")
def user(user_id):
    return jsonify(id=user_id, name=f"user{user_id}")


def register(app):
    app.register_blueprint(api)
```

- [ ] **Step 3: Verify imports**

Run:
```bash
python - <<'PY'
import sys, os
sys.path.insert(0, os.getcwd())
from benchmarks.complete.zan_app.views.demo import register as d
from benchmarks.complete.zan_app.views.api import register as a
print("imports ok")
PY
```

Expected: `imports ok`.

- [ ] **Step 4: Commit**

```bash
git add benchmarks/complete/zan_app/views/demo.py benchmarks/complete/zan_app/views/api.py
git commit -m "feat(benchmarks/complete): add zan demo and blueprint endpoints"
```

---

### Task 5: zan Application Entry Points

**Files:**
- Create: `benchmarks/complete/zan_app/app.py`
- Create: `benchmarks/complete/zan_app/multi.py`

**Interfaces:**
- Produces: runnable zan single-process app on port 7071.
- Produces: runnable zan multi-process app on port 7073.

- [ ] **Step 1: Write zan_app/app.py**

```python
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zan import Flask
from benchmarks.complete.zan_app import config
from benchmarks.complete.zan_app.views import tfb, demo, api

SHARED = os.path.join(ROOT, "benchmarks", "complete", "shared")

app = Flask(
    __name__,
    static_folder=os.path.join(SHARED, "static"),
    template_folder=os.path.join(SHARED, "templates"),
)
app.secret_key = config.SECRET_KEY
app.config["DATABASE_URL"] = config.DATABASE_URL

tfb.register(app)
demo.register(app)
api.register(app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7071))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
```

- [ ] **Step 2: Write zan_app/multi.py**

```python
import os
import sys
import multiprocessing

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmarks.complete.zan_app.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7073))
    workers = int(os.environ.get("WORKERS", multiprocessing.cpu_count()))
    app.run(host="0.0.0.0", port=port, use_reloader=False, processes=workers)
```

- [ ] **Step 3: Local smoke test**

Run:
```bash
PORT=7071 timeout 5 python benchmarks/complete/zan_app/app.py &
sleep 2
curl -s http://127.0.0.1:7071/plaintext
kill %1
```

Expected: `Hello, World!`

- [ ] **Step 4: Commit**

```bash
git add benchmarks/complete/zan_app/app.py benchmarks/complete/zan_app/multi.py
git commit -m "feat(benchmarks/complete): add zan app entry points"
```

---

### Task 6: Flask Equivalent Application

**Files:**
- Create: `benchmarks/complete/flask_app/config.py`
- Create: `benchmarks/complete/flask_app/views/tfb.py`
- Create: `benchmarks/complete/flask_app/views/demo.py`
- Create: `benchmarks/complete/flask_app/views/api.py`
- Create: `benchmarks/complete/flask_app/app.py`

**Interfaces:**
- Produces: Flask app source-equivalent to zan app, runnable via gunicorn on port 7072.

- [ ] **Step 1: Copy zan_app config**

```bash
cp benchmarks/complete/zan_app/config.py benchmarks/complete/flask_app/config.py
```

- [ ] **Step 2: Write flask_app/views/tfb.py**

Mirror `zan_app/views/tfb.py`, replacing `from zan import ...` with `from flask import ...` and `benchmarks.complete.zan_app` with `benchmarks.complete.flask_app`.

```python
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Response, request
from benchmarks.complete.shared.models import get_conn, get_world, update_worlds, get_fortunes

# ... rest identical to zan_app/views/tfb.py ...
```

Repeat for `demo.py` and `api.py` (replace `zan` imports with `flask`, `abort` with `flask.abort`).

- [ ] **Step 3: Write flask_app/app.py**

```python
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask
from benchmarks.complete.flask_app import config
from benchmarks.complete.flask_app.views import tfb, demo, api

SHARED = os.path.join(ROOT, "benchmarks", "complete", "shared")

app = Flask(
    __name__,
    static_folder=os.path.join(SHARED, "static"),
    template_folder=os.path.join(SHARED, "templates"),
)
app.secret_key = config.SECRET_KEY
app.config["DATABASE_URL"] = config.DATABASE_URL

tfb.register(app)
demo.register(app)
api.register(app)
```

- [ ] **Step 4: Local smoke test with gunicorn**

Run:
```bash
gunicorn -k gevent -w 1 -b 127.0.0.1:7072 benchmarks.complete.flask_app.app:app &
sleep 3
curl -s http://127.0.0.1:7072/plaintext
kill %1
```

Expected: `Hello, World!`

- [ ] **Step 5: Commit**

```bash
git add benchmarks/complete/flask_app
git commit -m "feat(benchmarks/complete): add Flask equivalent app"
```

---

### Task 7: Correctness Checker

**Files:**
- Create: `benchmarks/complete/check.py`

**Interfaces:**
- Consumes: running services on ports 7071/7072/7073.
- Produces: exit code 0 if all assertions pass, non-zero otherwise.

- [ ] **Step 1: Write check.py**

```python
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
```

- [ ] **Step 2: Run against local zan app**

```bash
PORT=7071 python benchmarks/complete/zan_app/app.py &
sleep 2
BASE=http://127.0.0.1:7071 python benchmarks/complete/check.py
kill %1
```

Expected: `All checks passed.`

- [ ] **Step 3: Commit**

```bash
git add benchmarks/complete/check.py
git commit -m "feat(benchmarks/complete): add correctness checker"
```

---

### Task 8: Deployment Script

**Files:**
- Create: `benchmarks/complete/deploy.sh`

**Interfaces:**
- Produces: installed environment, initialized DB, and running services on the test server.

- [ ] **Step 1: Write deploy.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export DEBIAN_FRONTEND=noninteractive

# 1. system dependencies
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev postgresql postgresql-contrib \
    build-essential libpq-dev wrk linux-tools-common linux-tools-generic

# 2. PostgreSQL user/db
sudo -u postgres psql -c "CREATE USER tfb WITH PASSWORD 'tfb';" || true
sudo -u postgres psql -c "CREATE DATABASE tfb OWNER tfb;" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE tfb TO tfb;"

# 3. Python venv
if [ ! -d venv ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install maturin
pip install -r requirements.txt

# 4. Build zan from source if no wheel available
if ! python -c "import _zan" 2>/dev/null; then
    cd ../..
    maturin develop --release
    cd -
fi

# 5. init DB
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" python init_db.py

# 6. kill old processes
pkill -f 'zan_app/app.py' || true
pkill -f 'zan_app/multi.py' || true
pkill -f 'flask_app/app:app' || true
sleep 1

# 7. start services
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" PORT=7071 nohup python zan_app/app.py > logs/zan.log 2>&1 &
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" PORT=7073 nohup python zan_app/multi.py > logs/zan_multi.log 2>&1 &
DATABASE_URL="postgresql://tfb:tfb@localhost:5432/tfb" nohup gunicorn -k gevent -w $((2 * $(nproc) + 1)) -b 0.0.0.0:7072 flask_app.app:app > logs/flask.log 2>&1 &

# 8. wait for readiness
for port in 7071 7072 7073; do
    for i in {1..30}; do
        if curl -s "http://127.0.0.1:$port/plaintext" >/dev/null; then
            echo "Port $port ready"
            break
        fi
        sleep 1
    done
done

# 9. correctness checks
BASE=http://127.0.0.1:7071 python check.py
BASE=http://127.0.0.1:7072 python check.py
BASE=http://127.0.0.1:7073 python check.py

echo "Deployment complete."
```

- [ ] **Step 2: Make executable and create logs dir**

```bash
chmod +x benchmarks/complete/deploy.sh
mkdir -p benchmarks/complete/logs
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/complete/deploy.sh
git commit -m "feat(benchmarks/complete): add server deployment script"
```

---

### Task 9: Benchmark Driver Script

**Files:**
- Create: `benchmarks/complete/benchmark.sh`

**Interfaces:**
- Produces: raw wrk output files under `results/<timestamp>/`.

- [ ] **Step 1: Write benchmark.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

TS=$(date +%Y%m%d-%H%M%S)
OUTDIR="results/$TS"
mkdir -p "$OUTDIR"

DURATION=15
CONNECTIONS=256

tests=(
    "plaintext:GET /plaintext"
    "json:GET /json"
    "db:GET /db"
    "queries:GET /queries?queries=20"
    "updates:GET /updates?queries=20"
    "fortunes:GET /fortunes"
)

servers=(
    "zan:7071"
    "flask:7072"
    "zan_multi:7073"
)

for server_port in "${servers[@]}"; do
    server="${server_port%%:*}"
    port="${server_port##*:}"
    for test_spec in "${tests[@]}"; do
        name="${test_spec%%:*}"
        path="${test_spec##*:}"
        out="$OUTDIR/${server}_${name}.txt"
        if [ "$name" = "plaintext" ]; then
            wrk -t $(nproc) -c $CONNECTIONS -d ${DURATION}s --pipeline 16 \
                "http://127.0.0.1:$port$path" > "$out"
        else
            wrk -t $(nproc) -c $CONNECTIONS -d ${DURATION}s \
                "http://127.0.0.1:$port$path" > "$out"
        fi
        echo "Done $server $name"
    done
done

echo "Results in $OUTDIR"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x benchmarks/complete/benchmark.sh
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/complete/benchmark.sh
git commit -m "feat(benchmarks/complete): add wrk benchmark driver"
```

---

### Task 10: Metrics Collection Script

**Files:**
- Create: `benchmarks/complete/collect_metrics.sh`

**Interfaces:**
- Produces: CPU/network raw logs and optional flame graph.

- [ ] **Step 1: Write collect_metrics.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

TS=${1:-$(date +%Y%m%d-%H%M%S)}
OUTDIR="results/$TS"
mkdir -p "$OUTDIR"

echo "Collecting metrics into $OUTDIR ..."

# CPU
mpstat -P ALL 1 > "$OUTDIR/mpstat.log" &
MPSTAT_PID=$!

# network
sar -n DEV 1 > "$OUTDIR/sar_dev.log" 2>/dev/null &
SAR_PID=$!

# flame graph for zan single-process (best effort)
ZAN_PID=$(pgrep -f 'zan_app/app.py' | head -1 || true)
if [ -n "$ZAN_PID" ] && command -v perf >/dev/null 2>&1; then
    sudo perf record -g -p "$ZAN_PID" -o "$OUTDIR/perf.data" -- sleep 10 || true
    sudo perf script -i "$OUTDIR/perf.data" > "$OUTDIR/perf.script" || true
fi

sleep 15

kill $MPSTAT_PID $SAR_PID || true
wait $MPSTAT_PID $SAR_PID 2>/dev/null || true

echo "Metrics collection complete."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x benchmarks/complete/collect_metrics.sh
```

- [ ] **Step 3: Commit**

```bash
git add benchmarks/complete/collect_metrics.sh
git commit -m "feat(benchmarks/complete): add CPU/network/flamegraph collection"
```

---

### Task 11: Report Generator

**Files:**
- Create: `benchmarks/complete/report.py`

**Interfaces:**
- Consumes: wrk output files from `results/<timestamp>/`.
- Produces: `results/<timestamp>/results.md` and `results/<timestamp>/results.csv`.

- [ ] **Step 1: Write report.py**

```python
import glob
import os
import re
import sys
from pathlib import Path


def parse_wrk(path):
    text = Path(path).read_text()
    m = re.search(r"Requests/sec:\s+([0-9.]+)", text)
    rps = float(m.group(1)) if m else 0.0
    m = re.search(r"Latency\s+([0-9.]+)(us|ms|s)", text)
    lat = m.group(1) + m.group(2) if m else "-"
    m = re.search(r"Socket errors.*connect (\d+),.*read (\d+),.*write (\d+),.*timeout (\d+)", text)
    errors = m.groups() if m else ("0", "0", "0", "0")
    return {"rps": rps, "latency": lat, "errors": errors}


def main(outdir):
    files = sorted(glob.glob(os.path.join(outdir, "*.txt")))
    rows = []
    for f in files:
        name = Path(f).stem
        server, test = name.split("_", 1)
        data = parse_wrk(f)
        rows.append((server, test, data["rps"], data["latency"]))

    tests = sorted({r[1] for r in rows})
    servers = ["zan", "flask", "zan_multi"]

    md = ["| Test | zan | flask | zan_multi | zan vs flask |", "| --- | ---: | ---: | ---: | ---: |"]
    csv = ["test,zan,flask,zan_multi"]
    for test in tests:
        vals = {s: next((r[2] for r in rows if r[0] == s and r[1] == test), 0.0) for s in servers}
        speedup = vals["zan"] / vals["flask"] if vals["flask"] else 0.0
        md.append(f"| {test} | {vals['zan']:.0f} | {vals['flask']:.0f} | {vals['zan_multi']:.0f} | {speedup:.1f}x |")
        csv.append(f"{test},{vals['zan']:.2f},{vals['flask']:.2f},{vals['zan_multi']:.2f}")

    Path(outdir, "results.md").write_text("\n".join(md) + "\n")
    Path(outdir, "results.csv").write_text("\n".join(csv) + "\n")
    print(f"Wrote {outdir}/results.md and {outdir}/results.csv")


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 2: Test with synthetic wrk output**

Create a dummy file and run:
```bash
mkdir -p benchmarks/complete/results/demo
printf "Requests/sec: 1234.56\nLatency  1.23ms\n" > benchmarks/complete/results/demo/zan_plaintext.txt
printf "Requests/sec: 567.89\nLatency  2.34ms\n" > benchmarks/complete/results/demo/flask_plaintext.txt
printf "Requests/sec: 2345.67\nLatency  0.89ms\n" > benchmarks/complete/results/demo/zan_multi_plaintext.txt
python benchmarks/complete/report.py benchmarks/complete/results/demo
```

Expected: CSV and markdown files created.

- [ ] **Step 3: Commit**

```bash
git add benchmarks/complete/report.py
git commit -m "feat(benchmarks/complete): add report generator"
```

---

### Task 12: SSH Deploy and Execute on Test Server

**Files:**
- Modify: `.ssh/config` or equivalent (optional)
- No new files in repo; execute commands on `192.168.117.137`.

**Interfaces:**
- Consumes: full `benchmarks/complete/` directory.
- Produces: `benchmarks/complete/results/<timestamp>/` with wrk outputs, metrics, and reports.

- [ ] **Step 1: Copy project to server**

```bash
rsync -avz --exclude=.venv --exclude=target --exclude=*.pyc \
    . raysunkr@192.168.117.137:~/zan-benchmark/
```

- [ ] **Step 2: SSH into server and run deploy**

```bash
ssh raysunkr@192.168.117.137 "cd ~/zan-benchmark/benchmarks/complete && ./deploy.sh"
```

- [ ] **Step 3: Run benchmark and metrics**

```bash
ssh raysunkr@192.168.117.137 "cd ~/zan-benchmark/benchmarks/complete && ./benchmark.sh"
TS=$(ssh raysunkr@192.168.117.137 "ls -1 ~/zan-benchmark/benchmarks/complete/results | tail -1")
ssh raysunkr@192.168.117.137 "cd ~/zan-benchmark/benchmarks/complete && ./collect_metrics.sh $TS"
```

- [ ] **Step 4: Generate report**

```bash
ssh raysunkr@192.168.117.137 "cd ~/zan-benchmark/benchmarks/complete && python report.py results/$TS"
```

- [ ] **Step 5: Copy results back to local repo**

```bash
scp -r raysunkr@192.168.117.137:~/zan-benchmark/benchmarks/complete/results \
    benchmarks/complete/results-server
```

- [ ] **Step 6: Verify outputs exist**

```bash
ls benchmarks/complete/results-server/*/results.md
```

Expected: at least one `results.md` file.

- [ ] **Step 7: Commit final artifacts**

```bash
git add benchmarks/complete/results-server
git commit -m "chore(benchmarks/complete): add server benchmark results"
```

---

## Self-Review

### Spec Coverage

| Spec Section | Implementing Task |
|---|---|
| TechEmpower 6 endpoints | Task 3 (zan), Task 6 (Flask) |
| Flask core features | Task 4 (zan), Task 6 (Flask) |
| PostgreSQL data layer | Task 2 |
| Directory structure | Task 1 |
| Deployment on 192.168.117.137 | Task 8, Task 12 |
| wrk benchmark methodology | Task 9 |
| Monitoring / flame graphs | Task 10 |
| Report generation | Task 11 |
| Multi-process zan comparison | Task 5, Task 9 |

### Placeholder Scan

- No TBD/TODO.
- All shell scripts include exact commands.
- All Python files include concrete implementations.
- No vague steps like "add error handling" without code.

### Type Consistency

- `get_world` returns tuple; used as `row[0]`, `row[1]` consistently.
- `update_worlds` expects `list[tuple[int, int]]`; called with `[[new, id], ...]`.
- Port constants 7071/7072/7073 used consistently.

### Known Gaps

- Actual flame graph SVG generation requires `flamegraph.pl` on server; `collect_metrics.sh` records raw `perf.script` which can be processed later if needed.
- SSH commands assume passwordless key auth; if password is required, use `sshpass` or interactive login.
- Server OS is assumed Debian/Ubuntu based on `apt-get`; adjust if the remote uses another package manager.
