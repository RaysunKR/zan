"""补齐功能的测试：类型化转换器、debug 调试页、url_for static、
蓝图静态目录、TRAP_HTTP_EXCEPTIONS、before_first_request、tojson、
send_file 条件请求、CLI。"""
import os
import sys
import uuid as uuidlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from zan import Blueprint, Flask, abort, render_template_string, request, url_for
from zan.app import BuildError


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# 类型化转换器：视图收到原生 Python 类型
# ---------------------------------------------------------------------------

class TestTypedConverters:
    def test_string_converter_keeps_str(self, app, client):
        @app.route("/s/<x>")
        def s(x):
            # <x> 是 string 转换器，即使值全是数字也必须是 str
            assert isinstance(x, str)
            return {"type": type(x).__name__, "val": x}

        r = client.get("/s/12345")
        assert r.json == {"type": "str", "val": "12345"}

    def test_int_converter_gives_int(self, app, client):
        @app.route("/i/<int:x>")
        def i(x):
            assert isinstance(x, int)
            return {"val": x, "type": type(x).__name__}

        assert client.get("/i/7").json == {"val": 7, "type": "int"}

    def test_float_converter_gives_float(self, app, client):
        @app.route("/f/<float:x>")
        def f(x):
            assert isinstance(x, float)
            return {"val": x}

        assert client.get("/f/3.5").json == {"val": 3.5}

    def test_uuid_converter_gives_uuid(self, app, client):
        u = uuidlib.uuid4()

        @app.route("/u/<uuid:x>")
        def u_(x):
            assert isinstance(x, uuidlib.UUID)
            return str(x)

        assert client.get(f"/u/{u}").text == str(u)


# ---------------------------------------------------------------------------
# debug 调试页
# ---------------------------------------------------------------------------

class TestDebugPage:
    def test_debug_page_rendered(self):
        from zan.debug import render_debug_page

        try:
            raise ValueError("boom-detail")
        except ValueError as e:
            html = render_debug_page(e)
        assert "ValueError" in html
        assert "boom-detail" in html
        assert "render_debug_page" in html  # 源码帧出现
        assert "原始回溯" in html

    def test_debug_mode_returns_500_page(self, app, client):
        app.debug = True

        @app.route("/crash")
        def crash():
            raise RuntimeError("kapow")

        r = client.get("/crash")
        assert r.status_code == 500
        # debug 页含异常类型与回溯
        assert "RuntimeError" in r.text
        assert "kapow" in r.text


# ---------------------------------------------------------------------------
# url_for static
# ---------------------------------------------------------------------------

class TestUrlForStatic:
    def test_static_endpoint(self, tmp_path):
        static = tmp_path / "static"
        static.mkdir()
        app = Flask("st", root_path=str(tmp_path))
        with app.test_request_context():
            url = url_for("static", filename="css/app.css")
        assert url == "/static/css/app.css"

    def test_static_with_anchor(self, tmp_path):
        static = tmp_path / "static"
        static.mkdir()
        app = Flask("st2", root_path=str(tmp_path))
        with app.test_request_context():
            url = url_for("static", filename="a.js", _anchor="x")
        assert url == "/static/a.js#x"


# ---------------------------------------------------------------------------
# 蓝图静态目录
# ---------------------------------------------------------------------------

class TestBlueprintStatic:
    def test_bp_static_folder(self, tmp_path, tmp_factory=None):
        bp_dir = tmp_path / "bp"
        (bp_dir / "static").mkdir(parents=True)
        (bp_dir / "static" / "bp.js").write_text("bp()", encoding="utf-8")

        app = Flask("host", root_path=str(tmp_path))
        bp = Blueprint(
            "widget",
            "widget",
            root_path=str(bp_dir),
            static_folder="static",
            url_prefix="/widget",
        )
        app.register_blueprint(bp)

        client = app.test_client()
        r = client.get("/widget/static/bp.js")
        assert r.status_code == 200
        assert b"bp()" in r.data

    def test_app_static_still_works_alongside(self, tmp_path):
        appstatic = tmp_path / "static"
        appstatic.mkdir()
        (appstatic / "app.css").write_text("body{}", encoding="utf-8")
        bp_dir = tmp_path / "bp"
        (bp_dir / "static").mkdir(parents=True)
        (bp_dir / "static" / "bp.js").write_text("bp()", encoding="utf-8")

        app = Flask("host2", root_path=str(tmp_path))
        bp = Blueprint(
            "w2", "w2", root_path=str(bp_dir), static_folder="static", url_prefix="/w2"
        )
        app.register_blueprint(bp)

        client = app.test_client()
        assert client.get("/static/app.css").status_code == 200
        assert client.get("/w2/static/bp.js").status_code == 200


