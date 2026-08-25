"""蓝图（Blueprint）：把应用拆成可复用组件，API 对齐 flask.blueprints。

注册时（`Flask.register_blueprint`）依次：
1. 执行延迟注册的路由（自动拼 url_prefix，endpoint 加 ``蓝图名.`` 前缀）
2. 把蓝图级 errorhandler / before / after / teardown 钩子挂到 app 上
3. 蓝图自己的 static 目录挂载到 ``/<url_prefix>/static/``（Rust 服务）
"""
import os
import typing as t


class BlueprintSetupState:
    def __init__(self, blueprint, app, options, first_registration):
        self.blueprint = blueprint
        self.app = app
        self.options = options
        self.first_registration = first_registration
        self.url_prefix = options.get("url_prefix")
        if self.url_prefix is None:
            self.url_prefix = blueprint.url_prefix

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        if self.url_prefix:
            rule = "/".join((self.url_prefix.rstrip("/"), rule.lstrip("/")))
        options.setdefault("subdomain", self.options.get("subdomain"))
        endpoint_opts = options.pop("endpoint", None)
        if endpoint is None and endpoint_opts is not None:
            endpoint = endpoint_opts
        # blueprint endpoints are prefixed with the blueprint name
        if endpoint is None and view_func is not None:
            endpoint = view_func.__name__
        if endpoint is not None:
            endpoint = f"{self.blueprint.name}.{endpoint}"
        self.app.add_url_rule(rule, endpoint, view_func, **options)


class Blueprint:
    def __init__(
        self,
        name: str,
        import_name: str,
        static_folder=None,
        static_url_path=None,
        template_folder=None,
        url_prefix=None,
        subdomain=None,
        url_defaults=None,
        root_path=None,
        cli_group=None,
    ):
        self.name = name
        self.import_name = import_name
        self.static_folder = static_folder
        self.static_url_path = static_url_path
        self.template_folder = template_folder
        self.url_prefix = url_prefix
        self.subdomain = subdomain
        self.url_defaults = (url_defaults or {}).copy()
        self.root_path = root_path
        self.cli_group = cli_group if cli_group is not None else name
        self.deferred_functions: t.List[t.Callable] = []
        self.error_handlers: t.Dict[t.Any, t.Callable] = {}
        self.before_request_funcs: t.Dict[None, t.List] = {None: []}
        self.after_request_funcs: t.Dict[None, t.List] = {None: []}
        self.teardown_request_funcs: t.Dict[None, t.List] = {None: []}
        self.record_once_funcs: t.List = []
        self._got_registered_once = False

    def record(self, func):
        self.deferred_functions.append(func)

    def record_once(self, func):
        def wrapper(state):
            if state.first_registration:
                func(state)

        self.record(wrapper)

    def _make_setup_state(self, app, options, first_registration):
        return BlueprintSetupState(self, app, options, first_registration)

    def register(self, app, options, first_registration=False):
        state = self._make_setup_state(app, options, first_registration)
        # run deferred route registrations
        for func in self.deferred_functions:
            func(state)
        # register blueprint-local error handlers on the app
        for code_or_exc, handler in self.error_handlers.items():
            app.register_error_handler(code_or_exc, handler, blueprint=self.name)
        for key, funcs in self.before_request_funcs.items():
            app.before_request_funcs.setdefault(self.name, []).extend(funcs)
        for key, funcs in self.after_request_funcs.items():
            app.after_request_funcs.setdefault(self.name, []).extend(funcs)
        for key, funcs in self.teardown_request_funcs.items():
            app.teardown_request_funcs.setdefault(self.name, []).extend(funcs)
        # 蓝图静态目录：挂到 /<url_prefix>/static/ 由 Rust 内核服务
        if self.static_folder and self.root_path:
            folder = self.static_folder
            if not os.path.isabs(folder):
                folder = os.path.join(self.root_path, folder)
            if os.path.isdir(folder):
                prefix = self.static_url_path or (
                    (state.url_prefix or "/" + self.name).rstrip("/") + "/static"
                )
                app._add_static_folder(prefix, folder)

    # -- decorators -----------------------------------------------------------
    def route(self, rule, **options):
        def decorator(f):
            endpoint = options.pop("endpoint", f.__name__)

            def add_rule(state):
                state.add_url_rule(rule, endpoint, f, **options)

            self.record(add_rule)
            return f

        return decorator

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        def add_rule(state):
            state.add_url_rule(rule, endpoint, view_func, **options)

        self.record(add_rule)

    def errorhandler(self, code_or_exception):
        def decorator(f):
            self.error_handlers[code_or_exception] = f
            return f

        return decorator

    def before_request(self, f):
        self.before_request_funcs.setdefault(None, []).append(f)
        return f

    def before_app_request(self, f):
        self.record_once(lambda state: state.app.before_request(f))
        return f

    def after_request(self, f):
        self.after_request_funcs.setdefault(None, []).append(f)
        return f

    def after_app_request(self, f):
        self.record_once(lambda state: state.app.after_request(f))
        return f

    def teardown_request(self, f):
        self.teardown_request_funcs.setdefault(None, []).append(f)
        return f

    def teardown_app_request(self, f):
        self.record_once(lambda state: state.app.teardown_request(f))
        return f

    def app_context_processor(self, f):
        self.record_once(lambda state: state.app.context_processor(f))
        return f

    def context_processor(self, f):
        self.record_once(lambda state: state.app.blueprint_context_processor(self.name)(f))
        return f

    def app_errorhandler(self, code_or_exception):
        def decorator(f):
            self.record_once(
                lambda state: state.app.register_error_handler(code_or_exception, f)
            )
            return f

        return decorator

    def get_url_rule(self, rule: str) -> str:
        if self.url_prefix:
            return "/" + self.url_prefix.strip("/") + "/" + rule.lstrip("/")
        return rule
