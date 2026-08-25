"""zan 应用的核心模块：提供与 ``flask.Flask`` 同名同行为的 ``Flask`` 类。

整体分为几块：

- 路由注册（``route``/``add_url_rule``）与 URL 构建（``url_for``）
- 请求调度（Rust fast path 直达视图；错误/未匹配走 Python 全量管线）
- 上下文与钩子（before/after/teardown request、before_first_request）
- 响应构造（``make_response``/``jsonify``）
- 运行（``run``，含 debug 重载器）与测试（``test_client``）
"""
import os
import sys
import time
import typing as t
import warnings
from datetime import timedelta
from threading import Lock
from urllib.parse import quote, urljoin

from . import json as _json_provider
from .json import DefaultJSONProvider as _DefaultJSONProvider
from .blueprints import Blueprint
from .ctx import AppContext, RequestContext, _app_ctx_stack, _request_ctx_stack
from .exceptions import (
    HTTPException,
    default_exceptions,
)
from .helpers import (
    _date_to_http,
    _endpoint_from_view_func,
    _get_reason,
    get_debug_flag,
)
from .session import SecureCookieSessionInterface, SessionInterface
from .signals import (
    appcontext_tearing_down,
    got_request_exception,
    request_finished,
    request_started,
    request_tearing_down,
)
from .templating import Environment as _TemplateEnvironment
from .wrappers import Request, Response

try:
    from . import _zan
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "the zan Rust extension (_zan) is not built; run `maturin develop --release`"
    ) from e


def _get_packagenme(name):  # pragma: no cover - compat shim
    return name


class _Config(dict):
    """dict with attribute access, mirroring flask.Config.from_pyfile etc."""

    def __init__(self, root_path, defaults=None):
        super().__init__(defaults or {})

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        self[name] = value

    def from_object(self, obj, silent=False):
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)

    def from_pyfile(self, filename, silent=False):
        d = {}
        path = filename if os.path.isabs(filename) else os.path.join(self.root_path, filename)
        try:
            with open(path, "rb") as f:
                exec(compile(f.read(), path, "exec"), d)
        except OSError:
            if silent:
                return False
            raise
        for k, v in d.items():
            if k.isupper():
                self[k] = v
        return True

    def from_envvar(self, variable_name, silent=False):
        path = os.environ.get(variable_name)
        if not path:
            if silent:
                return False
            raise RuntimeError(f"environment variable {variable_name} is not set")
        return self.from_pyfile(path, silent=silent)

    def from_mapping(self, *mapping, **kwargs):
        sources = []
        if len(mapping) == 1:
            d = mapping[0]
            if hasattr(d, "items"):
                sources.append(d)
            else:
                raise TypeError("mapping expected")
        elif mapping:
            raise TypeError("expected at most 1 positional argument")
        sources.append(kwargs)
        for src in sources:
            for k, v in src.items():
                if k.isupper():
                    self[k] = v
        return True

    def get_namespace(self, namespace, lowercase=True, trim_namespace=True):
        out = {}
        for k, v in self.items():
            if k.startswith(namespace):
                key = k[len(namespace):]
                if lowercase:
                    key = key.lower()
                if trim_namespace:
                    key = key.lstrip("_")
                out[key] = v
        return out


