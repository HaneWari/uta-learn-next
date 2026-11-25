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

    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001
        return False


def run_window(url: str) -> bool:
    """pywebview window; False when the backend is unavailable."""
    try:
        import webview
    except Exception:  # noqa: BLE001
        return False

    state = _load_window_state()
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
        webview.start(debug=False)
        _save_window_state(window)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[uta] 窗口启动失败，改用浏览器：{e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--browser", action="store_true",
                    help="只启动后端并用系统浏览器打开")
    args = ap.parse_args()

    port = args.port or free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"[uta] 启动 {base}")
    start_server(port)
    if not wait_ready(base):
        print("[uta] 后端没有就绪，请查看 logs/utalearn.log")
        return 1

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
