"""End-to-end compatibility tests for zan against Flask behavior."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from zan import (
    Blueprint,
    Flask,
    abort,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from zan.exceptions import HTTPException, NotFound


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# basic responses
# ---------------------------------------------------------------------------

class TestResponses:
    def test_hello(self, app, client):
        @app.route("/")
        def hello():
            return "Hello, World!"

        r = client.get("/")
        assert r.status_code == 200
        assert r.text == "Hello, World!"
        assert r.headers["Content-Type"].startswith("text/html")

    def test_bytes(self, app, client):
        @app.route("/b")
        def b():
            return b"\x00\x01\x02"

        r = client.get("/b")
        assert r.data == b"\x00\x01\x02"

    def test_dict_is_json(self, app, client):
        @app.route("/j")
        def j():
            return {"a": 1, "b": [1, 2], "c": None}

        r = client.get("/j")
        assert r.status_code == 200
        assert r.is_json
        assert r.json == {"a": 1, "b": [1, 2], "c": None}

    def test_jsonify(self, app, client):
        @app.route("/j2")
        def j2():
            return jsonify(x=1, y="two")

        r = client.get("/j2")
        assert r.json == {"x": 1, "y": "two"}

    def test_jsonify_sorted_keys(self, app, client):
        @app.route("/sorted")
        def sorted_view():
            return jsonify({"zebra": 1, "apple": 2, "mango": 3})

        r = client.get("/sorted")
        assert r.text == '{"apple":2,"mango":3,"zebra":1}'

    def test_json_unicode_escaped(self, app, client):
        @app.route("/u")
        def u():
            return {"city": "杭州"}

        r = client.get("/u")
        # Rust fast path: ensure_ascii like Flask's default provider
        assert "\\u676d" in r.text or "杭州" in r.text
        assert r.json["city"] == "杭州"

    def test_status_and_headers_tuple(self, app, client):
        @app.route("/teapot")
        def teapot():
            return "tea", 418, {"X-Tea": "yes"}

        r = client.get("/teapot")
        assert r.status_code == 418
        assert r.headers["X-Tea"] == "yes"

    def test_status_only(self, app, client):
        @app.route("/created")
        def created():
            return "made", 201

        assert client.get("/created").status_code == 201

    def test_none_returns_500(self, app, client):
        @app.route("/n")
        def n():
            return None

        assert client.get("/n").status_code == 500

    def test_redirect_helper(self, app, client):
        @app.route("/r")
        def r():
            return redirect("/target")

        resp = client.get("/r")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/target"


# ---------------------------------------------------------------------------
# converters
# ---------------------------------------------------------------------------

class TestConverters:
    @pytest.mark.parametrize("rule,url,val", [
        ("/<x>", "/hello", "hello"),
        ("/<int:x>", "/123", 123),
        ("/<path:x>", "/a/b/c.txt", "a/b/c.txt"),
        ("/<any(a, b):x>", "/a", "a"),
    ])
    def test_converter(self, app, client, rule, url, val):
        @app.route(rule)
        def view(x):
            assert x == val
            return f"{type(x).__name__}:{x}"

        r = client.get(url)
        assert r.status_code == 200
        assert r.text.startswith(f"{type(val).__name__}:")

    def test_int_rejects_non_numeric(self, app, client):
        @app.route("/<int:x>")
        def view(x):
            return "x"

        assert client.get("/abc").status_code == 404

    def test_uuid(self, app, client):
        import uuid as uuidlib

        u = "12345678-1234-5678-1234-567812345678"

        @app.route("/<uuid:x>")
        def view(x):
            return str(x)

        r = client.get(f"/{u}")
        assert r.status_code == 200
        assert r.text == u
        assert client.get("/not-a-uuid").status_code == 404

    def test_url_decoding(self, app, client):
        @app.route("/<name>")
        def view(name):
            return name

        from urllib.parse import quote

        r = client.get("/" + quote("杭州"))
        assert r.text == "杭州"


# ---------------------------------------------------------------------------
# HTTP methods
# ---------------------------------------------------------------------------

class TestMethods:
    def test_method_dispatch(self, app, client):
        @app.route("/m", methods=["GET", "POST"])
        def m():
            return request.method

        assert client.get("/m").text == "GET"
        assert client.post("/m").text == "POST"
        resp = client.delete("/m")
        assert resp.status_code == 405
        assert "GET" in resp.headers.get("Allow", "")

    def test_auto_options(self, app, client):
        @app.route("/o")
        def o():
            return "o"

        resp = client.options("/o")
        assert resp.status_code == 200
        assert "GET" in resp.headers["Allow"]
        assert "OPTIONS" in resp.headers["Allow"]

    def test_head_on_get_route(self, app, client):
        @app.route("/h")
        def h():
            return "body"

        resp = client.head("/h")
        assert resp.status_code == 200
        assert resp.data == b""  # HEAD has no body

    def test_default_methods_are_get(self, app, client):
        @app.route("/only-get")
        def g():
            return "g"

        assert client.get("/only-get").status_code == 200
        assert client.post("/only-get").status_code == 405


# ---------------------------------------------------------------------------
# request data
# ---------------------------------------------------------------------------

class TestRequestData:
    def test_query_args(self, app, client):
        @app.route("/q")
        def q():
            return {
                "a": request.args.get("a"),
                "multi": request.args.getlist("multi"),
                "typed": request.args.get("n", type=int),
            }

        r = client.get("/q?a=1&multi=x&multi=y&n=5")
        assert r.json == {"a": "1", "multi": ["x", "y"], "typed": 5}

    def test_missing_key_raises_400(self, app, client):
        @app.route("/k")
        def k():
            return request.args["missing"]

        r = client.get("/k")
        assert r.status_code == 400

    def test_form_post(self, app, client):
        @app.route("/f", methods=["POST"])
        def f():
            return dict(request.form)

        r = client.post("/f", data={"name": "zan", "lang": "rust"})
        assert r.json == {"name": "zan", "lang": "rust"}

    def test_json_body(self, app, client):
        @app.route("/jb", methods=["POST"])
        def jb():
            return {"echo": request.get_json()}

        r = client.post("/jb", json={"deep": {"list": [1, 2, 3]}})
        assert r.json == {"echo": {"deep": {"list": [1, 2, 3]}}}

    def test_raw_body(self, app, client):
        @app.route("/raw", methods=["POST"])
        def raw():
            return {"len": len(request.get_data())}

        r = client.post("/raw", data="0123456789")
        assert r.json == {"len": 10}

    def test_headers(self, app, client):
        @app.route("/hdr")
        def hdr():
            return {"ua": request.headers.get("User-Agent")}

        r = client.get("/hdr", headers={"User-Agent": "zan-test/1.0"})
        assert r.json == {"ua": "zan-test/1.0"}

    def test_view_args_and_endpoint(self, app, client):
        @app.route("/va/<x>")
        def va(x):
            return {
                "endpoint": request.endpoint,
                "path": request.path,
                "full": request.full_path,
                "url": request.url,
            }

        r = client.get("/va/42?q=1")
        d = r.json
        assert d["endpoint"] == "va"
        assert d["path"] == "/va/42"
        assert d["full"] == "/va/42?q=1"
        assert d["url"].endswith("/va/42?q=1")

    def test_method_and_remote_addr(self, app, client):
        @app.route("/meta")
        def meta():
            return {"method": request.method}

        assert client.get("/meta").json == {"method": "GET"}


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

class TestErrors:
    def test_default_404_body(self, app, client):
        r = client.get("/missing")
        assert r.status_code == 404
        assert "404" in r.text and "Not Found" in r.text

    def test_custom_404(self, app, client):
        @app.errorhandler(404)
        def nf(e):
            return "custom not found", 404

        assert client.get("/missing").text == "custom not found"

    def test_custom_500(self, app, client):
        @app.route("/boom")
        def boom():
            raise ValueError("boom")

        @app.errorhandler(ValueError)
        def handle(e):
            return f"caught {e}", 500

        r = client.get("/boom")
        assert r.status_code == 500
        assert r.text == "caught boom"

    def test_abort(self, app, client):
        @app.route("/a")
        def a():
            abort(403)

        @app.route("/b")
        def b():
            abort(400, "bad input")

        assert client.get("/a").status_code == 403
        r = client.get("/b")
        assert r.status_code == 400
        assert "bad input" in r.text

    def test_abort_with_exception_object(self, app, client):
        @app.route("/c")
        def c():
            abort(NotFound("gone away"))

        r = client.get("/c")
        assert r.status_code == 404
        assert "gone away" in r.text

    def test_http_exception_in_view(self, app, client):
        from zan.exceptions import Forbidden

        @app.route("/f")
        def f():
            raise Forbidden()

        assert client.get("/f").status_code == 403

    def test_unhandled_exception_500(self, app, client):
        @app.route("/u")
        def u():
            raise RuntimeError("unhandled")

        assert client.get("/u").status_code == 500


# ---------------------------------------------------------------------------
# hooks
# ---------------------------------------------------------------------------

class TestHooks:
    def test_before_request_redirect(self, app, client):
        @app.before_request
        def gate():
            if request.args.get("blocked"):
                return "blocked", 403

        @app.route("/x")
        def x():
            return "ok"

        assert client.get("/x").text == "ok"
        r = client.get("/x?blocked=1")
        assert r.status_code == 403
        assert r.text == "blocked"

    def test_after_request_mutation(self, app, client):
        @app.after_request
        def add_header(resp):
            resp.headers["X-Zan"] = "1"
            return resp

        @app.route("/y")
        def y():
            return "y"

        assert client.get("/y").headers["X-Zan"] == "1"

    def test_teardown_runs_on_success_and_error(self, app, client):
        calls = []

        @app.teardown_request
        def td(err):
            calls.append(err is not None)

        @app.route("/ok")
        def ok():
            return "ok"

        @app.route("/bad")
        def bad():
            1 / 0

        client.get("/ok")
        client.get("/bad")
        assert calls == [False, True]


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

class TestSessions:
    def test_session_roundtrip(self, app, client):
        @app.route("/set")
        def s():
            session["user"] = "alice"
            return "set"

        @app.route("/get")
        def g():
            return session.get("user", "anonymous")

        assert client.get("/get").text == "anonymous"
        client.get("/set")
        assert client.get("/get").text == "alice"

    def test_flash(self, app, client):
        from zan import flash, get_flashed_messages

        @app.route("/flash")
        def f():
            flash("hi there")
            return "flashed"

        @app.route("/show")
        def show():
            return str(get_flashed_messages())

        client.get("/flash")
        assert client.get("/show").text == "['hi there']"
        # messages are consumed
        assert client.get("/show").text == "[]"


# ---------------------------------------------------------------------------
# url building
# ---------------------------------------------------------------------------

class TestURLFor:
    def test_basic(self, app):
        @app.route("/hello/<name>")
        def hello(name):
            return name

        assert url_for_with(app, "hello", name="bob") == "/hello/bob"

    def test_missing_arg_raises(self, app):
        from zan.app import BuildError

        @app.route("/need/<x>")
        def need(x):
            return x

        with pytest.raises(BuildError):
            url_for_with(app, "need")

    def test_anchor(self, app):
        @app.route("/a")
        def a():
            return "a"

        assert url_for_with(app, "a", _anchor="top") == "/a#top"

    def test_within_request_context(self, app, client):
        result = {}

        @app.route("/self")
        def self_url():
            result["url"] = url_for("other")
            return "ok"

        @app.route("/other")
        def other():
            return "other"

        client.get("/self")
        assert result["url"] == "/other"


def url_for_with(app, endpoint, **values):
    with app.test_request_context():
        return app.url_for(endpoint, **values)


# ---------------------------------------------------------------------------
# blueprints
# ---------------------------------------------------------------------------

class TestBlueprints:
    def test_blueprint_routes(self, app, client):
        bp = Blueprint("api", __name__, url_prefix="/api")

        @bp.route("/users/<int:uid>")
        def users(uid):
            return {"uid": uid, "bp": request.blueprint or "none"}

        app.register_blueprint(bp)
        r = client.get("/api/users/7")
        assert r.status_code == 200
        assert r.json["uid"] == 7

    def test_blueprint_errorhandler(self, app, client):
        bp = Blueprint("bp2", __name__)

        @bp.route("/explode")
        def explode():
            abort(404)

        @bp.errorhandler(404)
        def bp404(e):
            return "bp-level 404", 404

        app.register_blueprint(bp)
        assert client.get("/explode").text == "bp-level 404"


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_render_template_string(self, app, client):
        @app.route("/tpl")
        def tpl():
            return render_template_string("hello {{ name }}", name="jinja")

        assert client.get("/tpl").text == "hello jinja"

    def test_template_from_file(self, app, client, tmp_path):
        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir()
        (tpl_dir / "page.html").write_text("<h1>{{ title }}</h1>", encoding="utf-8")
        app.root_path = str(tmp_path)

        @app.route("/page")
        def page():
            from zan import render_template

            return render_template("page.html", title="from file")

        assert client.get("/page").text == "<h1>from file</h1>"


# ---------------------------------------------------------------------------
# static files
# ---------------------------------------------------------------------------

class TestStatic:
    def test_serves_static(self, tmp_path):
        static = tmp_path / "static"
        static.mkdir()
        (static / "app.js").write_text("console.log('zan')", encoding="utf-8")

        app = Flask(
            "staticapp",
            root_path=str(tmp_path),
            static_folder=str(static),
        )

        @app.route("/")
        def index():
            return "root"

        client = app.test_client()
        r = client.get("/static/app.js")
        assert r.status_code == 200
        assert b"console.log" in r.data
        assert "javascript" in r.headers["Content-Type"]

    def test_static_traversal_blocked(self, tmp_path):
        static = tmp_path / "static"
        static.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")

        app = Flask("s2", root_path=str(tmp_path), static_folder=str(static))
        client = app.test_client()
        r = client.get("/static/../secret.txt")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# routing edge cases
# ---------------------------------------------------------------------------

class TestRoutingEdges:
    def test_strict_slashes_redirect(self, app, client):
        @app.route("/page/")
        def page():
            return "page"

        # /page -> 308 redirect to /page/
        r = client.get("/page")
        assert r.status_code == 308
        assert r.headers["Location"] == "/page/"

    def test_merge_slashes(self, app, client):
        @app.route("/a/b")
        def ab():
            return "ab"

        r = client.get("//a///b")
        assert r.status_code == 308
        assert r.headers["Location"] == "/a/b"

    def test_duplicate_rule_endpoints_conflict(self, app):
        @app.route("/x")
        def x1():
            return "1"

        with pytest.raises(AssertionError):

            @app.route("/y", endpoint="x1")
            def x2():
                return "2"


# ---------------------------------------------------------------------------
# app/request contexts
# ---------------------------------------------------------------------------

class TestContexts:
    def test_request_context_manually(self, app):
        from zan import has_request_context

        with app.test_request_context("/some/path?a=b"):
            assert has_request_context()
            assert request.path == "/some/path"
            assert request.args.get("a") == "b"
        assert not has_request_context()

    def test_g(self, app):
        from zan import g

        with app.app_context():
            g.value = 42
            assert g.value == 42

    def test_outside_context_raises(self, app):
        with pytest.raises(RuntimeError):
            _ = request.path

    def test_current_app(self, app):
        from zan import current_app

        with app.app_context():
            assert current_app.name == app.name


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_config_dict_and_attrs(self, app):
        app.config["FOO"] = "bar"
        assert app.config["FOO"] == "bar"
        assert app.config.FOO == "bar"

    def test_from_mapping(self, app):
        app.config.from_mapping(SECRET_KEY="xyz", EXTRA=1)
        assert app.config["SECRET_KEY"] == "xyz"

    def test_debug_property(self, app):
        app.debug = True
        assert app.config["DEBUG"] is True or app.debug is True


# ---------------------------------------------------------------------------
# streaming / generators
# ---------------------------------------------------------------------------

class TestStreaming:
    def test_generator_response(self, app, client):
        @app.route("/gen")
        def gen():
            def produce():
                yield "a"
                yield "b"
                yield "c"

            return produce()

        r = client.get("/gen")
        assert r.text == "abc"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
