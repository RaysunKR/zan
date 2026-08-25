"""TFB 端点正确性自检：对照规范逐项断言响应形状、头、转义与 clamp。"""
import json
import os
import re
import sqlite3
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7071"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tfb.db")

ok = 0


def get(path):
    r = urllib.request.urlopen(BASE + path, timeout=10)
    return r.status, dict(r.headers), r.read()


def check(name, cond):
    global ok
    if not cond:
        print(f"  FAIL {name}")
        sys.exit(1)
    ok += 1
    print(f"  ok   {name}")


print(f"== TFB correctness @ {BASE} ==")

# plaintext
st, hdr, body = get("/plaintext")
check("plaintext body", body == b"Hello, World!")
check("plaintext status", st == 200)
check("plaintext content-type", "text/plain" in hdr.get("Content-Type", ""))

# json
st, hdr, body = get("/json")
d = json.loads(body)
check("json shape", d == {"message": "Hello, World!"})
check("json content-type", "application/json" in hdr.get("Content-Type", ""))

# db
st, hdr, body = get("/db")
d = json.loads(body)
check("db keys", set(d.keys()) == {"id", "randomNumber"})
check("db ranges", 1 <= d["id"] <= 10000 and 1 <= d["randomNumber"] <= 10000)

# queries clamp
for q, expect in [("", 1), ("?queries=20", 20), ("?queries=9999", 500), ("?queries=abc", 1), ("?queries=0", 1)]:
    st, hdr, body = get("/queries" + q)
    arr = json.loads(body)
    check(f"queries{q or '(default)'} -> {expect}", isinstance(arr, list) and len(arr) == expect)

# updates
st, hdr, body = get("/updates?queries=5")
arr = json.loads(body)
check("updates shape", len(arr) == 5 and set(arr[0].keys()) == {"id", "randomNumber"})
conn = sqlite3.connect(DB)
db_row = conn.execute("SELECT randomnumber FROM world WHERE id=?", (arr[0]["id"],)).fetchone()
check("updates persisted", db_row[0] == arr[0]["randomNumber"])

# fortunes
st, hdr, body = get("/fortunes")
text = body.decode()
check("fortunes content-type", "text/html" in hdr.get("Content-Type", ""))
check("fortunes escaped", "&lt;script&gt;" in text and "<script>alert" not in text)
check("fortunes additional", "Additional fortune added at request time." in text)
check("fortunes rows", text.count("<tr>") == 13 + 1)  # header + 13 items
msgs = re.findall(r"<tr><td>\d+</td><td>(.*?)</td></tr>", text)
check("fortunes sorted", msgs == sorted(msgs))

print(f"\n全部通过（{ok} 项断言）")
