# 快速入门

本页内容：用 zan 写一个完整的小应用——路由、请求、响应、模板、静态文件、会话、蓝图、错误处理，以及如何运行与调试。每节代码都可以直接运行（假定已按 [安装与构建](index.md#安装与构建) 构建好 `_zan` 扩展）。

## 最小应用

创建 `app.py`：

```python
from zan import Flask

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello, World!"

if __name__ == "__main__":
    app.run()
```

运行：

```bash
python app.py
# 或者用 CLI：
python -m zan run
```

访问 `http://127.0.0.1:5000/` 即可看到 Hello, World!。

## 路由

用 `@app.route` 装饰器把 URL 绑定到函数；URL 变量用 `<转换器:名字>` 声明：

```python
from zan import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return "index"

@app.route("/user/<name>")          # string 转换器（默认），str
def user(name):
    return f"Hello, {name}!"

@app.route("/post/<int:post_id>")   # int 转换器，视图收到 int
def post(post_id):
    return jsonify(post_id=post_id)

@app.route("/files/<path:subpath>") # path 转换器，可含斜杠
def files(subpath):
    return {"file": subpath}
```

一个视图处理多个方法用 `methods`；默认只有 `GET`（`HEAD` 隐含可用）：

```python
@app.route("/login", methods=["GET", "POST"])
def login():
    from zan import request
    if request.method == "POST":
        return "processing login"
    return "login form"
```

更多细节（uuid/any 转换器、308 重定向、405、OPTIONS）见[路由](routing.md)。

## 请求

`request` 是一个模块级代理，在视图（请求上下文）内直接使用：

```python
from zan import Flask, jsonify, request

app = Flask(__name__)

@app.route("/inspect")
def inspect():
    return jsonify(
        args=request.args.get("q", ""),       # 查询串
        form=dict(request.form),              # 表单（POST）
        json=request.get_json(silent=True),   # JSON body（无则 None）
        ua=request.headers.get("User-Agent", ""),
    )

@app.route("/echo", methods=["POST"])
def echo():
    return {"you_sent": request.get_json()}
```

```bash
curl -X POST http://127.0.0.1:5000/echo -H "Content-Type: application/json" \
     -d '{"hello": "zan"}'
```

完整属性列表见[请求对象](request.md)。

## 响应

视图可以直接返回 `str`/`bytes`/`dict`/`list`/`Response`，或 `(body, status, headers)` 元组：

```python
from zan import Flask, jsonify, make_response

app = Flask(__name__)

@app.route("/text")
def text():
    return "plain text"                        # 200, text/html

@app.route("/json")
def json_view():
    return {"a": 1}                            # 自动 JSON 化

@app.route("/created")
def created():
    return "made", 201, {"X-Custom": "yes"}    # 状态码 + 头

@app.route("/teapot")
def teapot():
    return "tea", 418

@app.route("/resp")
def resp():
    r = make_response("body", 200)
    r.headers["X-Zan"] = "1"
    return r
```

重定向与文件下载：

```python
from zan import redirect, send_file

@app.route("/go")
def go():
    return redirect("/text")

@app.route("/download")
def download():
    return send_file("data/report.pdf")
```

更多细节见[响应对象](response.md)。

## 模板

模板功能依赖可选的 jinja2（`pip install jinja2`）。默认模板目录是应用
所在目录下的 `templates/`：

```
templates/
  index.html
```

```python
from zan import Flask, render_template

app = Flask(__name__)

@app.route("/tpl/<name>")
def tpl(name):
    return render_template("index.html", name=name)
```

```html
<!-- templates/index.html -->
<h1>Hello {{ name }}!</h1>
```

也可以渲染字符串模板，或在模板里用 `url_for`、`get_flashed_messages` 与 `|tojson`：

```python
from zan import render_template_string

@app.route("/t")
def t():
    return render_template_string("Hello {{ name }}!", name="zan")
```

## 静态文件

默认目录 `<root_path>/static/` 由 Rust 内核直接服务，路径为 `/static/<文件名>`：

```
static/
  app.js
  css/site.css
```

访问 `http://127.0.0.1:5000/static/app.js`。支持 `Last-Modified`/304 缓存、
MIME 推断与路径穿越防护（`/static/../secret.txt` 返回 404）。
在模板中用 `url_for('static', filename='app.js')` 生成链接。

## 会话

会话基于签名 Cookie，需要先设置 `SECRET_KEY`：

```python
from zan import Flask, redirect, request, session, flash

app = Flask(__name__)
app.secret_key = "dev-secret"   # 生产环境请用随机值

@app.route("/login", methods=["POST"])
def login():
    session["user"] = request.form.get("user", "?")
    flash("logged in")
    return redirect("/")

@app.route("/whoami")
def whoami():
    return {"user": session.get("user")}
```

更多细节（签名原理、permanent、闪存分类）见[会话与闪存](session.md)。

## 蓝图

蓝图用于把应用拆成可复用的组件：

```python
from zan import Blueprint, Flask, jsonify

app = Flask(__name__)
api = Blueprint("api", __name__, url_prefix="/api")

@api.route("/ping")
def ping():
    return {"pong": True}

@api.route("/users/<int:uid>")
def users(uid):
    return jsonify(uid=uid)

app.register_blueprint(api)
```

蓝图还可拥有自己的钩子、错误处理器、静态目录与模板目录，见[蓝图](blueprints.md)。

## 错误处理

用 `errorhandler` 自定义错误页；用 `abort` 中断请求：

```python
from zan import Flask, abort

app = Flask(__name__)

@app.errorhandler(404)
def not_found(e):
    return "custom not found", 404

@app.errorhandler(ValueError)
def on_value_error(e):
    return f"caught {e}", 500

@app.route("/boom")
def boom():
    abort(500, "something broke")
```

完整 `HTTPException` 家族与 `abort` 的全部用法见[错误处理](errors.md)。

## 运行与调试

```python
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
```

`debug=True` 时：

- 未捕获异常渲染交互式 traceback 调试页（局部变量、源码上下文）；
- 自动启用重载器——修改任何用户 `.py` 文件后服务器自动重启；
- 可以用 `NO_COLOR`/`FORCE_COLOR` 环境变量控制彩色输出。

也可以用环境变量 `FLASK_DEBUG=1` 开启。调试模式绝不要暴露在公网上。详见[调试](debugging.md)。

## 下一步

- [路由](routing.md)、[请求对象](request.md)、[响应对象](response.md)
- [上下文与钩子](context.md)、[蓝图](blueprints.md)
- [测试](testing.md)：用 `test_client` 写单元测试
- [常见问题](faq.md)：与 Flask 的差异清单
