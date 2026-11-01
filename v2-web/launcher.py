"""launcher.py —— 桌面应用入口。

双击 exe（或源码运行 `python launcher.py`）后：
1. 在 127.0.0.1 上找空闲端口起 FastAPI 服务；
2. 用系统默认浏览器打开页面（保证麦克风权限完整，内嵌 WebView 拿不到麦克风）；
3. 弹一个小控制窗，显示地址与配置状态，关掉它就退出应用。

为什么不内嵌网页窗口：口语练习要录音，浏览器原生的 getUserMedia
权限流程最可靠；WebView2 里常被静默拒绝，功能反而废掉。

参数：
    --no-window   只起服务不开界面（调试用）
    --port N      指定端口（默认从 8000 起找空位）
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_VERSION = "2.0.0"


# ---------------------------------------------------------------------
# 端口与就绪检测
# ---------------------------------------------------------------------
def find_free_port(preferred: int = 8000, span: int = 30) -> int:
    """从 preferred 开始找一个能绑定的端口；都不行就让系统分配。"""
    for port in range(preferred, preferred + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, timeout: float = 90.0) -> bool:
    """轮询 /api/status，等服务真正可访问（首启动要加载依赖，可能较慢）。"""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/status", timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


# ---------------------------------------------------------------------
# 启动服务
# ---------------------------------------------------------------------
def start_server(port: int):
    """在后台线程里跑 uvicorn，返回 (Server 实例, 线程)。"""
    import uvicorn

    from server import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    # uvicorn 默认会装信号处理器，非主线程里装会报错，这里关掉
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    return server, thread


# ---------------------------------------------------------------------
# 控制窗（tkinter）
# ---------------------------------------------------------------------
def show_control_window(url: str, cfg_path: Path, llm_desc: str, server) -> None:
    """小控制窗：显示状态、打开页面、打开配置目录，关窗即退出。"""
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"spoken · 智能英语口语教练 v{APP_VERSION}")
    root.geometry("560x300")
    root.minsize(480, 260)

    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:  # noqa: BLE001
        pass

    outer = ttk.Frame(root, padding=20)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text="服务已启动", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
    ttk.Label(outer, text="页面应该已经在浏览器里打开了；没打开就点下面的按钮。",
              foreground="#666").pack(anchor="w", pady=(4, 14))

    link = ttk.Label(outer, text=url, foreground="#1a6ed8", cursor="hand2",
                     font=("Consolas", 11))
    link.pack(anchor="w")
    link.bind("<Button-1>", lambda _e: webbrowser.open(url))

    # 状态区
    box = ttk.LabelFrame(outer, text="运行状态", padding=10)
    box.pack(fill="x", pady=14)

    key_ok = "未配置" not in llm_desc and "MockLLM" not in llm_desc
    ttk.Label(box, text="模型").grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Label(box, text=llm_desc, wraplength=380).grid(row=0, column=1, sticky="w")

    ttk.Label(box, text="配置").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(6, 0))
    ttk.Label(box, text=str(cfg_path), wraplength=380,
              foreground="#666").grid(row=1, column=1, sticky="w", pady=(6, 0))

    if not key_ok:
        ttk.Label(box, text="还没填 API Key，对话和评分会走离线演示。填完重启本程序生效。",
                  foreground="#c0392b", wraplength=440).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

    # 按钮区
    btns = ttk.Frame(outer)
    btns.pack(fill="x", side="bottom")

    ttk.Button(btns, text="打开页面", command=lambda: webbrowser.open(url)).pack(side="left")

    def open_cfg():
        folder = cfg_path.parent
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            messagebox.showinfo("配置文件位置", str(cfg_path))

    ttk.Button(btns, text="打开配置文件夹", command=open_cfg).pack(side="left", padx=8)

    def quit_app():
        server.should_exit = True
        root.destroy()

    ttk.Button(btns, text="退出", command=quit_app).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.mainloop()


# ---------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    no_window = "--no-window" in argv

    port = 8000
    if "--port" in argv:
        try:
            port = int(argv[argv.index("--port") + 1])
        except (IndexError, ValueError):
            pass

    # 首次运行先生成 config.yaml，让用户知道去哪填 Key
    from apppaths import APP_TITLE, data_dir, ensure_config

    cfg_path, created = ensure_config()

    port = find_free_port(port)
    url = f"http://127.0.0.1:{port}"

    try:
        server, _thread = start_server(port)
    except Exception as exc:  # noqa: BLE001
        msg = f"启动服务失败：{exc}"
        print(msg)
        try:
            import tkinter.messagebox as mb
            mb.showerror(APP_TITLE, msg)
        except Exception:  # noqa: BLE001
            pass
        return 1

    if not wait_ready(url):
        print("服务启动超时，请检查依赖是否完整。")
        server.should_exit = True
        return 1

    # 取一次模型描述，控制窗里显示
    llm_desc = "未知"
    try:
        from server import _build_llm
        _, llm_desc = _build_llm()
    except Exception as exc:  # noqa: BLE001
        llm_desc = f"读取失败：{exc}"

    print(f"spoken {APP_VERSION} 已启动：{url}")
    print(f"配置文件：{cfg_path}" + ("（本次新建，请填 api_key）" if created else ""))

    if no_window:
        print("（--no-window：只起服务，Ctrl+C 退出）")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.should_exit = True
        return 0

    webbrowser.open(url)
    try:
        show_control_window(url, cfg_path, llm_desc, server)
    except Exception as exc:  # noqa: BLE001
        # 没有 tkinter / 无图形界面时退化成纯服务模式
        print(f"控制窗打开失败（{exc}），服务继续运行在 {url}，Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        server.should_exit = True
        time.sleep(0.4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
