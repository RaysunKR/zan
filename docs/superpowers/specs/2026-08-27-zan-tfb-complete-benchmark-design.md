# zan 完整服务部署与 TechEmpower 风格性能测试设计

## 1. 目标与范围

在测试服务器 `192.168.117.137` 上部署一个功能完整的 Web 服务，使用 zan 编写，并与 Flask 编写的等价服务进行 TechEmpower 风格的性能对照测试。

覆盖范围：

1. **TechEmpower 6 个标准端点**（plaintext、json、db、queries、updates、fortunes），使用 PostgreSQL。
2. **Flask 核心特性演示**：蓝图（Blueprint）、服务端模板渲染（Jinja2）、静态文件服务、Session/Flash、错误处理器、`url_for`/`redirect`/`jsonify`。
3. **性能对照**：zan 单进程、zan 多进程 `run(processes=N)`、Flask + gunicorn + gevent。
4. **可复现输出**：部署脚本、压测脚本、结果表格、监控数据。

## 2. 目录结构

在仓库中新建 `benchmarks/complete/` 目录：

```
benchmarks/complete/
├── shared/
│   ├── __init__.py
│   ├── models.py              # PostgreSQL 数据访问（world / fortune）
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html         # 首页：展示端点列表
│   │   └── fortunes.html      # TFB fortunes 模板
│   └── static/
│       ├── css/style.css
│       └── js/app.js
├── zan_app/
│   ├── app.py                 # zan Flask 实例、路由注册
│   ├── multi.py               # zan 多进程入口（app.run(processes=N)）
│   ├── views/
│   │   ├── tfb.py             # 6 个 TFB 端点
│   │   ├── demo.py            # 首页、模板、静态、session/flash
│   │   └── api.py             # 蓝图 API
│   └── config.py
├── flask_app/
│   └── （与 zan_app 等价结构，仅框架替换为 flask）
├── init_db.py                 # 创建数据库、表、灌入数据
├── requirements.txt           # 依赖：zan / flask / gunicorn / gevent / psycopg / jinja2
├── deploy.sh                  # 服务器上一键安装、建库、启服务
├── benchmark.sh               # wrk 压测主脚本
├── collect_metrics.sh         # 压测期间采集 CPU、火焰图
├── check.py                   # 正确性自检
└── report.py                  # 解析 wrk 输出，生成 results.md + CSV
```

## 3. 服务端点

zan 与 Flask 两个服务的源码应逐行等价：仅 `from zan import ...` 与 `from flask import ...` 不同，视图逻辑、模板、静态文件、配置完全一致。

| 路径 | 方法 | 说明 |
|---|---|---|
| `/plaintext` | GET | TFB：返回 `Hello, World!`，`text/plain` |
| `/json` | GET | TFB：返回 `{"message":"Hello, World!"}` |
| `/db` | GET | TFB：随机查 1 条 world |
| `/queries?queries=N` | GET | TFB：随机查 N 条 world（N 夹逼 1–500） |
| `/updates?queries=N` | GET | TFB：查 N 条并更新 randomNumber |
| `/fortunes` | GET | TFB：渲染 fortunes 模板 |
| `/` | GET | 首页，展示所有端点链接 |
| `/demo/template` | GET | Jinja2 模板渲染 |
| `/demo/session` | GET/POST | Session 读写、Flash 消息 |
| `/demo/static` | GET | 静态文件页面 |
| `/api/ping` | GET | 蓝图：简单 JSON |
| `/api/user/<int:id>` | GET | 蓝图：带参数路由 |
| `/error/<int:code>` | GET | 触发错误处理器 |

TFB 端点输出严格对齐 TechEmpower 规范；新增端点用于展示 Flask 兼容性。

## 4. 数据库层

使用 `psycopg`（psycopg 3）直连，避免 ORM 开销干扰框架对比。

