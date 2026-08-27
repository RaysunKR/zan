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


def update_worlds(conn, rows: list[tuple[int, int]]):
    """rows: [(new_random, id), ...]"""
    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE world SET randomnumber = %s WHERE id = %s",
            rows,
        )
    conn.commit()


def get_fortunes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, message FROM fortune")
        return cur.fetchall()
