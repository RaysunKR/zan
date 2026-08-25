"""类型化的上下文栈与代理基础设施，对齐 werkzeug.local 的语义。

对象本身是纯 Python；栈的增删查由 `_CtxStack` 维护。请求上下文
（`RequestContext`）持有请求对象与匹配结果，应用上下文
（`AppContext`）持有 app 与 `g`。模块底部是一个极简的 blinker 兼容
信号实现——安装了 blinker 时优先使用真 blinker。
"""
import typing as t
from contextlib import contextmanager

if t.TYPE_CHECKING:  # pragma: no cover
    from .wrappers import Request


class _CtxStack:
    def __init__(self, name: str) -> None:
        self.name = name
        self._stack: t.List[t.Any] = []

    def push(self, obj: t.Any) -> t.List[t.Any]:
        self._stack.append(obj)
        return self._stack

    def pop(self) -> t.Any:
        if not self._stack:
            return None
        return self._stack.pop()

    def top(self) -> t.Any:
        if not self._stack:
            return None
        return self._stack[-1]

    def __len__(self) -> int:
        return len(self._stack)

    def __bool__(self) -> bool:
        return bool(self._stack)


class RequestContext:
    """One request: holds the request object and matched endpoint/view args."""

    def __init__(self, app: "t.Any", request: "Request", endpoint=None, view_args=None) -> None:
        self.app = app
        self.request = request
        self.url_rule = None
        self.error = None
        self.matched = endpoint is not None
        self.request.endpoint = endpoint
        self.request.view_args = view_args or {}
        self._preserved = False
        self._implicit_app_ctx = None

    def push(self) -> None:
        # 与 Flask 一致：请求上下文隐式确保应用上下文存在
        app_ctx = self.app.app_context()
        app_ctx.push()
        self._implicit_app_ctx = app_ctx
        _request_ctx_stack.push(self)
        session_interface = getattr(self.app, "session_interface", None)
        if session_interface is not None:
            self.request.session = session_interface.open_session(self.app, self.request)
            if self.request.session is None:
                self.request.session = session_interface.make_null_session(self.app)

    def pop(self, exc=None) -> None:
        _request_ctx_stack.pop()
        if self.request.session is not None:
            session_interface = getattr(self.app, "session_interface", None)
            if session_interface is not None and not isinstance(
                self.request.session, NullSession
            ):
                session_interface.save_session(self.app, self.request.session, self._response_for_save())
        # 弹出隐式创建的应用上下文（若当前顶部的 app ctx 是我们推的）
        implicit = getattr(self, "_implicit_app_ctx", None)
        if implicit is not None:
            self._implicit_app_ctx = None
            implicit.pop(exc)

    def _response_for_save(self):
        """The response cookie changes must land on. The Rust core calls
        ctx pop *before* serializing, so we stash a real Response object here."""
        if getattr(self, "response", None) is not None:
            return self.response
        from .wrappers import Response

        return Response(b"")

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.pop(exc_value)


class AppContext:
    def __init__(self, app: "t.Any") -> None:
        self.app = app
        self.g = app.app_ctx_globals_class()
        self._refcnt = 0

    def push(self) -> None:
        self._refcnt += 1
        _app_ctx_stack.push(self)
        appcontext_pushed.send(self.app)

    def pop(self, exc=None) -> None:
        self._refcnt -= 1
        if self._refcnt == 0:
            _app_ctx_stack.pop()
            appcontext_popped.send(self.app)

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.pop(exc_value)


class NullSession(dict):
    pass


_request_ctx_stack = _CtxStack("request_ctx")
_app_ctx_stack = _CtxStack("app_ctx")


def _lookup_req_object(name: str):
    top = _request_ctx_stack.top()
    if top is None:
        raise RuntimeError("Working outside of request context.\n"
                           "This typically means that you attempted to use functionality that needed "
                           "an active HTTP request. Consult the documentation on testing for "
                           "information about how to avoid this problem.")
    return getattr(top.request, name)


def _lookup_app_object(name: str):
    top = _app_ctx_stack.top()
    if top is None:
        raise RuntimeError("Working outside of application context.\n"
                           "This typically means that you attempted to use functionality that "
                           "needs an active application context.")
    return getattr(top, name)


def _find_app():
    top = _app_ctx_stack.top()
    if top is None:
        raise RuntimeError("Working outside of application context.")
    return top.app


# --- signals (no-op blinker replacement with the same call surface) ---
class _Signal:
    """Minimal blinker-compatible signal: supports send/connect/disconnect and
    receivers connected via decorators. If blinker is installed, prefer it."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._receivers: t.Dict[t.Any, t.Callable] = {}
        # use real blinker if available for full semantics
        try:
            import blinker  # type: ignore

            self._blinker = blinker.signal(name)
        except ImportError:
            self._blinker = None

    def connect(self, receiver, sender=t.Any, weak=True):
        if self._blinker is not None:
            import blinker

            # blinker 的「任意发送者」哨兵是 blinker.ANY；typing.Any 只是默认值占位
            if sender is t.Any or sender is None:
                sender = blinker.ANY
            return self._blinker.connect(receiver, sender=sender, weak=weak)
        self._receivers[receiver] = receiver
        return receiver

    def disconnect(self, receiver, sender=t.Any):
        if self._blinker is not None:
            import blinker

            if sender is t.Any or sender is None:
                sender = blinker.ANY
            return self._blinker.disconnect(receiver, sender=sender)
        self._receivers.pop(receiver, None)

    def send(self, sender=None, /, **kwargs):
        if self._blinker is not None:
            return self._blinker.send(sender, **kwargs)
        results = []
        for receiver in list(self._receivers.values()):
            results.append((receiver, receiver(sender, **kwargs)))
        return results

    def has_receivers_for(self, sender) -> bool:
        if self._blinker is not None:
            return self._blinker.has_receivers_for(sender)
        return bool(self._receivers)

    def __call__(self, sender=None, /, **kwargs):
        return self.send(sender, **kwargs)


# keep imports at the bottom to avoid a cycle with .signals
from .signals import appcontext_pushed, appcontext_popped  # noqa: E402


@contextmanager
def appcontext_preserved(request_ctx):
    request_ctx._preserved = True
    try:
        yield
    finally:
        request_ctx._preserved = False