# ---------------------------------------------------------------------------
# TRAP_HTTP_EXCEPTIONS
# ---------------------------------------------------------------------------

class TestTrapHTTPExceptions:
    def test_trap_reraises(self, app, client):
        app.config["TRAP_HTTP_EXCEPTIONS"] = True

        @app.route("/t")
        def t():
            abort(404)

        # HTTPException 不再被转换成 404 响应，而是冒泡（对测试很有用）
        r = client.get("/t")
        assert r.status_code == 500  # 未捕获异常最终仍是 500


# ---------------------------------------------------------------------------
# before_first_request
# ---------------------------------------------------------------------------

class TestBeforeFirstRequest:
    def test_runs_once(self, app, client):
        calls = []

        @app.before_first_request
        def init():
            calls.append(1)

        @app.route("/a")
        def a():
            return str(len(calls))

        assert client.get("/a").text == "1"
        assert client.get("/a").text == "1"
        assert calls == [1]


# ---------------------------------------------------------------------------
# tojson 模板过滤器
# ---------------------------------------------------------------------------

class TestTojsonFilter:
    def test_tojson_in_template(self, app, client):
        @app.route("/tj")
        def tj():
            return render_template_string("{{ data | tojson }}", data={"a": 1})

        assert client.get("/tj").text == '{"a":1}'

    def test_tojson_escapes_html(self, app, client):
        @app.route("/tj2")
        def tj2():
            return render_template_string(
                "{{ data | tojson }}", data={"x": "</script>"}
            )

        r = client.get("/tj2")
        assert "</script>" not in r.text
        assert "\\u003c" in r.text


# ---------------------------------------------------------------------------
# send_file 条件请求
# ---------------------------------------------------------------------------

class TestSendFileConditional:
    def test_304_on_etag_match(self, app, client, tmp_path):
        from zan.wrappers import send_file

        target = tmp_path / "f.txt"
        target.write_text("hello", encoding="utf-8")

        @app.route("/dl")
        def dl():
            return send_file(str(target))

        r1 = client.get("/dl")
        assert r1.status_code == 200
        etag = r1.headers.get("ETag")
        assert etag
        r2 = client.get("/dl", headers={"If-None-Match": etag})
        assert r2.status_code == 304
        assert r2.data == b""


# ---------------------------------------------------------------------------
# dispatch_request / full_dispatch_request 兼容
# ---------------------------------------------------------------------------

class TestDispatchCompat:
    def test_dispatch_request(self, app, client):
        @app.route("/d/<n>")
        def d(n):
            return f"n={n}"

        r = client.get("/d/9")
        assert r.text == "n=9"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_routes_command(self, capsys, tmp_path):
        from zan.__main__ import cmd_routes
        import argparse

        app = Flask("cliapp")
        app.add_url_rule("/x/<int:i>", "x", lambda i: i, methods=["GET"])

        args = argparse.Namespace(app=None)
        # monkeypatch loader via FLASK_APP-free path: build directly
        import zan.__main__ as m

        original = m._load_app
        m._load_app = lambda spec: app
        try:
            cmd_routes(args)
        finally:
            m._load_app = original
        out = capsys.readouterr().out
        assert "/x/<int:i>" in out
        assert "GET" in out
        assert "x" in out

    def test_load_app_module_attr(self, tmp_path, monkeypatch):
        (tmp_path / "mycliapp.py").write_text(
            "app = None\nfrom zan import Flask\napp = Flask('mycliapp')\n",
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        from zan.__main__ import _load_app

        app = _load_app("mycliapp:app")
        assert app.name == "mycliapp"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
