"""TechEmpower 基准测试端点 —— zan 实现。

六个标准测试（按 TFB 规范）：

- GET /plaintext               → "Hello, World!"（text/plain）
- GET /json                    → {"message": "Hello, World!"}
- GET /db                      → 单行随机 world 查询
- GET /queries?queries=N       → N 行随机查询（默认 1，夹逼 1..500）
- GET /updates?queries=N       → N 行查询并更新 randomnumber
- GET /fortunes                → fortune 表 + 请求时追加项，模板渲染并转义

性能路径说明：plaintext/json/db/queries/updates 的返回值走 Rust 原生
序列化（str / dict / list，不构造 Python Response 对象）；fortunes 按
规范必须走服务端模板（jinja2，autoescape 开启）。
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from zan import Flask, Response, request

import db as tfb_db

app = Flask(__name__, static_folder=None, template_folder=None)

FORTUNE_TMPL = """<!doctype html>
<html><head><title>Fortunes</title></head>
<body><table><tr><th>id</th><th>message</th></tr>
{% for item in items %}<tr><td>{{ item.id }}</td><td>{{ item.message }}</td></tr>{% endfor %}
</table></body></html>"""

# fortunes 按规范必须用服务端模板渲染；显式开启 autoescape 以转义
# fortune 文本中的 < > & ' 等字符
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
    # 元组 + 显式头：str 部分由 Rust 原生处理，无 Python Response 构造
    return "Hello, World!", 200, {"Content-Type": "text/plain"}


@app.route("/json")
def json_test():
    return {"message": "Hello, World!"}


@app.route("/db")
def db_test():
    conn = tfb_db.get_conn()
    wid = random.randint(1, 10000)
    row = tfb_db.get_world(conn, wid)
    return {"id": row[0], "randomNumber": row[1]}


@app.route("/queries")
def queries_test():
    n = _clamp_queries()
    conn = tfb_db.get_conn()
    out = []
    for _ in range(n):
        row = tfb_db.get_world(conn, random.randint(1, 10000))
        out.append({"id": row[0], "randomNumber": row[1]})
    return out


@app.route("/updates")
def updates_test():
    n = _clamp_queries()
    conn = tfb_db.get_conn()
    rows = []
    for _ in range(n):
        row = tfb_db.get_world(conn, random.randint(1, 10000))
        rows.append([random.randint(1, 10000), row[0]])
    tfb_db.update_worlds(conn, rows)
    return [{"id": rid, "randomNumber": new} for new, rid in rows]


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
    port = int(os.environ.get("TFB_PORT", 7071))
    # TFB 是纯吞吐测试：关闭访问日志，单进程（IO 密集 + Rust 内核）
    app.testing = False
    app.run(host="127.0.0.1", port=port, use_reloader=False)
