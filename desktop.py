"""Desktop shell: one window instead of a cmd console plus a browser tab.

The portable build used to open a console and then the default browser. For a
non-technical user that raises three questions the app cannot answer from
inside: what is the black window, why is the app still running after the tab
closes, and why did closing the window kill it. This module runs the server in
process and puts the stage in a pywebview window (Edge WebView2 on Windows).

Fallbacks, in order:
  * no pywebview / no WebView2  → open the system browser (old behaviour),
  * browser cannot start either → keep the console and print the URL.

`UTALEARN_NO_WINDOW=1` forces the browser path, which is what the smoke test
and anyone debugging the server wants.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
BACKEND = APP_ROOT / "backend"
WINDOW_STATE = APP_ROOT / "localdata" / "_ui" / "window.json"


def _silence_pythonw() -> None:
    """Give `pythonw.exe` a sink for stdout/stderr instead of `None`.

    A GUI interpreter starts with both streams set to `None`, so anything that
    touches `.isatty()` or `.write()` dies — uvicorn's log formatter calls
    `sys.stdout.isatty()` while configuring itself, which killed the windowed
    `.vbs` entry point on start-up. A throwaway `StringIO` keeps those calls
    harmless; the app's real log still goes to `localdata/logs/`.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, io.StringIO())


def prepare_env() -> None:
    """Make the portable layout visible without a `.cmd` wrapper.

    The extension packs are folders next to the app (`browsers/`, `models/`),
    and both libraries that read them only look at environment variables.
    Setting them here rather than in a launcher keeps every entry point — the
    `.vbs`, the console `.cmd`, `desktop.py` run by hand — on the same path.
    """
    os.environ.setdefault("PYTHONHOME", str(APP_ROOT / "python"))
    os.environ.setdefault("HF_HOME", str(APP_ROOT / "models"))
    browsers = APP_ROOT / "browsers"
    if browsers.is_dir():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
    # Windows groups taskbar buttons by AppUserModelID. Without an explicit one
    # the window inherits `pythonw.exe`'s identity, so the taskbar button keeps
    # Python's icon even though the form itself has ours.
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "HaneWari.UtaLearnNext")
        except Exception:  # noqa: BLE001
            pass


def free_port(start: int = 8000, end: int = 8010) -> int:
    """First port in the range that nothing is listening on."""
    for port in range(start, end + 1):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"{start}-{end} 都被占用，无法启动")


