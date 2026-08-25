"""zan-blog：功能完备的博客应用。

- 后端：zan（本仓库的框架）+ SQLite + markdown
- 前端：React + shadcn/ui 的 Vite 构建产物（backend/static/），
  由同一个 zan 进程直接服务 —— **单一服务进程，无独立前端服务**

运行::

    python app.py            # http://127.0.0.1:8000
    # 管理密码默认 admin123，可用 BLOG_ADMIN_PASSWORD 覆盖

API 契约见 ../API.md。
"""
import json
import os
import re
import secrets
import sys

import markdown as _md

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from zan import Flask, abort, jsonify, request, session
from zan.exceptions import BadRequest, NotFound, Unauthorized
from zan.wrappers import Response, send_file

from db import get_conn, now_iso, reading_minutes, row_to_post, slugify
from seed import seed_if_empty

app = Flask(
    __name__,
    static_folder=None,   # 静态由下面的 SPA 路由自己处理
    template_folder=None,
)
app.config["SECRET_KEY"] = os.environ.get("BLOG_SECRET_KEY") or secrets.token_hex(16)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
BLOG_TITLE = os.environ.get("BLOG_TITLE", "zan 之声")
ADMIN_PASSWORD = os.environ.get("BLOG_ADMIN_PASSWORD", "admin123")

_md_converter = _md.Markdown(extensions=["fenced_code", "tables", "nl2br"])


def md_to_html(md_text: str) -> str:
    _md_converter.reset()
    return _md_converter.convert(md_text or "")


def is_admin() -> bool:
    return bool(session.get("admin"))


def require_admin():
    if not is_admin():
        raise Unauthorized("需要管理员登录")


def ensure_sid() -> str:
    """每个会话一个随机标识，用于「一人一赞」。"""
    sid = session.get("sid")
    if not sid:
        sid = secrets.token_hex(8)
        session["sid"] = sid
    return sid


def parse_tags(raw) -> list:
    """接受列表或逗号分隔字符串，规范化为去空的标签列表。"""
    if isinstance(raw, str):
        parts = raw.split(",")
    elif isinstance(raw, list):
        parts = [str(x) for x in raw]
    else:
        parts = []
    seen, out = set(), []
    for p in (s.strip() for s in parts):
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out[:8]  # 最多 8 个标签


# ---------------------------------------------------------------------------
# API：文章
# ---------------------------------------------------------------------------

