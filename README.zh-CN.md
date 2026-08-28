# zan

**一个用 Rust 写内核的 Python Web 框架，体验与 Flask 完全一致，性能高出数倍。**

```python
from zan import Flask, jsonify, request

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello, World!"

@app.route("/user/<int:uid>")
def user(uid):
    return jsonify(uid=uid, name=f"user{uid}")

@app.route("/post", methods=["POST"])
def post():
    return jsonify(echo=request.get_json())

if __name__ == "__main__":
    app.run()   # zan/0.1.0 — Rust HTTP 服务器
```

把 `from flask import ...` 改成 `from zan import ...`，其余代码不用动。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/zan.svg)](https://pypi.org/project/zan/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Rust 1.75+](https://img.shields.io/badge/rust-1.75%2B-orange.svg)](https://www.rust-lang.org/)

[English README](README.md)

## 安装

zan 为 Windows、macOS 和 Linux 提供预编译 wheel，无需安装 Rust 工具链：

```bash
pip install zan
```

可选模板支持：

```bash
pip install zan[templates]
```

如需从源码构建，见下方「从源码构建」。

## 从源码构建

需要 Rust 工具链（`rustc` 1.75+）与 Python 3.8+：

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows；Linux/macOS 为 bin/activate
pip install maturin pytest jinja2
maturin develop --release
pytest tests/ -q
```

模板功能依赖可选的 `jinja2`（`pip install jinja2`），未安装时 `render_template*` 会给出明确报错。

## Flask 兼容性

已实现并测试（91 个用例）的 API 面：

| 类别 | 内容 |
| --- | --- |
| 应用 | `Flask(import_name)`、`route/add_url_rule`、`run`、`start/stop`（非阻塞多实例）、`test_client`、`config`、`debug`、`secret_key`、`logger`、`cli`、`extensions`、`name` |
| 路由 | `<string>` `<int>` `<float>` `<path>` `<uuid>` `<any(a,b)>` 转换器、`methods`、`endpoint`、strict-slash 308 重定向、merge-slashes 重定向、HEAD/OPTIONS 自动处理、405 + `Allow` |
| 请求 | `request.args/form/values/json/data/get_json/headers/cookies/method/path/url/endpoint/view_args/blueprint/remote_addr/user_agent/authorization`、multipart 文件上传 |
| 响应 | str/bytes/dict/list/`Response`/`(body, status, headers)` 元组、生成器、`make_response`、`jsonify`（sorted keys + ensure_ascii）、`redirect`、`send_file`、`set_cookie/delete_cookie` |
| 钩子 | `before_request`、`after_request`、`teardown_request`、`teardown_appcontext`、`context_processor` |
| 错误 | 完整 `HTTPException` 家族、`abort`、`errorhandler`（按状态码与异常类）、debug 模式 traceback 页 |
| 上下文 | `request`/`session`/`g`/`current_app` 代理、`app_context`/`request_context`/`test_request_context`、上下文外访问抛 `RuntimeError` |
| 会话 | 签名 Cookie 会话（HMAC-SHA256，itsdangerous 语义）、`flash`/`get_flashed_messages` |
| 蓝图 | `Blueprint`、`url_prefix`、蓝图级路由/钩子/错误处理、`bp.endpoint` 命名 |
| 模板 | `render_template`、`render_template_string`、蓝图模板目录、`url_for`/`get_flashed_messages` 注入 |
| URL 构建 | `url_for`（参数、`_anchor`、`_external`、蓝图默认值） |
| 静态文件 | `/static/` 由 Rust 直接服务（Last-Modified/304、MIME 推断、路径穿越防护） |
| 信号 | 全套信号（有 blinker 用 blinker，无则内置兼容实现） |
| 多实例 | 同进程多个应用同时 `start()`/`stop()`，共享 Rust 运行时 |
| 多核 | `run(processes=N)` 多进程 + Rust TCP 负载均衡（round-robin、X-Forwarded-For） |

已知差异（刻意为之或暂未实现）：

- 不实现 Werkzeug reloader（debug 模式改代码需手动重启，会有 warning 提示）
- 不基于 WSGI：应用由内置 Rust 服务器运行，不经过 `werkzeug.serving`/gunicorn
- `request.scheme` 固定为 `http`（TLS 暂未做，见「路线图」）

## 性能

### 本地微基准（Windows、Python 3.13、8 keep-alive 连接、纯 Python 视图函数）

| 场景 | zan | Flask dev server | 加速 |
| --- | --- | --- | --- |
| 纯文本 | 3205 req/s | 291 req/s | **11.0x** |
| JSON | 2941 req/s | 423 req/s | **6.9x** |
| 路由参数 | 3077 req/s | 419 req/s | **7.4x** |
| POST JSON | 2375 req/s | 422 req/s | **5.6x** |

### TechEmpower 标准测试

在 Ubuntu 服务器（8 核、PostgreSQL 16）上跑六类规范端点（`/plaintext`、`/json`、`/db`、`/queries`、`/updates`、`/fortunes`），严格按 TechEmpower wrk 方法：256 连接、每轮 15 秒、取 3 轮中位数。Flask 侧使用 gunicorn + gevent。zan 对 DB 端点启用 Rust 原生处理器，应用层代码无需改动。

| 测试 | zan | flask | zan_multi | zan 相比 flask |
| --- | ---: | ---: | ---: | ---: |
| plaintext | 65 141 | 40 372 | 98 613 | 1.6x |
| json | 67 144 | 37 966 | 110 427 | 1.8x |
| db | 43 937 | 15 122 | 40 832 | 2.9x |
| queries | 36 587 | 11 377 | 29 150 | 3.2x |
| updates | 16 614 | 4 297 | 13 909 | 3.9x |
| fortunes | 43 108 | 14 270 | 40 519 | 3.0x |

zan 所有端点均以 0 错误完成测试。DB 类指标受 PostgreSQL 单机吞吐限制。

多核：`run(processes=N)` 突破 GIL，CPU 密集视图近似线性扩展（2 核实测 1.9x）。

复现方式：

```bash
cd benchmarks/complete
bash deploy.sh        # 安装依赖、编译 zan、启动服务
bash benchmark.sh     # 运行 wrk，结果写入 results/<时间戳>
python3 report.py results/<时间戳>
```

注意 Flask dev server（Werkzeug）本身未开 keep-alive，本地微基准对两者使用同一客户端与负载。

## 架构

```
┌─────────────────────────────────────────────┐
│ 你的代码（与 Flask 相同的写法）                  │
├─────────────────────────────────────────────┤
│ zan Python 层（app/wrappers/ctx/session/...） │  ← 兼容层：Flask API 逐一对齐
├──────────────────────── PyO3 ────────────────┤
│ zan Rust 内核 (_zan)                          │
│  • 进程级共享 tokio 运行时（worker=CPU 核数，多实例复用）│
│  • tokio 多线程 HTTP/1.1 服务器（keep-alive、   │
│    chunked、管线化、100-continue、超时/大小上限）│
│  • Trie 路由器（Werkzeug 转换器语义、静态优先、  │
│    strict/merge-slash 重定向）                 │
│  • 静态文件服务（完全在 Rust 侧，不碰 GIL）      │
│  • Rust 原生 JSON 序列化（与 json.dumps 输出对齐）│
│  • TCP 负载均衡器（多进程模式，round-robin + XFF）│
│  • 错误路径：404/405/413/431 等不进 Python      │
└─────────────────────────────────────────────┘
```

- 每个请求由 tokio worker 解析，命中路由后经 `spawn_blocking` 进入 Python（`allow_threads` 期间不占 GIL），视图运行时推送完整的 app/request 上下文，钩子、信号、会话语义与 Flask 一致。
- 视图返回 str/bytes/dict/tuple 时在 Rust 侧直接序列化；`Response` 对象通过 `_fast()` 以 `(status, headers, body)` 元组过 FFI，无中间 environ。
- 未捕获异常回退到 Python 错误处理链（errorhandler → HTTPException → 500），debug 模式渲染 traceback 页。

## 项目结构

```
src/            Rust 内核
  router.rs     Trie 路由 + 转换器
  http.rs       连接/解析/静态文件/调度
  json.rs       原生 JSON 序列化
  pyapi.rs      PyO3 Server 类（共享运行时/生命周期/负载均衡入口）
  balancer.rs   多进程 TCP 负载均衡器
zan/            Python 兼容层（16 个模块）
tests/          91 个用例（兼容 62 / 功能 18 / 同 rule 多方法 3 / 多实例多核 8）
blog/           完整博客示例（zan 后端 + React/shadcn 前端，单进程服务）
benchmarks/     基准：keep-alive 对比 / 多核扩展 / TechEmpower 标准（tfb/）
```

## 文档

完整的中文文档在 [`docs/`](docs/index.md) 目录：

- [文档首页](docs/index.md) — 简介、特性表、快速上手
- [快速入门](docs/quickstart.md) — 路由、请求、响应、模板、会话、蓝图、错误处理
- [路由](docs/routing.md) — 全部转换器、methods、strict-slash 308、405、OPTIONS/HEAD
- [请求对象](docs/request.md) — `request` 的全部属性与方法
- [响应对象](docs/response.md) — 视图返回值、`jsonify`、`redirect`、`send_file`、Cookie
- [上下文与钩子](docs/context.md) — `request/session/g/current_app`、钩子、信号
- [会话与闪存](docs/session.md) — 签名 Cookie 原理、permanent、`flash`
- [蓝图](docs/blueprints.md) — 注册、`url_prefix`、蓝图级钩子/静态目录/模板目录
- [错误处理](docs/errors.md) — `HTTPException` 家族、`abort`、`errorhandler`
- [调试](docs/debugging.md) — 调试页、重载器、彩色输出
- [命令行](docs/cli.md) — `python -m zan run/shell/routes`
- [配置参考](docs/config.md) — 全部配置键
- [多实例与多核](docs/multi.md) — `start/stop` 多应用共存、`processes=N` 多进程、负载均衡
- [架构](docs/architecture.md) — Rust 内核、PyO3 边界、请求生命周期、性能数据
- [测试](docs/testing.md) — `test_client`、`test_request_context`、pytest 集成
- [常见问题](docs/faq.md) — 与 Flask 的差异、部署建议、性能调优

## 路线图

- HTTPS/TLS（rustls）与 HTTP/2
- WebSocket 支持
- `url_for` 对 `external` + `SERVER_NAME` 的更多边缘行为
- Windows 之外平台的 CI 矩阵与 abi3 wheel 发布

## 协议

[MIT](LICENSE) © 2026 RaysunKR
