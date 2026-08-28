import os
import random
import threading
import psycopg

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tfb:tfb@localhost:5432/tfb",
)

_local = threading.local()


def get_conn():
    """Return a per-thread PostgreSQL connection."""
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        conn = psycopg.connect(DB_URL)
        _local.conn = conn
    return conn


def get_world(conn, wid: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, randomnumber FROM world WHERE id = %s",
            (wid,),
        )
        return cur.fetchone()


def get_worlds(conn, wids: list[int]):
    """Return [(id, randomnumber), ...] ordered like the input list (with duplicates preserved)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT w.id, w.randomnumber FROM world w "
            "JOIN unnest(%s::int[]) AS t(id) ON w.id = t.id",
            (wids,),
        )
        return cur.fetchall()


def update_worlds(conn, rows: list[tuple[int, int]]):
    """rows: [(new_random, id), ...]. Sorts by id internally to avoid deadlocks."""
    sorted_rows = sorted(rows, key=lambda r: r[1])
    ids = [r[1] for r in sorted_rows]
    nums = [r[0] for r in sorted_rows]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE world SET randomnumber = t.num "
            "FROM (SELECT unnest(%s::int[]) AS num, unnest(%s::int[]) AS id) AS t "
            "WHERE world.id = t.id",
            (nums, ids),
        )
    conn.commit()


def get_fortunes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, message FROM fortune")
        return cur.fetchall()
