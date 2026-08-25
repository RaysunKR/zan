"""种子数据：首次运行且库为空时写入 5 篇示例文章与评论。"""
from db import get_conn, now_iso, reading_minutes, slugify

POSTS = [
    {
        "title": "为什么我用 Rust 给 Python 写了一个 Web 框架",
        "summary": "Python 的开发效率 + Rust 的运行性能，能不能同时拿到？zan 的答案是：把 HTTP 内核下沉到 Rust，把开发者体验留在 Python。",
        "tags": "Rust,Python,zan",
        "content_md": """## 起点

Flask 的优雅之处在于：**你写的每一行代码都是业务逻辑**。路由是装饰器，
请求是对象，响应是返回值。但它背后的 Werkzeug 开发服务器慢得出了名。

换个角度：HTTP 解析、路由匹配、静态文件、JSON 序列化——这些和业务
毫无关系，为什么要用 Python 做？

## zan 的架构

```
你的代码（Flask 写法）
    ↓ PyO3
Rust 内核：tokio + httparse + trie 路由
```

- 请求解析、404/405、静态文件：**完全不进 Python**
- 视图调度：`spawn_blocking` + GIL，钩子/会话语义与 Flask 一致
- 返回 `dict` 时由 Rust 直接序列化 JSON

## 数字

keep-alive 8 连接压测：纯文本 **11x**、JSON 6.9x、POST 5.6x。

## 什么时候不该用

- 需要 WSGI 中间件生态（gunicorn、sentry 旧版集成）时
- 需要 async 视图时（暂未支持）

其余时候，把 `from flask import` 改成 `from zan import` 试试。""",
    },
    {
        "title": "PyO3 踩坑记：GIL、Bound API 与 spawn_blocking",
        "summary": "三个最容易翻车的地方：什么时候必须持锁、0.22 的 _bound 后缀、以及为什么视图调用要丢进阻塞线程池。",
        "tags": "Rust,PyO3",
        "content_md": """## GIL 不是摆设

tokio 的 worker 线程默认不持有 GIL。调用任何 Python 对象之前必须
`Python::with_gil`，否则直接段错误。

## 0.22 的 Bound API

```rust
// 旧 API 已废弃
PyList::new(py, iter)
// 0.22 正确姿势
PyList::new_bound(py, iter)
```

`Py<T>` 的 `clone` 需要 `py` 参数——跨 await 持有 `Py<PyAny>` 时，
存**索引**、进 GIL 后再取引用。

## spawn_blocking 的必要性

视图是同步 Python 代码，直接在 tokio worker 上跑会阻塞 reactor。
`spawn_blocking` 让它进阻塞池，`py.allow_threads` 期间释放 GIL
让别的请求并行。""",
    },
    {
        "title": "从 Flask 迁移到 zan：一份清单",
        "summary": "绝大多数项目改一行 import 就能跑。这份清单列出真正需要注意的差异：reloader、WSGI、部署方式。",
        "tags": "Flask,迁移,zan",
        "content_md": """## 一行迁移

```python
- from flask import Flask, request, jsonify
+ from zan import Flask, request, jsonify
```

路由、钩子、会话、蓝图、模板、错误处理——API 完全一致。

## 需要注意的差异

1. **没有 WSGI**：不能用 gunicorn/uwsgi，`app.run()` 就是生产级服务器
2. **reloader 是子进程模型**：行为与 Werkzeug 一致，但 Windows 上
   终止依赖进程组
3. **request.scheme 暂为 http**：TLS 在路线图上，目前建议前置 Nginx

## 部署建议

```
Nginx (TLS/压缩) → zan (127.0.0.1:5000) → SQLite/PG
```

单进程即可吃满一个小型 VPS 的 CPU。""",
    },
    {
        "title": "用 trie 做路由匹配，比正则快在哪",
        "summary": "Werkzeug 把规则编译成正则再逐个匹配；zan 按段建 trie，一次遍历拿到全部候选。这篇讲优先级怎么排。",
        "tags": "Rust,算法,路由",
        "content_md": """## 段拆分 + trie

`/user/<int:uid>/profile` 拆成三段：静态 `user`、参数 `<int:uid>`、
静态 `profile`。插入 trie 时静态段与参数段分列表存放。

匹配时对每一段：先试静态（精确），再按**特异性**试参数转换器：

```
static > int > float > uuid > any > string > path(尾段)
```

一次深度优先遍历得到全部候选，按方法裁决（405 的 Allow 头由此而来）。

## 为什么不用正则

规则一多，正则逐个 `match` 是 O(n)。trie 把公共前缀合并，
路径 `/a/b/c` 只走一条链——复杂度只和**路径长度**有关。""",
    },
    {
        "title": "博客上线记：这个站本身就是 zan 写的",
        "summary": "吃自己的狗粮：zan-blog 的后端是 zan，前端 React + shadcn/ui 构建成静态文件，由同一个 zan 进程服务。",
        "tags": "zan,博客,React",
        "content_md": """## 架构

- **后端**：zan + SQLite，JSON API（文章/评论/标签/搜索/分页/点赞）
- **前端**：React + shadcn/ui（Tailwind + Radix），Vite 构建成纯静态文件
- **部署**：只有一个进程。`app.py` 同时服务 API 与静态站点

## 为什么不起独立前端服务

静态文件交给 zan 的 Rust 内核直接吐——带 Last-Modified/304、
MIME 推断，比 Node 静态服务还快。API 与页面同源，没有 CORS。

## 功能清单

草稿/发布、Markdown、标签、搜索、分页、评论、点赞、阅读时长、
浏览量、管理端（登录/编辑/删除）。

这篇文章本身，就是用这套系统发布的。""",
    },
]

COMMENTS = [
    (1, "阿明", "11x 太猛了，请问 Windows 支持怎么样？"),
    (1, "作者", "开发就是在 Windows 上做的，MSVC 工具链直接编。"),
    (2, "rustacean", "Bound API 那段太真实了，我上周刚被 deprecated 警告淹没。"),
    (5, "路人甲", "吃狗粮是最好的测试（dogfooding +1"),
]


def seed_if_empty() -> None:
    """库为空时写入种子数据。"""
    conn = get_conn()
    try:
        if conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] > 0:
            return
        ts = now_iso()
        for i, p in enumerate(POSTS):
            slug = slugify(p["title"], conn) if p["title"].isascii() else f"post-{i + 1}"
            cur = conn.execute(
                """INSERT INTO posts
                   (slug, title, summary, content_md, tags, draft, views, likes,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,0,?,?,?,?)""",
                (
                    slug,
                    p["title"],
                    p["summary"],
                    p["content_md"],
                    p["tags"],
                    20 + i * 7,
                    2 + i,
                    ts,
                    ts,
                ),
            )
            post_id = cur.lastrowid
            for (pid, author, body) in COMMENTS:
                if pid == i + 1:
                    conn.execute(
                        "INSERT INTO comments (post_id, author, body, created_at)"
                        " VALUES (?,?,?,?)",
                        (post_id, author, body, ts),
                    )
        conn.commit()
    finally:
        conn.close()
