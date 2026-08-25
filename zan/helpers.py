"""工具函数集合：对齐 flask.helpers 与少量 werkzeug 工具。

包含：状态码 → reason 映射、HTTP 日期格式化/解析、URL 引用、
flash/读取 flash 消息、`send_from_directory`、`stream_with_context` 等。
"""
import os
import re
import typing as t
from datetime import datetime, timezone
from urllib.parse import quote

if t.TYPE_CHECKING:  # pragma: no cover
    from .wrappers import Response

_REASONS = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    206: "Partial Content", 301: "Moved Permanently", 302: "Found",
    303: "See Other", 304: "Not Modified", 307: "Temporary Redirect",
    308: "Permanent Redirect", 400: "Bad Request", 401: "Unauthorized",
    402: "Payment Required", 403: "Forbidden", 404: "Not Found",
    405: "Method Not Allowed", 406: "Not Acceptable", 408: "Request Timeout",
    409: "Conflict", 410: "Gone", 411: "Length Required",
    412: "Precondition Failed", 413: "Content Too Large", 414: "URI Too Long",
    415: "Unsupported Media Type", 416: "Range Not Satisfiable",
    417: "Expectation Failed", 418: "I'm a Teapot",
    422: "Unprocessable Content", 423: "Locked", 428: "Precondition Required",
    429: "Too Many Requests", 431: "Request Header Fields Too Large",
    451: "Unavailable For Legal Reasons", 500: "Internal Server Error",
    501: "Not Implemented", 502: "Bad Gateway", 503: "Service Unavailable",
    504: "Gateway Timeout", 505: "HTTP Version Not Supported",
}


def _get_reason(code: int) -> str:
    return _REASONS.get(code, "Unknown")


_WKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = [
    None, "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _dt_to_http(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return (
        f"{_WKDAYS[dt.weekday()]}, {dt.day:02d} {_MONTHS[dt.month]} "
        f"{dt.year:04d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} GMT"
    )


def _date_to_http(d) -> str:
    return _dt_to_http(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))


def url_quote(s, safe="/") -> str:
    if isinstance(s, str):
        return quote(s.encode("utf-8"), safe=safe)
    return quote(s, safe=safe)


def flash(message, category="message") -> None:
    """Flash a message to the next request. Requires an active request."""
    from .ctx import _request_ctx_stack

    ctx = _request_ctx_stack.top()
    if ctx is None:
        raise RuntimeError(
            "Attempted to flash a message but the request context is not available."
        )
    flashes = ctx.request.session.setdefault("_flashes", []) if ctx.request.session is not None else ctx.request.flashes
    flashes.append((category, message))
    from .signals import message_flashed

    message_flashed.send(_app_proxy() or ctx.app, message=message, category=category)


def _app_proxy():
    from .ctx import _app_ctx_stack

    top = _app_ctx_stack.top()
    return top.app if top else None


def get_flashed_messages(
    with_categories=False, category_filter=None
) -> t.Union[t.List[str], t.List[t.Tuple[str, str]]]:
    from .ctx import _request_ctx_stack

    ctx = _request_ctx_stack.top()
    if ctx is None:
        raise RuntimeError(
            "Attempted to call get_flashed_messages but the request context is not available."
        )
    if "_flashes" in ctx.request.session:
        flashes = list(ctx.request.session.pop("_flashes"))
        ctx.request.session.modified = True
    else:
        flashes = list(ctx.request.flashes)
        ctx.request.flashes = []
    if category_filter:
        flashes = [f for f in flashes if f[0] in category_filter]
    if not with_categories:
        return [m for _, m in flashes]
    return flashes


def _endpoint_from_view_func(view_func):
    return view_func.__name__


def get_debug_flag() -> bool:
    val = os.environ.get("FLASK_DEBUG")
    return val not in (None, "0", "false", "no")


def _split_whitespace(s: str):
    return [p for p in re.split(r"\s+", s) if p]


def send_from_directory(directory, path, **kwargs):
    from .wrappers import send_file as _sf

    return _sf(os.path.join(directory, path), **kwargs)


def make_response(*args):
    """Module-level make_response that operates on the current app."""
    from .ctx import _find_app

    return _find_app().make_response(*args)


def stream_with_context(generator_or_function):
    """Kept for API compatibility. In zan the request context is managed per
    dispatch, so a plain generator works; we just track contexts explicitly."""

    if hasattr(generator_or_function, "__call__"):
        def wrapper(*args, **kwargs):
            gen = generator_or_function(*args, **kwargs)
            return stream_with_context(gen)

        return wrapper

    from .ctx import _request_ctx_stack

    ctx = _request_ctx_stack.top()
    if ctx is None:
        raise RuntimeError("stream_with_context() requires an active request context.")

    def generator():
        with ctx:
            yield from generator_or_function

    return generator()
