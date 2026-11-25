"""Assemble the portable, no-install build of Uta Learn Next (Windows).

One core archive per release plus two *optional* extension packs, so a user
downloads only what they need:

  UtaLearnNext-<ver>.zip            the whole app            (~290 MB)
  UtaLearnNext-chromium.zip         + bundled Chromium       (~316 MB, version-free)
  UtaLearnNext-custom-lyrics.zip    whisper + ja-zh models for 自定义歌词 (~500 MB, version-free)

All are plain "unzip and double-click" — no Python, no Node, no ffmpeg, no
admin rights. An extension pack lands as a folder next to the app (`browsers/`,
`models/`) and is picked up on the next start; data lives inside the folder
(or %LOCALAPPDATA% when read-only). Both extension packs are version-
independent — a browser binary and a frozen speech model change far slower
than the app, so they are built once and reused on every release.

Usage:
  python tools/build_portable.py                 # core zip + chromium pack
  python tools/build_portable.py --no-chromium   # core zip only
  python tools/build_portable.py --custom-pack   # only the custom-lyrics extension zip
  python tools/build_portable.py --no-zip        # just the folder
  python tools/build_portable.py --ci            # folder only, no chromium (CI smoke)
  python tools/build_portable.py --out D:/x      # build elsewhere (space!)
  python tools/build_portable.py --ffmpeg-dir C:/ffmpeg/bin

Python deps come from `backend/requirements.lock` (uv export, hashes pinned), so
the same lock always installs the same wheels. Download inputs are pinned in
`tools/build_manifest.json`; a hash mismatch aborts the build.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _app_version() -> str:
    src = (ROOT / "backend" / "app" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src)
    if not m:
        raise SystemExit("backend/app/version.py 里找不到 APP_VERSION")
    return m.group(1)


MANIFEST = json.loads((ROOT / "tools" / "build_manifest.json").read_text(encoding="utf-8"))
VERSION = _app_version()

PY_VERSION = MANIFEST["python"]["version"]
PY_ZIP = MANIFEST["python"]["url"]
PY_ZIP_SHA = MANIFEST["python"]["sha256"]
GET_PIP = MANIFEST["get_pip"]["url"]
GET_PIP_SHA = MANIFEST["get_pip"]["sha256"]
# "essentials" is ~1/3 the size of the full build and still has libx264 + aac +
# the common audio decoders and the fps/setpts/tpad filters this app needs.
FFMPEG_ZIP = MANIFEST["ffmpeg"]["url"]
FFMPEG_SHA = MANIFEST["ffmpeg"].get("sha256")
REQUIREMENTS_LOCK = ROOT / "backend" / "requirements.lock"


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def copy_tree(src: Path, dst: Path, ignore: tuple[str, ...] = ()) -> None:
    def _ignore(_dir, names):
        return [n for n in names if n in ignore or n == "__pycache__"]

    shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str | None = None) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        if sha256 is None or sha256_file(dest) == sha256:
            say(f"已缓存 {dest.name}")
            return dest
        say(f"{dest.name} 哈希不符，重新下载")
        dest.unlink()
    say(f"下载 {dest.name} …")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=300) as r, dest.open("wb") as fh:
        shutil.copyfileobj(r, fh)
    if sha256:
        got = sha256_file(dest)
        if got != sha256:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"{dest.name} SHA256 不符：期望 {sha256}，实际 {got}")
    return dest


def build_python(base: Path) -> Path:
    py = base / "python"
    if (py / "python.exe").exists():
        say("python/ 已存在，跳过")
        return py
    py.mkdir(parents=True, exist_ok=True)
    zpath = download(PY_ZIP, base.parent / "cache" / "python-embed.zip", PY_ZIP_SHA)
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
    if not REQUIREMENTS_LOCK.exists():
        raise SystemExit(
            f"缺少 {REQUIREMENTS_LOCK}。先运行：\n"
            "  cd backend && uv lock && uv export --frozen --no-dev "
            "--extra speech --extra export --extra desktop --no-emit-project --format requirements-txt "
            "--hashes -o requirements.lock")
    pip_boot = download(GET_PIP, base.parent / "cache" / "get-pip.py", GET_PIP_SHA)
    say("安装 pip …")
    subprocess.run([str(exe), str(pip_boot), "--no-warn-script-location", "-q"], check=True)
    # unidic-lite ships as sdist only, so the embedded interpreter needs a
    # build backend (setuptools+wheel) before the real deps can compile
    subprocess.run([str(exe), "-m", "pip", "install", "-q",
                    "--no-warn-script-location", "setuptools", "wheel"], check=True)
    say("安装依赖（requirements.lock，逐包哈希校验，几分钟）…")
    subprocess.run([str(exe), "-m", "pip", "install", "-q",
                    "--no-warn-script-location", "--require-hashes",
                    "-r", str(REQUIREMENTS_LOCK)], check=True)


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

    zpath = download(
        FFMPEG_ZIP, base.parent / "cache" / "ffmpeg-essentials.zip", FFMPEG_SHA)
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
    # `ffmpeg` is playwright's own recorder component — record_video_dir needs
    # its ffmpeg-* build, separate from the mux ffmpeg in bin/
    subprocess.run([str(py / "python.exe"), "-m", "playwright", "install",
                    "chromium", "ffmpeg"],
                   check=True, env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(browsers)})
    return browsers


def ffmpeg_version(bin_dir: Path) -> str:
    try:
        out = subprocess.run(
            [str(bin_dir / "ffmpeg.exe"), "-version"],
            capture_output=True, text=True, timeout=15, check=False)
        return (out.stdout.splitlines() or ["unknown"])[0].strip()
    except OSError:
        return "unknown"


def compute_runtime_id(ffmpeg_ver: str) -> tuple[str, str]:
    """Hash every input that can change native/runtime behaviour.

    Two builds with the same interpreter, dependency lock and ffmpeg binary
    produce the same id even on different days, so an update can tell "same
    runtime, only code changed" from "ship the whole runtime again".
    """
    req_sha = sha256_file(REQUIREMENTS_LOCK) if REQUIREMENTS_LOCK.exists() else "missing"
    digest = hashlib.sha256()
    digest.update(f"python={PY_VERSION}\n".encode())
    digest.update(f"requirements={req_sha}\n".encode())
    digest.update(f"ffmpeg={ffmpeg_ver}\n".encode())
    return digest.hexdigest(), req_sha


def write_build_info(base: Path, ffmpeg_ver: str) -> dict:
    runtime_id, req_sha = compute_runtime_id(ffmpeg_ver)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=15, check=False
        ).stdout.strip() or "unknown"
    except OSError:
        commit = "unknown"
    info = {
        "app": "UtaLearn Next",
        "version": VERSION,
        "commit": commit,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "runtime_id": runtime_id,
        "python": PY_VERSION,
        "requirements_sha256": req_sha,
        "ffmpeg": ffmpeg_ver,
    }
    (base / "BUILD_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say(f"BUILD_INFO.json runtime_id={runtime_id[:12]}…")
    return info


LAUNCHER_LINES = [
    "@echo off",
    "REM 免安装启动器:不写注册表、不改 PATH、不需要管理员权限。",
    "REM 默认用 pythonw 启动桌面窗口;需要看日志时用「(控制台)」那个入口。",
    "setlocal",
    'cd /d "%~dp0"',
    'set "PYTHONHOME=%~dp0python"',
    'set "PYTHONPATH=%~dp0python;%~dp0python\\Lib\\site-packages"',
    'if exist "%~dp0browsers" set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browsers"',
    "REM 语音识别模型放在 models/ 下(自定义歌词扩展包解压进来即是);设了",
    "REM HF_HOME 后 huggingface_hub 也优先用它,扩展包与缓存共用一处。",
    'if not defined HF_HOME set "HF_HOME=%~dp0models"',
    "REM 歌词源/whisper 模型要联网。系统代理不一定会写进 *_PROXY 环境变量,",
    "REM 而 httpx 只认 env——探测常见本地代理端口并显式导出,让有 Clash/V2Ray",
    "REM 的机器开箱即用,没代理的机器则直连不受影响。",
    'if not defined HTTPS_PROXY for %%P in (7890 7897 10808 1080 8889 4780) do (',
    "  if not defined HTTPS_PROXY (",
    '    "%~dp0python\\python.exe" -c "import socket,sys;s=socket.socket();s.settimeout(0.25);sys.exit(0 if s.connect_ex((\'127.0.0.1\',%%P))==0 else 1)" 2>nul',
    '    if not errorlevel 1 set "HTTPS_PROXY=http://127.0.0.1:%%P"',
    "  )",
    ")",
    'if defined HTTPS_PROXY if not defined HTTP_PROXY set "HTTP_PROXY=%HTTPS_PROXY%"',
    "REM desktop.py 负责选端口、等后端就绪、开窗口;窗口起不来就退回系统浏览器。",
    'if /i "%~1"=="--console" (',
    '  "%~dp0python\\python.exe" "%~dp0desktop.py"',
    ") else (",
    '  "%~dp0python\\pythonw.exe" "%~dp0desktop.py"',
    ")",
]

CONSOLE_LAUNCHER_LINES = [
    "@echo off",
    "REM 调试入口:保留控制台,能看到后端日志。",
    'cd /d "%~dp0"',
    'set "PYTHONHOME=%~dp0python"',
    'set "PYTHONPATH=%~dp0python;%~dp0python\\Lib\\site-packages"',
    'if exist "%~dp0browsers" set "PLAYWRIGHT_BROWSERS_PATH=%~dp0browsers"',
    'if not defined HF_HOME set "HF_HOME=%~dp0models"',
    '"%~dp0python\\python.exe" "%~dp0desktop.py"',
    "pause",
]

VBS_LINES = [
    "' 双击这个文件启动 Uta Learn Next,不出现控制台窗口。",
    "' 出问题需要看日志时,改用「启动 Uta Learn Next (控制台).cmd」。",
    'Set fso = CreateObject("Scripting.FileSystemObject")',
    "root = fso.GetParentFolderName(WScript.ScriptFullName)",
    'Set shell = CreateObject("WScript.Shell")',
    "shell.CurrentDirectory = root",
    'shell.Run Chr(34) & root & "\\python\\pythonw.exe" & Chr(34) & " " & Chr(34) & root & "\\desktop.py" & Chr(34), 0, False',
]


def write_launcher(base: Path) -> None:
    p = base / "启动 Uta Learn Next.cmd"
    # binary write: text mode turns \r\n into \r\r\n on Windows
    p.write_bytes(("\r\n".join(LAUNCHER_LINES) + "\r\n").encode("utf-8"))
    say(f"已生成 {p.name}")
    console = base / "启动 Uta Learn Next (控制台).cmd"
    console.write_bytes(("\r\n".join(CONSOLE_LAUNCHER_LINES) + "\r\n").encode("utf-8"))
    vbs = base / "启动 Uta Learn Next.vbs"
    vbs.write_bytes(("\r\n".join(VBS_LINES) + "\r\n").encode("utf-8"))
    shutil.copy2(ROOT / "desktop.py", base / "desktop.py")
    say("已生成 desktop.py 与三个启动入口")


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


def make_addon_zip(folder: Path, out: Path) -> Path:
    """Zip a single extension folder as `<folder>/…` — no UtaLearnNext wrapper.

    Extension packs drop straight into the app folder (`browsers/` or
    `models/` next to `启动 Uta Learn Next.cmd`), so the archive carries the
    folder itself, not a wrapper the unpacker would have to peel off.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    say(f"打包 {out.name} …")
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in folder.rglob("*"):
            if f.is_file():
                z.write(f, f"{folder.name}/{f.relative_to(folder)}")
                total += 1
        z.writestr(
            f"{folder.name}/README-where-this-goes.txt",
            "把这个压缩包解压到 UtaLearnNext 应用目录里，\n"
            "让里面的文件夹落到应用目录中（如 browsers/ 或 models/），\n"
            "之后重新启动程序即可生效。\n",
        )
        total += 1
    say(f"  {total} 个文件，{out.stat().st_size / 1048576:.0f} MB")
    return out


