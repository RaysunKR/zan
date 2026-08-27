import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import flash, get_flashed_messages, redirect, render_template, request, session, url_for


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
        from flask import abort
        abort(code)
