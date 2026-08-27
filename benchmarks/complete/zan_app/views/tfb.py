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
