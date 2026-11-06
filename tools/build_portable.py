"""Assemble a portable, no-install build of Uta Learn Next (Windows).

Produces  dist-portable/UtaLearnNext/  which runs by double-clicking a .cmd in
it — no Python, no Node, no ffmpeg, no admin rights, nothing written outside the
folder (unless it lands somewhere read-only, in which case the app falls back to
%LOCALAPPDATA%, see backend/main.py).

What gets bundled:
  python/           embeddable CPython + the packages the app imports
  backend/          application code and data
  frontend/dist/    pre-built SPA (so Node is never needed)
  bin/              ffmpeg.exe + ffprobe.exe
  browsers/         optional Chromium for video export (--with-export)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "dist-portable"
APP = OUT_ROOT / "UtaLearnNext"
PY_VERSION = "3.13.2"
PY_ZIP = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"

# Core + speech; torch (GPU) is deliberately excluded — it is 4.4 GB and only
# speeds up whisper. Playwright the *package* is small; the browser is separate.
REQUIREMENTS = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "python-multipart>=0.0.9",
    "httpx[http2]>=0.27",
    "numpy>=1.26",
    "pillow>=10.0",
    "fugashi>=1.3",
    "unidic-lite>=1.0",
    "faster-whisper>=1.0",
    "playwright>=1.44",
]


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def copy_tree(src: Path, dst: Path, ignore: tuple[str, ...] = ()) -> None:
    def _ignore(_dir, names):
        return [n for n in names if n in ignore or n == "__pycache__"]

    shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)


def download(url: str, dest: Path) -> Path:
    say(f"下载 {url.split('/')[-1]} …")
    with urllib.request.urlopen(url, timeout=180) as r, dest.open("wb") as fh:
        shutil.copyfileobj(r, fh)
    return dest


def build_python() -> Path:
    py = APP / "python"
    if (py / "python.exe").exists():
        say("python/ 已存在，跳过")
        return py
    py.mkdir(parents=True, exist_ok=True)
    zpath = OUT_ROOT / "python-embed.zip"
    download(PY_ZIP, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(py)
    zpath.unlink(missing_ok=True)

    # the embeddable build ships with site-packages disabled
    pth = next(py.glob("python*._pth"))
    lines = [ln for ln in pth.read_text(encoding="utf-8").splitlines()]
    if "Lib\\site-packages" not in lines:
        lines.append("Lib\\site-packages")
    text = "\n".join(("import site" if ln.strip() == "#import site" else ln) for ln in lines)
    if "import site" not in text:
        text += "\nimport site"
    pth.write_text(text + "\n", encoding="utf-8")
    say(f"已解压 Python {PY_VERSION}")
    return py


def install_packages(py: Path) -> None:
    exe = py / "python.exe"
    if (py / "Lib" / "site-packages" / "fastapi").exists():
        say("依赖已安装，跳过")
        return
    pip_boot = OUT_ROOT / "get-pip.py"
    download(GET_PIP, pip_boot)
    say("安装 pip …")
    subprocess.run([str(exe), str(pip_boot), "--no-warn-script-location", "-q"], check=True)
    pip_boot.unlink(missing_ok=True)
    say(f"安装依赖（{len(REQUIREMENTS)} 个包，约几分钟）…")
    subprocess.run([str(exe), "-m", "pip", "install", "-q",
                    "--no-warn-script-location", *REQUIREMENTS], check=True)


def copy_ffmpeg() -> None:
    bin_dir = APP / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        if not found:
            say(f"[!] 找不到 {tool}，请先装到 PATH 再打包")
            continue
        shutil.copy2(found, bin_dir / Path(found).name)
        say(f"已复制 {Path(found).name}")


def copy_browser() -> None:
    say("复制 Chromium（导出用，约 430MB）…")
    try:
        subprocess.run([str(APP / "python" / "python.exe"), "-m", "playwright", "install",
                        "chromium"], check=True, env={**__import__("os").environ,
                        "PLAYWRIGHT_BROWSERS_PATH": str(APP / "browsers")})
    except Exception as e:  # noqa: BLE001
        say(f"[!] Chromium 复制失败：{e}")


def write_launcher() -> None:
    launcher = APP / "启动 Uta Learn Next.cmd"
    lines = [
        "@echo off",
        "REM 免安装启动器：不写注册表、不改 PATH、不需要管理员权限。",
        "setlocal",
        'cd /d "%~dp0"',
        'set "PYTHONHOME=%~dp0python"',
        'set "PYTHONPATH=%~dp0python;%~dp0python\\Lib\\site-packages"',
        'if exist "%~dp0browsers" set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browsers"',
        'start "" http://127.0.0.1:8000/',
        "cd backend",
        '"%~dp0python\\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000',
        "pause",
    ]
    # binary write: text mode turns \\r\\n into \\r\\r\\n on Windows
    launcher.write_bytes(("\\r\\n".join(lines) + "\\r\\n").encode("utf-8"))
    say(f"已生成 {launcher.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-export", action="store_true", help="同时打包 Chromium")
    args = ap.parse_args()

    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        say("frontend/dist 不存在，请先 npm run build")
        return 2

    APP.mkdir(parents=True, exist_ok=True)
    say(f"输出目录 {APP}")

    copy_tree(ROOT / "backend", APP / "backend", ignore=(".venv", "utalearn_backend.egg-info"))
    copy_tree(ROOT / "frontend" / "dist", APP / "frontend" / "dist")
    for name in ("README.md", "LICENSE"):
        shutil.copy2(ROOT / name, APP / name)
    say("已复制代码与前端产物")

    py = build_python()
    install_packages(py)
    copy_ffmpeg()
    if args.with_export:
        copy_browser()
    write_launcher()

    total = sum(f.stat().st_size for f in APP.rglob("*") if f.is_file())
    say(f"完成，总大小 {total / 1048576:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
