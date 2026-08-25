# 会话与闪存

本页内容：`SECRET_KEY` 的设置、签名 Cookie 会话的原理（HMAC-SHA256）、
`permanent` 会话、`flash`/`get_flashed_messages`、无密钥时的行为。

## 基本用法

会话基于签名 Cookie：数据存在客户端 Cookie 里，服务端用 `SECRET_KEY`
签名防篡改。使用会话前必须设置密钥：

```python
from zan import Flask, redirect, request, session

app = Flask(__name__)
app.secret_key = "dev-secret"        # 等价于 app.config["SECRET_KEY"] = ...
```

`session` 在请求上下文中就是一个 dict：

```python
@app.route("/login", methods=["POST"])
def login():
    session["user"] = request.form.get("user", "?")
    return redirect("/whoami")

@app.route("/whoami")
def whoami():
    return {"user": session.get("user")}   # 未登录为 None

@app.route("/logout")
def logout():
    session.pop("user", None)
    return "bye"
```

未设置 `SECRET_KEY` 时，对 session 的任何**写操作**抛出：

```
RuntimeError: The session is unavailable because no secret key was set.
Set the secret_key on the application to something unique and secret.
```

生成随机密钥：

```python
from zan.session import generate_secret_key
app.secret_key = generate_secret_key()   # 64 位十六进制字符
```

## 签名原理（HMAC-SHA256）

Cookie 值的构造与 itsdangerous 的 `URLSafeSerializer` 语义对齐：

1. 会话 dict 经 `TaggedJSONSerializer` 序列化为紧凑 JSON
   （`{" t": true, "y": ...}` 标记 `datetime`，`{" t": "tuple"}` 标记元组，
   读回时还原类型）；
2. JSON 字节做 URL-safe base64 编码（去掉 `=` 填充）得到 payload；
3. 签名密钥 = `SHA256(SECRET_KEY + "cookie-session")`（salt 为
   `"cookie-session"`），签名 = `HMAC-SHA256(签名密钥, payload)`；
4. Cookie 值 = `payload + "." + base64url(签名)`。

读取时用 `hmac.compare_digest` 恒时比较验签；签名不匹配或 payload 损坏时
**静默丢弃**，会话视为空——攻击者无法伪造内容，但任何拿到 Cookie 的人都能
**读取**内容（只签名、不加密，与 Flask 相同）。

因此：**不要在 session 里放密码等敏感明文**；需要服务端存储请自行扩展
`SessionInterface`。

## Cookie 属性

由配置控制（见[配置参考](config.md#会话)）：

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| `SESSION_COOKIE_NAME` | `session` | Cookie 名 |
| `SESSION_COOKIE_DOMAIN` | `None` | Domain 属性 |
| `SESSION_COOKIE_PATH` | `None`（回退 `APPLICATION_ROOT`） | Path 属性 |
| `SESSION_COOKIE_HTTPONLY` | `True` | HttpOnly |
| `SESSION_COOKIE_SECURE` | `False` | Secure |
| `SESSION_COOKIE_SAMESITE` | `None` | SameSite |

Cookie 何时写出：会话被**修改**（`session.modified = True`）时；若只是
读取过且 `SESSION_REFRESH_EACH_REQUEST=True`（默认），也会刷新。
会话被清空且修改过时，直接删除 Cookie。

## permanent 会话

默认情况下会话是浏览器会话级 Cookie（浏览器关闭即失效）。设置
`session.permanent = True` 后，Cookie 带 `Expires`/`Max-Age`，有效期由
`PERMANENT_SESSION_LIFETIME`（默认 `timedelta(days=31)`）决定：

```python
@app.route("/remember")
def remember():
    session["user"] = "alice"
    session.permanent = True        # 31 天有效
    return "ok"
```

```python
from datetime import timedelta
app.permanent_session_lifetime = timedelta(hours=1)   # 等价于改配置
```

## flash / get_flashed_messages

闪存消息存在 session 里，**下一次请求**取出后即被消费：

```python
from zan import Flask, flash, get_flashed_messages, redirect, render_template_string

app = Flask(__name__)
app.secret_key = "dev-secret"

@app.route("/flash")
def do_flash():
    flash("Saved!")                  # 默认分类 "message"
    flash("Something went wrong", category="error")
    return redirect("/show")

@app.route("/show")
def show():
    return render_template_string(
        "{% for m in get_flashed_messages() %}{{ m }}{% endfor %}"
    )
```

```python
get_flashed_messages()                            # ["Saved!", "Something went wrong"]
get_flashed_messages(with_categories=True)        # [("message", "Saved!"), ("error", ...)]
get_flashed_messages(category_filter=["error"])   # 只取指定分类
```

特点：

- 消息在读取后**删除**——同一路径第二次请求返回 `[]`；
- `flash()` 需要活动请求上下文（消息存在当前 session 中）；
- 每次发送触发 `message_flashed` 信号（见[上下文与钩子](context.md#信号)）；
- 模板中可直接调用全局函数 `get_flashed_messages()`（由 jinja 环境注入）。

## 相关文档

- [上下文与钩子](context.md)
- [配置参考](config.md)
- [快速入门·会话](quickstart.md#会话)
