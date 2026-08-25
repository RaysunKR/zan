# 调试

本页内容：debug 模式的开启方式与效果、交互式调试页的功能、重载器的进程模型（主进程 + worker 子进程、`ZAN_RUN_MAIN`）、彩色输出的控制。

## 开启 debug 模式

三种方式（优先级：`run()` 参数 > `FLASK_DEBUG` 环境变量 > 默认关闭）：

```python
app.run(debug=True)                 # 代码里
```

```bash
FLASK_DEBUG=1 python app.py         # 环境变量
python -m zan run --debug           # CLI
```

`app.debug = True` 或 `app.config["DEBUG"] = True` 也可设置，但注意：
`run()` 会在启动时用参数/环境变量覆盖它。debug 模式等效于：

- `app.debug = True`、`app.config["DEBUG"] = True`；
- 未捕获异常渲染交互式调试页（见下文）；
- 自动启用重载器（可用 `app.run(debug=True, use_reloader=False)` 关闭）。

**警告**：调试页会展示源码与局部变量，绝不要让 debug 模式暴露在公网上。

## 调试页

debug 模式下，视图中未捕获的异常返回 500 + Werkzeug 风格的 HTML 调试页：

- 异常类型与消息（如 `RuntimeError: kapow`）；
- **多帧回溯**，每帧可点击展开（`<details>`），显示：
  - 出错行附近的源码（前后各约 6 行，出错行高亮）；
  - 该帧的全部**局部变量**（`repr`，超 300 字符截断，repr 失败给占位符）；
- 页面底部附完整原始 traceback 文本（深色块，可直接复制）。

非 debug 模式下同样的异常返回简单的 500 页，不泄露任何细节。
可以脱离服务器直接渲染调试页（测试/离线分析）：

```python
from zan.debug import render_debug_page

try:
    raise ValueError("boom")
except ValueError as e:
    html = render_debug_page(e)
```

## 重载器

debug 模式（或 `use_reloader=True`）时采用「主进程 + worker 子进程」模型，
与 Werkzeug 的 reloader 行为对齐：

```
主进程（监视器，不运行服务器）
  └── worker 子进程（真正运行 app.run 的进程，ZAN_RUN_MAIN=1）
```

工作方式：

1. 主进程 spawn worker 子进程（重新执行 `python ... 你的启动命令`），并
   设置环境变量 `ZAN_RUN_MAIN=1`；
2. worker 中的 `app.run()` 检测到 `ZAN_RUN_MAIN=1`，直接运行服务器，
   不再进入重载逻辑（避免无限递归）；
3. 主进程每 1 秒扫描一遍**已导入的用户 `.py` 文件**（忽略标准库与
   site-packages）的 mtime，外加 `app.run(extra_files=[...])` 显式指定的
   文件；
4. 检测到变化 → terminate worker（5 秒不等则 kill）→ 重新 spawn；
5. worker 正常退出（如 Ctrl+C）→ 主进程跟随退出；worker 异常退出 →
   3 秒后自动拉起（连续崩溃时给排查时间）。

启动时输出：

```
 * zan 正在以重载模式启动（监视用户 .py 文件）
 * 检测到代码变动，正在重启…
```

注意：重载器只监视 Python 源文件；模板、静态文件不需要重启即生效。
Rust 侧（`src/*.rs`）改动需要重新 `maturin develop --release` 并手动重启。

如果代码里自己判断是否处于 worker 进程：

```python
from zan.debug import Reloader
Reloader.is_main_process()    # False 表示当前是 worker（ZAN_RUN_MAIN=1）
```

## 彩色输出

启动与日志信息带 ANSI 颜色（绿色 `*` 信息、黄色警告、红色错误）：

```
 * zan 'app' 启动
 * 调试模式：开启（重载器运行中）
 * 地址: http://127.0.0.1:5000
 * 按 CTRL+C 退出
```

控制方式：

| 环境变量 | 效果 |
| --- | --- |
| `NO_COLOR=1` | 强制关闭颜色 |
| `FORCE_COLOR=1` | 强制开启颜色（重定向到文件时有用） |
| （都不设） | 输出流是 tty 则开启，否则关闭（Windows 10+ 终端同样支持） |

## 相关文档

- [错误处理](errors.md)
- [命令行](cli.md)
- [配置参考](config.md#核心)
