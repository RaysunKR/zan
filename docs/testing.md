# 测试

本页内容：`test_client` 的用法（`get/post/json/data/headers`）、cookie jar、`test_request_context`、pytest 集成示例（取自本仓库 `tests/` 的真实写法）。

## test_client

`app.test_client()` 返回一个模拟浏览器（请求不经过网络，直接打到 Rust
内核的测试入口）：

```python
from zan import Flask

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello, World!"

client = app.test_client()
r = client.get("/")
r.status_code      # 200
r.text             # "Hello, World!"
r.data             # b"Hello, World!"
r.headers["Content-Type"]   # "text/html; charset=utf-8"
```

### 请求方法

```python
client.get(url, **kw)
client.post(url, **kw)
client.put(url, **kw)
client.patch(url, **kw)
client.delete(url, **kw)
client.head(url, **kw)
client.options(url, **kw)
client.open("POST", url, **kw)      # 通用形式
```

### 传数据

| 参数 | 用途 |
| --- | --- |
| `data="文本"` / `data=b"字节"` | 原始 body |
| `data={"k": "v"}` | 表单 POST（自动 URL 编码 + `Content-Type: application/x-www-form-urlencoded`） |
| `json={"k": 1}` | JSON body（自动序列化 + `Content-Type: application/json`） |
| `headers={"X-Token": "abc"}` | 请求头 |

### 响应对象

```python
r.status_code          # int
r.status               # "404 Not Found"
r.data / r.text        # bytes / str
r.json                 # 解析后的 JSON（坏 JSON 为 None）
r.get_json(silent=True)
r.headers["Location"]
r.content_type / r.mimetype
r.is_json
```

### cookie jar

测试客户端维护一个简单 cookie jar：响应里的 `Set-Cookie` 自动存入，
后续请求自动带上；空值 Cookie 会从 jar 中移除。因此**会话测试不需要手动
搬运 Cookie**：

```python
app.secret_key = "test"

@app.route("/set")
def s():
    from zan import session
    session["user"] = "alice"
    return "set"

@app.route("/get")
def g():
    from zan import session
    return session.get("user", "anonymous")

client = app.test_client()
assert client.get("/get").text == "anonymous"
client.get("/set")                          # Set-Cookie 自动进 jar
assert client.get("/get").text == "alice"   # Cookie 自动带上
```

## test_request_context

不发起请求、手动构造请求环境：

```python
from zan import request, url_for

with app.test_request_context("/some/path?a=b"):
    assert request.path == "/some/path"
    assert request.args.get("a") == "b"
    url = url_for("hello", name="bob")

# 离开 with 块后上下文弹出
from zan import has_request_context
assert not has_request_context()
```

支持 `method` 参数与 `Request` 对象：

```python
with app.test_request_context("/submit", method="POST"):
    assert request.method == "POST"
```

`app.request_context(...)` 是 `test_request_context` 的别名。

## 测试真实服务器（start/stop）

`test_client` 不经过 socket。若要测试完整链路（真连接、keep-alive、
静态文件的 304 头等），用非阻塞的 `start`/`stop` 起真实服务器：

```python
import urllib.request
import pytest
from zan import Flask

@pytest.fixture()
def live_server():
    app = Flask(__name__)

    @app.route("/")
    def index():
        return "live"

    sid, addr = app.start(port=0)          # 随机可用端口
    yield f"http://{addr}"
    app.stop(sid)                            # 测试结束优雅停止

def test_live(live_server):
    with urllib.request.urlopen(live_server + "/") as r:
        assert r.read() == b"live"
```

多个应用可以在同一测试进程里并存（各自 `start(port=0)`），适合测
跨服务交互。详见[多实例与多核](multi.md)。

## pytest 集成示例

与仓库 `tests/` 的真实写法一致——每个测试函数拿到全新的 app 与 client：

```python
# conftest.py 或测试文件内
import pytest
from zan import Flask

@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    return app

@pytest.fixture()
def client(app):
    return app.test_client()
```

```python
# test_myapp.py
from zan import jsonify, request

def test_json_endpoint(app, client):
    @app.route("/j")
    def j():
        return {"a": 1}

    r = client.get("/j")
    assert r.status_code == 200
    assert r.json == {"a": 1}

def test_form_post(app, client):
    @app.route("/f", methods=["POST"])
    def f():
        return dict(request.form)

    r = client.post("/f", data={"name": "zan", "lang": "rust"})
    assert r.json == {"name": "zan", "lang": "rust"}

def test_error(app, client):
    @app.route("/missing")
    def missing():
        return "never"

    r = client.get("/nope")
    assert r.status_code == 404
```

### 常用断言速查

```python
r.status_code == 201
r.text == "Hello"
r.json == {"x": 1}
r.headers["Location"] == "/target"
"GET" in r.headers.get("Allow", "")
b"content" in r.data
```

### TRAP_HTTP_EXCEPTIONS 配合测试

想让 `abort` 的异常直接暴露成 Python 异常而不是 404 响应时：

```python
app.config["TRAP_HTTP_EXCEPTIONS"] = True
```

见[错误处理](errors.md#trap_http_exceptions)。

### 运行本仓库的测试

```bash
pytest tests/ -q      # 91 个用例（兼容性 + 功能 + 多实例/多核）
```

## 相关文档

- [请求对象](request.md)、[响应对象](response.md)
- [会话与闪存](session.md)
- [配置参考](config.md)
