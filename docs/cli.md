# 命令行

本页内容：`python -m zan` 的三个命令——`run`（开发服务器）、`shell`（交互式解释器）、`routes`（列出路由）——以及 `--app` / `FLASK_APP` 的应用发现约定。

## 应用发现

三个命令都按同样的顺序定位应用对象（`--app` 参数 > `FLASK_APP` 环境变量 > 默认 `app`）：

```
python -m zan run --app myapp            # 模块名
FLASK_APP=myapp python -m zan run        # 环境变量
python -m zan run                        # 默认尝试模块 "app"
```

模块加载规则（与 Flask CLI 对齐）：

| 指定形式 | 行为 |
| --- | --- |
| `myapp` | 在模块中依次查找属性 `app` → `application` → `create_app` |
| `myapp:myapp2` | 取模块属性 `myapp2` |
| `myapp:create_app()` | 调用工厂函数（末尾 `()` 表示调用） |

找不到任何候选时退出并提示：

```
在模块 'xxx' 中未找到 app/application/create_app；请用 FLASK_APP=模块:变量 指定
```

## zan run

运行开发服务器：

```bash
python -m zan run                          # 127.0.0.1:5000
python -m zan run --host 0.0.0.0 --port 8080
python -m zan run --debug                  # 调试模式（含重载器）
python -m zan run --no-reload --debug      # 调试但不用重载器
python -m zan run --app myapp:make_app()   # 工厂函数
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--app` | 读 `FLASK_APP` 或 `app` | 应用位置（`module` 或 `module:attr`） |
| `--host` | `127.0.0.1` | 监听地址，`0.0.0.0` 对外开放 |
| `--port` | `5000` | 端口 |
| `--debug` | 关 | 调试模式（见[调试](debugging.md)） |
| `--reload` / `--no-reload` | 随 debug | 是否启用重载器 |

等价的 Python 写法是 `app.run(host=..., port=..., debug=...)`；
不带参数的 `app.run()` 还会读 `FLASK_RUN_PORT` 环境变量作为默认端口。
多核部署：`app.run(processes=N)`（CLI 暂未暴露该参数，用 Python 入口），
见[多实例与多核](multi.md)。

## zan shell

进入带应用上下文的交互式解释器（`python -m zan shell [--app ...]`）。

预注入的名字（与 Flask shell 相同）：

- `app` —— 加载到的应用对象；
- `current_app`、`g`、`request`、`session` —— 四个代理；
- `url_for` —— 绑定到应用的 URL 构建函数。

由于已经在 `app.app_context()` 内，可以直接调用需要上下文的函数：

```
$ python -m zan shell
zan 0.1.0 shell
应用: <Flask 'app'>
>>> current_app.name
'app'
>>> url_for("hello", name="bob")      # 需要请求上下文的用法见下
```

`url_for` 在应用上下文内即可用；访问 `request` 的属性仍需请求上下文：

```
>>> with app.test_request_context("/x?a=1"):
...     request.args.get("a")
'1'
```

## zan routes

列出全部路由（`python -m zan routes [--app ...]`）：

```
$ python -m zan routes
Rule              Methods                       Endpoint
----------------------------------------------------------
/api/ping         GET, HEAD, OPTIONS            api.ping
/hello/<name>     GET, HEAD, OPTIONS            hello
/login            GET, HEAD, OPTIONS, POST      login
```

三列分别是规则原文、方法集合（含自动的 HEAD/OPTIONS）、endpoint
（蓝图路由带 `蓝图名.` 前缀）。没有路由时输出 `(无路由)`。

## 相关文档

- [快速入门](quickstart.md#运行与调试)
- [调试](debugging.md)
- [常见问题](faq.md)（部署建议）
