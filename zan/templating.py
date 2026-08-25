"""Jinja2 模板集成（依赖可选安装的 jinja2 包）。

- 应用模板目录：``<root_path>/<template_folder>``
- 蓝图模板目录：``<bp.root_path>/<bp.template_folder>``，
  模板名形如 ``bp/name.html`` 时优先从蓝图目录加载
- 注入模板全局：``url_for``、``get_flashed_messages``、``config``，
  以及 ``|tojson`` 过滤器
未安装 jinja2 时 `render_template*` 会抛出带安装指引的 RuntimeError。
"""
import os
import typing as t

try:
    import jinja2

    def _guess_autoescape(template_name):
        if template_name is None:
            return False
        return template_name.endswith((".html", ".htm", ".xml", ".xhtml"))

    class DispatchingJinjaLoader(jinja2.BaseLoader):
        def __init__(self, app):
            self.app = app

        def get_source(self, environment, template):
            for loader in self._iter_loaders(template):
                try:
                    return loader.get_source(environment, template)
                except jinja2.TemplateNotFound:
                    continue
            raise jinja2.TemplateNotFound(template)

        def _iter_loaders(self, template):
            # blueprint loader first if the template looks like `bp/name.html`
            parts = template.split("/", 1)
            if len(parts) == 2:
                bp = self.app.blueprints.get(parts[0])
                if bp is not None and getattr(bp, "template_folder", None):
                    yield jinja2.FileSystemLoader(
                        os.path.join(bp.root_path or ".", bp.template_folder)
                    )
            if self.app.template_folder:
                yield jinja2.FileSystemLoader(
                    os.path.join(self.app.root_path, self.app.template_folder)
                )

    class JinjaEnvironment(jinja2.Environment):
        pass

    _available = True
except ImportError:  # pragma: no cover
    _available = False


class Environment:
    """A wrapper exposing enough of the flask.templating surface; rendering
    itself is delegated to jinja2 when installed."""

    def __init__(self, app):
        self.app = app
        if not _available:
            self.env = None
            return
        self.env = JinjaEnvironment(
            autoescape=_guess_autoescape,
            loader=DispatchingJinjaLoader(app),
            extensions=[],
        )
        self.env.globals.update(
            url_for=self.app.url_for,
            get_flashed_messages=self._get_flashed_messages,
            config=self.app.config,
            request=None,  # bound per-render below
            session=None,
            g=None,
        )
        # |tojson 过滤器（与 Flask 相同的名字）
        from .json import tojson_filter

        self.env.filters["tojson"] = tojson_filter

    def _get_flashed_messages(self, *args, **kwargs):
        from .helpers import get_flashed_messages

        return get_flashed_messages(*args, **kwargs)

    def from_string(self, source):
        if not _available:
            raise RuntimeError(
                "jinja2 is required for templating: pip install jinja2"
            )
        return self.env.from_string(source)

    def get_template(self, name):
        if not _available:
            raise RuntimeError(
                "jinja2 is required for templating: pip install jinja2"
            )
        return self.env.get_template(name)

    def render(self, template, context):
        if not _available:
            raise RuntimeError(
                "jinja2 is required for templating: pip install jinja2"
            )
        # bind request/session proxies lazily via context processors
        ctx = dict(self.app.template_context_processors[None]()) if self.app else {}
        ctx.update(context or {})
        return template.render(**ctx)
