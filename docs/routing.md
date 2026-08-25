# 路由

本页内容：路由规则的全部转换器（`string`/`int`/`float`/`path`/`uuid`/`any`）及其类型语义、`methods` 与 `endpoint`、strict-slash 与 merge-slashes 的 308 重定向、405 + `Allow`、自动的 OPTIONS/HEAD 处理。

## 注册路由

两种等价方式：

```python
from zan import Flask

app = Flask(__name__)

# 装饰器
@app.route("/hello/<name>")
def hello(name):
    return f"Hello, {name}!"

# 直接调用
def bye(name):
    return f"Bye, {name}!"

app.add_url_rule("/bye/<name>", endpoint="bye", view_func=bye)
```

不指定 `endpoint` 时默认取视图函数名（`view_func.__name__`）。同一
endpoint 重复注册不同函数会抛 `AssertionError`。

## 转换器

规则中 `<名字>` 或 `<转换器:名字>` 声明 URL 变量，视图按关键字参数接收。
转换器决定匹配哪些 URL 以及视图收到的 **Python 类型**：

| 转换器 | 示例规则 | 匹配 | 视图收到 |
| --- | --- | --- | --- |
| `string`（默认） | `/<x>`、`/<string:x>` | 不含 `/` 的一段 | `str` |
| `int` | `/<int:x>` | 纯数字（不含符号、小数点） | `int` |
| `float` | `/<float:x>` | 带小数点的数字，如 `3.5` | `float` |
| `path` | `/<path:x>` | 任意段，**可含 `/`**，只能放最后 | `str` |
| `uuid` | `/<uuid:x>` | 标准 UUID 十六进制串 | `uuid.UUID` 实例 |
| `any` | `/<any(a, b):x>` | 仅限括号中列出的字面量 | `str`（命中的字面量） |

```python
@app.route("/s/<x>")             # string：即使全是数字也是 str
def s(x): ...

@app.route("/i/<int:x>")         # int：视图收到 7 而非 "7"
def i(x): ...

@app.route("/f/<float:x>")       # float：/f/3.5 → 3.5
def f(x): ...

@app.route("/u/<uuid:x>")        # uuid：视图收到 uuid.UUID 实例
def u(x): ...

@app.route("/files/<path:p>")    # path：/files/a/b/c.txt → "a/b/c.txt"
def files(p): ...

@app.route("/lang/<any(en, zh):code>")   # any：仅匹配 /lang/en 或 /lang/zh
def lang(code): ...
```

类型不匹配即视为未命中：`/<int:x>` 遇到 `/abc` 返回 404；`/<uuid:x>` 遇到
`/not-a-uuid` 返回 404。URL 中的百分号编码会被先解码再匹配，
`/` + `quote("杭州")` 传给 `/<name>` 视图收到 `"杭州"`。

当多条规则都能匹配同一路径时，匹配优先级为：
**静态段 > `int` > `float` > `uuid` > `any` > `string` > `path` 尾段**。
例如 `/user/<int:uid>` 与 `/user/me` 同时存在时，`/user/me` 命中静态段。

## methods

`methods` 指定规则接受的 HTTP 方法，不区分大小写，会归一化为大写：

```python
@app.route("/m", methods=["GET", "POST"])
def m(): ...

@app.route("/only-post", methods=["POST"])
def only_post(): ...
```

- 不传 `methods` 时默认 `("GET",)`。
- 规则含 `GET` 时 `HEAD` 隐含可用（响应无 body，见下文）。
- 传入字符串（`methods="GET"`）会抛 `TypeError`，必须是列表/元组。

## 405 与 Allow

方法不匹配返回 `405 Method Not Allowed`，并带上 `Allow` 头列出该路径
支持的全部方法：

```python
@app.route("/m", methods=["GET", "POST"])
def m(): ...
```

```
DELETE /m  →  405, Allow: GET, HEAD, OPTIONS, POST
```

## OPTIONS 自动处理

只要 `provide_automatic_options` 未显式关闭（默认开启），每个规则自动响应
`OPTIONS`，返回 200 与完整 `Allow` 头，无需自己写视图：

```
OPTIONS /m  →  200, Allow: GET, HEAD, OPTIONS, POST
```

## HEAD 自动处理

规则含 `GET` 时 `HEAD` 请求自动可用：执行视图后丢弃响应体，
只返回状态码与头。测试客户端中 `client.head("/h").data == b""`。

## strict-slash：308 尾斜杠重定向

规则以 `/` 结尾而请求没有尾斜杠（或反过来）时，返回 308 永久重定向到
规范形式，与 Werkzeug 语义一致：

```python
@app.route("/page/")
def page(): ...
```

```
GET /page   →  308, Location: /page/
```

## merge-slashes：连续斜杠合并

路径中出现连续斜杠时，重定向到合并后的规范路径：

```
GET //a///b  →  308, Location: /a/b
```

## endpoint 与 url_for

endpoint 是路由的名字，`url_for` 用它反查 URL（详见
[响应对象](response.md#url_for)）：

```python
@app.route("/hello/<name>")
def hello(name): ...

with app.test_request_context():
    url = url_for("hello", name="bob")   # → "/hello/bob"
```

蓝图路由的 endpoint 自动带蓝图前缀（`bp名.视图名`），见[蓝图](blueprints.md)。

## 相关文档

- [快速入门](quickstart.md#路由)
- [蓝图](blueprints.md)
- [测试](testing.md)
