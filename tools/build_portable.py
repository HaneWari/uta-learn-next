"""Assemble portable, no-install builds of Uta Learn Next (Windows).

Two archives of the same release, so users pick what they need:

  UtaLearnNext-<ver>-lite.zip   core app, no browser        (~450 MB)
  UtaLearnNext-<ver>-full.zip   + Chromium for video export (~900 MB)

Both are plain "unzip and double-click" — no Python, no Node, no ffmpeg, no
admin rights. Data lives inside the folder (or %LOCALAPPDATA% when read-only).

Usage:
  python tools/build_portable.py                 # build both zips
  python tools/build_portable.py --no-zip        # just the folder
  python tools/build_portable.py --out D:/x      # build elsewhere (space!)
  python tools/build_portable.py --ffmpeg-dir C:/ffmpeg/bin
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.1.0"

PY_VERSION = "3.13.2"
PY_ZIP = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"
# "essentials" is ~1/3 the size of the full build and still has libx264 + aac +
# the common audio decoders and the fps/setpts/tpad filters this app needs.
FFMPEG_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

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
    if dest.exists() and dest.stat().st_size > 0:
        say(f"已缓存 {dest.name}")
        return dest
    say(f"下载 {dest.name} …")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r, dest.open("wb") as fh:
        shutil.copyfileobj(r, fh)
    return dest


def build_python(base: Path) -> Path:
    py = base / "python"
    if (py / "python.exe").exists():
        say("python/ 已存在，跳过")
        return py
    py.mkdir(parents=True, exist_ok=True)
    zpath = download(PY_ZIP, base.parent / "cache" / "python-embed.zip")
    with zipfile.ZipFile(zpath) as z:
        z.extractall(py)

    pth = next(py.glob("python*._pth"))
    lines = pth.read_text(encoding="utf-8").splitlines()
    if "Lib\\site-packages" not in lines:
        lines.append("Lib\\site-packages")
    text = "\n".join("import site" if ln.strip() == "#import site" else ln for ln in lines)
    if "import site" not in text:
        text += "\nimport site"
    pth.write_text(text + "\n", encoding="utf-8")
    say(f"已解压 Python {PY_VERSION}")
    return py


def install_packages(py: Path, base: Path) -> None:
    exe = py / "python.exe"
    if (py / "Lib" / "site-packages" / "fastapi").exists():
        say("依赖已安装，跳过")
        return
    pip_boot = download(GET_PIP, base.parent / "cache" / "get-pip.py")
    say("安装 pip …")
    subprocess.run([str(exe), str(pip_boot), "--no-warn-script-location", "-q"], check=True)
    say(f"安装依赖（{len(REQUIREMENTS)} 个包，几分钟）…")
    subprocess.run([str(exe), "-m", "pip", "install", "-q",
                    "--no-warn-script-location", *REQUIREMENTS], check=True)


def fetch_ffmpeg(base: Path, explicit: Path | None) -> Path:
    """Return a folder holding ffmpeg.exe + ffprobe.exe (slim build by default)."""
    bin_dir = base / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if (bin_dir / "ffmpeg.exe").exists() and (bin_dir / "ffprobe.exe").exists():
        say("bin/ 已就绪，跳过")
        return bin_dir

    if explicit:
        for tool in ("ffmpeg", "ffprobe"):
            src = explicit / f"{tool}.exe"
            if not src.exists():
                src = explicit / tool
            if not src.exists():
                raise SystemExit(f"在 {explicit} 找不到 {tool}")
            shutil.copy2(src, bin_dir / f"{tool}.exe")
        say(f"已从 {explicit} 复制 ffmpeg")
        return bin_dir

    zpath = download(FFMPEG_ZIP, base.parent / "cache" / "ffmpeg-essentials.zip")
    say("解压 ffmpeg（精简版）…")
    with zipfile.ZipFile(zpath) as z:
        for member in z.namelist():
            name = Path(member).name
            if name in ("ffmpeg.exe", "ffprobe.exe"):
                with z.open(member) as src, (bin_dir / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    for tool in ("ffmpeg.exe", "ffprobe.exe"):
        if not (bin_dir / tool).exists():
            raise SystemExit(f"精简包里没有 {tool}")
    size = sum((bin_dir / t).stat().st_size for t in ("ffmpeg.exe", "ffprobe.exe")) / 1048576
    say(f"ffmpeg 精简版就绪（{size:.0f} MB）")
    return bin_dir


def install_chromium(py: Path, base: Path, dest: Path | None = None) -> Path:
    """Install Chromium into a folder that ships as browsers/ in the full zip.

    `dest` may point outside the build tree so a big browser download does not
    have to live next to the app while packaging.
    """
    browsers = dest or (base.parent / "browsers")
    if any(browsers.glob("chromium-*")):
        say("Chromium 已就绪，跳过")
        return browsers
    say("安装 Chromium（导出用，约 430MB）…")
    subprocess.run([str(py / "python.exe"), "-m", "playwright", "install", "chromium"],
                   check=True, env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers)})
    return browsers


LAUNCHER_LINES = [
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


def write_launcher(base: Path) -> None:
    p = base / "启动 Uta Learn Next.cmd"
    # binary write: text mode turns \r\n into \r\r\n on Windows
    p.write_bytes(("\r\n".join(LAUNCHER_LINES) + "\r\n").encode("utf-8"))
    say(f"已生成 {p.name}")


def make_zip(base: Path, out: Path, extra: dict[str, Path] | None = None) -> Path:
    """Zip `base`, optionally adding extra trees under their own folder name."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    say(f"打包 {out.name} …")
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in base.rglob("*"):
            if f.is_file():
                z.write(f, f"UtaLearnNext/{f.relative_to(base)}")
                total += 1
        for folder, src in (extra or {}).items():
            for f in src.rglob("*"):
                if f.is_file():
                    z.write(f, f"UtaLearnNext/{folder}/{f.relative_to(src)}")
                    total += 1
    say(f"  {total} 个文件，{out.stat().st_size / 1048576:.0f} MB")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist-portable"), help="构建目录")
    ap.add_argument("--no-zip", action="store_true", help="只生成文件夹")
    ap.add_argument("--ffmpeg-dir", default=None, help="自带 ffmpeg 的目录（跳过下载）")
    ap.add_argument("--no-full", action="store_true", help="只做 lite 包")
    ap.add_argument("--zip-out", default=None, help="ZIP 输出目录（默认与构建目录同级）")
    ap.add_argument("--browsers-dir", default=None, help="Chromium 安装位置（默认构建目录旁）")
    args = ap.parse_args()

    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        say("frontend/dist 不存在，请先 npm run build")
        return 2

    out_root = Path(args.out).resolve()
    base = out_root / "UtaLearnNext"
    say(f"输出目录 {base}")

    copy_tree(ROOT / "backend", base / "backend", ignore=(".venv", "utalearn_backend.egg-info"))
    copy_tree(ROOT / "frontend" / "dist", base / "frontend" / "dist")
    for name in ("README.md", "LICENSE"):
        shutil.copy2(ROOT / name, base / name)
    say("已复制代码与前端产物")

    py = build_python(base)
    install_packages(py, base)
    fetch_ffmpeg(base, Path(args.ffmpeg_dir) if args.ffmpeg_dir else None)
    write_launcher(base)

    size = sum(f.stat().st_size for f in base.rglob("*") if f.is_file()) / 1048576
    say(f"核心目录 {size:.0f} MB")

    if args.no_zip:
        return 0

    zip_root = Path(args.zip_out).resolve() if args.zip_out else out_root
    make_zip(base, zip_root / f"UtaLearnNext-{VERSION}-lite.zip")

    if not args.no_full:
        bdir = Path(args.browsers_dir).resolve() if args.browsers_dir else None
        browsers = install_chromium(py, base, bdir)
        make_zip(base, zip_root / f"UtaLearnNext-{VERSION}-full.zip",
                 extra={"browsers": browsers})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
