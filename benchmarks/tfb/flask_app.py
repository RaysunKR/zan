"""TechEmpower 基准端点 —— Flask 对照实现。

与 zan_app.py 完全相同的逻辑与数据集，唯一差别是框架本身
（Flask dev server，threaded）。注意：Werkzeug 开发服务器不支持
keep-alive，这与官方 TFB 中 Flask 用 gunicorn 等生产服务器的跑法
不同——本对照只反映「同一台机器上的开箱即用配置」。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Response, jsonify, request

import db as tfb_db

app = Flask(__name__)

FORTUNE_TMPL = """<!doctype html>
<html><head><title>Fortunes</title></head>
<body><table><tr><th>id</th><th>message</th></tr>
{% for item in items %}<tr><td>{{ item.id }}</td><td>{{ item.message }}</td></tr>{% endfor %}
</table></body></html>"""

import jinja2

_fortune_env = jinja2.Environment(autoescape=True)
_fortune_tmpl = _fortune_env.from_string(FORTUNE_TMPL)


def _clamp_queries() -> int:
    try:
        n = int(request.args.get("queries", 1))
    except (TypeError, ValueError):
        return 1
    return max(1, min(500, n))


@app.route("/plaintext")
def plaintext():
    return Response("Hello, World!", mimetype="text/plain")


@app.route("/json")
def json_test():
    return jsonify(message="Hello, World!")


@app.route("/db")
def db_test():
    conn = tfb_db.get_conn()
    row = tfb_db.get_world(conn, random.randint(1, 10000))
    return jsonify(id=row[0], randomNumber=row[1])


@app.route("/queries")
def queries_test():
    n = _clamp_queries()
    conn = tfb_db.get_conn()
    out = []
    for _ in range(n):
        row = tfb_db.get_world(conn, random.randint(1, 10000))
        out.append({"id": row[0], "randomNumber": row[1]})
    return jsonify(out)


@app.route("/updates")
def updates_test():
    n = _clamp_queries()
    conn = tfb_db.get_conn()
    rows = []
    for _ in range(n):
        row = tfb_db.get_world(conn, random.randint(1, 10000))
        rows.append([random.randint(1, 10000), row[0]])
    tfb_db.update_worlds(conn, rows)
    return jsonify([{"id": rid, "randomNumber": new} for new, rid in rows])


@app.route("/fortunes")
def fortunes_test():
    conn = tfb_db.get_conn()
    items = [
        {"id": r[0], "message": r[1]}
        for r in conn.execute("SELECT id, message FROM fortune").fetchall()
    ]
    items.append({"id": 0, "message": "Additional fortune added at request time."})
    items.sort(key=lambda it: it["message"])
    return Response(_fortune_tmpl.render(items=items), mimetype="text/html")


if __name__ == "__main__":
    port = int(os.environ.get("TFB_PORT", 7072))
    server = os.environ.get("TFB_SERVER", "waitress")
    if server == "waitress":
        # 生产级 WSGI 服务器（支持 keep-alive），与 autocannon 匹配
        from waitress import serve

        serve(app, host="127.0.0.1", port=port, threads=8, channel_timeout=60)
    else:
        app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
