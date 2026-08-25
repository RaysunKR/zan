# zan-blog API 契约（前后端共同遵守）

Base URL: 同源（前端由 zan 直接服务，无跨域）。

## 认证
会话 Cookie（`session`）。登录：`POST /api/login` `{"password": "..."}` → `{"ok": true}` 或 401。
`GET /api/me` → `{"authenticated": bool}`。`POST /api/logout`。
管理密码：环境变量 `BLOG_ADMIN_PASSWORD`，默认 `admin123`。

## 文章
- `GET /api/posts?page=1&per_page=10&q=关键词&tag=标签名`
  → `{"items": [PostCard...], "total": int, "page": int, "pages": int}`
  PostCard: `{id, slug, title, summary, tags: [str], created_at, reading_minutes, views, draft}`
  只返回非草稿（未认证时）；认证后包含草稿，且 draft 文章带 `draft: true`。
- `GET /api/posts/<slug>` → Post 详情
  `{id, slug, title, summary, content_html, content_md, tags, created_at, updated_at, views, reading_minutes, draft, prev_slug, prev_title, next_slug, next_title}`
  未命中或草稿未认证 → 404 `{"error": "..."}`。每次命中 views+1。
- `POST /api/posts`（认证）`{title, summary, content_md, tags: [str], draft, slug?}`
  → 201 + Post 详情。slug 缺省由标题生成。
- `PUT /api/posts/<id>`（认证）同上字段 → 200 + Post。
- `DELETE /api/posts/<id>`（认证）→ `{"ok": true}`。
- `POST /api/posts/<slug>/like` → `{"likes": int}`（每会话一次）。

## 评论
- `GET /api/posts/<slug>/comments` → `{"items": [{id, author, body, created_at}]}`
- `POST /api/posts/<slug>/comments` `{"author": str, "body": str}` → 201 + 评论对象。

## 标签
- `GET /api/tags` → `{"items": [{"name": str, "count": int}]}`

## 元信息
- `GET /api/meta` → `{"blog_title": str, "posts": int, "comments": int}`

## 约定
- 时间格式 ISO8601 字符串。
- 错误统一 `{"error": str}`，状态码语义化（400/401/404）。
- 前端路由（SPA，未知路径回退 index.html）：
  `/` 文章列表；`/post/:slug` 详情；`/login` 管理登录；
  `/admin` 文章管理（列表/新建/编辑，路由 `/admin/edit/:id`、`/admin/new`）。
- 静态资源在 `/assets/*`（Vite 构建产物），favicon `/favicon.ico`。
