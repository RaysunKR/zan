"""SQLite 数据层：建表、连接管理与基础查询封装。

连接策略：每次调用 `get_conn()` 新建连接（SQLite 打开成本低，
且天然规避多线程共享问题），`foreign_keys` 打开，`journal_mode=WAL`
提高并发读写表现。数据库文件路径由环境变量 `BLOG_DB` 控制，
默认 ``blog/backend/blog.db``。
"""
import os
import sqlite3
import threading
from datetime import datetime, timezone

_DB_PATH = os.environ.get(
    "BLOG_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog.db"),
)

_init_lock = threading.Lock()
_initialized = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    content_md  TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',          -- 逗号分隔
    draft       INTEGER NOT NULL DEFAULT 0,
    views       INTEGER NOT NULL DEFAULT 0,
    likes       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS likes (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    sid     TEXT NOT NULL,                         -- 会话标识，一人一赞
    UNIQUE(post_id, sid)
);

CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
"""


def now_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def get_conn() -> sqlite3.Connection:
    """获取一个新的数据库连接（行工厂=dict）。"""
    global _initialized
    with _init_lock:
        if not _initialized:
            conn = sqlite3.connect(_DB_PATH)
            conn.executescript(SCHEMA)
            conn.commit()
            conn.close()
            _initialized = True
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_post(r: sqlite3.Row, with_content: bool = False) -> dict:
    """把 posts 行转成 API 契约中的 Post 对象。"""
    d = {
        "id": r["id"],
        "slug": r["slug"],
        "title": r["title"],
        "summary": r["summary"],
        "tags": [t for t in r["tags"].split(",") if t],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "views": r["views"],
        "likes": r["likes"],
        "draft": bool(r["draft"]),
    }
    if with_content:
        d["content_md"] = r["content_md"]
    return d


def reading_minutes(md: str) -> int:
    """按中文 ~400 字/分钟估算阅读时长。"""
    return max(1, round(len(md) / 400))


def slugify(title: str, conn: sqlite3.Connection) -> str:
    """由标题生成 URL 安全的 slug；中文标题退化为 post-<随机>。"""
    keep = "".join(
        ch for ch in title.lower() if ch.isascii() and (ch.isalnum() or ch == " ")
    ).strip().replace(" ", "-")
    keep = "-".join(p for p in keep.split("-") if p)
    base = keep or "post"
    slug = base
    n = 1
    while conn.execute("SELECT 1 FROM posts WHERE slug=?", (slug,)).fetchone():
        n += 1
        slug = f"{base}-{n}"
    return slug
