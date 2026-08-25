"""zan —— Rust 内核、Flask 体验的 Python Web 框架。

从 Flask 迁移：把 ``from flask import ...`` 改成 ``from zan import ...``。

本包导出的公开符号（与 Flask 同名同义）::

    Flask, Blueprint, Request, Response,
    request, session, g, current_app,
    abort, HTTPException 及其全部子类,
    render_template, render_template_string, make_response,
    redirect, url_for, jsonify, flash, get_flashed_messages,
    send_file, send_from_directory, escape, has_request_context ...
"""
import typing as t

from .app import Flask
from .blueprints import Blueprint
from .exceptions import (
    BadRequest,
    BadRequestKeyError,
    Conflict,
    Forbidden,
    Gone,
    HTTPException,
    ImATeapot,
    InternalServerError,
    LengthRequired,
    MethodNotAllowed,
    NotAcceptable,
    NotFound,
    PayloadTooLarge,
    PreconditionFailed,
    RangeNotSatisfiable,
    RequestTimeout,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
    UnprocessableEntity,
    UnsupportedMediaType,
    URITooLong,
    abort,
)
from .globals import current_app, g, request, session
from .helpers import flash, get_flashed_messages, url_quote
from .json import dumps as json_dumps
from .json import loads as json_loads
from .json import DefaultJSONProvider
from .session import NullSession, SecureCookieSession
from .templating import Environment
from .wrappers import (
    Request,
    Response,
    send_file,
)

try:
    import _zan

    __version__ = _zan._version
except ImportError:  # pragma: no cover
    __version__ = "0.1.0"


def escape(s):
    """HTML 转义；优先使用 markupsafe（返回 Markup），否则用内置 html.escape。"""
    try:
        from markupsafe import escape as _escape

        return _escape(s)
    except ImportError:
        import html

        return html.escape(str(s))


def render_template(template_name_or_list, **context):
    """按名字从模板目录渲染模板（需安装 jinja2）。"""
    ctx = current_app
    template = ctx.jinja_env.get_template(template_name_or_list)
    return template.render(**context)


def render_template_string(source, **context):
    """把字符串当作模板渲染（需安装 jinja2）。"""
    template = current_app.jinja_env.from_string(source)
    return template.render(**context)


def make_response(*args):
    """模块级 make_response：转发给当前应用的 ``Flask.make_response``。"""
    return current_app.make_response(*args)


def redirect(location, code=302):
    """重定向响应：302 临时（默认）/ 301 / 307 / 308。"""
    from .wrappers import Response

    if location is None:
        raise TypeError("location must be given")
    rv = Response(
        f"<!doctype html>\n<html lang=en>\n<title>{code} Redirecting...</title>\n"
        f"<h1>{code} Redirecting...</h1>\n"
        f'<p>You should be redirected automatically to the target URL: '
        f'<a href="{location}">{location}</a>. If not, click the link.</p>\n',
        code,
        [("Content-Type", "text/html; charset=utf-8"), ("Location", location)],
    )
    return rv


def url_for(endpoint, **values):
    """模块级 url_for：转发给当前应用的 ``Flask.url_for``。"""
    return current_app.url_for(endpoint, **values)


def jsonify(*args, **kwargs):
    return current_app.jsonify(*args, **kwargs)


def stream_with_context(generator_or_function):
    from .helpers import stream_with_context as _swc

    return _swc(generator_or_function)


def get_template_attribute(template_name, attribute):
    template = current_app.jinja_env.get_template(template_name)
    return getattr(template.module, attribute)


def has_app_context() -> bool:
    from .ctx import _app_ctx_stack

    return bool(_app_ctx_stack)


def has_request_context() -> bool:
    from .ctx import _request_ctx_stack

    return bool(_request_ctx_stack)


def copy_current_request_context(f):
    from .ctx import _request_ctx_stack

    ctx = _request_ctx_stack.top()
    if ctx is None:
        raise RuntimeError("This decorator must be used within a request context.")

    def wrapper(*args, **kwargs):
        with ctx:
            return f(*args, **kwargs)

    return wrapper


def get_flashed_messages_(*args, **kwargs):
    from .helpers import get_flashed_messages as _gfm

    return _gfm(*args, **kwargs)


# re-exports for `from zan import *`
__all__ = [
    "Flask", "Blueprint", "Request", "Response", "send_file", "send_from_directory",
    "request", "session", "g", "current_app", "abort", "HTTPException",
    "BadRequest", "BadRequestKeyError", "Conflict", "Forbidden", "Gone",
    "ImATeapot", "InternalServerError", "LengthRequired", "MethodNotAllowed",
    "NotAcceptable", "NotFound", "PayloadTooLarge", "PreconditionFailed",
    "RangeNotSatisfiable", "RequestTimeout", "ServiceUnavailable",
    "TooManyRequests", "Unauthorized", "UnprocessableEntity",
    "UnsupportedMediaType", "URITooLong", "render_template",
    "render_template_string", "make_response", "redirect", "url_for",
    "flash", "get_flashed_messages", "escape", "json_dumps", "json_loads",
    "url_quote", "has_app_context", "has_request_context",
    "copy_current_request_context", "stream_with_context", "Environment",
    "NullSession", "SecureCookieSession", "__version__",
]
