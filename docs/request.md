# 请求对象

本页内容：`zan.request` 的全部属性与方法——`args`/`form`/`values`/`json`/`get_json`/`data`、`headers`/`cookies`/`files`、URL 系列、`endpoint`/`view_args`/`blueprint`、`remote_addr`/`user_agent`/`authorization`。

`request` 是模块级代理（见[上下文](context.md)），只在请求上下文内有效；
在上下文外访问属性抛 `RuntimeError("Working outside of request context.")`。

```python
from zan import Flask, jsonify, request

app = Flask(__name__)

@app.route("/req")
def req():
    return {"method": request.method, "path": request.path}
```

## 查询串：args

`args` 是 `MultiDict`（同一 key 可有多个值，`__getitem__`/`get` 取第一个）：

```python
request.args.get("a")               # 单值，缺省 None
request.args["missing"]             # 缺 key 时抛 BadRequestKeyError → 400
request.args.getlist("multi")       # 全部值，如 ?multi=x&multi=y → ["x", "y"]
request.args.get("n", type=int)     # 类型转换，失败返回 default
request.args.to_dict(flat=False)    # {"multi": ["x", "y"]}
"a" in request.args                 # 成员判断
```

## 表单：form

`Content-Type: application/x-www-form-urlencoded` 的 POST body：

```python
request.form.get("name")
request.form.getlist("tags")
dict(request.form)                  # {"name": "zan"}
```

## args + form 合并：values

```python
request.values.get("q")    # 先查 args 再查 form
```

## JSON：json / get_json

```python
request.get_json()               # Content-Type 非 application/json 时返回 None
request.get_json(force=True)     # 忽略 Content-Type 强制解析
request.get_json(silent=True)    # 解析失败返回 None 而非抛 400
request.json                     # 非 JSON 请求时抛 BadRequest（400）
request.is_json                  # Content-Type 是 application/json（或 +json 结尾）
```

解析结果有缓存，多次调用只解析一次。

## 原始 body：data / get_data

```python
request.data               # bytes
request.get_data(as_text=True)   # str（按 charset 解码）
```

## 头：headers

`headers` 大小写不敏感：

```python
request.headers.get("User-Agent")
request.headers["Content-Type"]
request.headers.get("X-Retry", type=int)   # 类型转换
"X-Token" in request.headers
request.headers.get_all("Set-Cookie")      # 同名多值
```

## Cookie：cookies

```python
request.cookies.get("session_id")
```

（值已做百分号解码。）

## 文件上传：files

`multipart/form-data` 的 POST，字段是 `FileStorage` 对象：

```python
@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if f is None:
        return {"error": "no file"}, 400
    f.save("uploads/" + f.filename)      # 保存到磁盘
    return {"filename": f.filename,
            "content_type": f.content_type,
            "size": f.content_length}
```

`FileStorage` 主要接口：`read/readline/readlines/seek/tell/close/__iter__`、
`save(dst, buffer_size=16384)`、属性 `stream/filename/name/content_type/headers`。

## URL 系列

| 属性 | 示例值（请求 `GET /va/42?q=1`，Host: localhost:5000） |
| --- | --- |
| `request.path` | `/va/42` |
| `request.full_path` | `/va/42?q=1`（无查询串时为 `"/va/42?"`） |
| `request.url` | `http://localhost:5000/va/42?q=1` |
| `request.base_url` | `http://localhost:5000/va/42` |
| `request.url_root` | `http://localhost:5000/` |
| `request.host` | `localhost:5000`（取自 Host 头） |
| `request.query_string` | `q=1`（原始字符串） |
| `request.scheme` | `http`（固定值，TLS 暂未实现） |

## 路由元数据

```python
request.endpoint     # 匹配的 endpoint，如 "va" 或 "api.users"；未匹配为 None
request.view_args    # 路由参数 dict，如 {"x": "42"}
request.blueprint    # 请求所属蓝图名（endpoint 前缀），无蓝图为 None
request.url_rule     # 保留字段（当前为 None）
```

## 其他

```python
request.method                  # "GET" / "POST" / ...
request.remote_addr             # 客户端地址，如 "127.0.0.1"
request.content_type            # Content-Type 头
request.mimetype                # Content-Type 去掉参数部分
request.content_length          # Content-Length（int），无头时取 body 长度
request.charset                 # 从 Content-Type 推断，默认 utf-8
request.user_agent              # .string 属性为原始 User-Agent 字符串
request.is_secure               # 固定 False（无 TLS）
request.if_modified_since       # If-Modified-Since 头解析成的 UTC datetime（可 None）

auth = request.authorization    # Authorization 头
if auth:
    auth.type     # 小写 scheme，如 "bearer" / "basic"
    auth.token    # scheme 之后的 token 字符串
```

注意：`user_agent` 只保留原始字符串（`str(request.user_agent)`），不提供
浏览器/平台解析；`authorization` 不做 Base64 解码，需要时自行处理
`auth.token`。

## 相关文档

- [响应对象](response.md)
- [上下文与钩子](context.md)
- [测试](testing.md)（`test_request_context` 的用法）
