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
import sys
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


def _app_name() -> str:
    src = (ROOT / "backend" / "app" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'APP_NAME\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else "Uta Learn Next"


MANIFEST = json.loads((ROOT / "tools" / "build_manifest.json").read_text(encoding="utf-8"))
VERSION = _app_version()
APP_NAME = _app_name()

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
    # Windows CI runners default to a cp1252 console, which cannot encode the
    # Chinese progress lines and aborts the build before it starts
    try:
        print(f"  {msg}", flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(f"  {msg}\n".encode("utf-8", "replace"))
        sys.stdout.flush()


def copy_tree(src: Path, dst: Path, ignore: tuple[str, ...] = ()) -> None:
    def _ignore(_dir, names):
        # every virtualenv, not just `.venv`: a local `uv` test environment
        # (or anything else) must never end up in the shipped package
        return [
            n for n in names
            if n in ignore or n == "__pycache__" or n.startswith(".venv")
        ]

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
    """Return a folder holding ffmpeg.exe (slim build unless given one)."""
    bin_dir = base / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if (bin_dir / "ffmpeg.exe").exists():
        say("bin/ 已就绪，跳过")
        return bin_dir

    if explicit:
        for tool in ("ffmpeg",):
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
            # ffprobe is gone: duration comes from `ffmpeg -i` now
            if name == "ffmpeg.exe":
                with z.open(member) as src, (bin_dir / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    for tool in ("ffmpeg.exe",):
        if not (bin_dir / tool).exists():
            raise SystemExit(f"精简包里没有 {tool}")
    size = (bin_dir / "ffmpeg.exe").stat().st_size / 1048576
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


def write_build_info(base: Path, ffmpeg_ver: str,
                     patch_from: str = "") -> dict:
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
    if patch_from:
        info["patch_from"] = patch_from
    (base / "BUILD_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say(f"BUILD_INFO.json runtime_id={runtime_id[:12]}…")
    return info


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

LAUNCHER_EXE = "UtaLearn Next.exe"

# The C# compiler that ships with the .NET Framework — present on a stock
# Windows 10/11 and used by the Windows CI image, so no SDK install is needed.
_CSC_CANDIDATES = (
    r"Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    r"Microsoft.NET\Framework\v4.0.30319\csc.exe",
)


def _csc() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for rel in _CSC_CANDIDATES:
        candidate = windir / rel
        if candidate.exists():
            return candidate
    raise SystemExit(
        "找不到 csc.exe(.NET Framework 自带的 C# 编译器),无法生成启动器。\n"
        "Windows 10/11 自带;精简系统请安装 .NET Framework 4.x 运行时。")


def build_launcher_exe(out: Path) -> Path:
    """Compile `tools/launcher/Launcher.cs` into the shipped `UtaLearn Next.exe`.

    A signed exe is the only launcher Windows can show as a verified publisher;
    `.vbs`/`.cmd` cannot carry an Authenticode signature at all, which is why
    this replaced them rather than sitting next to them.

    The version resource is written from `app.version.APP_VERSION` (via a
    generated `AssemblyInfo.cs`) rather than hardcoded in the .cs, because
    `version.py` is the single source of truth for the version number.
    """
    icon = ROOT / "tools" / "assets" / "app.ico"
    if not icon.exists():
        raise SystemExit(f"缺图标 {icon},先运行 python tools/make_icon.py")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    # a four-part version is required by the assembly attributes; APP_VERSION
    # is 2.0.0, so pad it rather than inventing a separate number
    parts = (VERSION.split(".") + ["0", "0", "0"])[:4]
    four = ".".join(parts)
    assembly = out.parent / "_AssemblyInfo.g.cs"
    assembly.write_text(
        "using System.Reflection;\n"
        f'[assembly: AssemblyTitle("{APP_NAME}")]\n'
        '[assembly: AssemblyDescription("跟着日语歌学日语 — 逐字高亮、假名注音、词汇卡")]\n'
        f'[assembly: AssemblyProduct("{APP_NAME}")]\n'
        '[assembly: AssemblyCompany("HaneWari")]\n'
        f'[assembly: AssemblyCopyright("Copyright © {datetime.now(UTC).year} HaneWari")]\n'
        f'[assembly: AssemblyVersion("{four}")]\n'
        f'[assembly: AssemblyFileVersion("{four}")]\n'
        f'[assembly: AssemblyInformationalVersion("{VERSION}")]\n',
        encoding="utf-8")
    cmd = [
        str(_csc()), "/nologo", "/target:winexe", "/platform:anycpu", "/optimize+",
        f"/out:{out}", f"/win32icon:{icon}",
        str(ROOT / "tools" / "launcher" / "Launcher.cs"),
        str(assembly),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    finally:
        assembly.unlink(missing_ok=True)
    if result.returncode != 0 or not out.exists():
        raise SystemExit(f"编译启动器失败:\n{result.stdout}\n{result.stderr}")
    say(f"已生成 {out.name}({out.stat().st_size / 1024:.0f} KB)")
    return out


def write_launcher(base: Path) -> None:
    # A reused build folder still holds whatever the previous build wrote here.
    # None of it may survive: the exe is the single double-click entry, and a
    # stale .cmd/.vbs beside it only confuses users (and ships dead weight).
    for stale in ("启动 Uta Learn Next.cmd", "启动 Uta Learn Next.vbs"):
        (base / stale).unlink(missing_ok=True)
    build_launcher_exe(base / LAUNCHER_EXE)
    console = base / "启动 Uta Learn Next (控制台).cmd"
    console.write_bytes(("\r\n".join(CONSOLE_LAUNCHER_LINES) + "\r\n").encode("utf-8"))
    shutil.copy2(ROOT / "desktop.py", base / "desktop.py")
    say(f"已生成 desktop.py、{LAUNCHER_EXE} 与 {console.name}")


# Packages that only exist to *build* an environment, or that nothing on the
# runtime path imports. Shipping them cost ~69 MB of the download.
_PRUNE = (
    "pip", "setuptools", "wheel", "pkg_resources",
    "_distutils_hack", "setuptools-*.dist-info", "pip-*.dist-info",
    "wheel-*.dist-info",
    # onnxruntime is only reached through faster-whisper's optional VAD, which
    # this app never enables ("VAD 已禁用" in the plan)
    "onnxruntime", "onnxruntime-*.dist-info", "onnxruntime_*.dist-info",
    "coloredlogs", "humanfriendly", "flatbuffers",
)


def prune_site_packages(base: Path) -> int:
    """Drop build-only and unimported packages from the shipped runtime.

    Each name is checked against the frozen lock's import graph first: if the
    app or any kept dependency imported it, the removal would surface as a
    crash on a user' machine, which is exactly what this build is trying to
    avoid. The list is deliberately short and verified, not "everything
    suspicious".
    """
    site = base / "python" / "Lib" / "site-packages"
    if not site.is_dir():
        return 0
    freed = 0
    # a `.pth` file belonging to a removed package breaks every interpreter
    # start with "No module named '_distutils_hack'"; drop them with the package
    for pth in site.glob("distutils-precedence.pth"):
        freed += pth.stat().st_size
        pth.unlink(missing_ok=True)
    for pattern in _PRUNE:
        for path in site.glob(pattern):
            if path.is_file():
                freed += path.stat().st_size
                path.unlink(missing_ok=True)
                continue
            if not path.is_dir():
                continue
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path, ignore_errors=True)
            freed += size
    if freed:
        say(f"已移除构建期依赖,节省 {freed / 1048576:.0f} MB")
    return freed


def make_zip(base: Path, out: Path, extra: dict[str, Path] | None = None) -> Path:
    """Zip `base`, optionally adding extra trees under their own folder name."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    say(f"打包 {out.name} …")
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(base)
            # A build folder smoke-tested in place carries the interpreter's
            # bytecode cache and a `localdata/` with logs. Neither belongs in a
            # user's fresh install: the cache is dead weight and the logs are
            # this build machine's history.
            if "__pycache__" in rel.parts or rel.suffix == ".pyc":
                continue
            if rel.parts[0] in ("localdata", "exports", "_update", "app.prev"):
                continue
            z.write(f, f"UtaLearnNext/{rel}")
            total += 1
        for folder, src in (extra or {}).items():
            for f in src.rglob("*"):
                if f.is_file():
                    z.write(f, f"UtaLearnNext/{folder}/{f.relative_to(src)}")
                    total += 1
    say(f"  {total} 个文件，{out.stat().st_size / 1048576:.0f} MB")
    return out


# --------------------------------------------------------------------------- #
# custom-lyrics extension pack (version-independent)
# --------------------------------------------------------------------------- #
# Bundles the two models 自定义歌词 needs under `models/`: the whisper STT
# model (re-quantised to int8 below) and the ja-zh translation model
# (already int8 in `models/translate-ja-zh`). Neither is ever pulled from
# HuggingFace at runtime — the pack is what lets them work offline.
WHISPER_REPO = "Systran/faster-whisper-small"
# the original OpenAI weights, which CT2's converter understands
WHISPER_HF_REPO = "openai/whisper-small"
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
            f"(运行一次自定义歌词对齐),或设置 HF_HOME 指向缓存。\n  {repo_dir}")
    best = None
    for d in sorted(snap.iterdir()):
        if (d / "model.bin").exists():
            best = d  # keep the newest valid snapshot
    if best is None:
        raise SystemExit(f"{snap} 里没有完整的模型快照(缺 model.bin)")
    return best


# Parts of Playwright's browser folder the app never launches. The frame
# renderer uses `chromium-*/chrome.exe` through CDP; `chrome-headless-shell` is
# the separate binary `HeadlessExperimental.beginFrame` needs, which the plan
# explicitly avoids. Shipping it cost 287 MB of the add-on.
BROWSER_SKIP = ("chromium_headless_shell-",)


def make_addon_zip(folder: Path, out: Path) -> Path:
    """Zip a single extension folder as `<folder>/...` — no UtaLearnNext wrapper.

    Extension packs drop straight into the app folder (`browsers/` or
    `models/` next to `UtaLearn Next.exe`), so the archive carries the
    folder itself, not a wrapper the unpacker would have to peel off.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    say(f"打包 {out.name} ...")
    total = 0
    skipped = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in folder.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(folder)
            if any(part.startswith(BROWSER_SKIP) for part in rel.parts):
                skipped += 1
                continue
            z.write(f, f"{folder.name}/{rel}")
            total += 1
        z.writestr(
            f"{folder.name}/README-where-this-goes.txt",
            "把这个压缩包解压到 UtaLearnNext 应用目录里,\n"
            "让里面的文件夹落到应用目录中(如 browsers/ 或 models/),\n"
            "之后重新启动程序即可生效。\n",
        )
        total += 1
    if skipped:
        say(f"  跳过 {skipped} 个不用的浏览器组件(headless shell)")
    say(f"  {total} 个文件,{out.stat().st_size / 1048576:.0f} MB")
    return out


def _quantise_whisper(src: Path, dest: Path) -> Path:
    """Re-export the model as int8, halving the pack (461 MB → ~237 MB).

    The upstream `faster-whisper-small` repo only ships fp16 weights, but
    inference on CPU already runs int8 (`WhisperModel(compute_type="int8")`),
    so storing fp16 on disk means every user downloads 224 MB they never use.
    Converting needs torch + transformers, which are build-machine tools and
    never enter the package; when they are absent the fp16 copy is used and the
    size difference is reported.
    """
    try:
        from ctranslate2.converters import TransformersConverter
    except ImportError:
        say("  没有 ctranslate2/torch,保留 fp16(体积不会减半)")
        return src
    if dest.is_dir() and (dest / "model.bin").exists() \
            and (dest / "model.bin").stat().st_size < (src / "model.bin").stat().st_size * 0.7:
        say("  int8 模型已就位,跳过")
        return dest
    say("  转换为 int8(约 2 分钟,只在这一步需要 torch)...")
    shutil.rmtree(dest, ignore_errors=True)
    TransformersConverter(WHISPER_HF_REPO).convert(str(dest), quantization="int8", force=True)
    return dest


def stage_whisper_model(dest: Path) -> Path:
    """Materialise `dest/whisper-small` as an int8 model dir."""
    raw = dest / f"{WHISPER_DIRNAME}-fp16"
    target = dest / WHISPER_DIRNAME

    # the source is either the local fp16 snapshot or a converted int8 dir
    # produced by a previous run
    if target.is_dir() and (target / "model.bin").exists():
        size = (target / "model.bin").stat().st_size / 1048576
        if size < 300:
            say(f"whisper-small 已就位(int8,{size:.0f} MB),跳过")
            return target

    src = _whisper_snapshot()
    if not raw.is_dir() or not (raw / "model.bin").exists():
        say(f"复制 whisper-small({src.name[:12]}...)...")
        raw.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            # blobs arrive as symlinks into the blob store; resolve them so the
            # zip holds real bytes, not links
            if f.is_file() or f.is_symlink():
                shutil.copy2(f.resolve(), raw / f.name)

    _quantise_whisper(raw, target)
    if not (target / "model.bin").exists():
        # conversion unavailable: fall back to the fp16 copy under the real name
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(raw, target)

    # faster-whisper needs tokenizer/vocabulary files that CT2's converter does
    # not write; they are identical to the fp16 snapshot's
    for name in ("tokenizer.json", "vocabulary.txt", "preprocessor_config.json"):
        origin = raw / name
        if origin.exists() and not (target / name).exists():
            shutil.copy2(origin, target / name)
    shutil.rmtree(raw, ignore_errors=True)

    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / 1048576
    say(f"  models/{WHISPER_DIRNAME} = {size:.0f} MB(int8)")
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


def make_update_manifest(base: Path, patch: Path | None, full: Path, out: Path,
                         notes: str = "") -> Path:
    """`update.json`: version, runtime_id and the assets with hashes.

    `patch` is `None` for a release that no earlier build can upgrade to — the
    first release carrying the updater has nothing to patch *from*, so shipping
    a patch asset there would be a file users could download and fail to use.
    The manifest simply omits the key, and `updater.decide` falls back to the
    full package.

    The name must stay `update.json`: `updater.fetch_manifest` reads it through
    `releases/latest/download/update.json`, which only resolves while every
    release publishes that exact asset name.
    """
    info = json.loads((base / "BUILD_INFO.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": 1,
        "version": info["version"],
        "released_at": datetime.now(UTC).date().isoformat(),
        "notes": notes,
        "runtime_id": info["runtime_id"],
        "full": {
            "name": full.name,
            "size": full.stat().st_size,
            "sha256": sha256_file(full),
        },
    }
    if patch is not None:
        manifest["patch"] = {
            "name": patch.name,
            "size": patch.stat().st_size,
            "sha256": sha256_file(patch),
            "min_version": info.get("patch_from") or info["version"],
        }
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    say(f"已生成 {out.name}" + ("" if patch is not None else "(无补丁:首个带更新器的版本)"))
    return out


def make_custom_lyrics_zip(out: Path) -> Path:
    """Standalone zip: `models/whisper-small/...` + `models/translate-ja-zh/...`.

    Files land directly under `models/` with no wrapper — the app reads the
    archive by the folder names, same as the chromium pack reads `browsers/`.

    The whisper half comes from *this project's* `models/whisper-small`, which
    `stage_whisper_model` has already reduced to int8. Reading the HF cache
    here (as this used to) shipped the 461 MB fp16 weights while the app only
    ever ran int8 — 224 MB of dead download per user.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    say(f"打包 {out.name} ...")

    staging = out.parent / "_pack-staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    whisper = stage_whisper_model(staging)
    translate = _translate_snapshot()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for snap, sub in ((whisper, WHISPER_DIRNAME),
                          (translate, TRANSLATE_DIRNAME)):
            for f in sorted(snap.iterdir()):
                if f.is_file() or f.is_symlink():
                    z.write(f.resolve(), f"models/{sub}/{f.name}")
        z.writestr(
            "models/README-where-this-goes.txt",
            "把本包解压到 UtaLearnNext 应用目录里,得到\n"
            "  models/whisper-small/model.bin   语音识别( int8 )\n"
            "  models/translate-ja-zh/model.bin  日→中翻译\n"
            "之后重新启动程序,自定义歌词即可离线对齐与翻译。\n"
            "本包与版本无关,升级应用不用重下。\n",
        )
    shutil.rmtree(staging, ignore_errors=True)
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
    ap.add_argument("--patch-from", default="",
                    help="补丁可覆盖的最旧版本,如 2.0.0;留空则不出补丁")
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

    copy_tree(ROOT / "backend", base / "backend",
              ignore=("utalearn_backend.egg-info", ".pytest_cache", ".ruff_cache"))
    copy_tree(ROOT / "frontend" / "dist", base / "frontend" / "dist")
    # CHANGELOG stays in the repo: a user running the app has no use for a
    # version-by-version history, and the release notes already say what
    # changed for this download.
    for name in ("README.md", "LICENSE", "PRIVACY.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, base / name)
    # the desktop shell lives at the app root: it owns the port choice, the
    # readiness wait and the pywebview window
    shutil.copy2(ROOT / "desktop.py", base / "desktop.py")
    # The window/taskbar icon is read from the app root at runtime; the exe
    # embeds the same file as a resource, but the pywebview host needs the
    # `.ico` on disk to replace Edge/Python's default window icon.
    shutil.copy2(ROOT / "tools" / "assets" / "app.ico", base / "app.ico")
    say("已复制代码与前端产物")

    py = build_python(base)
    install_packages(py, base)
    bin_dir = fetch_ffmpeg(base, Path(args.ffmpeg_dir) if args.ffmpeg_dir else None)
    write_build_info(base, ffmpeg_version(bin_dir), args.patch_from)
    prune_site_packages(base)
    write_launcher(base)

    size = sum(f.stat().st_size for f in base.rglob("*") if f.is_file()) / 1048576
    say(f"核心目录 {size:.0f} MB")

    if args.no_zip:
        return 0

    zip_root = Path(args.zip_out).resolve() if args.zip_out else out_root
    full = make_zip(base, zip_root / f"UtaLearnNext-{VERSION}.zip")
    # A patch is only useful if an *older* build can install it. The release
    # that first carried the updater has no predecessor with one, so it ships
    # the full package alone; `--patch-from <version>` declares the oldest
    # build the patch applies to (defaults to the previous minor).
    patch = None
    if args.patch_from:
        # Constant name so the updater can build one URL for every release;
        # the version it leads to lives in update.json, not in the filename.
        patch = make_patch_zip(base, zip_root / "auto-update-patch.zip")
    else:
        say("不生成补丁:这是第一个带更新器的版本(下次发版用 --patch-from)")
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
