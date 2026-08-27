"""Rust 异步 PostgreSQL 后端（通过 _zan._db）的模型层。

保持与 shared/models.py 类似的高层语义，但函数签名不再传递连接对象，
由 Rust 侧内部管理连接池与异步执行。
"""

import random
import os
from zan import _zan

DB = _zan._db


def get_world(wid: int):
    """返回 (id, randomnumber) 元组。"""
    return DB.db_get_world(wid)


def get_worlds(wids: list[int]):
    """按输入顺序返回 [(id, randomnumber), ...]。"""
    return DB.db_get_worlds(wids)


def update_worlds(rows: list[tuple[int, int]]):
    """rows: [(new_random, id), ...]"""
    DB.db_update_worlds(rows)


def get_fortunes():
    """返回 [(id, message), ...]。"""
    return DB.db_get_fortunes()