- `world` 表：`id INT PRIMARY KEY, randomnumber INT`，10000 行。
- `fortune` 表：`id INT PRIMARY KEY, message TEXT`，12 条固定数据 + 运行时追加 1 条。
- 连接：每个视图函数内 `with get_conn() as conn:` 获取连接，函数结束关闭。
- 事务：`queries` 只读；`updates` 显式 `BEGIN / COMMIT`。

## 5. 部署流程

通过 SSH 登录 `192.168.117.137` 后执行 `deploy.sh`：

1. 安装系统依赖：`python3-dev`, `postgresql`, `postgresql-contrib`, `build-essential`, `libpq-dev`, `wrk`, `perf`。
2. 创建 Python venv，安装 `requirements.txt`。
3. 如 zan 无预编译 wheel，在服务器上用 `maturin build --release` 编译并安装 `_zan` 扩展。
4. 初始化 PostgreSQL：创建 `tfb` 数据库和用户，运行 `init_db.py`。
5. 启动服务：
   - zan 单进程：端口 7071（`python zan_app/app.py`）
   - zan 多进程：端口 7073（`python zan_app/multi.py`，调用 `app.run(processes=N)`）
   - Flask + gunicorn + gevent：端口 7072（`gunicorn -k gevent -w ... flask_app.app:app`）
6. 健康检查与正确性自检。

## 6. 压测方法

使用 `wrk`，参照 TechEmpower 官方配置：

| 测试 | 并发连接 | 持续时间 | pipeline | 请求 |
|---|---|---|---|---|
| plaintext | 256 | 15s | 16 | GET `/plaintext` |
| json | 256 | 15s | 无 | GET `/json` |
| db | 256 | 15s | 无 | GET `/db` |
| queries | 256 | 15s | 无 | GET `/queries?queries=20` |
| updates | 256 | 15s | 无 | GET `/updates?queries=20` |
| fortunes | 256 | 15s | 无 | GET `/fortunes` |

对比维度：

- zan 单进程（端口 7071）
- zan 多进程 `run(processes=N)`（端口 7073，N = CPU 逻辑核数）
- Flask + gunicorn + gevent（端口 7072，workers = 2 × CPU 核数 + 1）

每个端点预热后跑 3 轮，取中位数。

## 7. 监控与火焰图

压测同时运行：

1. `mpstat -P ALL 1` 记录各核 CPU。
2. `sar -n DEV 1` 记录网卡流量（如可用）。
3. `perf record -g -p <pid>` 采样 10s，生成火焰图（需要 `perf` 和 flamegraph.pl）。
4. 原始数据保存到 `benchmarks/complete/results/<timestamp>/`。

如 `perf` 不可用，降级为 `py-spy` 对 Python 进程采样。

## 8. 报告生成

`report.py` 解析 `wrk` 输出，生成：

- `results.md`：RPS、平均延迟、p50/p99、错误率、加速比表格。
- `results.csv`：便于后续画图或导入表格工具。
- 可选 `results.png`：RPS 对比柱状图（matplotlib）。

## 9. 成功标准

1. zan 与 Flask 服务均可稳定启动，并通过 `check.py` 正确性验证。
2. 6 个 TFB 端点全部完成 wrk 压测。
3. 报告包含 zan 单进程、zan 多进程、Flask+gunicorn 三列数据。
4. `deploy.sh` 与 `benchmark.sh` 可在服务器上一键复现。

## 10. 已知风险与应对

| 风险 | 应对 |
|---|---|
| 测试服务器无 Rust 工具链 | `deploy.sh` 中检测并安装 rustup，或优先使用 zan 预编译 wheel |
| 服务器无 `wrk` | 通过包管理器安装，或源码编译 |
| PostgreSQL 访问权限 | `deploy.sh` 中创建专用 `tfb` 用户并配置本地 trust/md5 |
| 端口冲突 | 使用 7071/7072/7073，脚本启动前检查占用 |
| `perf` 需要 root | 火焰图降级为 `py-spy`（无需 root），或 sudo 运行 perf |
