"""JSON 支持：app 上的 provider 对象 + 模块级 dumps/loads。

`DefaultJSONProvider` 对齐 Flask 2.3+ 的行为：键排序、ensure_ascii、
紧凑分隔符、datetime/date/UUID 的 default 序列化。
`tojson_filter` 是模板里 ``{{ x | tojson }}`` 用的过滤器，
会额外转义 ``< > & '`` 以便安全内嵌 HTML。
"""
import json as _json
import typing as t


class HeadersProxy:
    """Read-mostly header view over a list of tuples (test responses)."""

    def __init__(self, items):
        self._items = [(str(k), str(v)) for k, v in items]

    def get(self, key, default=None):
        for k, v in self._items:
            if k.lower() == key.lower():
                return v
        return default

    def get_all(self, key):
        return [v for k, v in self._items if k.lower() == key.lower()]

    def __contains__(self, key):
        return any(k.lower() == key.lower() for k, _ in self._items)

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def items(self):
        return list(self._items)

    def to_list(self):
        return list(self._items)

    def __len__(self):
        return len(self._items)

    def __repr__(self):
        return f"HeadersProxy({self._items!r})"


class DefaultJSONProvider:
    """Mirrors flask.json.provider.DefaultJSONProvider's surface."""

    sort_keys = True
    compact: t.Optional[bool] = None
    mimetype = "application/json"
    ensure_ascii = True

    def __init__(self, app):
        self.app = app

    def dumps(self, obj, **kwargs):
        kwargs.setdefault("default", self.default)
        kwargs.setdefault("sort_keys", self.sort_keys)
        kwargs.setdefault("ensure_ascii", self.ensure_ascii)
        if self.compact is None:
            kwargs.setdefault("separators", (",", ":"))
        return _json.dumps(obj, **kwargs)

    def loads(self, s, **kwargs):
        return _json.loads(s, **kwargs)

    def default(self, o):
        from datetime import date, datetime
        from uuid import UUID

        if isinstance(o, datetime):
            return o.strftime("%a, %d %b %Y %H:%M:%S GMT")
        if isinstance(o, date):
            return o.strftime("%a, %d %b %Y %H:%M:%S GMT")
        if isinstance(o, UUID):
            return str(o)
        if hasattr(o, "__html__"):
            return str(o.__html__())
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    def response(self, *args, **kwargs):
        obj = kwargs.pop("obj", None)
        if obj is None and args:
            if len(args) == 1:
                obj = args[0]
            else:
                obj = list(args)
        if obj is None:
            obj = kwargs or {}
        from .wrappers import Response

        return Response(
            self.dumps(obj),
            mimetype=self.mimetype,
        )


def dumps(obj, **kwargs):
    return _json.dumps(obj, **kwargs)


def loads(s, **kwargs):
    return _json.loads(s, **kwargs)


def tojson_filter(obj, **kwargs):
    """Jinja ``|tojson`` 过滤器：输出 JSON 并转义 HTML 安全字符。

    无 markupsafe 时退化为普通字符串（safe 标记丢失，但输出不变）。
    """
    kwargs.setdefault("separators", (",", ":"))
    rv = dumps(obj, **kwargs)
    # 转义 < > & ' 以便安全内嵌 <script>（与 Flask 的 tojson 相同）
    rv = (
        rv.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )
    try:
        from markupsafe import Markup

        return Markup(rv)
    except ImportError:
        return rv
