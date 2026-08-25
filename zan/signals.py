"""信号：对齐 flask.signals 的表面 API。

安装了 blinker 时直接复用真 blinker（完整语义）；否则使用内置的
兼容实现（支持 connect/disconnect/send/has_receivers_for）。
可用信号与 Flask 相同：request_started、request_finished、
got_request_exception、request_tearing_down、appcontext_* 等。
"""
from .ctx import _Signal

signals_available = True
try:
    import blinker  # noqa: F401
except ImportError:
    signals_available = False

request_started = _Signal("request-started")
request_finished = _Signal("request-finished")
request_tearing_down = _Signal("request-tearing-down")
got_request_exception = _Signal("got-request-exception")
appcontext_tearing_down = _Signal("appcontext-tearing-down")
appcontext_pushed = _Signal("appcontext-pushed")
appcontext_popped = _Signal("appcontext-popped")
message_flashed = _Signal("message-flashed")
