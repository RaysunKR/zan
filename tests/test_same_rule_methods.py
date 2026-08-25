"""框架增强：同一 rule 注册多个方法分立的视图函数（Flask 常见写法）。

    @app.route("/x", methods=["GET"])
    def get_x(): ...

    @app.route("/x", methods=["POST"])
    def post_x(): ...

框架自动生成方法分发视图，两个函数各自保留 endpoint。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from zan import Flask


@pytest.fixture()
def app():
    return Flask(__name__)


def test_same_rule_split_methods(app):
    @app.route("/thing", methods=["GET"])
    def get_thing():
        return "GOT"

    @app.route("/thing", methods=["POST"])
    def post_thing():
        return "POSTED"

    c = app.test_client()
    assert c.get("/thing").text == "GOT"
    assert c.post("/thing").text == "POSTED"
    assert c.delete("/thing").status_code == 405
    allow = c.delete("/thing").headers.get("Allow", "")
    assert "GET" in allow and "POST" in allow


def test_same_rule_with_params(app):
    @app.route("/item/<int:n>", methods=["GET"])
    def read(n):
        return f"read:{n}"

    @app.route("/item/<int:n>", methods=["PUT"])
    def write(n):
        return f"write:{n}", 201

    c = app.test_client()
    assert c.get("/item/3").text == "read:3"
    r = c.put("/item/3")
    assert r.status_code == 201
    assert r.text == "write:3"


def test_endpoint_functions_preserved(app):
    @app.route("/dup", methods=["GET"])
    def a():
        return "a"

    @app.route("/dup", methods=["POST"])
    def b():
        return "b"

    # 两个原始 endpoint 都能 url_for
    with app.test_request_context():
        pass
    # 视图函数表完好
    assert app.view_functions["a"]() == "a"
    assert app.view_functions["b"]() == "b"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
