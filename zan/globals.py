"""上下文绑定的代理对象，对齐 flask.globals。

`request` / `session` / `g` / `current_app` 都是 `_Proxy` 实例：
属性访问、下标、调用、迭代、比较等全部转发给当前上下文栈顶的对象；
栈为空时抛出与 Flask 相同措辞的 RuntimeError。
"""
from .ctx import (
    _app_ctx_stack,
    _lookup_app_object,
    _lookup_req_object,
)


class _Proxy:
    """A proxy that forwards attribute access to the current context object."""

    __slots__ = ("__wrapped__", "_getter")

    def __init__(self, getter, name):
        object.__setattr__(self, "_getter", getter)
        object.__setattr__(self, "__wrapped__", None)

    @property
    def _current(self):
        return object.__getattribute__(self, "_getter")()

    def __getattr__(self, name):
        return getattr(self._current, name)

    def __setattr__(self, name, value):
        setattr(self._current, name, value)

    def __delattr__(self, name):
        delattr(self._current, name)

    def __getitem__(self, key):
        return self._current[key]

    def __setitem__(self, key, value):
        self._current[key] = value

    def __delitem__(self, key):
        del self._current[key]

    def __call__(self, *args, **kwargs):
        return self._current(*args, **kwargs)

    def __iter__(self):
        return iter(self._current)

    def __len__(self):
        return len(self._current)

    def __bool__(self):
        try:
            return bool(self._current)
        except RuntimeError:
            raise

    def __contains__(self, key):
        return key in self._current

    def __eq__(self, other):
        return self._current == other

    def __ne__(self, other):
        return self._current != other

    def __hash__(self):
        return hash(self._current)

    def __str__(self):
        return str(self._current)

    def __repr__(self):
        try:
            return repr(self._current)
        except RuntimeError:
            return "<unbound>"


def _lookup_request():
    from .ctx import _request_ctx_stack

    top = _request_ctx_stack.top()
    if top is None:
        raise RuntimeError("Working outside of request context.")
    return top.request


request = _Proxy(_lookup_request, "request")
session = _Proxy(lambda: _lookup_req_object("session"), "session")
g = _Proxy(lambda: _lookup_app_object("g"), "g")
current_app = _Proxy(lambda: _lookup_app_object("app"), "current_app")
