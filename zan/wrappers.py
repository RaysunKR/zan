"""请求与响应封装：API 对齐 flask.Request / flask.Response 及用户
常用的 werkzeug 部分（Headers、MultiDict、FileStorage、send_file）。

设计要点：
- `Request` 由 Rust 内核在调度时构造（构造参数与 `_zan` 约定一致），
  body 为已完整读取的 bytes
- `Response` 持有 bytes；`_fast()` 返回 `(status, headers, body)` 元组，
  是 Python 响应跨 FFI 回 Rust 的唯一通道
- `Headers` 是大小写不敏感的多值映射；`_MultiDict` 取值时首个优先，
  `getlist` 返回全部
"""
import io
import json as _json
import os
import typing as t
from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote, unquote

from .helpers import _dt_to_http, _get_reason

_crlf_re = None


def _detect_charset(content_type: t.Optional[str]) -> str:
    if not content_type:
        return "utf-8"
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part[8:].strip("\"'") or "utf-8"
    return "utf-8"


class FileStorage:
    """A minimal werkzeug FileStorage equivalent."""

    def __init__(self, stream, filename, name, content_type, headers=None):
        self.stream = stream
        self.filename = filename or "upload"
        self.name = name
        self.content_type = content_type or "application/octet-stream"
        self.headers = headers or {}
        # naive: assume the stream holds everything
        try:
            stream.seek(0, os.SEEK_END)
            self._size = stream.tell()
            stream.seek(0)
        except Exception:
            self._size = 0

    def read(self, *args):
        return self.stream.read(*args)

    def readline(self, *args):
        return self.stream.readline(*args)

    def readlines(self):
        return self.stream.readlines()

    def __iter__(self):
        return iter(self.stream)

    def __len__(self):
        return self._size

    def save(self, dst, buffer_size=16384):
        close_dst = False
        if isinstance(dst, str):
            dst = open(dst, "wb")
            close_dst = True
        try:
            copyfileobj(self.stream, dst, buffer_size)
        finally:
            if close_dst:
                dst.close()

    def seek(self, *args):
        return self.stream.seek(*args)

    def tell(self):
        return self.stream.tell()

    def close(self):
        self.stream.close()

    @property
    def content_length(self):
        return self._size


def copyfileobj(src, dst, length=16384):
    while True:
        buf = src.read(length)
        if not buf:
            break
        dst.write(buf)


class Headers:
    """Multi-map header collection with case-insensitive keys."""

    def __init__(self, items=None):
        self._list: t.List[t.Tuple[str, str]] = []
        if items:
            for k, v in items:
                self.add(k, v)

    def add(self, key, value):
        self._list.append((str(key), str(value)))

    def get(self, key, default=None, type=None):
        for k, v in self._list:
            if k.lower() == key.lower():
                if type is not None:
                    try:
                        return type(v)
                    except (ValueError, TypeError):
                        return default
                return v
        return default

    def get_all(self, key):
        return [v for k, v in self._list if k.lower() == key.lower()]

    def __contains__(self, key):
        return any(k.lower() == key.lower() for k, _ in self._list)

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key, value):
        self.set(key, value)

    def set(self, key, value):
        self.remove(key)
        self.add(key, value)

    def remove(self, key):
        self._list = [(k, v) for k, v in self._list if k.lower() != key.lower()]

    def clear(self):
        self._list.clear()

    def items(self):
        return list(self._list)

    def keys(self):
        return [k for k, _ in self._list]

    def values(self):
        return [v for _, v in self._list]

    def __len__(self):
        return len(self._list)

    def __iter__(self):
        return iter(self._list)

    def to_list(self):
        return list(self._list)

    def copy(self):
        h = Headers()
        h._list = list(self._list)
        return h

    def __repr__(self):
        return f"Headers({self._list!r})"

    def add_header(self, key, value):
        self.add(key, value)


