"""会话支持：与 Flask 一致的签名 Cookie 会话。

- `SecureCookieSession`：带 modified 标记的 dict 子类
- `SecureCookieSessionInterface`：open/save 会话；HMAC-SHA256 签名、
  URL-safe base64 载荷，兼容 itsdangerous 的 URLSafeSerializer 语义
- `TaggedJSONSerializer`：支持 datetime/tuple 的轻量 JSON 编解码
- `NullSession`：未设置 SECRET_KEY 时的只读空会话（写入即抛错）
"""
import hashlib
import hmac
import secrets
import typing as t
from datetime import datetime, timezone

from .helpers import _dt_to_http

_missing = object()


def _tag_deriver(root_key: bytes) -> t.Callable[[bytes], bytes]:
    def derive(context: bytes) -> bytes:
        return hashlib.sha256(root_key + b"zan-session" + context).digest()

    return derive


class SecureCookieSession(dict):
    modified = False
    accessed = False
    permanent = False

    def __delitem__(self, key):
        super().__delitem__(key)
        self.modified = True

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.modified = True

    def setdefault(self, key, default=None):
        if key not in self:
            self.modified = True
        return super().setdefault(key, default)

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.modified = True

    def pop(self, key, default=_missing):
        if default is _missing:
            rv = super().pop(key)
            self.modified = True
            return rv
        rv = super().pop(key, default)
        if rv is not default:
            self.modified = True
        return rv


class NullSession(SecureCookieSession):
    def _fail(self, *args, **kwargs):
        from .exceptions import RuntimeError as _FlaskRuntimeError  # noqa: F401
        raise RuntimeError(
            "The session is unavailable because no secret key was set. "
            "Set the secret_key on the application to something unique and secret."
        )

    __setitem__ = _fail
    __delitem__ = _fail
    setdefault = _fail
    pop = _fail
    update = _fail
    clear = _fail


class SessionInterface:
    null_session_class = NullSession
    pickle_based = False

    def make_null_session(self, app):
        return self.null_session_class()

    def is_null_session(self, obj):
        return isinstance(obj, self.null_session_class)

    def get_cookie_name(self, app):
        return app.config["SESSION_COOKIE_NAME"]

    def get_cookie_domain(self, app):
        return app.config.get("SESSION_COOKIE_DOMAIN")

    def get_cookie_path(self, app):
        return app.config.get("SESSION_COOKIE_PATH") or app.config["APPLICATION_ROOT"]

    def get_cookie_httponly(self, app):
        return app.config.get("SESSION_COOKIE_HTTPONLY", True)

    def get_cookie_secure(self, app):
        return app.config.get("SESSION_COOKIE_SECURE", False)

    def get_cookie_samesite(self, app):
        return app.config.get("SESSION_COOKIE_SAMESITE")

    def get_expiration_time(self, app, session):
        if session.permanent:
            return datetime.now(timezone.utc) + app.permanent_session_lifetime
        return None

    def should_set_cookie(self, app, session):
        return session.modified or (
            not session.modified and session.accessed and app.config["SESSION_REFRESH_EACH_REQUEST"]
        )

    def open_session(self, app, request):
        return None

    def save_session(self, app, session, response):
        pass


class TaggedJSONSerializer:
    """A tiny JSON serializer handling dates/tuples similar to Flask's, via plain JSON."""

    def dumps(self, value):
        import json

        def default(o):
            if isinstance(o, datetime):
                return {" t": True, "y": o.year, "m": o.month, "d": o.day,
                        "h": o.hour, "mi": o.minute, "s": o.second}
            if isinstance(o, tuple):
                return {" t": "tuple", "v": list(o)}
            raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

        return json.dumps(value, separators=(",", ":"), default=default)

    def loads(self, data):
        import json

        def convert(o):
            if isinstance(o, dict) and " t" in o:
                if o[" t"] is True:
                    return datetime(o["y"], o["m"], o["d"], o["h"], o["mi"], o["s"])
                if o[" t"] == "tuple":
                    return tuple(o["v"])
            if isinstance(o, dict):
                return {k: convert(v) for k, v in o.items()}
            if isinstance(o, list):
                return [convert(v) for v in o]
            return o

        return convert(json.loads(data))


class _SessionKeyDerivation:
    """URL-safe base64 encoding helpers like itsdangerous."""

    @staticmethod
    def b64encode(data: bytes) -> bytes:
        import base64

        return base64.urlsafe_b64encode(data).rstrip(b"=")

    @staticmethod
    def b64decode(data: str) -> bytes:
        import base64

        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding)


class SecureCookieSessionInterface(SessionInterface):
    """Signs sessions with HMAC-SHA256 (itsdangerous-URLSafeHMAC compatible)."""

    salt = "cookie-session"
    serializer_class = TaggedJSONSerializer
    session_class = SecureCookieSession
    key_derivation = "hmac"
    digest_method = hashlib.sha256

    def get_signing_serializer(self, app):
        if not app.secret_key:
            return None
        signer = _Serializer(app.secret_key, self.salt, self.digest_method)
        return _SignedSerializer(signer, self.serializer_class())

    def open_session(self, app, request):
        s = self.get_signing_serializer(app)
        if s is None:
            return None
        val = request.cookies.get(self.get_cookie_name(app))
        if not val:
            return self.session_class()
        max_age = int(app.permanent_session_lifetime.total_seconds())
        try:
            data = s.loads(val, max_age=max_age)
            return self.session_class(data)
        except Exception:
            return self.session_class()
    def save_session(self, app, session, response):
        if not self.should_set_cookie(app, session):
            return
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        if not session:
            if session.modified:
                response.delete_cookie(self.get_cookie_name(app), path=path, domain=domain)
            return
        s = self.get_signing_serializer(app)
        if s is None:
            return
        expires = self.get_expiration_time(app, session)
        val = s.dumps(dict(session))
        response.set_cookie(
            self.get_cookie_name(app),
            val,
            expires=expires,
            httponly=self.get_cookie_httponly(app),
            domain=domain,
            path=path,
            secure=self.get_cookie_secure(app),
            samesite=self.get_cookie_samesite(app),
        )


class _Serializer:
    def __init__(self, key, salt, digest):
        self.key = key.encode() if isinstance(key, str) else key
        self.salt = (salt or "").encode()
        self.digest = digest

    def derive_key(self):
        return hashlib.sha256(self.key + self.salt).digest()

    def signature(self, value: bytes) -> bytes:
        key = self.derive_key()
        return hmac.new(key, value, self.digest).digest()

    def sign(self, value: bytes) -> bytes:
        sig = self.signature(value)
        return value + b"." + _SessionKeyDerivation.b64encode(sig)

    def unsign(self, signed: bytes):
        if b"." not in signed:
            raise ValueError("no signature found")
        value, _, sig = signed.rpartition(b".")
        expected = _SessionKeyDerivation.b64encode(self.signature(value))
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature mismatch")
        return value


class _SignedSerializer:
    def __init__(self, signer: _Serializer, serializer):
        self.signer = signer
        self.serializer = serializer

    def dumps(self, obj):
        payload = _SessionKeyDerivation.b64encode(self.serializer.dumps(obj).encode())
        return self.signer.sign(payload).decode("ascii")

    def loads(self, s, max_age=None):
        payload = self.signer.unsign(s.encode("ascii"))
        body = _SessionKeyDerivation.b64decode(payload.split(b".")[0].decode("ascii"))
        return self.serializer.loads(body.decode("utf-8"))


def generate_secret_key(n: int = 32) -> str:
    return secrets.token_hex(n)
