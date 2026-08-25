# 错误处理

本页内容：`HTTPException` 家族的完整清单、`abort` 的三种用法、
`errorhandler`（按状态码与异常类）、蓝图级错误处理、`TRAP_HTTP_EXCEPTIONS`。

## HTTPException 家族

所有 HTTP 错误都是 `zan.exceptions.HTTPException` 的子类，可直接在视图中
`raise`，框架会转成对应状态码的响应：

```python
from zan.exceptions import Forbidden

@app.route("/admin")
def admin():
    raise Forbidden()      # 403
```

导出的异常类（`from zan import ...` 或 `from zan.exceptions import ...`）：

| 异常类 | 状态码 |
| --- | --- |
| `BadRequest` | 400 |
| `Unauthorized` | 401 |
| `Forbidden` | 403 |
| `NotFound` | 404 |
| `MethodNotAllowed` | 405（带 `Allow` 头） |
| `NotAcceptable` | 406 |
| `RequestTimeout` | 408 |
| `Conflict` | 409 |
| `Gone` | 410 |
| `LengthRequired` | 411 |
| `PreconditionFailed` | 412 |
| `PayloadTooLarge` | 413 |
| `URITooLong` | 414 |
| `UnsupportedMediaType` | 415 |
| `RangeNotSatisfiable` | 416 |
| `ImATeapot` | 418 |
| `UnprocessableEntity` | 422 |
| `TooManyRequests` | 429 |
| `InternalServerError` | 500 |
| `ServiceUnavailable` | 503 |

`exceptions.py` 内还有 `ExpectationFailed`(417)、`NotImplemented`(501)、
`BadGateway`(502)、`GatewayTimeout`(504)，需从 `zan.exceptions` 导入。

每个异常有 `code`、`description`（默认英文描述）、`name`（如 `"Not Found"`），
`get_response()` 生成 Werkzeug 风格的 HTML 错误页。构造时可覆盖描述：

```python
raise NotFound("这个用户不存在")     # 页面正文显示自定义描述
```

`BadRequestKeyError`（400，`BadRequest` 与 `KeyError` 的子类）是
`request.args["缺失键"]` / `request.form["缺失键"]` 时抛出的。

## abort

`zan.abort` 有三种调用方式：

```python
from zan import abort
from zan.exceptions import NotFound

# 1. 状态码
abort(403)                    # raise Forbidden()

# 2. 状态码 + 描述
abort(400, "bad input")       # raise BadRequest("bad input")，页面含 "bad input"
abort(500, "something broke")

# 3. 异常实例（或 Response）
abort(NotFound("gone away"))
abort(SomeHTTPException(response=some_response))
```

无效状态码（如 `abort(599)`）抛 `ValueError`。`abort` 是**抛出**而不是
返回，后面的代码不会执行。

## errorhandler

### 按状态码

```python
@app.errorhandler(404)
def not_found(e):             # e 是对应的 HTTPException
    return "custom not found", 404

@app.errorhandler(500)
def server_error(e):
    return "custom five hundred", 500
```

### 按异常类

捕获任意异常（含非 HTTP 异常），按 MRO 匹配父类：

```python
@app.errorhandler(ValueError)
def on_value_error(e):
    return f"caught {e}", 500

@app.errorhandler(Exception)         # 兜底：所有未处理异常
def catch_all(e):
    return {"error": "internal"}, 500
```

处理器返回 `None` 时按无处理器处理（继续走默认错误响应）。

### 蓝图级

处理器先在当前蓝图内查找，找不到再落到应用级（见[蓝图](blueprints.md#蓝图级错误处理)）：

```python
bp = Blueprint("api", __name__)

@bp.errorhandler(404)
def api_404(e):
    return {"error": "not found"}, 404
```

## 默认行为

- 未匹配路由 → 404（Werkzeug 风格 HTML 页）；
- 方法不匹配 → 405 + `Allow` 头；
- 视图抛 `HTTPException` → 对应状态码；
- 视图抛其他异常 → 500；debug 模式渲染交互式调试页（见[调试](debugging.md)）；
- 路由/静态文件层的 404/405/413/431 由 Rust 内核直接返回，不进入 Python
  管线（因此这些路径上的错误页无法被 `errorhandler` 定制）。

## TRAP_HTTP_EXCEPTIONS

`app.config["TRAP_HTTP_EXCEPTIONS"] = True` 时，`HTTPException` 不再被
转换成错误响应，而是像普通异常一样冒泡：

```python
app.config["TRAP_HTTP_EXCEPTIONS"] = True

@app.route("/t")
def t():
    abort(404)
    # 没有 errorhandler 接住时最终仍是 500
```

这在测试中很有用：可以让 `abort` 的异常直接暴露成 Python 异常被
`pytest.raises` 断言，而不是变成 404 响应。

## 相关文档

- [调试](debugging.md)（debug 模式下 500 的展示）
- [蓝图](blueprints.md#蓝图级错误处理)
- [测试](testing.md)
