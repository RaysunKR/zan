# 架构

本页内容：Rust 内核的组成（tokio/httparse/trie 路由/静态文件/JSON）、PyO3 边界上的数据流、请求生命周期时序（从 socket 到视图再回来）、性能数据。

## 总体分层

```
┌─────────────────────────────────────────────┐
│ 你的代码（与 Flask 相同的写法）                  │
├─────────────────────────────────────────────┤
│ zan Python 层（app/wrappers/ctx/session/...） │  ← 兼容层：Flask API 逐一对齐
├──────────────────────── PyO3 ────────────────┤
│ zan Rust 内核 (_zan)                          │
│  • tokio 多线程 HTTP/1.1 服务器（keep-alive、   │
│    chunked、管线化、100-continue、超时/大小上限）│
│  • Trie 路由器（Werkzeug 转换器语义、静态优先、  │
│    strict/merge-slash 重定向）                 │
│  • 静态文件服务（完全在 Rust 侧，不碰 GIL）      │
│  • Rust 原生 JSON 序列化（与 json.dumps 输出对齐）│
│  • 错误路径：404/405/413/431 等不进 Python      │
└─────────────────────────────────────────────┘
```

不基于 WSGI：应用由内置 Rust 服务器运行，没有 `environ`/`start_response`，
不经过 `werkzeug.serving`/gunicorn。

## 源码布局

| 路径 | 内容 |
| --- | --- |
| `src/http.rs` | HTTP/1.1 连接处理：头/查询串解析、静态文件服务（canonicalize 防穿越、Last-Modified/304）、调度管线（`handle` → 路由匹配 → `dispatch_python` 跨 FFI）、响应写出（统一补 `Server`/`Date`/`Content-Length`）、连接循环（keep-alive、chunked、100-continue、超时） |
| `src/router.rs` | Trie 路由 + 转换器（`Conv::Str/Int/Float/Path/Uuid/Any`）。原始（百分号编码的）路径切段后在 trie 上同时走静态段与参数段，收集候选按优先级排序：静态 > int > float > uuid > any > string > path 尾段；未命中套用 Werkzeug 重定向规则（合并斜杠、严格尾斜杠，308） |
| `src/json.rs` | Rust 原生 JSON 序列化，输出与 `json.dumps`（含 ensure_ascii、键排序）对齐 |
| `src/pyapi.rs` | PyO3 `Server` 类：`add_rule`/`set_static`/`set_flags`/`start`/`stop`/`run`/`run_balancer`/`test_request` 等跨语言入口；进程级共享 tokio 运行时与运行中服务器注册表 |
| `src/balancer.rs` | 多进程模式的 TCP 负载均衡器：对外端口 accept，连接级 round-robin 转发给各 worker，转发首条请求时注入 `X-Forwarded-For` |
| `zan/*.py` | Python 兼容层（15 个模块）：`Flask` 应用、Request/Response 包装、上下文栈、会话、蓝图、模板、调试、CLI、信号 |

## Python 层与 Rust 内核的边界

`app.run()` / `test_client()` 首次调用时 `_ensure_server()` 编译出
`_zan.Server`：

1. `add_rule(rule, methods, view, endpoint, auto_options)` —— 把每条规则的
   **视图函数对象**直接交给 Rust 保存；
2. `set_static(prefix, folder)` —— 应用与各蓝图的静态目录；
3. `set_pipeline(app._pipeline)` —— fast path：`(request, view, kwargs) → Response`，
   在 Python 侧完成上下文 push、钩子、信号、会话；
4. `set_dispatch(app._process)` —— slow path：404/405 等错误回退到 Python
   全量管线（保证 errorhandler 生效）；
5. `set_flags(fast, debug, log, max_body, cc_max_age, trap_http, ...)`。

之后任何路由增删（`add_url_rule`/`register_blueprint`）都会把 `_server`
置空，下次请求重建——热注册路由不受支持。

## 请求生命周期时序

```
客户端
  │ TCP 连接
  ▼
tokio worker（Rust，全程不占 GIL）
  ① 解析请求行与头（上限：头 64 KiB / 100 个头；读超时 60s）
  ② 路由匹配（trie）
     ├── 命中静态前缀 → serve_static：MIME 推断、canonicalize 防穿越、
     │   Last-Modified/304 → 直接写出，不进 Python
     ├── 未命中 → merge-slash / strict-slash → 308 重定向（Rust 直接写出）
     ├── 路径无规则 → 404（Rust 直接写出）
     ├── 方法不匹配 → 405 + Allow（Rust 直接写出）
     └── 命中视图规则：
  ③ 读 body（上限 max_body，默认 64 MiB，超出 → 413，Rust 直接写出）
  ④ spawn_blocking 拿 GIL（等待期间 allow_threads，其他线程不被阻塞）
  ▼
Python fast path（app._pipeline）
  ⑤ 构造 zan.Request（方法/路径/查询对/头/body/remote_addr）
  ⑥ push AppContext → push RequestContext（隐式开启会话）
  ⑦ request_started 信号
  ⑧ before_first_request（仅首个请求）→ 蓝图 before_request → 应用 before_request
  ⑨ 视图函数（路由参数已按转换器转成原生类型：int/float/uuid.UUID）
  ⑩ 异常 → errorhandler 链 → HTTPException.get_response() → 500
     （debug 模式渲染调试页）
  ⑪ make_response（str/bytes/dict/Response/元组 → Response）
  ⑫ 应用 after_request → 蓝图 after_request（注册逆序）
  ⑬ request_finished 信号；pop RequestContext（写回会话 Cookie）
     → pop AppContext
  ▼
Rust 侧写出
  ⑭ Response._fast() 以 (status, headers, body) 元组过 FFI（无中间 environ）
     ——str/bytes/dict/list/元组返回值也可以在 Rust 侧直接序列化
  ⑮ 统一补 Server/Date/Content-Length，写回 socket（keep-alive 复用连接）
```

