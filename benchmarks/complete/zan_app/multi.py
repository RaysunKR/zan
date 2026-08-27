import os
import sys
import multiprocessing

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmarks.complete.zan_app.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7073))
    workers = int(os.environ.get("WORKERS", multiprocessing.cpu_count()))
    app.run(host="0.0.0.0", port=port, use_reloader=False, processes=workers)