@app.route("/api/posts", methods=["GET"])
def api_posts():
    """文章列表：分页 + 搜索（标题/摘要/正文）+ 标签筛选。"""
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(50, max(1, int(request.args.get("per_page", 10))))
    except ValueError:
        raise BadRequest("page/per_page 必须是整数")
    q = (request.args.get("q") or "").strip()
    tag = (request.args.get("tag") or "").strip()

    where, params = [], []
    if not is_admin():
        where.append("draft = 0")
    if q:
        where.append("(title LIKE ? OR summary LIKE ? OR content_md LIKE ?)")
        params += [f"%{q}%"] * 3
    if tag:
        # 逗号分隔存储，用双逗号夹逼匹配避免前缀误伤
        where.append("(',' || tags || ',') LIKE ?")
        params.append(f"%,{tag},%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM posts{clause}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM posts{clause} ORDER BY created_at DESC, id DESC"
            f" LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
    finally:
        conn.close()
    return jsonify(
        items=[row_to_post(r) for r in rows],
        total=total,
        page=page,
        pages=max(1, -(-total // per_page)),
    )


@app.route("/api/posts/<slug>", methods=["GET"])
def api_post_detail(slug):
    """文章详情：渲染 HTML、浏览量 +1、附上一篇/下一篇。"""
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
        if r is None or (r["draft"] and not is_admin()):
            raise NotFound("文章不存在")
        conn.execute("UPDATE posts SET views = views + 1 WHERE id = ?", (r["id"],))
        conn.commit()
        # 上下篇（同可见性范围内，按时间序）
        vis = "AND draft = 0" if not is_admin() else ""
        prev = conn.execute(
            f"SELECT slug, title FROM posts WHERE (created_at, id) < (?, ?) {vis}"
            " ORDER BY created_at DESC, id DESC LIMIT 1",
            (r["created_at"], r["id"]),
        ).fetchone()
        nxt = conn.execute(
            f"SELECT slug, title FROM posts WHERE (created_at, id) > (?, ?) {vis}"
            " ORDER BY created_at ASC, id ASC LIMIT 1",
            (r["created_at"], r["id"]),
        ).fetchone()
    finally:
        conn.close()
    post = row_to_post(r, with_content=True)
    post["content_html"] = md_to_html(r["content_md"])
    post["reading_minutes"] = reading_minutes(r["content_md"])
    post["prev_slug"] = prev["slug"] if prev else None
    post["prev_title"] = prev["title"] if prev else None
    post["next_slug"] = nxt["slug"] if nxt else None
    post["next_title"] = nxt["title"] if nxt else None
    post["views"] = r["views"] + 1
    return jsonify(post)


def _validate_post_payload(data: dict):
    """新建/编辑共用的字段校验，返回规范化的字段 dict。"""
    title = (data.get("title") or "").strip()
    if not title:
        raise BadRequest("标题不能为空")
    if len(title) > 200:
        raise BadRequest("标题过长")
    content_md = data.get("content_md") or ""
    summary = (data.get("summary") or content_md[:120]).strip()
    return {
        "title": title,
        "summary": summary,
        "content_md": content_md,
        "tags": parse_tags(data.get("tags")),
        "draft": 1 if data.get("draft") else 0,
    }


@app.route("/api/posts", methods=["POST"])
def api_create_post():
    """新建文章（管理员）。"""
    require_admin()
    data = request.get_json(silent=True) or {}
    fields = _validate_post_payload(data)
    conn = get_conn()
    try:
        slug = (data.get("slug") or "").strip()
        slug = re.sub(r"[^a-z0-9-]", "", slug.lower()) if slug else None
        if not slug:
            slug = slugify(fields["title"], conn)
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO posts (slug, title, summary, content_md, tags, draft,"
            " views, likes, created_at, updated_at) VALUES (?,?,?,?,?,?,0,0,?,?)",
            (
                slug,
                fields["title"],
                fields["summary"],
                fields["content_md"],
                ",".join(fields["tags"]),
                fields["draft"],
                ts,
                ts,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()
    post = row_to_post(row, with_content=True)
    post["content_html"] = md_to_html(row["content_md"])
    return jsonify(post), 201


@app.route("/api/posts/<int:pid>", methods=["PUT"])
def api_update_post(pid):
    require_admin()
    data = request.get_json(silent=True) or {}
    fields = _validate_post_payload(data)
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()
        if row is None:
            raise NotFound("文章不存在")
        conn.execute(
            "UPDATE posts SET title=?, summary=?, content_md=?, tags=?, draft=?,"
            " updated_at=? WHERE id=?",
            (
                fields["title"],
                fields["summary"],
                fields["content_md"],
                ",".join(fields["tags"]),
                fields["draft"],
                now_iso(),
                pid,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()
    post = row_to_post(row, with_content=True)
    post["content_html"] = md_to_html(row["content_md"])
    return jsonify(post)


@app.route("/api/posts/<int:pid>", methods=["DELETE"])
def api_delete_post(pid):
    require_admin()
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM posts WHERE id = ?", (pid,))
        conn.commit()
        if cur.rowcount == 0:
            raise NotFound("文章不存在")
    finally:
        conn.close()
    return jsonify(ok=True)


@app.route("/api/posts/<slug>/like", methods=["POST"])
def api_like_post(slug):
    """点赞：每会话每篇一次，重复请求幂等。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id, likes FROM posts WHERE slug = ?", (slug,)).fetchone()
        if row is None or row["likes"] is None:
            raise NotFound("文章不存在")
        sid = ensure_sid()
        if conn.execute(
            "SELECT 1 FROM likes WHERE post_id=? AND sid=?", (row["id"], sid)
        ).fetchone():
            return jsonify(likes=row["likes"])
        conn.execute("INSERT INTO likes (post_id, sid) VALUES (?,?)", (row["id"], sid))
        conn.execute("UPDATE posts SET likes = likes + 1 WHERE id = ?", (row["id"],))
        conn.commit()
        likes = conn.execute(
            "SELECT likes FROM posts WHERE id = ?", (row["id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    return jsonify(likes=likes)


# ---------------------------------------------------------------------------
# API：评论 / 标签 / 元信息 / 认证
# ---------------------------------------------------------------------------

@app.route("/api/posts/<slug>/comments", methods=["GET"])
def api_comments(slug):
    """评论列表。"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM posts WHERE slug=?", (slug,)).fetchone()
        if row is None:
            raise NotFound("文章不存在")
        rows = conn.execute(
            "SELECT id, author, body, created_at FROM comments WHERE post_id=?"
            " ORDER BY created_at ASC, id ASC",
            (row["id"],),
        ).fetchall()
    finally:
        conn.close()
    return jsonify(items=[dict(r) for r in rows])


@app.route("/api/posts/<slug>/comments", methods=["POST"])
def api_add_comment(slug):
    """发表评论。"""
    data = request.get_json(silent=True) or {}
    author = (data.get("author") or "").strip() or "匿名读者"
    body = (data.get("body") or "").strip()
    if not body:
        raise BadRequest("评论内容不能为空")
    if len(author) > 40:
        raise BadRequest("昵称过长")
    if len(body) > 2000:
        raise BadRequest("评论过长")
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM posts WHERE slug=? AND draft=0", (slug,)).fetchone()
        if row is None:
            raise NotFound("文章不存在")
        cur = conn.execute(
            "INSERT INTO comments (post_id, author, body, created_at) VALUES (?,?,?,?)",
            (row["id"], author, body, now_iso()),
        )
        conn.commit()
        cid = cur.lastrowid
    finally:
        conn.close()
    return jsonify(id=cid, author=author, body=body, created_at=now_iso()), 201


@app.route("/api/tags")
def api_tags():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT tags FROM posts" + ("" if is_admin() else " WHERE draft = 0")
        ).fetchall()
    finally:
        conn.close()
    counter: dict = {}
    for r in rows:
        for t in (x.strip() for x in r["tags"].split(",")):
            if t:
                counter[t] = counter.get(t, 0) + 1
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return jsonify(items=[{"name": n, "count": c} for n, c in items])


@app.route("/api/meta")
def api_meta():
    conn = get_conn()
    try:
        posts = conn.execute(
            "SELECT COUNT(*) FROM posts" + ("" if is_admin() else " WHERE draft=0")
        ).fetchone()[0]
        comments = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    finally:
        conn.close()
    return jsonify(blog_title=BLOG_TITLE, posts=posts, comments=comments)


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify(error="密码错误"), 401
    session["admin"] = True
    session.permanent = True
    return jsonify(ok=True)


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("admin", None)
    return jsonify(ok=True)


@app.route("/api/me")
def api_me():
    return jsonify(authenticated=is_admin())


# ---------------------------------------------------------------------------
# SPA：/ 与全部非 API 路径 → 静态文件，缺失时回退 index.html
# ---------------------------------------------------------------------------

@app.route("/")
def spa_index():
    return send_file(os.path.join(STATIC_DIR, "index.html"))


@app.route("/<path:p>")
def spa_assets(p):
    """静态资源直出；未知路径回退 index.html（客户端路由）；
    /api/ 下的未知路径保持 404 JSON。"""
    if p.startswith("api/") or p.startswith("api"):
        return jsonify(error="接口不存在"), 404
    candidate = os.path.normpath(os.path.join(STATIC_DIR, p))
    if (
        candidate.startswith(STATIC_DIR)
        and os.path.isfile(candidate)
        and ".." not in p
    ):
        return send_file(candidate)
    return send_file(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    seed_if_empty()
    port = int(os.environ.get("BLOG_PORT", 8000))
    app.run(host="127.0.0.1", port=port)