class _MultiDict:
    """ werkzeug MultiDict subset used for args/form: first value wins for
    __getitem__/get, getlist returns all. """

    def __init__(self, pairs=()):
        self._pairs: t.List[t.Tuple[str, str]] = list(pairs)

    def get(self, key, default=None, type=None):
        for k, v in self._pairs:
            if k == key:
                if type is not None:
                    try:
                        return type(v)
                    except (ValueError, TypeError):
                        return default
                return v
        return default

    def getlist(self, key):
        return [v for k, v in self._pairs if k == key]

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            from .exceptions import BadRequestKeyError

            raise BadRequestKeyError(key)
        return v

    def __contains__(self, key):
        return any(k == key for k, _ in self._pairs)

    def __iter__(self):
        seen = set()
        for k, _ in self._pairs:
            if k not in seen:
                seen.add(k)
                yield k

    def items(self, multi=False):
        if multi:
            return list(self._pairs)
        seen = set()
        out = []
        for k, v in self._pairs:
            if k not in seen:
                seen.add(k)
                out.append((k, v))
        return out

    def values(self):
        seen = set()
        out = []
        for k, v in self._pairs:
            if k not in seen:
                seen.add(k)
                out.append(v)
        return out

    def keys(self):
        return list(self.__iter__())

    def lists(self):
        d: t.Dict[str, t.List[str]] = {}
        for k, v in self._pairs:
            d.setdefault(k, []).append(v)
        return list(d.items())

    def listitems(self):
        d: t.Dict[str, t.List[str]] = {}
        for k, v in self._pairs:
            d.setdefault(k, []).append(v)
        return d.items()

    def to_dict(self, flat=True):
        if flat:
            return dict(self.items())
        out: t.Dict[str, t.List[str]] = {}
        for k, v in self._pairs:
            out.setdefault(k, []).append(v)
        return out

    def __len__(self):
        return len(self.keys())

    def __eq__(self, other):
        if isinstance(other, _MultiDict):
            return self._pairs == other._pairs
        if isinstance(other, dict):
            return self.to_dict() == other
        return NotImplemented

    def __repr__(self):
        return f"MultiDict({self.items()!r})"


class CombinedMultiDict(_MultiDict):
    def __init__(self, dicts):
        pairs = []
        for d in dicts:
            pairs.extend(d._pairs if isinstance(d, _MultiDict) else d.items())
        super().__init__(pairs)


