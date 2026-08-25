"""TechEmpower 基准数据库层（SQLite 版）。

按 TFB 规范构建数据集：
- world 表：10000 行 (id 1..10000, randomnumber 1..10000)
- fortune 表：12 条消息（含特殊字符，用于转义测试）

连接策略：threading.local 每线程一个连接（视图在 tokio blocking 池的
固定线程集上执行），WAL + synchronous=NORMAL 让 updates 测试不必每事务
fsync。SQLite 与官方的 PostgreSQL 不同，结果只作本机相对比较。
"""
import os
import random
import sqlite3
import threading

DB_PATH = os.environ.get(
    "TFB_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tfb.db"),
)

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False

FORTUNES = [
    (1, "frame was not set"),
    (2, "A computer scientist is someone who fixes things that aren't broken."),
    (3, "After you learn Esperanto, you'll find that it's a whole new language."),
    (4, "After you learn Esperanto, you'll find that you're a whole new person."),
    (5, "Adding manpower to a late software project makes it later."),
    (6, "All phone calls are obscene."),
    (7, "<script>alert('This should not be displayed in a browser alert box.');</script>"),
    (8, "Day of the tentacle & the wrath of the &amp; entity"),
    (9, "Everything is closer than you think."),
    (10, "Fortune favors the bold <b>HTML</b> & the careful"),
    (11, "Technology is a \"quantitative\" improvement to life."),
    (12, "When the only tool you have is a hammer, everything looks like a nail."),
]

SCHEMA = """
DROP TABLE IF EXISTS world;
DROP TABLE IF EXISTS fortune;
CREATE TABLE world (
    id           INTEGER PRIMARY KEY,
    randomnumber INTEGER NOT NULL
);
CREATE TABLE fortune (
    id      INTEGER PRIMARY KEY,
    message TEXT NOT NULL
);
"""


def init_db() -> None:
    """（重新）创建并填充 TFB 数据集。"""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    rng = random.Random(42)
    conn.executemany(
        "INSERT INTO world (id, randomnumber) VALUES (?, ?)",
        ((i, rng.randint(1, 10000)) for i in range(1, 10001)),
    )
    conn.executemany("INSERT INTO fortune (id, message) VALUES (?, ?)", FORTUNES)
    conn.commit()
    conn.close()


def get_conn() -> sqlite3.Connection:
    """当前线程的连接（惰性创建）。"""
    global _initialized
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    with _init_lock:
        if not _initialized:
            # 首次使用时若库不存在则自动建库
            if not os.path.exists(DB_PATH):
                init_db()
            _initialized = True
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    _local.conn = conn
    return conn


def get_world(conn: sqlite3.Connection, wid: int):
    return conn.execute(
        "SELECT id, randomnumber FROM world WHERE id = ?", (wid,)
    ).fetchone()


def update_worlds(conn: sqlite3.Connection, rows):
    """rows: [(new_random, id), ...]"""
    conn.executemany(
        "UPDATE world SET randomnumber = ? WHERE id = ?", rows
    )
    conn.commit()