关键点：

- **静态文件、404/405/413/431、JSON 序列化都留在 Rust 侧**，纯文本/JSON
  这类简单视图几乎不产生 Python 对象；
- Python 视图运行期间持有 GIL，但等待请求解析/写响应时 Rust 线程不占
  GIL，多连接并发不受 Python 侧限制；
- 每个请求独立的上下文栈（`_request_ctx_stack`/`_app_ctx_stack`），
  语义与 Flask 完全一致（见[上下文与钩子](context.md)）。

## 运行时模型（多实例与多核）

- **进程级共享运行时**：整个 Python 进程只有一份 tokio 多线程运行时，
  IO worker 线程数 = CPU 逻辑核数（惰性创建）。多个 `Flask` 应用可以
  同时 `start()` 在线，共享这份运行时——线程开销不随实例数增长
  （详见[多实例与多核](multi.md)）。
- **非阻塞生命周期**：`app.start()` 返回 `(server_id, addr)`，
  `app.stop(id)` 优雅停止；阻塞的 `app.run()` 只是「start + 信号轮询 +
  stop」的组合。
- **多进程模式**：`app.run(processes=N)` 时本进程只运行纯 Rust 的
  TCP 负载均衡器（`src/balancer.rs`），把连接 round-robin 转发给 N 个
  worker 子进程（各自独立解释器与 GIL），突破 Python 单核限制；
  转发时注入 `X-Forwarded-For` 保留真实客户端 IP。

## 性能数据

### 与 Flask 的同机对比（keep-alive）

Windows、Python 3.13、8 keep-alive 连接、纯 Python 视图函数：

| 场景 | zan | Flask dev server | 加速 |
| --- | --- | --- | --- |
| 纯文本 | 3205 req/s | 291 req/s | **11.0x** |
| JSON | 2941 req/s | 423 req/s | **6.9x** |
| 路由参数 | 3077 req/s | 419 req/s | **7.4x** |
| POST JSON | 2375 req/s | 422 req/s | **5.6x** |

复现：`python benchmarks/bench_keepalive.py`（每请求新建连接的版本
`bench_vs_flask.py` 约 2–3x）。注意 Flask dev server（Werkzeug）本身未开
keep-alive，此对比对两者使用同一客户端与负载。

### TechEmpower 标准测试（本机近似）

按 TFB 规范实现六类标准端点（plaintext/json/db/queries/updates/
fortunes，world 10000 行 + fortune 转义陷阱数据集），两框架端点均通过
19 项规范断言。主对比为单连接串行（消除连接层实现差异，纯比框架
每请求开销；Flask 侧用生产级 WSGI 服务器 waitress）：

| 测试 | zan req/s | Flask+waitress req/s | 加速 |
| --- | ---: | ---: | ---: |
| plaintext | 1,150 | 199 | **5.8x** |
| json | 1,077 | 232 | **4.6x** |
| db | 115 | 101 | 1.1x |
| queries×20 | 127 | 103 | 1.2x |
| updates×20 | 135 | 78 | 1.7x |
| fortunes | 95 | 85 | 1.1x |

zan 并发吞吐（autocannon 20 连接，零错误）：plaintext **6,030–7,657 rps**、
json 5,768–6,061、db ~800、queries×20 ~700、updates×20 ~350、
fortunes ~750。

数据库主导的测试（db/queries/fortunes）差距收窄是普遍规律：瓶颈在
SQLite 查询与模板渲染，框架开销占比小——官方 TFB 榜单上所有框架皆然。
完整方法、局限声明与复现步骤见 `benchmarks/tfb/results.md`。

### 多核扩展

CPU 密集视图（~8ms 纯 Python 计算）下 `processes=N` 近似线性扩展，
受物理核数上限约束（2 核机器实测 1.9x）。复现：
`python benchmarks/bench_multiprocess2.py`。选型建议见
[多实例与多核](multi.md)。

## 路线图

- HTTPS/TLS（rustls）与 HTTP/2（`request.scheme` 届时不再固定为 `http`）；
- WebSocket 支持；
- `url_for` 对 `external` + `SERVER_NAME` 的更多边缘行为；
- 非 Windows 平台的 CI 矩阵与 abi3 wheel 发布。

## 相关文档

- [快速入门](quickstart.md)
- [上下文与钩子](context.md)
- [多实例与多核](multi.md)
- [常见问题](faq.md)