class Request:
    """The request object, one instance per request."""

    _fresh = False

    def __init__(
        self,
        method="GET",
        path="/",
        query_string="",
        query_pairs=None,
        headers=None,
        body=b"",
        remote_addr="127.0.0.1",
        endpoint=None,
        view_args=None,
        error_hint=None,
        allowed_methods=None,
    ):
        self.method = method
        self._path = path
        self.query_string = query_string
        self._query_pairs = query_pairs or []
        if headers and not isinstance(headers, Headers):
            headers = Headers(headers)
        self.headers = headers or Headers()
        self._body = body or b""
        self._remote = remote_addr
        self.endpoint = endpoint
        self.view_args = view_args
        self.routing_exception = None
        self.url_rule = None
        self.blueprint = None
        # error path metadata (fast-path 404/405)
        self._error_hint = error_hint
        self._allowed_methods = allowed_methods
        self.session = None
        self.flashes = []
        self._cached_json = (False, None)

    # -- URL parts ----------------------------------------------------------
    @property
    def path(self):
        return self._path

    @property
    def remote_addr(self):
        """客户端 IP。多进程模式下（或经反向代理时）优先取 X-Forwarded-For
        的第一个地址——父进程均衡器转发时会注入该头。"""
        if not hasattr(self, "_remote_final"):
            addr = self._remote
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                first = xff.split(",")[0].strip()
                if first:
                    addr = first
            self._remote_final = addr
        return self._remote_final

    @property
    def full_path(self):
        return f"{self.path}?{self.query_string}" if self.query_string else self.path + "?"

    @property
    def args(self):
        if not hasattr(self, "_args"):
            self._args = _MultiDict(self._query_pairs)
        return self._args

    @property
    def scheme(self):
        return "http"

    @property
    def host(self):
        return self.headers.get("Host", "localhost")

    @property
    def url_root(self):
        return f"{self.scheme}://{self.host}/"

    @property
    def base_url(self):
        return f"{self.scheme}://{self.host}{self.path}"

    @property
    def url(self):
        return f"{self.scheme}://{self.host}{self.full_path}".rstrip("?")

    @property
    def is_json(self):
        ct = self.content_type or ""
        return ct.startswith("application/json") or ct.endswith("+json")

    # -- body ----------------------------------------------------------------
    def get_data(self, cache=True, as_text=False):
        if as_text:
            return self._body.decode(self.charset, "replace")
        return self._body

    @property
    def data(self):
        return self.get_data()

    @property
    def charset(self):
        return _detect_charset(self.content_type)

    def get_json(self, force=False, silent=False):
        if not self.is_json and not force:
            return None
        if self._cached_json[0] is not False:
            cached = self._cached_json[1]
            if isinstance(cached, Exception):
                if silent:
                    return None
                raise cached
            return cached
        try:
            rv = _json.loads(self._body.decode(self.charset))
        except ValueError as e:
            if silent:
                rv = None
                self._cached_json = (True, e)
            else:
                self._cached_json = (True, e)
                raise
        else:
            self._cached_json = (True, rv)
        return rv

    @property
    def json(self):
        if not self.is_json:
            from .exceptions import BadRequest

            raise BadRequest("Did not attempt to load JSON because the request's Content-Type was not 'application/json'.")
        return self.get_json(force=True)

    @property
    def form(self):
        if not hasattr(self, "_form"):
            pairs: t.List[t.Tuple[str, str]] = []
            ct = self.content_type or ""
            if ct.startswith("application/x-www-form-urlencoded"):
                text = self._body.decode(self.charset, "replace")
                pairs = list(parse_qsl(text, keep_blank_values=True))
            self._form = _MultiDict(pairs)
        return self._form

    @property
    def files(self):
        if not hasattr(self, "_files"):
            pairs: t.List[t.Tuple[str, FileStorage]] = []
            ct = self.content_type or ""
            if ct.startswith("multipart/form-data"):
                try:
                    pairs = _parse_multipart(self._body, self.headers.get("Content-Type"))
                except Exception:
                    pairs = []
            self._files = _MultiDict([(k, v) for k, v in pairs])
        return self._files

    @property
    def values(self):
        return CombinedMultiDict([self.args, self.form])

    # -- headers --------------------------------------------------------------
    @property
    def content_type(self):
        return self.headers.get("Content-Type")

    @property
    def content_length(self):
        return self.headers.get("Content-Length", type=int) or len(self._body)

    @property
    def mimetype(self):
        return (self.content_type or "").split(";")[0].strip()

    @property
    def cookies(self):
        if not hasattr(self, "_cookies"):
            out = {}
            raw = self.headers.get("Cookie", "")
            for part in raw.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[unquote(k.strip())] = unquote(v.strip())
            self._cookies = _MultiDict(list(out.items()))
        return self._cookies

    @property
    def user_agent(self):
        raw = self.headers.get("User-Agent", "")
        return _UserAgent(raw)

    @property
    def authorization(self):
        raw = self.headers.get("Authorization")
        if not raw or " " not in raw:
            return None
        scheme, _, token = raw.partition(" ")
        return _Authorization(scheme.lower(), token.strip())

    @property
    def is_secure(self):
        return False

    @property
    def if_modified_since(self):
        raw = self.headers.get("If-Modified-Since")
        return _parse_http_datetime(raw)

    def __repr__(self):
        return f"<Request {self.method!r} {self.url!r}>"


class _UserAgent:
    def __init__(self, string):
        self.string = string

    def __str__(self):
        return self.string

    def __repr__(self):
        return f"<UserAgent {self.string!r}>"


class _Authorization:
    def __init__(self, type, token=None, username=None, password=None):
        self.type = type
        self.token = token
        self.username = username
        self.password = password

    def __repr__(self):
        return f"<Authorization {self.type}>"


