import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zan import Flask
from benchmarks.complete.zan_app import config
from benchmarks.complete.zan_app.views import tfb_rust as tfb, demo, api

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

# Rust 原生短路：常量响应端点无需进入 Python 视图
app._add_native_response("/plaintext", "GET", 200, [("Content-Type", "text/plain")], b"Hello, World!")
app._add_native_response("/json", "GET", 200, [("Content-Type", "application/json")], b'{"message":"Hello, World!"}')

# Rust 原生动态处理器：DB 端点完全绕过 Python GIL
for _path, _hid in (("/db", "db"), ("/queries", "queries"), ("/updates", "updates"), ("/fortunes", "fortunes")):
    app._set_native_handler(_path, "GET", _hid)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7071))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
