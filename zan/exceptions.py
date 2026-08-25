"""HTTP 异常体系，对齐 werkzeug.exceptions。

用法（与 Flask 完全一致）::

    from zan import abort, NotFound

    abort(404)
    abort(400, "参数不对")           # 自定义描述
    abort(NotFound("东西没了"))       # 直接抛异常实例
    raise Forbidden()

每个异常类通过 `get_response()` 产出对应的 HTML 错误页。
`default_exceptions` 是状态码 → 异常类的映射表，abort() 依赖它。
"""
import typing as t


class HTTPException(Exception):
    """Base class for exceptions that map to HTTP error responses."""

    code: t.Optional[int] = None
    description: t.Optional[str] = None

    def __init__(self, description=None, response=None):
        super().__init__()
        if description is not None:
            self.description = description
        self.response = response

    @property
    def name(self) -> str:
        from .helpers import _get_reason

        return _get_reason(self.code or 500)

    def get_description(self, environ=None, scope=None) -> str:
        if self.description is None:
            description = ""
        else:
            description = self.description
        return (
            "<!doctype html>\n"
            "<html lang=en>\n"
            f"<title>{self.code} {self.escape(self.name)}</title>\n"
            f"<h1>{self.code} {self.escape(self.name)}</h1>\n"
            f"<p>{self.escape(description)}</p>\n"
        )

    def get_body(self, environ=None, scope=None) -> str:
        return self.get_description(environ, scope)

    def get_headers(self, environ=None, scope=None):
        return [("Content-Type", "text/html; charset=utf-8")]

    def get_response(self, environ=None, scope=None):
        from .wrappers import Response

        if self.response is not None:
            return self.response
        resp = Response(self.get_body(environ, scope), self.code, self.get_headers(environ, scope))
        return resp

    def __str__(self) -> str:
        code = self.code if self.code is not None else "?"
        return f"{code}: {self.description if self.description else self.name}"

    @staticmethod
    def escape(s: str) -> str:
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )


class BadRequest(HTTPException):
    code = 400
    description = (
        "The browser (or proxy) sent a request that this server could "
        "not understand."
    )


class BadRequestKeyError(BadRequest, KeyError):
    def __init__(self, key=None):
        if key is None:
            key = "?"
        super().__init__(f"KeyError: '{key}'")
        self.key = key

    def __str__(self) -> str:
        return self.description or ""


class Unauthorized(HTTPException):
    code = 401
    description = (
        "The server could not verify that you are authorized to access "
        "the URL requested. You either supplied the wrong credentials "
        "(e.g. a bad password), or your browser doesn't understand how "
        "to supply the credentials required."
    )

    def __init__(self, description=None, response=None, www_authenticate=None):
        super().__init__(description, response)
        self.www_authenticate = www_authenticate

    def get_headers(self, environ=None, scope=None):
        headers = list(super().get_headers(environ, scope))
        if self.www_authenticate:
            headers.append(("WWW-Authenticate", str(self.www_authenticate)))
        return headers


class Forbidden(HTTPException):
    code = 403
    description = (
        "You don't have the permission to access the requested resource. "
        "It is either read-protected or not readable by the server."
    )


class NotFound(HTTPException):
    code = 404
    description = (
        "The requested URL was not found on the server. If you entered "
        "the URL manually please check your spelling and try again."
    )


class MethodNotAllowed(HTTPException):
    code = 405
    description = "The method is not allowed for the requested URL."

    def __init__(self, valid_methods=None, description=None, response=None):
        super().__init__(description=description, response=response)
        self.valid_methods = valid_methods

    def get_headers(self, environ=None, scope=None):
        headers = list(super().get_headers(environ, scope))
        if self.valid_methods:
            headers.append(("Allow", ", ".join(self.valid_methods)))
        return headers


class NotAcceptable(HTTPException):
    code = 406
    description = (
        "The resource identified by the request is only capable of "
        "generating response entities which have content characteristics "
        "not acceptable according to the accept headers sent in the request."
    )


