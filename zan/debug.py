"""zan 的调试支持：Werkzeug 风格的交互式调试页、彩色启动信息与代码重载器。

调试页不是 Werkzeug 的完整移植，而是提供同样有用的核心：
- 多帧回溯，可点击展开/折叠
- 每一帧的局部变量、源码上下文
- 原始 traceback 文本（供复制）
出于安全考虑，调试模式绝不应该暴露在公网上（与 Werkzeug 相同的建议）。

重载器采用「子进程 + 文件监视」模型，与 Werkzeug 的 run_simple(use_reloader=True)
行为对齐：主进程只负责监视并重启 worker 子进程，worker 崩溃后由主进程拉起。
"""
import os
import subprocess
import sys
import threading
import time
import traceback
import types

# ---------------------------------------------------------------------------
# ANSI 彩色输出
# ---------------------------------------------------------------------------

def _supports_color(stream) -> bool:
    """判断输出流是否支持 ANSI 颜色（Windows 10+ 的终端也支持）。"""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class _ColorStream:
    """包装 stderr/stdout，为带标记的行着色。"""

    def __init__(self, stream):
        self._stream = stream
        self._color = _supports_color(stream)

    def _write(self, text: str) -> None:
        # Windows 控制台可能不是 UTF-8：尽量以流可接受的编码输出
        try:
            self._stream.write(text)
        except UnicodeEncodeError:
            enc = getattr(self._stream, "encoding", None) or "ascii"
            self._stream.write(text.encode(enc, "replace").decode(enc, "replace"))

    def _paint(self, color: str, text: str) -> str:
        if not self._color:
            return text
        return f"\033[{color}m{text}\033[0m"

    def info(self, text: str) -> None:
        self._write(" \033[32m*\033[0m " if self._color else " * ")
        self._write(text + "\n")

    def warn(self, text: str) -> None:
        self._write(" \033[33m*\033[0m " if self._color else " * ")
        self._write(text + "\n")

    def error(self, text: str) -> None:
        self._write(" \033[31m*\033[0m " if self._color else " * ")
        self._write(text + "\n")

    def cyan(self, text: str) -> None:
        self._write(self._paint("36", text) + "\n")


# ---------------------------------------------------------------------------
# 调试页
# ---------------------------------------------------------------------------

_DEBUG_PAGE_TMPL = """<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<title>%(title)s</title>
<style>
 body { font-family: 'Segoe UI', Consolas, monospace; margin: 2em; background: #f5f5f5; color: #222; }
 h1 { font-size: 1.4em; }
 .exc-type { color: #b31d28; font-weight: bold; }
 .frame { background: #fff; border: 1px solid #ddd; border-radius: 4px; margin: 0.7em 0; }
 .frame > summary { cursor: pointer; padding: 0.5em 0.8em; font-weight: 600; }
 .frame-body { padding: 0 1em 0.8em 1em; }
 .src { background: #fafafa; border-left: 3px solid #bbb; padding: 0.4em 0.8em; overflow-x: auto; margin: 0.4em 0; }
 .src .line { white-space: pre; }
 .src .cur { background: #fdecea; display: inline-block; width: 100%%; }
 .vars { width: 100%%; border-collapse: collapse; margin-top: 0.4em; }
 .vars td, .vars th { border: 1px solid #e2e2e2; padding: 0.25em 0.6em; text-align: left; font-size: 0.92em; }
 .vars th { background: #f0f0f0; }
 pre.raw { background: #222; color: #eee; padding: 1em; overflow-x: auto; border-radius: 4px; }
 .hint { color: #777; font-size: 0.9em; }
</style>
</head>
<body>
<h1><span class="exc-type">%(exc_type)s</span>: %(exc_msg)s</h1>
<p class="hint">在 %(count)d 个帧中展开查看局部变量与源码。调试页仅限开发环境使用。</p>
%(frames)s
<h2>原始回溯</h2>
<pre class="raw">%(raw)s</pre>
<p class="hint">zan %(version)s 调试器</p>
</body>
</html>"""