# --------------------------------------------------------------------------- #
# custom-lyrics extension pack (version-independent)
# --------------------------------------------------------------------------- #
# Bundles the two models 自定义歌词 needs under `models/`: the whisper STT
# model (from this machine's HF cache) and the ja-zh translation model
# (converted int8 CT2 in `models/translate-ja-zh`). Neither is ever pulled
# from HuggingFace at runtime — the pack is what lets them work offline.

WHISPER_REPO = "Systran/faster-whisper-small"
WHISPER_DIRNAME = "whisper-small"
TRANSLATE_DIRNAME = "translate-ja-zh"


def _hf_cache() -> Path:
    for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        raw = os.environ.get(var)
        if raw:
            return Path(raw)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _whisper_snapshot() -> Path:
    """Locate the snapshot dir of the small model in the local HF cache."""
    repo_dir = _hf_cache() / ("models--" + WHISPER_REPO.replace("/", "--"))
    snap = repo_dir / "snapshots"
    if not snap.is_dir():
        raise SystemExit(
            f"在本机 HF 缓存找不到 {WHISPER_REPO}。先让程序下载一次 small 模型"
            f"（运行一次自定义歌词对齐），或设置 HF_HOME 指向缓存。\n  {repo_dir}")
    best = None
    for d in sorted(snap.iterdir()):
        if (d / "model.bin").exists():
            best = d  # keep the newest valid snapshot
    if best is None:
        raise SystemExit(f"{snap} 里没有完整的模型快照（缺 model.bin）")
    return best