class RequestTimeout(HTTPException):
    code = 408
    description = (
        "The connection was closed while waiting for the client to send "
        "the request."
    )


class Conflict(HTTPException):
    code = 409
    description = (
        "A conflict happened while processing the request. The resource "
        "might have been modified while the request was being processed."
    )


class Gone(HTTPException):
    code = 410
    description = (
        "The requested URL is no longer available on this server and "
        "there is no forwarding address."
    )


class LengthRequired(HTTPException):
    code = 411
    description = "A Content-Length header is required for this request."


class PreconditionFailed(HTTPException):
    code = 412
    description = (
        "The precondition on the request for the resource failed positive "
        "evaluation."
    )


class PayloadTooLarge(HTTPException):
    code = 413
    description = "The request entity is too large."


class URITooLong(HTTPException):
    code = 414
    description = "The URI provided was too long for the server to process."


class UnsupportedMediaType(HTTPException):
    code = 415
    description = (
        "The server does not support the media type transmitted in the request."
    )


class RangeNotSatisfiable(HTTPException):
    code = 416
    description = "The server cannot provide the requested range."


class ExpectationFailed(HTTPException):
    code = 417
    description = "The server could not meet the expectation given in the Expect header field."


class ImATeapot(HTTPException):
    code = 418
    description = "This server is a teapot, not a coffee machine."


class UnprocessableEntity(HTTPException):
    code = 422
    description = (
        "The request was well-formed but was unable to be followed due "
        "to semantic errors."
    )


class TooManyRequests(HTTPException):
    code = 429
    description = "The user has sent too many requests in a given amount of time."


class InternalServerError(HTTPException):
    code = 500
    description = (
        "The server encountered an internal error and was unable to "
        "complete your request. Either the server is overloaded or there "
        "is an error in the application."
    )


class NotImplemented(HTTPException):
    code = 501
    description = "The server does not support the action requested by the browser."


class BadGateway(HTTPException):
    code = 502
    description = (
        "The proxy server received an invalid response from an upstream server."
    )


class ServiceUnavailable(HTTPException):
    code = 503
    description = (
        "The server is temporarily unable to service your request due to "
        "maintenance downtime or capacity problems. Please try again later."
    )


class GatewayTimeout(HTTPException):
    code = 504
    description = "The connection to an upstream server timed out."


class RedirectNeeded(Exception):
    """Internal marker, not part of the public Flask API."""


default_exceptions: t.Dict[int, t.Type[HTTPException]] = {}


def _register(cls):
    if cls.code is not None:
        default_exceptions[cls.code] = cls
    return cls


for _cls in list(globals().values()):
    if isinstance(_cls, type) and issubclass(_cls, HTTPException) and _cls is not HTTPException:
        _register(_cls)


def abort(status, *args, **kwargs):
    """Raise an HTTPException (flask.abort compatible)."""
    from .exceptions import HTTPException as _HTTPException
    from .wrappers import Response as _Response

    if isinstance(status, _Response):
        raise _HTTPException(response=status)
    if isinstance(status, _HTTPException):
        raise status
    if not isinstance(status, int):
        raise TypeError("abort expects an int status, HTTPException, or Response")
    if args or kwargs:
        # description-style call: abort(400, "msg")
        try:
            exc_class = default_exceptions[status]
        except KeyError as err:
            raise ValueError(f"{status} is not a valid HTTP status code") from err
        raise exc_class(*args, **kwargs)
    try:
        exc_class = default_exceptions[status]
    except KeyError as err:
        raise ValueError(f"{status} is not a valid HTTP status code") from err
    raise exc_class()


class _Aborter:
    def __call__(self, status, *args, **kwargs):
        abort(status, *args, **kwargs)

    def __getattr__(self, name):
        exc_map = {c.__name__: c for c in default_exceptions.values()}
        if name in exc_map:
            return exc_map[name]
        raise AttributeError(name)


aborter = _Aborter()