class Response:
    """The response object. `zan` responses carry bytes; `status` accepts int
    or 'code reason'; `headers` accepts dict / list of tuples / Headers."""

    default_mimetype = "text/html"

    def __init__(self, response=None, status=None, headers=None, mimetype=None,
                 content_type=None, direct_passthrough=False):
        if response is None:
            response = b""
        self.response: t.List[bytes] = []
        self.set_data(response if isinstance(response, bytes) else str(response).encode("utf-8"))
        self.status_code = 200
        if status is not None:
            self.status = status
        self.headers = Headers()
        # merge explicit headers first so they win over defaults
        if headers:
            items = (
                headers.items()
                if isinstance(headers, (Headers, dict))
                else headers
            )
            for k, v in items:
                self.headers.set(k, v)
        ct = mimetype or content_type
        if ct:
            self.headers["Content-Type"] = ct
        elif self.headers.get("Content-Type") is None and not isinstance(
            response, (bytes, bytearray)
        ):
            self.headers["Content-Type"] = "text/html; charset=utf-8"

    # -- status ---------------------------------------------------------------
    @property
    def status_code(self):
        return self._status_code

    @status_code.setter
    def status_code(self, value):
        self._status_code = int(value)

    @property
    def status(self):
        return f"{self.status_code} {_get_reason(self.status_code)}"

    @status.setter
    def status(self, value):
        if isinstance(value, int):
            self.status_code = value
        else:
            digits = ""
            for ch in str(value):
                if ch.isdigit():
                    digits += ch
                else:
                    break
            self.status_code = int(digits or 200)

    @property
    def is_json(self):
        ct = self.headers.get("Content-Type", "")
        return ct.startswith("application/json") or ct.endswith("+json")

    # -- body -----------------------------------------------------------------
    def get_data(self, as_text=False):
        data = b"".join(self.response)
        if as_text:
            return data.decode(self.charset)
        return data

    def set_data(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.response = [data]

    @property
    def data(self):
        return self.get_data()

    @data.setter
    def data(self, value):
        self.set_data(value)

    def calculate_content_length(self):
        return len(self.get_data())

    @property
    def charset(self):
        return _detect_charset(self.headers.get("Content-Type"))

    def get_json(self, force=False, silent=False):
        if not (self.is_json or force):
            return None
        try:
            return _json.loads(self.get_data(as_text=True))
        except ValueError:
            if silent:
                return None
            raise

    @property
    def json(self):
        return self.get_json()

    @property
    def mimetype(self):
        return (self.headers.get("Content-Type") or "").split(";")[0].strip()

    @mimetype.setter
    def mimetype(self, value):
        self.headers.set("Content-Type", value)

    @property
    def content_type(self):
        return self.headers.get("Content-Type")

    @content_type.setter
    def content_type(self, value):
        self.headers.set("Content-Type", value)

    def set_cookie(self, key, value="", max_age=None, expires=None, path="/",
                   domain=None, secure=False, httponly=False, samesite=None):
        parts = [f"{key}={quote(value, safe='')}"]
        if expires is not None:
            if isinstance(expires, datetime):
                parts.append(f"Expires={_dt_to_http(expires)}")
            elif isinstance(expires, str):
                parts.append(f"Expires={expires}")
        if max_age is not None:
            parts.append(f"Max-Age={int(max_age)}")
        if domain:
            parts.append(f"Domain={domain}")
        if path is not None:
            parts.append(f"Path={path}")
        if secure:
            parts.append("Secure")
        if httponly:
            parts.append("HttpOnly")
        if samesite:
            parts.append(f"SameSite={samesite}")
        self.headers.add("Set-Cookie", "; ".join(parts))

    def delete_cookie(self, key, path="/", domain=None):
        self.set_cookie(key, expires=datetime(1970, 1, 1, tzinfo=timezone.utc), max_age=0,
                        path=path, domain=domain)

    # -- conversion used by the Rust core -------------------------------------
    def _fast(self):
        """Return (status, headers list, body bytes) for the Rust core."""
        length = self.calculate_content_length()
        headers = self.headers.to_list()
        if length is not None and self.status_code not in (204, 304):
            headers = [(k, v) for k, v in headers if k.lower() != "content-length"]
            headers.append(("Content-Length", str(length)))
        return (self.status_code, tuple(headers), self.get_data())

    def __iter__(self):
        yield self.get_data()

    def __repr__(self):
        return f"<Response {self.status}>"


def _parse_http_datetime(raw):
    """Parse 'Sun, 06 Nov 1994 08:49:37 GMT' into a UTC datetime."""
    if not raw:
        return None
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_multipart(body: bytes, content_type_header: str):
    """Very small multipart/form-data parser: fields + files."""
    boundary = None
    for part in (content_type_header or "").split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[9:].strip('"')
    if not boundary:
        return []
    delim = b"--" + boundary.encode()
    out = []
    chunks = body.split(delim)
    for chunk in chunks[1:-1]:
        chunk = chunk.strip(b"\r\n")
        if not chunk:
            continue
        if b"\r\n\r\n" in chunk:
            raw_headers, _, content = chunk.partition(b"\r\n\r\n")
        else:
            raw_headers, _, content = chunk, b"", chunk
        name = filename = None
        ctype = None
        for line in raw_headers.split(b"\r\n"):
            try:
                text = line.decode("utf-8", "replace")
            except Exception:
                continue
            tl = text.lower()
            if tl.startswith("content-disposition:"):
                for piece in text.split(";"):
                    piece = piece.strip()
                    if piece.startswith("name="):
                        name = piece[5:].strip('"')
                    elif piece.startswith("filename="):
                        filename = piece[9:].strip('"')
            elif tl.startswith("content-type:"):
                ctype = text.split(":", 1)[1].strip()
        if name is None:
            continue
        if filename is not None:
            fs = FileStorage(io.BytesIO(content), filename, name, ctype)
            out.append((name, fs))
        else:
            out.append((name, content.decode("utf-8", "replace")))
    return out


def send_file(path_or_buf, mimetype=None, as_attachment=False, download_name=None,
              conditional=True, etag=True, max_age=None, last_modified=None):
    """发送文件（本地路径或文件对象），与 ``flask.send_file`` 行为对齐。

    支持条件请求：客户端带 ``If-None-Match`` 命中 ETag 时返回 304。
    """
    import mimetypes

    if isinstance(path_or_buf, (str, bytes, os.PathLike)):
        path = os.fspath(path_or_buf)
        with open(path, "rb") as f:
            data = f.read()
        guessed, _ = mimetypes.guess_type(path)
        mt = mimetype or guessed or "application/octet-stream"
        default_name = os.path.basename(path)
        mtime = last_modified or os.path.getmtime(path)
    else:
        data = path_or_buf.read()
        mt = mimetype or "application/octet-stream"
        default_name = download_name or getattr(path_or_buf, "name", None)
        import time as _time

        mtime = last_modified or _time.time()
    resp = Response(data, mimetype=mt)
    if as_attachment:
        resp.headers.set(
            "Content-Disposition",
            f"attachment; filename={download_name or default_name}",
        )
    if max_age is not None:
        resp.headers.set("Cache-Control", f"public, max-age={int(max_age)}")
    resp.headers.set("Last-Modified", _dt_to_http(datetime.fromtimestamp(mtime, tz=timezone.utc)))
    if conditional and etag:
        import hashlib

        h = hashlib.sha1(data).hexdigest()
        resp.headers.set("ETag", f'"{h}"')

        # 条件请求：If-None-Match 命中 -> 304（清空 body，保留校验头）
        from .ctx import _request_ctx_stack

        ctx = _request_ctx_stack.top()
        if ctx is not None:
            inm = ctx.request.headers.get("If-None-Match")
            if inm and f'"{h}"' in inm:
                resp.status_code = 304
                resp.set_data(b"")
    return resp