def stage_whisper_model(dest: Path) -> Path:
    """Copy the snapshot into `dest/whisper-small` as a flat model dir."""
    src = _whisper_snapshot()
    target = dest / WHISPER_DIRNAME
    if target.is_dir() and (target / "model.bin").exists():
        say("whisper-small 模型已就位，跳过")
        return target
    say(f"复制 whisper-small 模型（{src.name[:12]}…）…")
    target.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        # blobs arrive as symlinks into the blob store; resolve them so the zip
        # holds real bytes, not links
        if f.is_file() or f.is_symlink():
            shutil.copy2(f.resolve(), target / f.name)
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1048576
    say(f"  models/{WHISPER_DIRNAME} = {size:.0f} MB")
    return target


def _translate_snapshot() -> Path:
    """The converted ja-zh model dir under `models/` next to the app."""
    d = Path(__file__).resolve().parents[1] / "models" / TRANSLATE_DIRNAME
    if not (d / "model.bin").exists():
        raise SystemExit(
            f"在 {d} 找不到翻译模型（缺 model.bin）。先把 opus-mt-ja-zh 的"
            f" int8 CT2 转换结果放进 models/{TRANSLATE_DIRNAME}/")
    return d


def make_patch_zip(base: Path, out: Path) -> Path:
    """Application layer only: backend/, frontend/dist/, desktop.py.

    A patch never touches `python/`, `bin/`, `models/`, `browsers/` or
    `localdata/` — those are the runtime, the extension packs and the user's
    own data. Keeping the patch this narrow is what makes it a few MB and safe
    to apply over any v2.x install.
    """
    include = ("backend/", "frontend/dist/")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    say(f"打包补丁 {out.name} …")
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for folder in include:
            src = base / folder
            if not src.is_dir():
                continue
            for f in src.rglob("*"):
                if not f.is_file() or "__pycache__" in f.parts:
                    continue
                z.write(f, f"{folder}{f.relative_to(src)}")
                total += 1
        desktop = base / "desktop.py"
        if desktop.exists():
            z.write(desktop, "desktop.py")
            total += 1
    say(f"  {total} 个文件,{out.stat().st_size / 1048576:.1f} MB")
    return out


