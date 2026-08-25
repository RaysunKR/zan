"""Example zan application exercising the Flask-style API."""
from zan import (
    Blueprint,
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret"

api = Blueprint("api", __name__, url_prefix="/api")


@app.route("/")
def index():
    return "<h1>Welcome to zan</h1>"


@app.route("/hello/<name>")
def hello(name):
    return f"Hello, {name}!"


@app.route("/user/<int:uid>")
def user(uid):
    return jsonify(uid=uid, profile=f"/user/{uid}/profile")


@app.route("/user/<int:uid>/profile")
def profile(uid):
    return {"uid": uid, "name": f"user{uid}"}


@app.route("/files/<path:p>")
def files(p):
    return {"file": p}


@app.route("/post", methods=["POST"])
def post():
    return jsonify(
        json=request.get_json(silent=True),
        form=dict(request.form),
        bytes=len(request.get_data()),
    )


@app.route("/login", methods=["POST"])
def login():
    session["user"] = request.form.get("user", "?")
    flash("logged in")
    return redirect("/")


@app.route("/whoami")
def whoami():
    return {"user": session.get("user")}


@app.route("/tpl/<name>")
def tpl(name):
    return render_template_string("Hello {{ name }}!", name=name)


@app.route("/boom")
def boom():
    abort(500, "something broke")


@api.route("/ping")
def ping():
    return {"pong": True}


app.register_blueprint(api)


@app.errorhandler(500)
def on_500(e):
    return "custom five hundred", 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001)
