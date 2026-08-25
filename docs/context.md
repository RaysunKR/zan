# 上下文与钩子

本页内容：`request`/`session`/`g`/`current_app` 四个代理的工作方式、
`app_context`/`request_context`/`test_request_context`、
before/after/teardown 钩子、`before_first_request`、信号列表。

## 四个代理

```python
from zan import request, session, g, current_app
```

它们都是模块级代理对象，把属性访问转发到**当前上下文**中的真实对象：

| 代理 | 来源 | 需要的上下文 |
| --- | --- | --- |
| `request` | 当前请求对象（`zan.Request`） | 请求上下文 |
| `session` | 当前请求的会话 dict | 请求上下文 |
| `g` | 应用上下文的 globals（dict + 属性访问） | 应用上下文 |
| `current_app` | 当前应用对象 | 应用上下文 |

在上下文之外访问会抛 `RuntimeError`：

```python
request.path    # RuntimeError: Working outside of request context.
```

检测当前是否处于上下文中：

```python
from zan import has_app_context, has_request_context
has_request_context()   # bool
has_app_context()       # bool
```

`g` 是每次应用上下文新建的空对象（dict + 属性访问二合一），用于在同一个
请求内跨函数共享数据：

```python
with app.app_context():
    g.value = 42
    assert g.value == 42
    assert g.get("missing", "default") == "default"
```

## 两种上下文

**应用上下文**（`AppContext`）：绑定 app 与 `g`。
**请求上下文**（`RequestContext`）：绑定 request、session，并**隐式确保**
应用上下文存在（自己 push 一个，pop 时再弹掉）。

```python
# 手动进入应用上下文
with app.app_context():
    current_app.name

# 请求上下文（接受 URL 字符串或 Request 对象）
with app.test_request_context("/some/path?a=b"):
    request.path            # "/some/path"
    request.args.get("a")   # "b"

# app.request_context 是 test_request_context 的别名
with app.request_context("/x"):
    ...
```

`test_request_context("/path?query", method="POST")` 可指定方法，用于在
测试/脚本里模拟请求环境（见[测试](testing.md)）。

## 请求生命周期中的钩子

一次请求按以下顺序执行（与 Flask 一致）：

1. `before_first_request` 钩子（仅第一个请求前，一次性）
2. 蓝图级 `before_request` → 应用级 `before_request`
3. 视图函数
4. 蓝图级 `after_request` → 应用级 `after_request`（注册逆序）
5. `teardown_request`（无论成功失败都执行）
6. `teardown_appcontext`

### before_request

任何一个 `before_request` 返回非 `None` 即**短路**，其返回值直接作为响应：

```python
from zan import Flask, request

app = Flask(__name__)

@app.before_request
def gate():
    if request.args.get("blocked"):
        return "blocked", 403     # 视图不再执行
```

### after_request

接收并必须返回 `Response`，常用于加公共头：

```python
@app.after_request
def add_header(resp):
    resp.headers["X-Zan"] = "1"
    return resp
```

### teardown_request

无论请求成功还是视图抛异常都会执行，参数是异常对象（无异常为 `None`）：

```python
@app.teardown_request
def cleanup(err):
    if err is not None:
        app.logger.warning("request failed", exc_info=err)
```

### teardown_appcontext

应用上下文弹出时执行，适合清理数据库连接等：

```python
@app.teardown_appcontext
def shutdown(err=None):
    ...
```

### before_first_request

第一个请求到来前执行一次（Flask 2.2 之前的 API）：

```python
@app.before_first_request
def init():
    print("初始化...")
```

### context_processor

向模板上下文注入变量（见[快速入门·模板](quickstart.md#模板)）：

```python
@app.context_processor
def inject_globals():
    return {"site_name": "zan demo"}
```

### 手动调度

在请求上下文中可以调用 `app.dispatch_request()` /
`app.full_dispatch_request()` 手动执行当前视图（含钩子），与 Flask 兼容。

## 信号

zan 提供全套 Flask 信号；安装了 `blinker` 时直接使用 blinker，否则用内置
的兼容实现（`connect`/`disconnect`/`send` 接口相同）：

```python
from zan.signals import request_started, request_finished

def log_start(sender, **kwargs):
    print("request started")

request_started.connect(log_start)
```

| 信号 | 触发时机 |
| --- | --- |
| `request_started` | 请求进入管线（上下文 push 后） |
| `request_finished` | 响应构造完成（参数 `response`） |
| `request_tearing_down` | 请求上下文即将弹出 |
| `got_request_exception` | 视图抛出非 HTTP 异常（参数 `exception`） |
| `appcontext_pushed` / `appcontext_popped` | 应用上下文 push/pop |
| `appcontext_tearing_down` | 应用上下文即将弹出 |
| `message_flashed` | `flash()` 被调用（参数 `message`、`category`） |

`zan.signals.signals_available` 表示 blinker 是否已安装。

## 相关文档

- [会话与闪存](session.md)
- [测试](testing.md)
- [架构](architecture.md)（请求在 Rust/Python 之间的完整时序）
