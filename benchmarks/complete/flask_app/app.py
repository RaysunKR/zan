import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask
from benchmarks.complete.flask_app import config
from benchmarks.complete.flask_app.views import tfb, demo, api

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
