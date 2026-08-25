# zan 文档

**zan** 是一个用 Rust 写内核、体验与 Flask 完全一致的 Python Web 框架。
把 `from flask import ...` 改成 `from zan import ...`，其余代码不用动。

```python
from zan import Flask, jsonify, request

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello, World!"

@app.route("/user/<int:uid>")
def user(uid):
    return jsonify(uid=uid, name=f"user{uid}")

if __name__ == "__main__":
    app.run()   # Rust HTTP 服务器，默认 127.0.0.1:5000
```

## 特性一览

| 类别 | 内容 |
| --- | --- |
| 路由 | `<string>` `<int>` `<float>` `<path>` `<uuid>` `<any(a,b)>` 转换器、`methods`、`endpoint`、strict-slash 308 重定向、merge-slashes 重定向、HEAD/OPTIONS 自动处理、405 + `Allow` |
| 请求 | `args/form/values/json/data/get_json/headers/cookies/files`、`url` 系列、`endpoint/view_args/blueprint/remote_addr/user_agent/authorization`、multipart 文件上传 |
| 响应 | str/bytes/dict/list/`Response`/元组/生成器、`make_response`、`jsonify`（sorted keys + ensure_ascii）、`redirect`、`send_file`（ETag/304）、`set_cookie/delete_cookie` |
| 钩子 | `before_request`、`after_request`、`teardown_request`、`teardown_appcontext`、`context_processor`、`before_first_request` |
| 错误 | 完整 `HTTPException` 家族、`abort`、`errorhandler`（按状态码与异常类）、debug 模式 traceback 页 |
| 上下文 | `request`/`session`/`g`/`current_app` 代理、`app_context`/`request_context`/`test_request_context` |
| 会话 | 签名 Cookie 会话（HMAC-SHA256）、`flash`/`get_flashed_messages` |
| 蓝图 | `Blueprint`、`url_prefix`、蓝图级路由/钩子/错误处理/静态目录/模板目录 |
| 模板 | `render_template`、`render_template_string`（依赖可选的 jinja2）、`url_for`/`get_flashed_messages` 注入、`|tojson` 过滤器 |
| 工具 | 内置 CLI（`python -m zan run/shell/routes`）、全套信号、调试重载器 |
| 性能 | 纯文本场景约为 Flask dev server 的 11 倍（见[架构](architecture.md)） |

## 安装与构建

需要 Rust 工具链（`rustc` 1.75+）与 Python 3.8+：

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows；Linux/macOS 为 bin/activate
pip install maturin pytest jinja2
maturin develop --release
pytest tests/ -q
```

模板功能依赖可选的 `jinja2`（`pip install jinja2`），未安装时 `render_template*` 会给出明确报错。

## 文档目录

| 文档 | 内容 |
| --- | --- |
| [快速入门](quickstart.md) | 从 Hello World 到一个完整小应用 |
| [路由](routing.md) | 转换器、methods、endpoint、308 重定向、405、OPTIONS/HEAD |
| [请求对象](request.md) | `request` 的全部属性与方法 |
| [响应对象](response.md) | 视图返回值、`make_response`、`jsonify`、`redirect`、`send_file`、Cookie |
| [上下文与钩子](context.md) | `request/session/g/current_app`、上下文栈、钩子、信号 |
| [会话与闪存](session.md) | 签名 Cookie 原理、`permanent`、`flash` |
| [蓝图](blueprints.md) | 注册、`url_prefix`、蓝图级钩子/静态目录/模板目录 |
| [错误处理](errors.md) | `HTTPException` 家族、`abort`、`errorhandler` |
| [调试](debugging.md) | debug 模式、调试页、重载器、彩色输出 |
| [命令行](cli.md) | `python -m zan run/shell/routes` |
| [配置参考](config.md) | 全部配置键的含义 |
| [多实例与多核](multi.md) | `start/stop` 多应用共存、`processes=N` 多进程模式 |
| [架构](architecture.md) | Rust 内核、PyO3 边界、请求生命周期、性能数据 |
| [测试](testing.md) | `test_client`、`test_request_context`、pytest 集成 |
| [常见问题](faq.md) | 与 Flask 的差异、部署建议、性能调优 |

## 与 Flask 的关系

zan 的目标是 API 兼容而非 WSGI 兼容：应用由内置的 Rust 服务器直接运行，
不经过 `werkzeug.serving`/gunicorn。已知的差异清单见[常见问题](faq.md)。
