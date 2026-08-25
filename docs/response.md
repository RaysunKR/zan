# 响应对象

本页内容：视图可以返回的所有类型、`make_response`、`jsonify`（排序与 ensure_ascii）、`redirect`、`send_file`（ETag/304）、`set_cookie`/`delete_cookie`、生成器响应，以及 `url_for`。

## 视图可返回的类型

`make_response`（以及调度器）接受以下返回值：

| 类型 | 行为 |
| --- | --- |
| `str` / `bytes` / `bytearray` | 直接作为响应体，默认 `text/html; charset=utf-8` |
| `dict` / `list` | 自动 JSON 序列化，`Content-Type: application/json` |
| `Response` 对象 | 原样使用 |
| `HTTPException` 实例 | 调用其 `get_response()` |
| 生成器/迭代器 | 逐块编码并**完整拼接**为一个响应体（见下文） |
| `(body, status)` 二元组 | 指定状态码 |
| `(body, status, headers)` 三元组 | 状态码 + 头（dict 或 (k, v) 列表） |
| `None` | 无效返回值，触发 500 |

```python
@app.route("/text")
def text():
    return "text"

@app.route("/bytes")
def raw():
    return b"\x00\x01\x02"

@app.route("/dict")
def d():
    return {"a": 1, "b": [1, 2], "c": None}

@app.route("/tuple")
def tup():
    return "tea", 418, {"X-Tea": "yes"}

@app.route("/exc")
def exc():
    from zan.exceptions import NotFound
    return NotFound("gone away")
```

`status` 可以是 `int` 或 `"404 Not Found"` 形式的字符串。

## make_response

需要修改响应头、状态码时用 `make_response`（模块级函数代理到当前 app）：

```python
from zan import make_response

@app.route("/mr")
def mr():
    r = make_response(("body", 200))
    r.headers["X-Custom"] = "1"
    r.status_code = 201
    return r
```

`Response` 对象的主要接口：

```python
r.data                  # bytes（get_data()）
r.get_data(as_text=True)
r.set_data("new body")
r.status_code           # int
r.status                # "200 OK"
r.mimetype / r.content_type
r.headers               # Headers 对象（大小写不敏感）
r.set_cookie(...) / r.delete_cookie(...)
```

## jsonify

```python
from zan import jsonify

jsonify(username="alice")            # {"username":"alice"}
jsonify({"a": 1})                    # 单个 dict 原样输出
jsonify(1, 2, 3)                     # 多个位置参数合成列表 [1,2,3]
```

与 Flask 相同的默认行为：

- **键排序**：`sort_keys=True`，输出 `{"apple":2,"mango":3,"zebra":1}`；
- **ensure_ascii**：非 ASCII 字符转义为 `\uXXXX`（`"杭州"` → `"\u676d\u5dde"`）；
- 紧凑分隔符：`{"a":1}` 而非 `{"a": 1}`；
- `Content-Type: application/json`。

这两个开关在 `app.json`（`DefaultJSONProvider`）上：

```python
app.json.sort_keys = False
app.json.ensure_ascii = False
```

`datetime`/`date` 序列化为 RFC 1123 GMT 字符串，`uuid.UUID` 序列化为字符串，
实现了 `__html__` 的对象取其 HTML。其他类型抛 `TypeError`。

模块级 `zan.json_dumps` / `zan.json_loads` 是标准库 `json.dumps/loads` 的别名。

## redirect

```python
from zan import redirect

return redirect("/target")          # 302 Found + Location 头
return redirect("/target", code=301)  # 指定状态码
return redirect(url_for("index"))
```

## url_for

按 endpoint 反查 URL（要求在请求上下文或 `test_request_context` 中调用）：

```python
from zan import url_for

@app.route("/hello/<name>")
def hello(name): ...

@app.route("/self")
def self_view():
    return {"url": url_for("hello", name="bob")}   # /hello/bob
```

- `url_for('static', filename='css/app.css')` → `/static/css/app.css`；
- `url_for("a", _anchor="top")` → `/a#top`；
- `url_for("a", _external=True)` → 用 `SERVER_NAME`（默认 localhost）拼绝对 URL；
- 蓝图 endpoint（`"api.users"`）自动带 url_prefix，并应用蓝图 `url_defaults`；
- 缺少必要参数时抛 `zan.app.BuildError`。

## send_file

发送本地文件或文件对象：

```python
from zan import send_file

@app.route("/download/<name>")
def download(name):
    return send_file(f"files/{name}")

send_file("report.pdf", mimetype="application/pdf")
send_file("report.pdf", as_attachment=True, download_name="2024-report.pdf")
send_file(buf, mimetype="image/png")            # 任何有 .read() 的对象
send_file("f.txt", max_age=3600)                # Cache-Control: public, max-age=3600
```

行为：

- MIME 类型由 `mimetype` 参数或文件扩展名推断（缺省
  `application/octet-stream`）；
- 自动设置 `Last-Modified`（文件 mtime）与 **ETag**（body 的 SHA-1 十六进制）；
- 条件请求：客户端带 `If-None-Match` 命中 ETag 时返回 **304**（空 body，
  保留校验头）；
- `as_attachment=True` 时设置 `Content-Disposition: attachment`。

另有 `send_from_directory(directory, path, **kwargs)`（在 `zan.helpers` 中），
先拼目录再交给 `send_file`。

注意：`send_file` 把整个文件读进内存，适合中小文件；大文件建议直接放到
`static/` 由 Rust 内核服务。

## set_cookie / delete_cookie

```python
@app.route("/set")
def set_cookie():
    r = make_response("ok")
    r.set_cookie("token", "abc",
                 max_age=3600,          # 秒
                 expires=datetime(2025, 1, 1, tzinfo=timezone.utc),
                 path="/",
                 domain="example.com",
                 secure=True,
                 httponly=True,
                 samesite="Lax")
    return r

@app.route("/clear")
def clear():
    r = make_response("ok")
    r.delete_cookie("token")            # Max-Age=0 + Expires=1970
    return r
```

## 生成器响应

返回任意可迭代对象（生成器、列表等）时，每个块会被编码（`bytes` 原样，
其他转 str）并拼接为完整响应体：

```python
@app.route("/gen")
def gen():
    def produce():
        yield "a"
        yield "b"
        yield "c"
    return produce()          # 响应体 "abc"
```

注意：zan 当前会把迭代器**完整消费**后一次性写出（设置 Content-Length），
不是逐块 flush 的流式传输。

## 相关文档

- [请求对象](request.md)
- [会话与闪存](session.md)（会话 Cookie 由框架自动设置）
- [配置参考](config.md)