_FRAME_TMPL = """<details class="frame">
<summary>File %(fname)s, line %(lineno)d, in %(funcname)s</summary>
<div class="frame-body">
<div class="src">%(source)s</div>
<table class="vars">
<tr><th>变量</th><th>值</th></tr>
%(vars)s
</table>
</div>
</details>"""


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _read_source_lines(filename: str, lineno: int, context: int = 6):
    """读取出错行附近的源码，返回 HTML 行列表（出错行高亮）。"""
    lines = []
    try:
        with open(filename, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except OSError:
        return ["<div class='line'>(无法读取源文件)</div>"]
    start = max(0, lineno - context - 1)
    end = min(len(all_lines), lineno + context)
    for i in range(start, end):
        mark = "cur" if i + 1 == lineno else ""
        text = _html_escape(all_lines[i].rstrip("\n"))
        lines.append(
            f"<div class='line {mark}'>{i + 1:5d} {text or ' '}</div>"
        )
    return lines


def _safe_repr(value, maxlen: int = 300) -> str:
    """repr 局部变量，失败时给出占位（与 pdb 的行为一致）。"""
    try:
        text = repr(value)
    except Exception:
        text = f"<repr 失败: {type(value).__name__}>"
    if len(text) > maxlen:
        text = text[:maxlen] + "...(截断)"
    return _html_escape(text)


def render_debug_page(exc: BaseException) -> str:
    """把未捕获异常渲染成 Werkzeug 风格的调试 HTML 页。"""
    import zan

    exc_type = type(exc).__name__
    exc_msg = _html_escape(str(exc))
    frames_html = []
    # werkzeug 顺序：最外层调用在前；逐帧渲染
    tb = exc.__traceback__
    entries = []
    while tb is not None:
        entries.append(tb.tb_frame)
        tb = tb.tb_next
    for frame in entries:
        code = frame.f_code
        fname = code.co_filename
        lineno = frame.f_lineno
        source = "".join(_read_source_lines(fname, lineno))
        rows = []
        for name in sorted(frame.f_locals):
            if name.startswith("__"):
                continue
            rows.append(
                f"<tr><td>{_html_escape(name)}</td><td>{_safe_repr(frame.f_locals[name])}</td></tr>"
            )
        vars_html = "\n".join(rows) if rows else "<tr><td colspan=2>(无局部变量)</td></tr>"
        frames_html.append(
            _FRAME_TMPL
            % {
                "fname": _html_escape(fname),
                "lineno": lineno,
                "funcname": _html_escape(code.co_name or "<module>"),
                "source": source,
                "vars": vars_html,
            }
        )
    raw = _html_escape("".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    ))
    return _DEBUG_PAGE_TMPL % {
        "title": _html_escape(f"{exc_type} — zan 调试器"),
        "exc_type": exc_type,
        "exc_msg": exc_msg,
        "count": len(entries),
        "frames": "\n".join(frames_html),
        "raw": raw,
        "version": getattr(zan, "__version__", "?"),
    }


# ---------------------------------------------------------------------------
# 重载器
# ---------------------------------------------------------------------------

class Reloader:
    """监视已导入的 .py 文件变动，变动后重启 worker 子进程。

    与 Werkzeug 相同的进程模型：

        主进程（监视器）
          └── worker 子进程（真正运行 app.run 的进程）

    worker 以环境变量 ``ZAN_RUN_MAIN=1`` 区分：主进程设置该变量后 spawn
    子进程，子进程中的 ``app.run(debug=True)`` 检测到它即直接运行服务器，
    不再进入重载逻辑（避免无限递归）。
    """

    POLL_INTERVAL = 1.0  # 秒

    def __init__(self, extra_files=None):
        self.extra_files = list(extra_files or [])
        self._mtimes: dict = {}

    def _iter_watch_files(self):
        """所有已加载的用户模块源文件 + 显式附加文件。"""
        seen = set()
        for path in self.extra_files:
            if os.path.isfile(path):
                p = os.path.abspath(path)
                if p not in seen:
                    seen.add(p)
                    yield p
        for mod in list(sys.modules.values()):
            if mod is None or not isinstance(mod, types.ModuleType):
                continue
            path = getattr(mod, "__file__", None)
            if not path or not path.endswith(".py"):
                continue
            # 忽略标准库与 site-packages，只监视用户代码
            if "site-packages" in path or path.startswith(sys.prefix):
                continue
            p = os.path.abspath(path)
            if p not in seen and os.path.isfile(p):
                seen.add(p)
                yield p

    def _scan_once(self) -> bool:
        """扫描一遍；返回是否有文件发生了修改。"""
        changed = False
        for path in self._iter_watch_files():
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            old = self._mtimes.get(path)
            if old is not None and mtime > old:
                changed = True
            self._mtimes[path] = mtime
        return changed

    def _record_initial(self):
        for _ in self._iter_watch_files():
            pass  # 触发 _mtimes 记录
        self._scan_once()

    def run_with_reloading(self, main_func, *args, **kwargs):
        """主进程入口：循环 spawn worker，监视文件变化并重启。"""
        err = _ColorStream(sys.stderr)
        err.info("zan 正在以重载模式启动（监视用户 .py 文件）")
        env = os.environ.copy()
        env["ZAN_RUN_MAIN"] = "1"
        # Windows 上没有 SIGTERM 优雅语义，直接用进程组终止
        while True:
            proc = subprocess.Popen(
                [sys.executable, "-u", *sys.argv],
                env=env,
                cwd=os.getcwd(),
            )
            self._record_initial()
            # 等待 worker 退出或文件变化
            while proc.poll() is None:
                time.sleep(self.POLL_INTERVAL)
                if self._scan_once():
                    err.warn("检测到代码变动，正在重启…")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    break
            else:
                # worker 正常退出（如 Ctrl+C）：跟随退出
                code = proc.returncode
                if code not in (0, None):
                    err.error(f"worker 以退出码 {code} 退出；3 秒后重启（Ctrl+C 停止）")
                    time.sleep(3)
                else:
                    return

    @staticmethod
    def is_main_process() -> bool:
        """当前进程是否为重载器主进程（即应该启动监视循环）。"""
        return os.environ.get("ZAN_RUN_MAIN") != "1"
