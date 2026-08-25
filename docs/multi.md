# 多实例与多核

本页内容：同进程运行多个应用（`start/stop` 非阻塞生命周期）、多进程模式
（`run(processes=N)`）的原理、负载均衡行为、`remote_addr` 与
X-Forwarded-For，以及容量规划建议。

## 同进程多实例

经典的 `app.run()` 会阻塞主线程。若需要在一个 Python 进程里同时服务
多个应用（例如多租户、灰度、测试编排），使用非阻塞 API：

```python
from zan import Flask

app_a = Flask("alpha")
app_b = Flask("beta")

@app_a.route("/")
def a(): return "A"

@app_b.route("/")
def b(): return "B"

sid_a, addr_a = app_a.start(port=0)   # 随机可用端口
sid_b, addr_b = app_b.start(port=0)
print(addr_a, addr_b)                 # 两个应用同时在线

app_a.stop(sid_a)                     # 停止其中一个，另一个不受影响
app_b.stop(sid_b)
```

- `start(host, port)` 返回 `(server_id, bound_addr)`；`port=0` 让系统
  分配端口（`bound_addr` 拿到实际地址）。
- `stop(server_id, timeout=5)` 优雅停止：关闭监听、给在途连接至多
  `timeout` 秒排空时间。
- 实例数没有上限；所有实例共享同一个 Rust 运行时（见下）。

## 共享运行时

整个进程只有**一个** tokio 多线程运行时，IO worker 线程数固定为
CPU 逻辑核数（`available_parallelism`）。首次 `start()`/`run()` 时惰性
创建。多实例不会成倍增加线程，只在实例间复用。

查询当前运行时信息：

```python
server = app._ensure_server()
server.runtime_workers   # IO worker 线程数（= CPU 核数）
server.cpu_count
server.running_servers   # 本进程运行中的实例数
```

## 多进程模式（多核扩展）

Python 视图受 GIL 限制，单进程最多用满约一个核。`processes=N` 启动
N 个 worker 子进程，每个进程独立的解释器与 GIL，真正并行执行视图：

```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, processes=4)
```

进程模型：

```
            对外端口 8000
父进程  ┌─ TCP 负载均衡器（纯 Rust，round-robin）
        │      │ 转发时注入 X-Forwarded-For
        ├─→ worker-0  127.0.0.1:随机  (独立 Python/GIL)
        ├─→ worker-1  127.0.0.1:随机
        ├─→ worker-2  ...
        └─→ worker-3
```

要点：

- **连接级亲和**：一条客户端连接始终落在同一个 worker（keep-alive
  语义完整保留）；新连接按 round-robin 分配。
- **真实客户端 IP**：均衡器把客户端 IP 以 `X-Forwarded-For` 注入首条
  请求，`request.remote_addr` 自动取 XFF 首地址。
- **worker 角色识别**：子进程以 `ZAN_WORKER=1` + `ZAN_WORKER_PORT`
  环境变量重新执行入口脚本；`app.run()` 检测到后只服务分配的本地端口。
  因此 `run(processes=N)` 的脚本必须能重复执行（`if __name__ == "__main__"`）。
- **Ctrl+C**：父进程收到信号后终止全部 worker（先 terminate，5 秒后 kill）。
- **debug/reloader 与多进程互斥**：多进程模式下自动禁用重载器
  （worker 由父进程管理，无需自重启）。

### 与 reloader / WSGI 的关系

- `use_reloader=True`（debug 默认开）只对单进程模式生效。
- 多进程模式下每个 worker 都会执行模块级代码；副作用（如全局连接池）
  在每个 worker 各有一份，这与 gunicorn 的行为一致。

## 容量规划

| 场景 | 建议 |
| --- | --- |
| IO 密集（代理、数据库等待为主） | 单进程即可：Rust 内核充分利用多核做 IO，视图等待时释放 GIL |
| CPU 密集（纯 Python 计算、模板渲染重） | `processes=CPU核数`，吞吐近似线性扩展 |
| 混合 | `processes=核数/2` 起步，压测调整 |

基准参考（`benchmarks/bench_multiprocess2.py`，~8ms 纯计算视图、
多客户端 keep-alive）：2 核机器上 `processes=2` 达 **1.9x**（受物理
核数上限约束）。核数更多的机器扩展更接近线性。

另见 TechEmpower 标准测试（`benchmarks/tfb/results.md`）：单连接
串行下 plaintext/json 类 zan 为 Flask 的 4.6–5.8x；数据库类测试
受 SQLite 主导收窄至 1.1–1.2x。

## 相关页面

- [架构](architecture.md) — 请求生命周期与运行时细节
- [配置](config.md) — 相关配置项
- [常见问题](faq.md) — 部署建议