class _TestClient:
    def __init__(self, app):
        self.app = app
        self.cookie_jar: dict = {}

    def _open(self, method, url, headers=None, data=None, json=None):
        hdrs = []
        if headers:
            if isinstance(headers, dict):
                headers = list(headers.items())
            hdrs = [(k, v) for k, v in headers]
        if self.cookie_jar:
            hdrs.append(("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookie_jar.items())))
        body = b""
        if data is not None:
            if isinstance(data, str):
                body = data.encode()
            elif isinstance(data, bytes):
                body = data
            elif isinstance(data, dict):
                from urllib.parse import urlencode

                body = urlencode(data).encode()
                hdrs.append(("Content-Type", "application/x-www-form-urlencoded"))
        if json is not None:
            import json as _jsonlib

            body = _jsonlib.dumps(json).encode()
            hdrs.append(("Content-Type", "application/json"))
        status, rheaders, rbody = self.app._ensure_server().test_request(method, url, hdrs, body)
        resp = _TestResponse(status, rheaders, rbody)
        # store Set-Cookie in the jar (simple client-side emulation)
        from .wrappers import Headers as _H

        for k, v in rheaders:
            if k.lower() == "set-cookie" and "=" in v.split(";")[0]:
                pair = v.split(";")[0]
                ck, _, cv = pair.partition("=")
                if cv == "":
                    self.cookie_jar.pop(ck.strip(), None)
                else:
                    self.cookie_jar[ck.strip()] = cv
        return resp

    def get(self, url, **kw):
        return self._open("GET", url, **kw)

    def post(self, url, **kw):
        return self._open("POST", url, **kw)

    def put(self, url, **kw):
        return self._open("PUT", url, **kw)

    def patch(self, url, **kw):
        return self._open("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._open("DELETE", url, **kw)

    def head(self, url, **kw):
        return self._open("HEAD", url, **kw)

    def options(self, url, **kw):
        return self._open("OPTIONS", url, **kw)

    def open(self, *args, **kwargs):
        if len(args) == 2 and isinstance(args[0], str):
            return self._open(args[0], args[1], **kwargs)
        if args and isinstance(args[0], str):
            return self._open("GET", args[0], **kwargs)
        raise TypeError("open(method, url, **kwargs)")


class _TestResponse:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = _json_provider.HeadersProxy(headers)
        self.body = bytes(body)

    @property
    def status(self):
        return f"{self.status_code} {_get_reason(self.status_code)}"

    @property
    def data(self):
        return self.body

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    def get_json(self, silent=False, force=False):
        import json as _jsonlib

        try:
            return _jsonlib.loads(self.text)
        except ValueError:
            if silent:
                return None
            raise

    @property
    def json(self):
        return self.get_json(silent=True)

    @property
    def content_type(self):
        return self.headers.get("Content-Type", "")

    @property
    def mimetype(self):
        return self.content_type.split(";")[0].strip()

    @property
    def is_json(self):
        return "json" in self.content_type

    def __repr__(self):
        return f"<TestResponse {self.status_code} [{len(self.body)} bytes]>"


class _AppCtxGlobals(dict):
    """flask.g default class: dict with attribute access."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def get(self, name, default=None):
        return dict.get(self, name, default)

    def pop(self, name, default=None):
        return dict.pop(self, name, default)

    def setdefault(self, name, default=None):
        return dict.setdefault(self, name, default)


class Flask:
    """The zan application object. API-compatible with flask.Flask."""

    #: the class of the objects passed to views / used internally
    request_class = Request
    response_class = Response
    jinja_environment = _TemplateEnvironment
    app_ctx_globals_class = _AppCtxGlobals
    session_interface: SessionInterface = SecureCookieSessionInterface()

    default_config = {
        "DEBUG": False,
        "TESTING": False,
        "SECRET_KEY": None,
        "SESSION_COOKIE_NAME": "session",
        "SESSION_COOKIE_DOMAIN": None,
        "SESSION_COOKIE_PATH": None,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_SAMESITE": None,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
        "SESSION_REFRESH_EACH_REQUEST": True,
        "MAX_CONTENT_LENGTH": None,
        "SEND_FILE_MAX_AGE_DEFAULT": None,
        "TRAP_HTTP_EXCEPTIONS": False,
        "TRAP_BAD_REQUEST_ERRORS": True,  # newer flask default (KeyError shows message)
        "APPLICATION_ROOT": "/",
        "SERVER_NAME": None,
        "PREFERRED_URL_SCHEME": "http",
        "JSON_AS_ASCII": True,
        "JSON_SORT_KEYS": True,
        "JSONIFY_MIMETYPE": "application/json",
        "TEMPLATES_AUTO_RELOAD": None,
        "EXPLAIN_TEMPLATE_LOADING": False,
        "MAX_COOKIE_SIZE": 4093,
        "FLOWER_VERBOSE_ERROR": None,
    }

    def __init__(
        self,
        import_name: str,
        static_url_path: t.Optional[str] = None,
        static_folder: t.Optional[str] = "static",
        static_host=None,
        host_matching=False,
        subdomain_matching=False,
        template_folder: t.Optional[str] = "templates",
        instance_path=None,
        instance_relative_config=False,
        root_path=None,
    ):
        self.import_name = import_name
        self.static_url_path = static_url_path
        self.static_folder = static_folder
        self.template_folder = template_folder
        self.instance_path = instance_path
        self.debug = False
        self.testing = False

        # locate root_path like Flask does
        if root_path is not None:
            self.root_path = root_path
        else:
            mod = sys.modules.get(import_name)
            if mod is not None and hasattr(mod, "__file__"):
                self.root_path = os.path.dirname(os.path.abspath(mod.__file__))
            else:
                self.root_path = os.getcwd()

        self.config = _Config(self.root_path)
        self.config.update(self.default_config)

        # routing structures
        self.url_map = {}  # rule string -> endpoint
        self.view_functions: t.Dict[str, t.Callable] = {}
        self._rules: t.Dict[str, t.Dict] = {}  # rule -> meta
        self.error_handler_spec: t.Dict[t.Optional[str], t.Dict] = {}
        self.before_request_funcs: t.Dict[t.Optional[str], t.List] = {None: []}
        self.after_request_funcs: t.Dict[t.Optional[str], t.List] = {None: []}
        self.teardown_request_funcs: t.Dict[t.Optional[str], t.List] = {None: []}
        self.teardown_appcontext_funcs: t.List = []
        self.url_default_functions: t.Dict[t.Optional[str], t.List] = {None: []}
        self.template_context_processors: t.Dict[t.Optional[str], t.List] = {None: []}
        self.blueprints: t.Dict[str, "Blueprint"] = {}
        self._blueprint_order: t.List[str] = []
        self.extensions: t.Dict[str, t.Any] = {}
        self.cli = _CLI(self)
        self._got_first_request = False
        self.before_first_request_funcs: t.List[t.Callable] = []
        self._lock = Lock()

        self.jinja_env = self.jinja_environment(self)
        self.json = _DefaultJSONProvider(self)

        # 静态目录列表（应用自身的 + 各蓝图注册进来的），由 Rust 内核服务
        self._static_folders: t.List[t.Tuple[str, str]] = []
        if self.static_folder is not None:
            folder = self.static_folder
            if not os.path.isabs(folder):
                folder = os.path.join(self.root_path, folder)
            if os.path.isdir(folder):
                prefix = self.static_url_path
                if prefix is None:
                    prefix = "/static"
                self._static_folders.append((prefix, folder))

        self._server = None

    def _add_static_folder(self, url_prefix: str, folder: str) -> None:
        """注册一个静态目录（应用或蓝图均可调用）。

        同一 URL 前缀重复注册时后者覆盖前者，与 Flask 的路由优先级一致。
        """
        self._static_folders = [
            (p, f) for p, f in self._static_folders if p != url_prefix
        ]
        self._static_folders.append((url_prefix, folder))
        self._server = None  # 使已编译的 server 失效，强制重建

    # ------------------------------------------------------------------
    # configuration
    # ------------------------------------------------------------------
    @property
    def secret_key(self):
        return self.config.get("SECRET_KEY")

    @secret_key.setter
    def secret_key(self, value):
        self.config["SECRET_KEY"] = value

    def get_send_file_max_age(self, filename):
        rv = self.config["SEND_FILE_MAX_AGE_DEFAULT"]
        return rv

    @property
    def permanent_session_lifetime(self):
        return self.config["PERMANENT_SESSION_LIFETIME"]

    def create_jinja_environment(self):
        return self.jinja_env

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------
    def add_url_rule(
        self,
        rule: str,
        endpoint: t.Optional[str] = None,
        view_func=None,
        provide_automatic_options: t.Optional[bool] = None,
        **options,
    ):
        """注册一条 URL 规则（`@app.route` 的底层实现）。

        :param rule: URL 规则，如 ``/user/<int:uid>``
        :param endpoint: 端点名；缺省用视图函数名
        :param view_func: 视图函数
        :param methods: 允许的方法列表（默认 ``["GET"]``，HEAD 随 GET）
        :param provide_automatic_options: 是否自动处理 OPTIONS（默认 True）
        """
        if view_func is not None and endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)
        if endpoint is None:
            raise TypeError("add_url_rule requires either a view_func or an endpoint")
        methods = options.pop("methods", None)
        if methods is None:
            methods = getattr(view_func, "methods", None) or ("GET",)
        if isinstance(methods, str):
            raise TypeError("methods must be a list of strings")
        methods = sorted({m.upper() for m in methods})
        if provide_automatic_options is None:
            auto_options = getattr(view_func, "provide_automatic_options", None)
            provide_automatic_options = auto_options if auto_options is not None else True
        if "HEAD" not in methods and "GET" in methods:
            methods = list(methods)
            # HEAD is implicit via GET
        # 同一 rule 重复注册（Flask 允许 GET/POST 分开两个函数写）：
        # 自动生成按方法分发的合并视图，保留各 endpoint 的独立函数。
        existing = self._rules.get(rule)
        if existing is not None and existing["endpoint"] != endpoint:
            old_endpoint = existing["endpoint"]
            new_entry = {
                "endpoint": endpoint,
                "methods": sorted(set(existing["methods"]) | set(methods)),
                "auto_options": provide_automatic_options
                or existing["auto_options"],
                # 每个方法 -> 原始 endpoint 的映射，供合并视图分发
                "method_map": {
                    **existing.get("method_map", {
                        m: old_endpoint for m in existing["methods"]
                    }),
                    **{m: endpoint for m in methods},
                },
            }
            dispatch_ep = f"{rule}#dispatch"
            if view_func is not None:
                # 新 endpoint 的原始函数也要登记（url_for/直接调用仍可用）
                old = self.view_functions.get(endpoint)
                if old is not None and old is not view_func:
                    raise AssertionError(
                        f"View function mapping is overwriting an existing endpoint function: {endpoint}"
                    )
                self.view_functions[endpoint] = view_func
            self.view_functions[dispatch_ep] = self._make_method_dispatcher(
                new_entry["method_map"]
            )
            self.url_map[rule] = dispatch_ep
            new_entry["endpoint"] = dispatch_ep
            self._rules[rule] = new_entry
            self._server = None
            self._got_first_request = False
            return
        self.url_map[rule] = endpoint
        if view_func is not None:
            old = self.view_functions.get(endpoint)
            if old is not None and old is not view_func:
                raise AssertionError(
                    f"View function mapping is overwriting an existing endpoint function: {endpoint}"
                )
            self.view_functions[endpoint] = view_func
        self._rules[rule] = {
            "endpoint": endpoint,
            "methods": methods,
            "auto_options": provide_automatic_options,
        }
        self._server = None  # invalidate compiled server
        self._got_first_request = False

    def _make_method_dispatcher(self, method_map: dict):
        """生成按 HTTP 方法分发到原 endpoint 视图的合并视图。"""

        def dispatch(**kwargs):
            from .globals import request

            ep = method_map.get(request.method) or method_map.get("GET")
            if ep is None:
                from .exceptions import MethodNotAllowed

                raise MethodNotAllowed(valid_methods=sorted(method_map))
            return self.view_functions[ep](**kwargs)

        return dispatch
        self._server = None  # invalidate compiled server
        self._got_first_request = False

    def route(self, rule: str, **options):
        """装饰器版 ``add_url_rule``：``@app.route("/path")``。"""

        def decorator(f):
            endpoint = options.pop("endpoint", None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f

        return decorator

    def url_for(self, endpoint: str, **values) -> str:
        """把 endpoint 与参数构建成 URL。

        - ``url_for('static', filename='app.js')`` → ``/static/app.js``
        - 支持 ``_anchor`` / ``_external`` / ``_scheme``
        - 蓝图 endpoint（``api.users``）自动带上 url_prefix
        - 缺少参数时抛出 :class:`zan.app.BuildError`
        """
        anchor = values.pop("_anchor", None)
        external = values.pop("_external", False)
        scheme = values.pop("_scheme", None)
        values.pop("_method", None)

        # static 端点：直接由静态目录配置构建
        if endpoint == "static" and self.has_static_folder:
            filename = values.pop("filename", "")
            prefix = self.static_url_path or "/static"
            url = "/".join((prefix.rstrip("/"), str(filename).lstrip("/")))
            if anchor:
                url += "#" + quote(str(anchor))
            if external:
                host = self.config.get("SERVER_NAME") or "localhost"
                url = f"{scheme or 'http'}://{host}{url}"
            return url

        # app- or blueprint-prefixed endpoint
        suffix = ""
        bp_name = None
        if "." in endpoint:
            bp_name, _, suffix = endpoint.partition(".")

        # url_defaults from blueprints
        if bp_name and bp_name in self.blueprints:
            for k, v in self.blueprints[bp_name].url_defaults.items():
                values.setdefault(k, v)
        for funcs in self.url_default_functions.values():
            for f in funcs:
                rv = f(endpoint, values)
                if rv:
                    values.update(rv)

        # find the rule that matches this endpoint
        target = None
        for rule, meta in self._rules.items():
            if meta["endpoint"] == endpoint:
                target = rule
                if not self._rule_missing_values(rule, values):
                    break
        if target is None:
            raise BuildError(endpoint, values)

        url = self._build_path(target, values)
        # 注意：self._rules 中的规则已包含蓝图的 url_prefix
        #（蓝图注册时通过 BlueprintSetupState.add_url_rule 拼接），
        # 因此这里不需要再次添加前缀。
        if anchor:
            url += "#" + quote(str(anchor))
        if external:
            host = self.config.get("SERVER_NAME") or "localhost"
            url = f"{scheme or 'http'}://{host}{url}"
        return url

    def _rule_missing_values(self, rule, values):
        parts = rule.split("/")
        for p in parts:
            if p.startswith("<") and p.endswith(">"):
                inner = p[1:-1]
                name = inner.split(":")[-1]
                if name not in values:
                    return True
        return False

    def _build_path(self, rule: str, values) -> str:
        out = []
        for seg in rule.split("/"):
            if seg.startswith("<") and seg.endswith(">"):
                inner = seg[1:-1]
                if ":" in inner:
                    _, name = inner.rsplit(":", 1)
                else:
                    name = inner
                if name not in values:
                    raise BuildError(rule, values)
                out.append(quote(str(values[name]), safe=""))
            else:
                out.append(seg)
        path = "/".join(out)
        if not path.startswith("/"):
            path = "/" + path
        return path

    # ------------------------------------------------------------------
    # hooks registration
    # ------------------------------------------------------------------
    def before_request(self, f):
        """注册请求前置钩子：返回非 None 即短路为响应。"""
        self.before_request_funcs[None].append(f)
        return f

    def after_request(self, f):
        """注册响应后置钩子：接收并返回 Response，逆序执行。"""
        self.after_request_funcs[None].append(f)
        return f

    def teardown_request(self, f):
        """注册请求销毁钩子：无论成功失败都执行，参数为异常或 None。"""
        self.teardown_request_funcs[None].append(f)
        return f

    def teardown_appcontext(self, f):
        self.teardown_appcontext_funcs.append(f)
        return f

    def context_processor(self, f):
        self.template_context_processors[None].append(f)
        return f

    def blueprint_context_processor(self, bp_name):
        def decorator(f):
            self.template_context_processors.setdefault(bp_name, []).append(f)
            return f

        return decorator

    def url_defaults(self, f):
        self.url_default_functions[None].append(f)
        return f

    def register_error_handler(self, code_or_exception, f, blueprint=None):
        if isinstance(code_or_exception, int):
            self.error_handler_spec.setdefault(blueprint, {}).setdefault("code", {})[code_or_exception] = f
        else:
            self.error_handler_spec.setdefault(blueprint, {}).setdefault("exc", {})[code_or_exception] = f

    def errorhandler(self, code_or_exception):
        """装饰器版 register_error_handler：按状态码或异常类注册。"""

        def decorator(f):
            self.register_error_handler(code_or_exception, f)
            return f

        return decorator

    def register_blueprint(self, blueprint: Blueprint, **options):
        """注册蓝图。可传 ``url_prefix=`` 覆盖蓝图自身的前缀。"""
        first_registration = blueprint.name not in self.blueprints
        self.blueprints[blueprint.name] = blueprint
        self._blueprint_order.append(blueprint.name)
        blueprint.register(self, options, first_registration)
        self._server = None
        self._got_first_request = False

    # ------------------------------------------------------------------
    # request dispatch internals
    # ------------------------------------------------------------------
    def _find_error_handler(self, e, blueprint=None):
        """Walk app + blueprint handlers, most specific first."""
        exc_class = e if isinstance(e, type) else type(e)
        code = getattr(e, "code", None)
        for bp_name in (blueprint, None):
            spec = self.error_handler_spec.get(bp_name, {})
            if code is not None:
                h = spec.get("code", {}).get(code)
                if h is not None:
                    return h
            exc_map = spec.get("exc", {})
            for cls in exc_class.__mro__:
                h = exc_map.get(cls)
                if h is not None:
                    return h
        return None

    def _pipeline(self, request, view, view_args):
        """Fast path: contexts + hooks + view, without full re-dispatch."""
        self._set_request_meta(request)
        request._current_view = view
        if view_args is not None:
            request.view_args = view_args
        app_ctx = AppContext(self)
        app_ctx.push()
        req_ctx = RequestContext(self, request, request.endpoint, request.view_args)
        req_ctx.push()
        error = None
        try:
            request_started.send(self)
            try:
                rv = self._dispatch_hooks_and_view(request, view, view_args)
            except Exception as e:
                error = e
                rv = self._handle_user_exception(e, request)
            response = self.make_response(rv)
            response = self._process_response(response, request)
            request_finished.send(self, response=response)
            req_ctx.response = response
            return response
        finally:
            request_tearing_down.send(self)
            self._run_teardown(error)
            req_ctx.pop()
            app_ctx.pop()

    def _set_request_meta(self, request):
        """Derive blueprint from endpoint ('api.users' -> 'api')."""
        if request.endpoint and "." in request.endpoint:
            request.blueprint = request.endpoint.split(".", 1)[0]
        else:
            request.blueprint = None

    def _run_teardown(self, error):
        for name in list(self.teardown_request_funcs):
            for f in self.teardown_request_funcs.get(name, []):
                try:
                    f(error)
                except Exception:
                    self.logger.exception("Error in teardown_request handler")

    def _process(self, request):
        """Full dispatch: used for error fallbacks and unmatched routes."""
        self._set_request_meta(request)
        app_ctx = AppContext(self)
        app_ctx.push()
        req_ctx = RequestContext(self, request)
        req_ctx.push()
        error = None
        try:
            request_started.send(self)
            try:
                if request._error_hint == "404":
                    from .exceptions import NotFound

                    raise NotFound()
                if request._error_hint == "405":
                    from .exceptions import MethodNotAllowed

                    raise MethodNotAllowed(valid_methods=request._allowed_methods)
                raise NotImplementedError
            except Exception as e:
                error = e
                rv = self._handle_user_exception(e, request)
            response = self.make_response(rv)
            response = self._process_response(response, request)
            request_finished.send(self, response=response)
            req_ctx.response = response
            return response
        finally:
            request_tearing_down.send(self)
            self._run_teardown(error)
            req_ctx.pop()
            app_ctx.pop()

    def _dispatch_hooks_and_view(self, request, view, view_args):
        """运行 before_request 钩子后调用视图。

        任何一个 before_request 返回非 None 即短路（其返回值作为响应体），
        与 Flask 的语义一致。
        """
        self._ensure_before_first_request()
        bp_name = request.blueprint
        for name in (bp_name, None):
            for f in self.before_request_funcs.get(name, ()):
                rv = f()
                if rv is not None:
                    return rv
        return view(**view_args)

    def dispatch_request(self):
        """Flask 兼容：调度当前请求上下文中的视图，返回视图返回值。

        在请求上下文中可调用（例如在 before_request 中检查后手动调度）。
        """
        ctx = _request_ctx_stack.top()
        if ctx is None:
            raise RuntimeError("dispatch_request() 需要活动的请求上下文")
        req = ctx.request
        return self._dispatch_hooks_and_view(req, req._current_view, req.view_args or {})

    def _ensure_before_first_request(self):
        """第一次收到请求时按注册顺序执行 before_first_request 钩子。"""
        if not self._got_first_request:
            with self._lock:
                if not self._got_first_request:
                    for f in self.before_first_request_funcs:
                        f()
                    self._got_first_request = True

    def before_first_request(self, f):
        """注册「首个请求前」执行一次的钩子（Flask 2.2 前的 API）。"""
        self.before_first_request_funcs.append(f)
        return f

    def _handle_user_exception(self, e, request):
        """把视图抛出的异常转换成响应值，或原样重新抛出。"""
        if isinstance(e, HTTPException):
            # TRAP_HTTP_EXCEPTIONS=True 时 HTTPException 也不吞掉，直接抛出
            if self.config.get("TRAP_HTTP_EXCEPTIONS"):
                raise e
            handler = self._find_error_handler(e, request.blueprint)
            if handler is not None:
                rv = handler(e)
                if rv is not None:
                    return rv
            return e
        handler = self._find_error_handler(e, request.blueprint)
        got_request_exception.send(self, exception=e)
        if handler is not None:
            rv = handler(e)
            if rv is not None:
                return rv
        raise e

    def _process_response(self, response, request):
        bp_name = request.blueprint
        # after_request in reverse registration order, app after blueprint
        for name in (bp_name, None):
            funcs = self.after_request_funcs.get(name, [])
            for f in reversed(funcs):
                response = f(response)
        return response

    def full_dispatch_request(self):
        """Flask-compat: dispatch using the current request context."""
        request = _request_ctx_stack.top().request
        try:
            rv = self._dispatch_hooks_and_view(request, request._current_view, request.view_args or {})
        except Exception as e:
            rv = self._handle_user_exception(e, request)
        return rv

    # ------------------------------------------------------------------
    # responses
    # ------------------------------------------------------------------
    def make_response(self, rv):
        """把视图返回值转换成 Response 对象。

        支持的返回类型（与 Flask 一致）::

            str            → text/html
            bytes          → application/octet-stream
            dict / list    → JSON（键排序、ensure_ascii）
            Response       → 原样
            HTTPException  → get_response()
            生成器          → 拼接为 body
            (body, status[, headers]) 元组
        """
        status = headers = None
        if isinstance(rv, tuple):
            if len(rv) == 3:
                rv, status, headers = rv
            elif len(rv) == 2:
                rv, status = rv
            elif len(rv) == 1:
                (rv,) = rv
            else:
                raise TypeError(
                    "The view function did not return a valid response tuple."
                    " The tuple must have the form (body, status, headers),"
                    " (body, status), or (body, headers)."
                )
        if isinstance(rv, HTTPException):
            rv = rv.get_response()
        if isinstance(rv, (list, dict)):
            rv = self.json.response(rv)
        if not isinstance(rv, (Response, str, bytes, bytearray)):
            if hasattr(rv, "__iter__") and not isinstance(rv, str):
                rv = Response(b"".join(chunk if isinstance(chunk, bytes) else str(chunk).encode() for chunk in rv))
            else:
                raise TypeError(
                    f"The view function did not return a valid response. The"
                    f" function either returned None or ended without a return"
                    f" statement. (type: {type(rv).__name__})"
                )
        if isinstance(rv, (str, bytes, bytearray)):
            rv = Response(rv)
        if status is not None:
            if isinstance(status, (int, str)):
                rv.status = status
            else:
                raise TypeError("Invalid status argument")
        if headers:
            if isinstance(headers, dict):
                headers = list(headers.items())
            for k, v in headers:
                rv.headers.set(k, v)
        return rv

    def jsonify(self, *args, **kwargs):
        """返回 JSON Response：``jsonify(a=1)`` 或 ``jsonify([1,2])``。"""
        if args and kwargs:
            raise TypeError("jsonify() behavior undefined when passed both args and kwargs")
        elif len(args) == 1:
            obj = args[0]
        elif args:
            obj = list(args)
        else:
            obj = kwargs
        return self.json.response(obj)

    # ------------------------------------------------------------------
    # contexts
    # ------------------------------------------------------------------
    def app_context(self):
        return AppContext(self)

    def request_context(self, environ_or_request):
        """Accept a zan Request or URL string."""
        return self.test_request_context(environ_or_request)

    def test_request_context(self, *args, **kwargs):
        if not args:
            return RequestContext(self, Request())
        first = args[0]
        if isinstance(first, Request):
            return RequestContext(self, first, *args[1:], **kwargs)
        if isinstance(first, str):
            url = first
            path, _, qs = url.partition("?")
            from urllib.parse import parse_qsl

            from .wrappers import Headers

            req = Request(
                method=kwargs.pop("method", "GET"),
                path=path,
                query_string=qs,
                query_pairs=list(parse_qsl(qs, keep_blank_values=True)),
                headers=Headers(),
                body=b"",
            )
            return RequestContext(self, req)
        raise TypeError("test_request_context expects a URL string or Request")

    # ------------------------------------------------------------------
    # running
    # ------------------------------------------------------------------
    def run(self, host=None, port=None, debug=None, load_dotenv=True, **options):
        """运行服务器（Rust 内核）。

        参数与 ``flask.Flask.run`` 一致：

        :param host: 监听地址，默认 ``127.0.0.1``；``0.0.0.0`` 对外开放
        :param port: 端口，默认 5000（或环境变量 ``FLASK_RUN_PORT``）
        :param debug: 调试模式；None 时读 ``FLASK_DEBUG``
        :param processes: **worker 进程数**。>1 时启用多进程模式：
            本进程只运行 TCP 负载均衡器（Rust），N 个 worker 子进程
            各自独立 GIL 真正并行执行 Python 视图——充分利用多核。
            每个请求经转发自动携带真实客户端 IP（X-Forwarded-For）。
        :param options: ``use_reloader``（默认随 debug）、``extra_files`` 等
        """
        if host is None:
            host = "127.0.0.1"
        if port is None:
            port = int(os.environ.get("FLASK_RUN_PORT", 5000))
        if debug is None:
            debug = get_debug_flag()
        self.debug = bool(debug)
        self.config["DEBUG"] = self.debug

        processes = options.pop("processes", None) or 1
        use_reloader = options.pop("use_reloader", None)
        if use_reloader is None:
            use_reloader = self.debug and processes <= 1
        extra_files = options.pop("extra_files", None)
        options.pop("threaded", None)
        options.pop("banner", None)

        from .debug import Reloader

        # 多进程模式中的 worker 子进程：只服务分配的本地端口，
        # 公共端口由父进程的均衡器持有
        if os.environ.get("ZAN_WORKER") == "1":
            wport = int(os.environ.get("ZAN_WORKER_PORT", port))
            server = self._ensure_server()
            server.run("127.0.0.1", wport)
            return

        if use_reloader and Reloader.is_main_process():
            Reloader(extra_files).run_with_reloading(None)
            return

        from .debug import _ColorStream

        err = _ColorStream(sys.stderr)
        if processes > 1:
            self._run_multi_process(host, port, processes, err)
            return

        err.info(f"zan {self.import_name!r} 启动")
        err.info(
            f"调试模式：{'开启（重载器' + ('运行中）' if use_reloader else '关闭）') if self.debug else '关闭'}"
        )
        server = self._ensure_server()
        banner = lambda addr: (
            err.info(f"地址: http://{addr if ':' in addr else host + ':' + str(port)}"),
            err.info("按 CTRL+C 退出"),
        )
        addr = server.run(host, port, 0, banner)
        return addr

    def _run_multi_process(self, host: str, port: int, processes: int, err) -> None:
        """多进程模式：父进程 = TCP 均衡器；N 个 worker 子进程各持独立 GIL。

        worker 通过环境变量 ``ZAN_WORKER=1`` 与 ``ZAN_WORKER_PORT`` 识别
        自己的角色：worker 不运行均衡器，只在 127.0.0.1 的分配端口上
        服务；父进程把对外端口的连接 round-robin 转发过来。
        """
        import multiprocessing as _mp
        import socket
        import subprocess

        def free_port() -> int:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            p = s.getsockname()[1]
            s.close()
            return p

        worker_env_base = os.environ.copy()
        worker_env_base.pop("ZAN_RUN_MAIN", None)

        # worker 子进程：同脚本同参数，以 ZAN_WORKER 环境变量区分角色
        worker_ports = []
        procs = []
        for _ in range(processes):
            wport = free_port()
            env = worker_env_base.copy()
            env["ZAN_WORKER"] = "1"
            env["ZAN_WORKER_PORT"] = str(wport)
            env["ZAN_WORKER_PUBLIC"] = f"{host}:{port}"
            proc = subprocess.Popen(
                [sys.executable, "-u", *sys.argv],
                env=env,
                cwd=os.getcwd(),
            )
            worker_ports.append(wport)
            procs.append(proc)

        err.info(f"zan 多进程模式：{processes} 个 worker + 均衡器")
        for i, proc in enumerate(procs):
            err.info(f"  worker-{i}: 127.0.0.1:{worker_ports[i]} (pid {proc.pid})")
        err.info(f"地址: http://{host}:{port}")
        err.info("按 CTRL+C 退出")

        # 等待 worker 就绪（端口可连）
        deadline = time.time() + 30
        for wport in worker_ports:
            while time.time() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", wport), timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.1)

        server = self._ensure_server()
        try:
            server.run_balancer(
                host, port, [f"127.0.0.1:{p}" for p in worker_ports]
            )
        finally:
            for proc in procs:
                if proc.poll() is None:
                    proc.terminate()
            for proc in procs:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    # ------------------------------------------------------------------
    # 非阻塞生命周期：多实例共存
    # ------------------------------------------------------------------

    def start(self, host="127.0.0.1", port=0):
        """非阻塞启动服务器（可同时启动多个实例，各监听不同端口）。

        返回 ``(server_id, addr)``；用 :meth:`stop` 停止。
        典型用法::

            sid, addr = app.start(port=0)      # 随机可用端口
            ...
            app.stop(sid)
        """
        server = self._ensure_server()
        sid = server.start(host, int(port))
        return sid, server.bound_addr(sid)

    def stop(self, server_id, timeout=5) -> bool:
        """停止 :meth:`start` 启动的服务器实例。"""
        return self._ensure_server().stop(server_id, timeout)

    def bound_addr(self, server_id):
        """查询运行中实例的绑定地址。"""
        return self._ensure_server().bound_addr(server_id)

    def _ensure_server(self):
        if self._server is not None:
            return self._server
        srv = _zan.Server()
        for rule, meta in self._rules.items():
            view = self.view_functions.get(meta["endpoint"])
            srv.add_rule(rule, meta["methods"], view, meta["endpoint"], meta["auto_options"])
        srv.set_request_class(self.request_class)
        srv.set_dispatch(self._process)
        srv.set_pipeline(self._pipeline)
        srv.set_convert_slow(self._convert_slow)
        srv.set_debug_page(self._debug_page)
        srv.set_http_exception(HTTPException)
        import uuid as _uuid

        srv.set_uuid_class(_uuid.UUID)
        for prefix, folder in self._static_folders:
            srv.set_static(prefix, folder)
        testing = bool(self.testing or self.config.get("TESTING"))
        max_body = self.config.get("MAX_CONTENT_LENGTH") or 64 * 1024 * 1024
        cc = self.config.get("SEND_FILE_MAX_AGE_DEFAULT")
        if cc is None:
            cc = 43200
        elif isinstance(cc, timedelta):
            cc = int(cc.total_seconds())
        srv.set_flags(
            fast=True,  # fast path is fully compatible since hooks run in it
            debug=bool(self.debug),
            log=not testing,
            max_body=int(max_body),
            cc_max_age=int(cc),
            trap_http=bool(self.config.get("TRAP_HTTP_EXCEPTIONS")),
        )
        self._server = srv
        return srv

    def _convert_slow(self, rv):
        """Rust fallback conversion for exotic return values."""
        try:
            return self.make_response(rv)
        except HTTPException as e:
            return e.get_response()
        except Exception as e:
            from .wrappers import Response as _R

            return _R("Internal Server Error", 500)

    def _debug_page(self, exc):
        """把未捕获异常渲染为 Werkzeug 风格的交互式调试页（仅 debug 模式）。"""
        from .debug import render_debug_page

        return Response(render_debug_page(exc), 500, mimetype="text/html")

    def test_client(self, use_cookies=True, **kwargs):
        """测试客户端：内存中直接走完整调度管线（不起 socket）。"""
        self._ensure_server()
        return _TestClient(self)

    # ------------------------------------------------------------------
    # misc Flask surface
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        if self.import_name == "__main__":
            path = getattr(sys.modules["__main__"], "__file__", None)
            if path:
                return os.path.splitext(os.path.basename(path))[0]
        return self.import_name

    def __repr__(self):
        return f"<Flask {self.name!r}>"

    def open_instance_resource(self, resource, mode="rb"):
        return open(os.path.join(self.instance_path or self.root_path, resource), mode)

    def send_static_file(self, filename):
        if not self.static_folder:
            raise RuntimeError("No static folder for this object")
        from .wrappers import send_file

        return send_file(os.path.join(self.static_folder, filename))

    @property
    def logger(self):
        import logging

        logger = logging.getLogger(self.import_name or "zan")
        if not logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s"))
            logger.addHandler(h)
        return logger

    @property
    def has_static_folder(self):
        return self.static_folder is not None

    @property
    def jinja_loader(self):
        if self.template_folder:
            return os.path.join(self.root_path, self.template_folder)
        return None


class BuildError(Exception):
    def __init__(self, endpoint, values, method=None):
        msg = (
            f"Could not build url for endpoint {endpoint!r}"
            + (f" with values {sorted(values.keys())!r}" if values else "")
            + (f" for method {method!r}" if method else "")
            + ". Did you forget to specify values [...]"
        )
        super().__init__(msg)
        self.endpoint = endpoint
        self.values = values


class _CLI:
    def __init__(self, app):
        self.app = app

    def command(self, *args, **kwargs):
        def decorator(f):
            return f

        return decorator

    def group(self, *args, **kwargs):
        def decorator(f):
            return f

        return decorator


# request-time binding used by full_dispatch_request
Request._current_view = None
