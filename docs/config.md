# 配置参考

本页内容：`Flask.default_config` 全部键的含义与默认值、`config` 对象的读写方式（`from_mapping`/`from_object`/`from_pyfile`/`from_envvar`/`get_namespace`）。

## 读写配置

`app.config` 是 dict 子类，同时支持字典与属性两种访问：

```python
app.config["SECRET_KEY"] = "xxx"
app.config.SECRET_KEY          # "xxx"（缺键抛 AttributeError）
app.config.get("SECRET_KEY")
"SECRET_KEY" in app.config
```

批量加载：

```python
app.config.from_mapping(SECRET_KEY="xyz", DEBUG=True)   # dict/kwargs，只收大写键

class Config:
    DEBUG = True
app.config.from_object(Config)                          # 只收全大写属性

app.config.from_pyfile("config.py")                     # 相对 root_path；silent=True 时文件缺失不报错

app.config.from_envvar("ZAN_CONFIG")                    # 环境变量指向配置文件

app.config.get_namespace("SESSION_")                    # {"cookie_name": "session", ...}
```

## 全部配置键

以下逐项对应 `zan/app.py` 中的 `default_config`。

### 核心

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `DEBUG` | `False` | 调试模式。开启后未捕获异常渲染调试页并默认启用重载器（见[调试](debugging.md)）。**不要在生产环境开启。** |
| `TESTING` | `False` | 测试模式。开启后 `_ensure_server` 关闭访问日志；`test_client` 下常用。 |
| `SECRET_KEY` | `None` | 会话签名密钥。不设置时 session 只读（写入抛 `RuntimeError`），`flash` 不可用（见[会话](session.md)）。 |
| `APPLICATION_ROOT` | `"/"` | 应用挂载根路径；作为会话 Cookie Path 的回退值。 |
| `SERVER_NAME` | `None` | 域名（如 `"example.com"`）。`url_for(_external=True)` 构建绝对 URL 时使用；未设置时用 `"localhost"`。 |
| `PREFERRED_URL_SCHEME` | `"http"` | `url_for` 构建外链时的默认 scheme。 |

### 请求限制

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `MAX_CONTENT_LENGTH` | `None` | 请求体大小上限（字节）。`None` 时内核上限 64 MiB；超过返回 413（Rust 侧直接返回，不进 Python）。见[性能调优](faq.md#性能调优)。 |
| `MAX_COOKIE_SIZE` | `4093` | Cookie 大小上限（保留字段，当前未强制执行）。 |

### 会话

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `SESSION_COOKIE_NAME` | `"session"` | 会话 Cookie 的名字。 |
| `SESSION_COOKIE_DOMAIN` | `None` | Cookie 的 Domain 属性；`None` 由浏览器按当前域处理。 |
| `SESSION_COOKIE_PATH` | `None` | Cookie 的 Path 属性；`None` 回退到 `APPLICATION_ROOT`。 |
| `SESSION_COOKIE_HTTPONLY` | `True` | HttpOnly——JS 无法读取该 Cookie。 |
| `SESSION_COOKIE_SECURE` | `False` | Secure——仅 HTTPS 传输。启用 TLS 前保持默认即可。 |
| `SESSION_COOKIE_SAMESITE` | `None` | SameSite 属性，可设 `"Strict"`/`"Lax"`/`"None"`。 |
| `PERMANENT_SESSION_LIFETIME` | `timedelta(days=31)` | `session.permanent = True` 时 Cookie 的有效期。 |
| `SESSION_REFRESH_EACH_REQUEST` | `True` | 每次请求（即使未修改会话、只读取过）都刷新会话 Cookie。 |

### 静态文件与缓存

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `SEND_FILE_MAX_AGE_DEFAULT` | `None` | `send_file` 与静态文件的 `Cache-Control: max-age` 秒数。`None` 时内核按 43200（12 小时）下发；传 `timedelta` 会换算成秒；`-1` 禁用 Cache-Control。 |

### 错误处理

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `TRAP_HTTP_EXCEPTIONS` | `False` | `True` 时 `HTTPException` 不被转换为错误响应，而是作为普通异常冒泡（见[错误处理](errors.md#trap_http_exceptions)）。 |
| `TRAP_BAD_REQUEST_ERRORS` | `True` | 与新版 Flask 默认一致：`request.args["缺键"]` 抛出的 `BadRequestKeyError` 带上键名信息。 |

### JSON

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `JSON_AS_ASCII` | `True` | 保留键（JSON 行为实际由 `app.json` provider 控制，见[响应对象](response.md#jsonify)）。 |
| `JSON_SORT_KEYS` | `True` | 同上，保留键；`jsonify` 默认排序。 |
| `JSONIFY_MIMETYPE` | `"application/json"` | JSON 响应的 Content-Type。 |

实际控制 `jsonify` 输出的是 `app.json`（`DefaultJSONProvider`）：

```python
app.json.sort_keys = False
app.json.ensure_ascii = False
```

### 模板

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `TEMPLATES_AUTO_RELOAD` | `None` | 保留键。模板改动由 jinja 的 auto_reload 处理，无需重启。 |
| `EXPLAIN_TEMPLATE_LOADING` | `False` | 保留键（jinja 调试特性，当前未实现）。 |

### 其他

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `FLOWER_VERBOSE_ERROR` | `None` | 保留键（兼容占位）。 |

## 相关文档

- [会话与闪存](session.md)
- [常见问题](faq.md#性能调优)
- [架构](architecture.md)
