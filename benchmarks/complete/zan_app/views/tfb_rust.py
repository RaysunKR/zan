import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zan import Response, request
from benchmarks.complete.shared.models_rust import get_world, get_worlds, update_worlds, get_fortunes

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
        row = get_world(random.randint(1, 10000))
        return {"id": row[0], "randomNumber": row[1]}

    @app.route("/queries")
    def queries_test():
        n = _clamp_queries()
        ids = [random.randint(1, 10000) for _ in range(n)]
        rows = get_worlds(ids)
        return [{"id": row[0], "randomNumber": row[1]} for row in rows]

    @app.route("/updates")
    def updates_test():
        n = _clamp_queries()
        rows = get_worlds([random.randint(1, 10000) for _ in range(n)])
        updates = [[random.randint(1, 10000), row[0]] for row in rows]
        update_worlds(updates)
        return [{"id": rid, "randomNumber": new} for new, rid in updates]

    @app.route("/fortunes")
    def fortunes_test():
        items = [{"id": r[0], "message": r[1]} for r in get_fortunes()]
        items.append({"id": 0, "message": "Additional fortune added at request time."})
        items.sort(key=lambda it: it["message"])
        return Response(_fortune_tmpl.render(items=items), mimetype="text/html")
