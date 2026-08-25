# 常见问题

本页内容：zan 与 Flask 的差异清单、从 Flask 迁移的注意事项、部署建议、性能调优。

## 与 Flask 的差异清单

zan 追求 **API 兼容**而非二进制/生态兼容。已知差异：

| 差异点 | 说明 |
| --- | --- |
| 不基于 WSGI | 应用由内置 Rust 服务器直接运行，不经过 `werkzeug.serving`、gunicorn、uWSGI；也没有 `environ`/`start_response`。 |
| `request.scheme` 固定为 `http` | TLS 暂未实现（路线图：rustls + HTTP/2），因此 `request.is_secure` 恒为 `False`。 |
| 异步语义不同 | 并发由 Rust 内核的 tokio 提供，Python 视图仍是同步函数；不支持 `async def` 视图。 |
| 静态文件不走 Python | `/static/` 由 Rust 内核服务；同理，路由层产生的 404/405/413/431 响应在 Rust 侧直接返回，**无法**被 `errorhandler` 定制。 |
| 重载器只监视 `.py` 文件 | 模板/静态文件改动即时生效；`.py` 改动自动重启；Rust 侧（`src/*.rs`）改动需重新 `maturin develop --release`。 |
| `send_file` 全量读入内存 | 无 ranged/streaming 响应；生成器迭代器也会被完整拼接（见[响应对象](response.md#生成器响应)）。 |
| `app.cli.command` 是空操作 | 自定义 CLI 命令装饰器保留签名但不注册（当前只有内置的 `run/shell/routes`）。 |
| `url_map` 不是 Werkzeug Map | 只是 `规则字符串 → endpoint` 的 dict 兼容物；不要依赖 Werkzeug 的 `Rule` 对象。 |
| 部分 `request` 属性是简化版 | `user_agent` 只有 `.string`；`authorization` 不做 Basic 解码（详见[请求对象](request.md#其他)）。 |
| `MAX_COOKIE_SIZE` 等保留键 | 个别 Flask 配置键只保留默认值不生效，见[配置参考](config.md)。 |

**从 Flask 迁移**：把 `from flask import ...` 改成 `from zan import ...`，
移除 `from werkzeug import ...` 依赖；`app.run()` 用法不变。若代码依赖
WSGI 中间件、`flask.cli` 自定义命令或 async 视图，需要改造。

## 部署建议

- **生产反代部署（推荐）**：zan 直接运行（`app.run(host="127.0.0.1", port=5000)`，
  关闭 debug），前置 Nginx/Caddy 做域名、静态缓存与访问控制。TLS 由反代
  终止（zan 侧暂无 TLS）；
- 进程守护交给 systemd / supervisor / Docker，容器内 `CMD ["python", "-m", "zan", "run", "--host", "0.0.0.0"]`；
- **不要**用 gunicorn/uWSGI——它们面向 WSGI 应用，对 zan 无效；
- debug 模式（调试页 + 重载器）只在开发环境开启；
- 需要多进程横向扩展时，每个进程独立运行（会话在 Cookie 中签名而非服务端
  存储，天然无共享状态问题，但要求各进程使用同一个 `SECRET_KEY`）。

## 性能调优

### MAX_CONTENT_LENGTH

默认 `None` 时内核限制请求体 64 MiB。按业务收紧可以更早拒绝恶意大包
（超限返回 413，不进 Python）：

```python
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024   # 16 MiB
```

### SEND_FILE_MAX_AGE_DEFAULT

`send_file` 与静态文件响应的 `Cache-Control: max-age` 秒数。
默认 `None` 时内核按 **43200 秒（12 小时）** 下发：

```python
from datetime import timedelta

# 缓存 7 天
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = timedelta(days=7)

# 关闭缓存（每次都验证）
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = -1
```

静态资源命中 `Last-Modified`/ETag 时返回 304（无 body），配合浏览器缓存
可显著降低带宽。

### 其他建议

- **大文件放 `static/`**：由 Rust 内核服务，不占 GIL；避免用 `send_file`
  传大文件（全量读入内存）；
- **会话只存小数据**：签名 Cookie 会随每个请求来回传输；
  `SESSION_REFRESH_EACH_REQUEST=False` 可让只读请求不再重发 Cookie；
- **关闭 debug 与重载器**：生产环境 `app.run(debug=False)`；
- 性能瓶颈通常在 Python 视图本身——纯 Rust 路径（静态文件、简单 JSON）
  与复杂 Python 视图之间差距可达数倍（见[架构·性能数据](architecture.md#性能数据)）；
- **CPU 密集业务用多进程**：`app.run(processes=核数)` 让视图真正并行
  （见[多实例与多核](multi.md)）；IO 密集业务单进程即可；
- 复现基准：`python benchmarks/bench_keepalive.py`（keep-alive 对比）、
  `benchmarks/bench_multiprocess2.py`（多核扩展）、
  `benchmarks/tfb/harness2.py`（TechEmpower 标准测试，见
  `benchmarks/tfb/results.md`）。

### TechEmpower 标准测试参考

按 TFB 规范的六类端点（plaintext/json/db/queries/updates/fortunes）
本机对照：框架开销主导的 plaintext/json 上 zan 为 Flask（waitress）
的 **4.6–5.8x**；数据库主导的 db/queries/fortunes 差距收窄到 1.1–1.2x
（瓶颈在 SQLite 与模板渲染，与官方 TFB 榜单规律一致）。完整数据与
方法声明见 `benchmarks/tfb/results.md`。

## 其他常见问题

**Q：`RuntimeError: the zan Rust extension (_zan) is not built`？**
先执行 `maturin develop --release` 构建 Rust 扩展（需要 rustc 1.75+）。

**Q：`render_template` 报 `jinja2 is required`？**
`pip install jinja2`。模板是可选依赖。

**Q：改了路由没生效？**
路由在 `app.run()`/首次请求时编译进 Rust 内核。新增路由必须在启动前完成
注册（`add_url_rule`/`register_blueprint` 会主动使编译缓存失效，但请避免
在服务运行后动态注册）。

**Q：`session` 写入抛 RuntimeError？**
没有设置 `SECRET_KEY`。见[会话与闪存](session.md)。

**Q：`Working outside of request context`？**
`request`/`session` 只在请求上下文（或 `test_request_context`）内可用，
见[上下文与钩子](context.md)。

## 相关文档

- [架构](architecture.md)、[配置参考](config.md)
- [调试](debugging.md)、[命令行](cli.md)
