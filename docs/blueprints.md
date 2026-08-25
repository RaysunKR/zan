# 蓝图

本页内容：`Blueprint` 的创建与注册、`url_prefix`、蓝图级钩子/错误处理、
蓝图静态目录与模板目录、endpoint 命名规则（`bp.name` 前缀）。

## 创建与注册

```python
from zan import Blueprint, Flask

app = Flask(__name__)

api = Blueprint("api", __name__, url_prefix="/api")

@api.route("/ping")
def ping():
    return {"pong": True}

@api.route("/users/<int:uid>")
def users(uid):
    return {"uid": uid}

app.register_blueprint(api)
# 路由：/api/ping、/api/users/<int:uid>
```

构造参数（与 Flask 对齐）：

```python
Blueprint(
    name,               # 蓝图名，参与 endpoint 命名，必须唯一
    import_name,        # 通常传 __name__
    static_folder=None,     # 蓝图自己的静态目录（相对 root_path）
    static_url_path=None,   # 静态 URL 前缀（默认 /<url_prefix>/static）
    template_folder=None,   # 蓝图模板目录（相对 root_path）
    url_prefix=None,        # URL 前缀
    url_defaults=None,      # dict：url_for 构建时的默认参数
    root_path=None,         # 根路径（默认由 import_name 推断）
)
```

注册时可覆盖选项：

```python
app.register_blueprint(api, url_prefix="/v2/api")
```

`register_blueprint` 之后新增的路由不会被已编译的服务器看到（`_server`
在注册时失效重建），请把注册放在应用启动路径上。

## endpoint 命名

蓝图内路由的 endpoint 自动加 `蓝图名.` 前缀：

```python
api = Blueprint("api", __name__)

@api.route("/ping")           # endpoint → "api.ping"
def ping(): ...

@api.route("/x", endpoint="thing")
def other(): ...              # endpoint → "api.thing"
```

因此 `url_for` 与错误处理都用带前缀的名字：

```python
url_for("api.ping")           # /api/ping
```

请求对象也能看出蓝图来源：

```python
request.blueprint             # "api"（取 endpoint 前缀），非蓝图为 None
request.endpoint              # "api.ping"
```

## 蓝图级钩子

注册到蓝图上的钩子只对该蓝图的请求生效：

```python
@api.before_request           # 只在 /api/* 请求前运行
def api_auth():
    from zan import request, abort
    if not request.headers.get("X-Token"):
        abort(401)

@api.after_request            # 只处理该蓝图的响应
def api_header(resp):
    resp.headers["X-Api"] = "1"
    return resp

@api.teardown_request         # 该蓝图请求结束时清理
def api_cleanup(err): ...
```

也可以把钩子注册到**整个应用**（`*_app_*` 系列，注册蓝图时生效）：

```python
@api.before_app_request       # 等价于 app.before_request
def global_gate(): ...

@api.after_app_request        # 等价于 app.after_request
def global_header(resp): ...

@api.teardown_app_request     # 等价于 app.teardown_request
def global_cleanup(err): ...

@api.app_context_processor    # 等价于 app.context_processor
def inject(): return {...}
```

执行顺序（与 Flask 一致）：蓝图 `before_request` → 应用 `before_request` →
视图 → 应用 `after_request` → 蓝图 `after_request`（各自按注册逆序）。

## 蓝图级错误处理

```python
api = Blueprint("api", __name__)

@api.errorhandler(404)
def api_404(e):
    return {"error": "not found"}, 404

@api.app_errorhandler(500)    # 注册到应用全局
def global_500(e):
    return {"error": "internal"}, 500
```

查找顺序：先蓝图处理器，再应用处理器（见[错误处理](errors.md)）。

## 蓝图静态目录

给蓝图设置 `static_folder` 与 `root_path` 后，静态文件挂载到
`/<url_prefix>/static/`（或 `static_url_path` 指定的前缀），由 Rust 内核
直接服务，与应用的 `/static/` 互不冲突：

```python
# 目录结构：
#   bp/static/bp.js
bp = Blueprint("widget", "widget",
               root_path="bp",         # 也可以是绝对路径
               static_folder="static",
               url_prefix="/widget")
app.register_blueprint(bp)

# GET /widget/static/bp.js  → 200，由 Rust 内核服务
# GET /static/app.css       → 200，应用自己的静态目录
```

## 蓝图模板目录

蓝图的 `template_folder` 通过分发式 loader 生效：模板名以 `蓝图名/` 开头时
优先在蓝图的模板目录中查找，回退到应用模板目录：

```
templates/base.html            # 应用模板
bp/templates/bp/index.html     # 蓝图模板
```

```python
bp = Blueprint("bp", __name__, template_folder="templates")

@api.route("/page")
def page():
    return render_template("bp/index.html")   # 命中蓝图模板
```

## 相关文档

- [路由](routing.md)
- [上下文与钩子](context.md)
- [错误处理](errors.md)