def make_update_manifest(base: Path, patch: Path, full: Path, out: Path,
                         notes: str = "") -> Path:
    """`update.json`: version, runtime_id and both assets with hashes."""
    info = json.loads((base / "BUILD_INFO.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": 1,
        "version": info["version"],
        "released_at": datetime.now(UTC).date().isoformat(),
        "notes": notes,
        "runtime_id": info["runtime_id"],
        "patch": {
            "name": patch.name,
            "size": patch.stat().st_size,
            "sha256": sha256_file(patch),
            "min_version": "2.0.0",
        },
        "full": {
            "name": full.name,
            "size": full.stat().st_size,
            "sha256": sha256_file(full),
        },
    }
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    say(f"已生成 {out.name}")
    return out


def make_custom_lyrics_zip(out: Path) -> Path:
    """Standalone zip: `models/whisper-small/…` + `models/translate-ja-zh/…`.

    Files land directly under `models/` with no wrapper — the app reads the
    archive by the folder names, same as the chromium pack reads `browsers/`.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    say(f"打包 {out.name} …")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        # model.bin is already quantised; re-deflating it buys ~nothing, but a
        # stored zip still decompresses fine and saves minutes of CPU
        for snap, sub in ((_whisper_snapshot(), WHISPER_DIRNAME),
                          (_translate_snapshot(), TRANSLATE_DIRNAME)):
            for f in sorted(snap.iterdir()):
                if f.is_file() or f.is_symlink():
                    z.write(f.resolve(), f"models/{sub}/{f.name}")
        z.writestr(
            "models/README-where-this-goes.txt",
            "把本包解压到 UtaLearnNext 应用目录里，得到\n"
            "  models/whisper-small/model.bin   语音识别\n"
            "  models/translate-ja-zh/model.bin  日→中翻译\n"
            "之后重新启动程序，自定义歌词即可离线对齐与翻译。\n",
        )
    say(f"  {out.stat().st_size / 1048576:.0f} MB")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist-portable"), help="构建目录")
    ap.add_argument("--no-zip", action="store_true", help="只生成文件夹")
    ap.add_argument("--ffmpeg-dir", default=None, help="自带 ffmpeg 的目录（跳过下载）")
    ap.add_argument("--no-chromium", action="store_true",
                    help="只出核心包，不打包 Chromium 扩展")
    ap.add_argument("--zip-out", default=None, help="ZIP 输出目录（默认与构建目录同级）")
    ap.add_argument("--browsers-dir", default=None, help="Chromium 安装位置（默认构建目录旁）")
    ap.add_argument("--custom-pack", action="store_true",
                    help="只生成自定义歌词扩展包 whisper+翻译（版本无关，一次构建长期复用）")
    ap.add_argument("--notes", default="", help="update.json 里的更新说明")
    ap.add_argument("--ci", action="store_true",
                    help="CI 冒烟：只生成目录，不装 Chromium、不打 zip")
    args = ap.parse_args()

    if args.ci:
        args.no_chromium = True
        args.no_zip = True

    if args.custom_pack:
        zip_root = Path(args.zip_out).resolve() if args.zip_out else Path(args.out).resolve()
        make_custom_lyrics_zip(zip_root / "UtaLearnNext-custom-lyrics.zip")
        return 0

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
    # the desktop shell lives at the app root: it owns the port choice, the
    # readiness wait and the pywebview window
    shutil.copy2(ROOT / "desktop.py", base / "desktop.py")
    say("已复制代码与前端产物")

    py = build_python(base)
    install_packages(py, base)
    bin_dir = fetch_ffmpeg(base, Path(args.ffmpeg_dir) if args.ffmpeg_dir else None)
    write_build_info(base, ffmpeg_version(bin_dir))
    write_launcher(base)

    size = sum(f.stat().st_size for f in base.rglob("*") if f.is_file()) / 1048576
    say(f"核心目录 {size:.0f} MB")

    if args.no_zip:
        return 0

    zip_root = Path(args.zip_out).resolve() if args.zip_out else out_root
    full = make_zip(base, zip_root / f"UtaLearnNext-{VERSION}.zip")
    patch = make_patch_zip(base, zip_root / f"UtaLearnNext-{VERSION}-patch.zip")
    make_update_manifest(base, patch, full, zip_root / "update.json",
                         notes=args.notes)

    if not args.no_chromium:
        bdir = Path(args.browsers_dir).resolve() if args.browsers_dir else None
        browsers = install_chromium(py, base, bdir)
        # standalone add-on: only the browsers/ tree, wrapped so it unzips
        # into the app folder as UtaLearnNext/browsers/. Version-free name —
        # a browser binary works with any app version.
        make_addon_zip(browsers, zip_root / "UtaLearnNext-chromium.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
