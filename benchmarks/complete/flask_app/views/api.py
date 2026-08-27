import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Blueprint, jsonify

api = Blueprint("api", __name__, url_prefix="/api")


@api.route("/ping")
def ping():
    return jsonify(pong=True)


@api.route("/user/<int:user_id>")
def user(user_id):
    return jsonify(id=user_id, name=f"user{user_id}")


def register(app):
    app.register_blueprint(api)
