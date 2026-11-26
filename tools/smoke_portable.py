"""Smoke-test a built portable folder: start it, hit the API, stop it.

Used by CI after `build_portable.py --ci`. It deliberately talks to the same
endpoints the launcher's readiness probe uses, so a green run proves the
embedded interpreter, the bundled site-packages and the built SPA all line up.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = ROOT / "dist-portable" / "UtaLearnNext"

# Windows CI runners default to a cp1252 console, which cannot encode the
# Chinese progress lines and would abort the smoke run before it starts.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def wait_ready(base_url: str, proc: subprocess.Popen, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"后端提前退出（code={proc.returncode}）\n{last}")
        try:
            status, _ = get(base_url + "/api/version", timeout=2.0)
            if status == 200:
                return
        except (urllib.error.URLError, OSError) as exc:
            last = str(exc)
        time.sleep(0.5)
    raise SystemExit(f"{timeout:.0f}s 内后端没有就绪：{last}")


def main() -> int:
    base = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_BASE
    exe = base / "python" / "python.exe"
    if not exe.exists():
        raise SystemExit(f"找不到 {exe}，先运行 build_portable.py")

    env = os.environ.copy()
    env["PYTHONHOME"] = str(base / "python")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(base / "python"), str(base / "python" / "Lib" / "site-packages")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["UTALEARN_DEV"] = "1"          # the smoke run must not depend on a token
    env["UTALEARN_TELEMETRY"] = "0"
    # no window, no tab: the point is the launcher path, not a GUI session
    env["UTALEARN_NO_WINDOW"] = "1"
    env["UTALEARN_NO_BROWSER"] = "1"
    if (base / "browsers").is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(base / "browsers")

    # an explicit port lets CI keep a predictable URL while still exercising
    # the real launcher; without one the launcher picks, exactly like a user run
    port = int(os.environ.get("UTALEARN_SMOKE_PORT") or free_port())
    base_url = f"http://127.0.0.1:{port}"
    print(f"启动 {exe} desktop.py @ {base_url}", flush=True)
    out = subprocess.PIPE
    proc = subprocess.Popen(
        [str(exe), "desktop.py", "--port", str(port), "--allow-multiple"],
        cwd=base, env=env, stdout=out, stderr=subprocess.STDOUT, text=True,
    )
    try:
        wait_ready(base_url, proc)

        status, body = get(base_url + "/api/version")
        version = json.loads(body)
        print(f"  /api/version -> {version}", flush=True)
        assert status == 200 and version.get("version"), "版本接口没有返回版本号"

        status, body = get(base_url + "/api/songs")
        songs = json.loads(body)
        assert status == 200 and isinstance(songs, list), "/api/songs 不是列表"
        print(f"  /api/songs -> {len(songs)} 首", flush=True)

        if (base / "frontend" / "dist" / "index.html").exists():
            status, body = get(base_url + "/")
            assert status == 200 and b"uta-token" in body, "首页没有注入本地 API 令牌"
            print("  / -> SPA 正常", flush=True)
        print("冒烟通过", flush=True)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
