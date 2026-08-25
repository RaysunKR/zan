"""zan 命令行接口：``python -m zan <命令>``。

支持与 Flask CLI 对齐的三个核心命令：

- ``run``    运行开发服务器（自动发现 app.py / FLASK_APP 指定的模块）
- ``shell``  进入带 app 上下文的交互式解释器
- ``routes`` 列出全部路由

用法示例::

    python -m zan run --port 5000 --debug
    python -m zan routes
    FLASK_APP=myapp:create_app() python -m zan run
"""
import argparse
import code
import importlib
import os
import sys


def _load_app(spec: str):
    """按 ``module:attr`` 或 ``module`` 形式加载应用对象。

    - ``myapp``            → myapp.app 或 myapp.application 或 myapp.create_app()
    - ``myapp:create_app()`` → 调用工厂
    - ``myapp:myapp2``     → 取模块属性 myapp2
    """
    spec = spec or os.environ.get("FLASK_APP") or "app"
    call_factory = False
    if spec.endswith("()"):
        call_factory = True
        spec = spec[:-2]
    if ":" in spec:
        module_name, attr = spec.split(":", 1)
    else:
        module_name, attr = spec, None

    mod = importlib.import_module(module_name)
    if attr is not None:
        obj = getattr(mod, attr)
    else:
        obj = None
        for name in ("app", "application", "create_app"):
            candidate = getattr(mod, name, None)
            if candidate is not None:
                obj = candidate
                break
        if obj is None:
            raise SystemExit(
                f"在模块 {module_name!r} 中未找到 app/application/create_app；"
                f"请用 FLASK_APP=模块:变量 指定"
            )
    if callable(obj) and (call_factory or getattr(obj, "__module__", None) != module_name or isinstance(obj, type)):
        obj = obj()
    return obj


def cmd_run(args):
    app = _load_app(args.app)
    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=args.reload if args.reload is not None else None,
    )


def cmd_shell(args):
    app = _load_app(args.app)
    banner = f"zan {getattr(__import__('zan'), '__version__', '?')} shell\n应用: {app!r}\n"
    ctx = {"app": app}
    # 注入常用对象（与 Flask shell 相同）
    from zan import current_app, g, request, session, url_for

    ctx.update(
        {
            "current_app": current_app,
            "g": g,
            "request": request,
            "session": session,
            "url_for": app.url_for,
        }
    )
    with app.app_context():
        code.interact(banner=banner, local=ctx)


def cmd_routes(args):
    app = _load_app(args.app)
    rows = []
    for rule, meta in app._rules.items():
        rows.append(
            (
                rule,
                sorted(meta["methods"]),
                meta["endpoint"],
            )
        )
    if not rows:
        print("(无路由)")
        return
    w_rule = max(len(r[0]) for r in rows)
    w_ep = max(len(r[2]) for r in rows)
    print(f"{'Rule':<{w_rule}}  {'Methods':<28}  Endpoint")
    print("-" * (w_rule + w_ep + 32))
    for rule, methods, endpoint in sorted(rows):
        print(f"{rule:<{w_rule}}  {', '.join(methods):<28}  {endpoint}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m zan",
        description="zan Web 框架命令行工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument(
            "--app",
            default=None,
            help="应用位置（module 或 module:attr），默认读 FLASK_APP 或 app",
        )

    p_run = sub.add_parser("run", help="运行开发服务器")
    common(p_run)
    p_run.add_argument("--host", default="127.0.0.1", help="监听地址")
    p_run.add_argument("--port", type=int, default=5000, help="端口")
    p_run.add_argument("--debug", action="store_true", help="调试模式")
    p_run.add_argument(
        "--reload",
        dest="reload",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否启用重载器（默认随 debug）",
    )
    p_run.set_defaults(func=cmd_run)

    p_shell = sub.add_parser("shell", help="进入交互式解释器")
    common(p_shell)
    p_shell.set_defaults(func=cmd_shell)

    p_routes = sub.add_parser("routes", help="列出路由")
    common(p_routes)
    p_routes.set_defaults(func=cmd_routes)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