def wait_ready(base: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/version", timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    return False


def start_server(port: int) -> threading.Thread:
    """Run uvicorn in a thread so the GUI owns the main thread."""
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    import uvicorn

    config = uvicorn.Config("main:app", host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="uta-server")
    thread.start()
    # keep a reference so the server is not collected while the window runs
    start_server.server = server  # type: ignore[attr-defined]
    return thread


def _load_window_state() -> dict:
    import json

    try:
        return json.loads(WINDOW_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_window_state(window) -> None:
    import json

    try:
        WINDOW_STATE.parent.mkdir(parents=True, exist_ok=True)
        WINDOW_STATE.write_text(json.dumps({
            "width": window.width, "height": window.height,
            "x": window.x, "y": window.y,
        }), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def open_in_browser(url: str) -> bool:
    import webbrowser

    # the smoke test and CI have no desktop session; opening a browser there
    # would either fail noisily or leave a stray tab on the build machine
    if os.environ.get("UTALEARN_NO_BROWSER") == "1":
        return True
    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001
        return False


def _active_jobs(base: str) -> int:
    """How many jobs are still queued or running.

    Closing the window kills the in-process server, so a running build or
    export would be lost. The plan asks for a confirmation; asking needs a
    number, otherwise the dialog is a generic "are you sure".
    """
    try:
        with urllib.request.urlopen(base + "/api/jobs?active=true", timeout=2) as r:
            return len(json.loads(r.read()))
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def _ask_yes_no(title: str, text: str) -> bool:
    """Blocking yes/no box without tkinter.

    The portable Python has no `tkinter` (it would add ~10 MB for one dialog),
    so the old implementation fell through to "refuse to close" on every
    packaged build — which is why 关闭窗口时确认 looked broken. Win32's
    `MessageBoxW` already exists in every Windows install and pumps its own
    message loop, so it is safe to call from the pywebview closing handler.
    """
    if os.name == "nt":
        try:
            import ctypes

            MB_YESNO = 0x04
            MB_ICONWARNING = 0x30
            MB_SETFOREGROUND = 0x10000
            answer = ctypes.windll.user32.MessageBoxW(
                None, text, title,
                MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND)
            return answer == 6  # IDYES
        except Exception:  # noqa: BLE001
            pass
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        answer = messagebox.askyesno(title, text)
        root.destroy()
        return bool(answer)
    except Exception:  # noqa: BLE001
        return False


def _setting(name: str, default):
    """Read one saved setting without booting the server.

    `desktop.py` runs around the FastAPI app, and the closing handler has to
    answer instantly; reading the same `settings.json` the app writes is
    cheaper than an HTTP round trip and works even if the server is wedged.
    """
    env = os.environ.get("DATA_DIR")
    if env:
        root = Path(env)
    else:
        # mirror app.paths: the folder next to the app when writable, else the
        # per-user directory (Program Files installs)
        root = APP_ROOT / "localdata"
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            base = os.environ.get("LOCALAPPDATA") or str(Path.home())
            root = Path(base) / "UtaLearnNext" / "localdata"
    try:
        data = json.loads((root / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data.get(name, default) if isinstance(data, dict) else default


def confirm_close(base: str) -> bool:
    """True when it is safe to close.

    The 设置 switch decides *whether* to ask at all — with it on, closing asks
    once (that is what the user turned on); with it off, the window closes at
    once. Running jobs add a line to the prompt instead of being the only
    reason to ask, which is what made the feature look dead on an idle app.
    """
    if not _setting("confirm_close", True):
        return True
    count = _active_jobs(base)
    text = "确定要退出 Uta Learn Next 吗?"
    if count > 0:
        text = (f"还有 {count} 个任务正在进行(生成、导出或下载)。\n"
                "退出会中断它们,确定退出吗?")
    return _ask_yes_no("Uta Learn Next", text)


class SingleInstance:
    """Named mutex so a second double-click focuses the first window.

    Without it two copies start, both pick a port, and the user has two windows
    writing the same `localdata/`. On non-Windows the class is a no-op — the
    desktop shell only ships on Windows.
    """

    NAME = "UtaLearnNext.SingleInstance"

    def __enter__(self):
        self.handle = None
        if os.name != "nt":
            return self
        try:
            import ctypes

            self._ctypes = ctypes
            self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, self.NAME)
            already = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
            if already:
                raise SystemExit(focus_existing() or 0)
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001
            # a missing/renamed kernel32 is not worth failing startup over
            self.handle = None
        return self

    def __exit__(self, *_exc):
        if os.name == "nt" and self.handle:
            try:
                self._ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:  # noqa: BLE001
                pass
        return False


def focus_existing() -> int:
    """Ask the running copy to show itself, then exit 0."""
    try:
        import urllib.request

        # the first copy publishes its port in localdata/_ui/port.txt
        port_file = APP_ROOT / "localdata" / "_ui" / "port.txt"
        port = int(port_file.read_text(encoding="utf-8").strip())
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/system/focus", timeout=2)
    except Exception:  # noqa: BLE001
        pass
    print("[uta] 已经有一个窗口在运行。")
    return 0


def publish_port(port: int) -> None:
    try:
        target = APP_ROOT / "localdata" / "_ui"
        target.mkdir(parents=True, exist_ok=True)
        (target / "port.txt").write_text(str(port), encoding="utf-8")
    except OSError:
        pass


def _install_tray(window, url: str) -> None:
    """Best-effort tray icon: 显示主窗口 / 在浏览器中打开 / 打开目录 / 退出.

    pywebview has no tray of its own, so this needs `pystray` + Pillow. Both are
    optional: a missing tray is a smaller problem than a shell that refuses to
    start, so every failure here is swallowed and the window still works.
    """
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:  # noqa: BLE001
        return

    def icon_image():
        # the tray must wear the same mark as the window/exe; drawing a 唄 with
        # Pillow's default bitmap font produced a broken glyph on many systems
        path = _window_icon()
        if path:
            try:
                return Image.open(path).convert("RGBA")
            except OSError:
                pass
        img = Image.new("RGB", (64, 64), "#f7efe1")
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), outline="#ff8a3d", width=4)
        return img

    def show(_icon, _item=None):
        try:
            window.show()
            window.restore()
        except Exception:  # noqa: BLE001
            pass

    def open_dir(_icon, _item=None):
        import subprocess

        try:
            if os.name == "nt":
                # CREATE_NO_WINDOW: without it a `pythonw` parent still flashes
                # a console before Explorer takes over (§ the terminal-flash
                # report; the backend learned the same lesson).
                subprocess.Popen(
                    ["explorer", str(APP_ROOT)],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except Exception:  # noqa: BLE001
            pass

    def quit_app(icon, _item=None):
        icon.stop()
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("显示主窗口", show, default=True),
        pystray.MenuItem("在浏览器中打开", lambda *_: open_in_browser(url)),
        pystray.MenuItem("打开应用目录", open_dir),
        pystray.MenuItem("退出", quit_app),
    )
    tray = pystray.Icon("uta-learn-next", icon_image(), "Uta Learn Next", menu)
    threading.Thread(target=tray.run, daemon=True, name="uta-tray").start()


def _window_icon() -> str | None:
    """Path to the `.ico` the window/taskbar should show.

    pywebview's WinForms backend accepts an `.ico` path; the portable build
    ships one next to `desktop.py` (`app.ico`), a source checkout has it under
    `tools/assets/`. Returning None keeps pywebview's fallback instead of
    failing the whole window over a missing icon.
    """
    for candidate in (APP_ROOT / "app.ico",
                      APP_ROOT / "tools" / "assets" / "app.ico"):
        if candidate.is_file():
            return str(candidate)
    return None


def run_window(url: str) -> bool:
    """pywebview window; False when the backend is unavailable."""
    try:
        import webview
    except Exception:  # noqa: BLE001
        return False

    state = _load_window_state()
    icon = _window_icon()
    try:
        window = webview.create_window(
            "Uta Learn Next",
            url,
            width=int(state.get("width") or 1280),
            height=int(state.get("height") or 820),
            x=state.get("x"),
            y=state.get("y"),
            min_size=(900, 600),
            background_color="#f7efe1",
        )
        # Closing the window kills the in-process server; ask first when work
        # would be lost. pywebview 5+ supports a closing handler.
        def on_closing() -> bool:
            return confirm_close(url.rstrip("/"))

        try:
            window.events.closing += on_closing
        except Exception:  # noqa: BLE001
            pass
        # the tray menu and the settings page both need a "show me again" hook
        _install_tray(window, url)
        # `icon` is what WinForms puts on the *window*; without it the caption
        # and taskbar show Edge's icon (or, worse, the Python one). The exe's
        # embedded resource only covers Explorer, not the webview host.
        webview.start(debug=False, icon=icon)
        _save_window_state(window)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[uta] 窗口启动失败，改用浏览器：{e}")
        return False


def main() -> int:
    _silence_pythonw()
    prepare_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--browser", action="store_true",
                    help="只启动后端并用系统浏览器打开")
    ap.add_argument("--allow-multiple", action="store_true",
                    help="debug only: skip the single-instance check")
    # every option has to be registered *before* parse_args: an argument added
    # afterwards never reaches the namespace and reading it raises
    args = ap.parse_args()

    if args.allow_multiple:
        return _run(args)
    with SingleInstance():
        return _run(args)


def _run(args) -> int:

    port = args.port or free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"[uta] 启动 {base}")
    start_server(port)
    if not wait_ready(base):
        print("[uta] 后端没有就绪，请查看 logs/utalearn.log")
        return 1
    publish_port(port)

    headless = args.browser or os.environ.get("UTALEARN_NO_WINDOW") == "1"
    if not headless and run_window(base):
        # window closed → process exits → the daemon server dies with it
        return 0

    if not args.browser and os.environ.get("UTALEARN_NO_WINDOW") != "1":
        print("[uta] 没有可用的 WebView2，改用系统浏览器")
    if not open_in_browser(base):
        print(f"[uta] 请在浏览器打开 {base}")
    print("[uta] 关闭这个窗口即可退出应用。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
