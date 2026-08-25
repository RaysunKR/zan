# TechEmpower 风格基准 · 本机结果

按 TechEmpower Framework Benchmark 规范实现六类标准测试端点
（plaintext / json / db / queries / updates / fortunes），在
zan 与 Flask 上做同机对照。官方 rig 需要 Linux 裸机集群 + Docker，
本测试是规范的**本机近似**，方法与局限如下。

## 测试实现

- `zan_app.py` / `flask_app.py`：逻辑逐行等价，仅框架不同
- 数据集：TFB 规范的 world 表（10000 行）+ fortune 表（12 条含
  `<script>`、`&amp;` 等转义陷阱消息），SQLite + WAL
- 正确性：`check.py` 对照规范逐项断言（响应形状、Content-Type、
  queries 参数夹逼 1..500、updates 落库、fortunes 转义/排序/行数），
  **两框架各 19/19 通过**
- zan 的视图返回走 Rust 原生序列化（str/dict/list，不构造 Python
  Response）；fortunes 按规范用 jinja2 模板 + autoescape

## 方法与局限（与官方 rig 的差异，如实声明）

- 本机 2 核 Windows，压测客户端与服务端同机竞争 CPU，绝对值偏低
- 数据库是 SQLite 而非 PostgreSQL/MySQL
- 无官方 rig 的裸机隔离、多轮取中位数、盲测验证
- Flask 侧服务器选型说明：
  - Werkzeug dev server 不支持 keep-alive，高并发下大量连接失败，
    数据不可用（首轮实验证实）
  - waitress（生产级 WSGI）在 Windows 的高并发连接下退化严重
    （asyncore 模型，20 并发仅 ~8 rps）
  - 因此主对比采用**单连接串行 keep-alive**（httpx）：消除一切连接层
    实现差异，纯粹比较框架的每请求开销；两框架条件完全相同

## 主结果：单连接串行（每请求开销对比）

| 测试 | zan req/s | Flask+waitress req/s | 加速 |
| --- | ---: | ---: | ---: |
| plaintext | 1,150 | 199 | **5.8x** |
| json | 1,077 | 232 | **4.6x** |
| db | 115 | 101 | 1.1x |
| queries×20 | 127 | 103 | 1.2x |
| updates×20 | 135 | 78 | 1.7x |
| fortunes | 95 | 85 | 1.1x |

## zan 吞吐参考：autocannon 20 并发连接（10s，0 错误）

| 测试 | req/s | 平均延迟 | p99 |
| --- | ---: | ---: | ---: |
| plaintext | 6,030–7,657 | 2.1ms | 9–11ms |
| json | 5,768–6,061 | 3.0ms | 10ms |
| db | 795–867 | 24.6ms | 91–99ms |
| queries×20 | 675–759 | 29.2ms | 111–116ms |
| updates×20 | 345–370 | 52.2ms | 645–656ms |
| fortunes | 747–786 | 26.3ms | 100–114ms |

（两轮 harness 的区间；Flask 侧无有效并发数据，原因见上。）

## 解读

- **框架开销主导的测试**（plaintext/json）：zan 4.6–5.8x——HTTP 解析、
  路由、JSON 序列化、响应写出全在 Rust 内核完成
- **数据库主导的测试**（db/queries/fortunes）：1.1–1.2x——瓶颈在
  SQLite 查询与模板渲染，框架开销占比小，差距自然收窄。这符合
  官方 TFB 榜单上所有框架的普遍规律
- **updates**：1.7x，SQLite 写事务放大了差异（zan 的请求管线更短，
  事务周转更快）
- 在官方 rig（PostgreSQL + 裸机 + 多核）上，数据库类测试的两框架
  差距预计同样会收窄；plaintext/json 类的相对差距结构则会保持

## 复现

```bash
cd benchmarks/tfb
python db.py            # 重建数据集（已含在首次运行）
python zan_app.py       # 127.0.0.1:7071
python flask_app.py     # 127.0.0.1:7072（waitress）
python check.py http://127.0.0.1:7071   # 正确性自检
python harness2.py      # 主对比（串行）
python harness.py       # autocannon 并发（zan 侧有效）
```
