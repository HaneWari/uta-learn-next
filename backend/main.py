"""UtaLearn API.

Two jobs:
1. **Configure** — search QQ Music / Kugou / Lrclib for lyrics, or take an
   uploaded audio file plus pasted lyrics and estimate the timing with
   whisper + vocal energy.
2. **Play** — serve a dataset (`song_data.json` + `audio.mp3`) to the karaoke
   stage, plus the built SPA when `frontend/dist` exists.

A dataset is a folder under `DATA_DIR`. Folders starting with `_` are internal
(uploads), never listed as songs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import export, fallback, jobs, retime
from app import translate as translate_mod
from app.builder import _is_credit
from app.builder import build as build_song
from app.builder import slugify
from app.builder import retime_words
from app.dicts import analyze, enrich, find_grammar, parse_reading_marks
from app.sources import SOURCES, Song, get_source, search_all

# --------------------------------------------------------------------------- #
# where data lives
# --------------------------------------------------------------------------- #
# Everything is resolved against the *application folder*, never the current
# working directory: a portable build gets unzipped anywhere and started from
# anywhere, and `../localdata` relative to CWD silently pointed at the wrong
# place (or at nothing) as soon as the launcher's working directory changed.
APP_ROOT = Path(__file__).resolve().parent.parent


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _user_dir(name: str) -> Path:
    """Per-user fallback for when the app folder itself is read-only."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "UtaLearnNext" / name


def _resolve_dir(env_name: str, portable: Path, fallback_name: str) -> Path:
    """env override → folder next to the app → per-user directory."""
    raw = os.environ.get(env_name)
    if raw:
        p = Path(raw).expanduser()
        return (p if p.is_absolute() else APP_ROOT / p).resolve()
    if _is_writable(portable):
        return portable.resolve()
    return _user_dir(fallback_name)


DATA_DIR = _resolve_dir("DATA_DIR", APP_ROOT / "localdata", "localdata")
UPLOAD_DIR = DATA_DIR / "_uploads"
DEFAULT_SONG = os.environ.get("DEFAULT_SONG", "braveheart")
DIST_DIR = APP_ROOT / "frontend" / "dist"
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".mp4"}
MAX_UPLOAD = 200 * 1024 * 1024
EXPORT_DIR = _resolve_dir("EXPORT_DIR", APP_ROOT / "exports", "exports")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # staging uploads are only meaningful while a song is being configured
    try:
        removed = _prune_uploads()
        if removed:
            print(f"[uta] 清理了 {removed} 个过期上传")
    except Exception:  # noqa: BLE001
        pass
    print(f"[uta] 程序目录 {APP_ROOT}")
    print(f"[uta] 数据目录 {DATA_DIR}")
    print(f"[uta] 导出目录 {EXPORT_DIR}")
    yield


app = FastAPI(title="Uta Learn Next API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

NO_CACHE = {"Cache-Control": "no-store, max-age=0"}

# Where the export's headless browser should reach this server. Override with
# UTALEARN_BASE_URL when running behind a different host/port.
BASE_URL = os.environ.get("UTALEARN_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


# --------------------------------------------------------------------------- #
# datasets
# --------------------------------------------------------------------------- #
def dataset(name: str | None) -> Path:
    if name:
        # `_`-prefixed folders are internal (_uploads, _ui) and must never be
        # reachable as a song, same rule list_datasets uses.
        if "/" in name or "\\" in name or name.startswith(".") or name.startswith("_"):
            raise HTTPException(status_code=400, detail="bad song name")
        candidate = DATA_DIR / name
        if not candidate.is_dir():
            # Generating the same song twice appends "-2", and deleting the older
            # one leaves stale links behind. Point at the survivor instead of a
            # bare "not found".
            base = re.sub(r"-\d+$", "", name)
            near = [p.name for p in DATA_DIR.glob(f"{base}*") if p.is_dir()] \
                if DATA_DIR.is_dir() else []
            hint = f"，可用的是：{'、'.join(near[:3])}" if near else ""
            raise HTTPException(status_code=404, detail=f"unknown song: {name}{hint}")
        return candidate
    nested = DATA_DIR / DEFAULT_SONG
    if nested.is_dir() and (nested / "song_data.json").exists():
        return nested
    return DATA_DIR


_AUDIO_DUR: dict[tuple[str, float, int], float] = {}


def _audio_duration(path: Path) -> float:
    """Actual playable length of a dataset's audio file (0 when unreadable).

    `meta.duration_seconds` describes the *lyric timeline*, which is regularly
    shorter than the user's own file (a trimmed intro, a different edit), so the
    song list has to ask the audio itself or it advertises the wrong length.
    """
    try:
        st = path.stat()
    except OSError:
        return 0.0
    key = (str(path), st.st_mtime, st.st_size)
    cached = _AUDIO_DUR.get(key)
    if cached is None:
        if len(_AUDIO_DUR) > 64:
            _AUDIO_DUR.clear()
        cached = float(fallback.probe_duration(path) or 0.0)
        _AUDIO_DUR[key] = cached
    return cached


def _prune_uploads(max_age_hours: float = 24.0) -> int:
    """Drop staging uploads that were never turned into a dataset.

    Every build copies the audio into its dataset, so a file left in _uploads is
    only useful while the user is still in the middle of configuring that song.
    Without this the folder grows without bound.
    """
    if not UPLOAD_DIR.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in UPLOAD_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def list_datasets() -> list[dict]:
    if not DATA_DIR.is_dir():
        return []
    out = []
    for entry in sorted(DATA_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        data = entry / "song_data.json"
        if not data.exists():
            continue
        try:
            meta = json.loads(data.read_text(encoding="utf-8")).get("meta", {})
        except Exception:  # noqa: BLE001
            meta = {}
        audio = entry / "audio.mp3"
        has_audio = audio.exists()
        out.append({
            "name": entry.name,
            "title": meta.get("title") or entry.name,
            "artist": meta.get("artist") or "",
            "duration": (_audio_duration(audio) if has_audio else 0)
                        or meta.get("duration_seconds") or 0,
            "has_audio": has_audio,
            "source": meta.get("source") or "",
        })
    return out


def _free_name(base: str) -> str:
    name = slugify(base) or "song"
    candidate, i = name, 2
    while (DATA_DIR / candidate).exists():
        candidate = f"{name}-{i}"
        i += 1
    return candidate


def _save_dataset(name: str, song: dict, audio: Path | None) -> Path:
    out = DATA_DIR / name
    out.mkdir(parents=True, exist_ok=True)
    # Record whether an audio file is actually present: the stage must not
    # request /api/audio for a lyrics-only dataset, and duration_seconds is the
    # length of the lyric timeline, not proof of a file.
    has_audio = audio is not None and audio.exists()
    song.setdefault("meta", {})["has_audio"] = bool(has_audio)
    (out / "song_data.json").write_text(
        json.dumps(song, ensure_ascii=False, indent=2), encoding="utf-8")
    if has_audio:
        shutil.copyfile(audio, out / "audio.mp3")
    return out


def _upload_path(upload_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", upload_id or ""):
        raise HTTPException(status_code=400, detail="bad upload id")
    for p in UPLOAD_DIR.glob(f"{upload_id}.*"):
        return p
    raise HTTPException(status_code=404, detail="上传的音频已过期，请重新上传")



def _try_retime(parsed, audio: Path, progress) -> dict | None:
    """Fit the source timeline onto `audio`; None when the fit is not trusted.

    Runs whisper once. The transcription is cached on the ParsedLyrics object so
    a failed fit can fall straight through to the whisper build without paying
    for a second pass.
    """
    cached = getattr(parsed, "_wsegs", None)
    if cached is None:
        progress(0.15, "识别你的音频，用于对齐版本差异…")
        try:
            wav = fallback.to_wav(audio)
            x, sr = fallback.load_wav(wav)
            wsegs = fallback._transcribe(x, progress)
        except Exception as e:  # noqa: BLE001
            progress(0.18, f"识别失败，改用其他方式：{e}")
            return None
        finally:
            try:
                wav.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
        parsed._wsegs = wsegs
    else:
        wsegs = cached

    if not wsegs:
        return None
    try:
        fitted = retime.fit(parsed, wsegs)
    except Exception:  # noqa: BLE001
        return None
    if not fitted or not fitted.get("ok"):
        if fitted:
            progress(0.20, f"重对时不可靠（残差 {fitted['residual']:.2f}s），改用全量对齐")
        return None
    return fitted


def _lyric_lines(parsed, title: str, artist: str, source_song: Song | None = None) -> list[str]:
    """Plain lyric text lines from a parsed source, credits dropped.

    Credits are matched against the *source* song's title/artist, not the name
    the user typed: the header block in a QRC payload repeats the release title,
    which the user's own label rarely matches.
    """
    meta = {"title": title, "artist": artist}
    if source_song is not None:
        meta = {"title": source_song.title, "artist": source_song.artist}
    out = []
    for i, line in enumerate(parsed.lines):
        text = "".join(u[0] for u in (line.get("units") or [])).strip()
        if not text or _is_credit(text, meta, head=i < 6):
            continue
        out.append(text)
    return out


def _attach_translation(data: dict, translation) -> None:
    """Time-match the source's translation lines onto estimated segments."""
    if not translation:
        return
    for seg in data["segments"]:
        best = min(translation, key=lambda p: abs(p[0] - seg["start"]))
        if abs(best[0] - seg["start"]) <= 3.0:
            seg["translation_zh"] = best[1]


def _meta_flag(name: str, key: str) -> bool:
    """Read a boolean meta flag off a dataset without trusting the caller."""
    path = dataset(name) / "song_data.json"
    try:
        return bool(json.loads(path.read_text(encoding="utf-8"))
                    .get("meta", {}).get(key))
    except Exception:
        return False


def _mmss(raw) -> float:
    """Parse a "m:ss" (or plain seconds) crop point; anything else is 0."""
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, (int, float)):
        return max(0.0, float(raw))
    s = str(raw).strip()
    if ":" in s:
        try:
            m, sec = s.split(":", 1)
            return max(0.0, int(m) * 60 + float(sec))
        except ValueError:
            return 0.0
    try:
        return max(0.0, float(s))
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- #
# config API
# --------------------------------------------------------------------------- #
@app.get("/api/sources")
def api_sources():
    return [{"name": s.name, "label": s.label} for s in SOURCES.values()]


@app.post("/api/search")
async def api_search(payload: dict):
    query = (payload.get("query") or "").strip()
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="请输入至少 2 个字符")
    names = payload.get("sources") or None
    results, errors = search_all(query, names)
    return {"results": results, "errors": errors}


@app.post("/api/uploads")
async def api_upload(file: UploadFile):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的音频格式：{ext or '未知'}")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex[:12]
    dest = UPLOAD_DIR / f"{uid}{ext}"
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="音频超过 200MB")
            fh.write(chunk)
    try:
        duration = fallback.probe_duration(dest)
    except Exception:  # noqa: BLE001
        duration = 0.0
    if duration <= 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="无法读取该音频，请换一个文件")
    return {"id": uid, "filename": file.filename, "duration": round(duration, 2),
            "size": size}


def _song_from_payload(raw: dict) -> Song:
    keep = ("source", "id", "title", "artist", "album", "duration", "kind", "extra")
    data = {k: raw.get(k) for k in keep}
    if not data["source"] or not data["id"]:
        raise HTTPException(status_code=400, detail="搜索结果不完整")
    data["duration"] = float(data["duration"] or 0)
    data["extra"] = data["extra"] or {}
    data["album"] = data["album"] or ""
    data["artist"] = data["artist"] or ""
    data["title"] = data["title"] or ""
    data["kind"] = data["kind"] or "line"
    return Song(**data)


@app.post("/api/build")
async def api_build(payload: dict):
    """Build a dataset from a lyric source, optionally against the user's audio.

    With no audio the source's own timestamps are authoritative (QQ/Kugou give
    per-character times). With audio, the source only supplies the *lyric text*
    and the timeline is estimated from that audio — otherwise a user whose file
    is a different edit (a TV-size cut, a live take) would get a dataset that is
    uniformly offset by the difference between the two recordings.
    """
    song = _song_from_payload(payload.get("song") or {})
    upload_id = payload.get("upload_id")
    title = (payload.get("title") or song.title).strip()
    artist = (payload.get("artist") or song.artist).strip()
    name = _free_name(f"{title} {artist}".strip())
    audio = _upload_path(upload_id) if upload_id else None
    label = get_source(song.source).label

    jid = jobs.create("build")

    def work(progress):
        progress(0.08, f"从 {label} 取歌词…")
        parsed = get_source(song.source).fetch(song)
        if not parsed.lines:
            raise RuntimeError("这个来源没有可用的歌词")

        # A file whose length matches the source almost certainly *is* that
        # recording, and then the source's per-character timestamps beat any
        # estimate. Only re-align when the lengths disagree — that means a
        # different edit (TV size, live take, own cut).
        # Manual version matching: the source's own per-character timeline is
        # authoritative, but a different edit (TV-size cut, a trimmed intro,
        # a live take) makes it disagree with the uploaded file. Rather than
        # auto-aligning (a whisper pass over a whole song just to learn an
        # offset), the user supplies the cut point for whichever side is
        # longer. `lyric_start` says where in the *source* timeline the audio
        # begins (source longer, intro skipped); `audio_start` says where in
        # the *audio* the lyric timeline begins (audio longer, instrumental
        # intro). Seconds are "m:ss" strings straight from the config page.
        lyric_start = _mmss(payload.get("lyric_start"))
        audio_start = _mmss(payload.get("audio_start"))

        if audio is not None:
            got = fallback.probe_duration(audio)
            if song.duration and got < song.duration - 2.0:
                # audio shorter: the source describes a longer recording, drop
                # what the file does not reach
                time_shift = -lyric_start
                max_time = got
                align_note = f"{label} 逐字时间戳 · 音频较短手动裁剪"
                progress(0.55, f"音频较短，歌词时间轴从 {lyric_start:g}s 起裁到 {got:g}s…")
            elif song.duration and got > song.duration + 2.0:
                # audio longer: it has extra room the lyric timeline never
                # fills (an instrumental head/tail) — shift the whole lyric
                # clock forward instead of guessing where lines land
                time_shift = audio_start
                max_time = got
                align_note = f"{label} 逐字时间戳 · 音频较长手动裁剪"
                progress(0.55, f"音频较长，歌词时间轴整体后移 {audio_start:g}s…")
            else:
                time_shift = 0.0
                max_time = None
                align_note = f"{label} 逐字时间戳"
                progress(0.55, f"分词并生成 {len(parsed.lines)} 行…")

            data = build_song(parsed, {
                "title": title, "artist": artist,
                "youtube_url": "", "language": "ja",
                "whisperx_model": "none",
                "align_model": align_note,
                "vocal_separation": "none",
                "source": label,
                "source_kind": parsed.kind,
            }, credit_names={"title": song.title, "artist": song.artist},
                time_shift=time_shift, max_time=max_time)
        else:
            progress(0.55, f"分词并生成 {len(parsed.lines)} 行…")
            data = build_song(parsed, {
                "title": title, "artist": artist,
                "youtube_url": "", "language": "ja",
                "whisperx_model": "none",
                "align_model": f"{label} 逐字时间戳",
                "vocal_separation": "none",
                "source": label,
                "source_kind": parsed.kind,
            }, credit_names={"title": song.title, "artist": song.artist})

        if not data["segments"]:
            raise RuntimeError("歌词解析后为空")
        progress(0.88, "写入数据集…")
        _save_dataset(name, data, audio)
        return {"name": name, "title": title, "artist": artist,
                "segments": len(data["segments"]),
                "duration": data["meta"]["duration_seconds"],
                "has_audio": bool(audio)}

    jobs.run(jid, work)
    return {"job_id": jid, "name": name}


@app.post("/api/build-text")
async def api_build_text(payload: dict):
    """Estimate timing from an uploaded audio + the user's own lyric text."""
    upload_id = (payload.get("upload_id") or "").strip()
    text = payload.get("lyrics") or ""
    if not upload_id:
        raise HTTPException(status_code=400, detail="请先上传音频")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise HTTPException(status_code=400, detail="请粘贴歌词，每行一句（至少 2 行）")
    audio = _upload_path(upload_id)
    title = (payload.get("title") or audio.stem).strip()
    artist = (payload.get("artist") or "").strip()
    name = _free_name(f"{title} {artist}".strip())

    jid = jobs.create("fallback")

    def work(progress):
        data = fallback.build_from_audio(audio, lines, {
            "title": title, "artist": artist,
            "youtube_url": "", "language": "ja",
            "whisperx_model": os.environ.get("UTALEARN_WHISPER", "large-v3"),
            "align_model": "whisper 切片转写 + 假名全局对齐 + 逐字锚定",
            "vocal_separation": "none",
            "source": "本地上传 + whisper",
            "source_kind": "estimated",
        }, progress=progress)
        # translation is part of the build job, not a separate step: it only
        # runs when the user asked for it, after the timing is already solved,
        # so a missing translate pack never wastes a whisper pass
        if payload.get("translate"):
            progress(0.93, f"翻译 {len(data['segments'])} 行…")
            try:
                zh = translate_mod.translate_lines(
                    [s["text"] for s in data["segments"]])
                for seg, line in zip(data["segments"], zh):
                    if line:
                        seg["translation_zh"] = line
            except RuntimeError as e:
                # a missing pack is a soft failure: the dataset is already
                # built, the listener just gets no gloss
                progress(0.95, f"翻译失败：{e}")
        _save_dataset(name, data, audio)
        return {"name": name, "title": title, "artist": artist,
                "segments": len(data["segments"]),
                "duration": data["meta"]["duration_seconds"],
                "has_audio": True}

    jobs.run(jid, work)
    return {"job_id": jid, "name": name}


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job


# --------------------------------------------------------------------------- #
# whisper model extension pack
# --------------------------------------------------------------------------- #
# The custom-lyrics path needs a bundled speech model under `models/`. It is
# never pulled from HuggingFace: the config page offers a one-click install
# that fetches the version-independent `whisper-small` zip off the *latest*
# GitHub release of this repo and unpacks it next to the app.

GITHUB_REPO = "HaneWari/uta-learn-next"
WHISPER_ASSET = "UtaLearnNext-whisper-small.zip"
_WHISPER_NAME = "whisper-small"


def _whisper_model_dir() -> Path:
    return APP_ROOT / "models" / _WHISPER_NAME


def _whisper_installed() -> bool:
    d = _whisper_model_dir()
    return d.is_dir() and (d / "model.bin").exists()


@app.get("/api/models/status")
def api_model_status():
    return {"installed": _whisper_installed(),
            "path": str(_whisper_model_dir()),
            "asset": WHISPER_ASSET}


def _latest_whisper_url() -> str:
    """Stable download URL of the whisper zip on the newest release.

    ``releases/latest/download/<asset>`` redirects to the newest release's
    asset without touching the API, so it is immune to the anonymous GitHub
    API rate limit that would otherwise 403 the install on a busy day.
    """
    return (f"https://github.com/{GITHUB_REPO}/releases/latest/download/"
            f"{WHISPER_ASSET}")


@app.post("/api/models/install")
def api_model_install():
    """Download + unpack the whisper extension pack in the background."""
    if _whisper_installed():
        return {"job_id": None, "installed": True}
    jid = jobs.create("model-install")

    def work(progress):
        import io
        import zipfile
        import httpx

        progress(0.05, "查询最新发行版…")
        url = _latest_whisper_url()
        progress(0.10, "下载模型扩展包（约 426MB，请稍候）…")
        buf = io.BytesIO()
        with httpx.Client(timeout=None, follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                got = 0
                for chunk in r.iter_bytes(1 << 20):
                    buf.write(chunk)
                    got += len(chunk)
                    if total:
                        # download spans 10%–80% of the job
                        progress(0.10 + 0.70 * got / total,
                                 f"下载模型扩展包… {got // 1048576}MB")
        progress(0.85, "解压到 models/…")
        dest = APP_ROOT / "models"
        dest.mkdir(parents=True, exist_ok=True)
        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            # the zip carries a `UtaLearnNext/` wrapper (same as the core and
            # chromium packs); strip it so `…/models/whisper-small/` lands
            # inside the app folder no matter where the user unzipped it
            for member in z.namelist():
                rel = member[len("UtaLearnNext/"):] \
                    if member.startswith("UtaLearnNext/") else member
                if not rel.startswith("models/"):
                    continue
                target = APP_ROOT / rel
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        if not _whisper_installed():
            raise RuntimeError("解压后未找到 models/whisper-small/model.bin")
        progress(0.98, "安装完成")
        return {"installed": True, "path": str(_whisper_model_dir())}

    jobs.run(jid, work)
    return {"job_id": jid}


# --------------------------------------------------------------------------- #
# export environment: bundled-Chromium extension pack + playwright self-fix
# --------------------------------------------------------------------------- #
# The core zip ships the `playwright` *package* but no browser binary. On a
# machine whose own browser is Chromium-based the export just borrows it; when
# it isn't (Firefox / no browser / a broken webview), the user can either let
# the app repair playwright or pull the version-free `chromium` extension pack
# — same release-asset mechanism as the whisper model.

CHROMIUM_ASSET = "UtaLearnNext-chromium.zip"


def _browsers_dir() -> Path:
    return Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", APP_ROOT / "browsers"))


def _chromium_pack_installed() -> bool:
    d = _browsers_dir()
    return d.is_dir() and any(d.glob("chromium-*"))


def _latest_chromium_url() -> str:
    return (f"https://github.com/{GITHUB_REPO}/releases/latest/download/"
            f"{CHROMIUM_ASSET}")


@app.get("/api/export/env")
def api_export_env():
    """Deep export-environment probe run on demand (not cached).

    The frontend calls this when the user clicks 导出视频, so the answer is
    always about the machine *right now* — a browser installed since startup
    shows up without an app restart.
    """
    return export.env_check()


@app.post("/api/export/fix-playwright")
def api_export_fix_playwright():
    """Try to repair the playwright runtime: pip-install the package and pull
    its matching chromium build. Cheap when already present, a real fix when
    the package was stripped or its browser download was interrupted.
    """
    jid = jobs.create("export-fix")

    def work(progress):
        import subprocess
        import sys

        progress(0.1, "检查 playwright 包…")
        try:
            import playwright  # noqa: F401
            progress(0.4, "playwright 已安装，补装浏览器…")
        except Exception:  # noqa: BLE001
            progress(0.15, "安装 playwright …")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "playwright"],
                check=True, capture_output=True)
            progress(0.4, "playwright 装好，下载浏览器…")

        progress(0.55, "下载 Chromium（约 130MB，请稍候）…")
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True, capture_output=True, env=dict(os.environ))

        progress(0.9, "验证浏览器…")
        c = export.env_check()
        if not c["checks"]["browser_launch"]:
            raise RuntimeError(
                "playwright 已修复但浏览器仍无法启动：" +
                (c["checks"]["launch_error"] or "未知原因"))
        progress(0.98, "完成")
        return {"ok": True, "env": c}

    jobs.run(jid, work)
    return {"job_id": jid}


@app.post("/api/export/install-chromium")
def api_export_install_chromium():
    """Download + unpack the bundled-Chromium extension pack.

    Used when the machine has no usable Chromium-core browser *and* the
    playwright route can't help (e.g. its download is blocked). The zip drops a
    `browsers/` folder next to the app, exactly like the manual extension.
    """
    if _chromium_pack_installed():
        return {"job_id": None, "installed": True}
    jid = jobs.create("chromium-install")

    def work(progress):
        import io
        import zipfile
        import httpx

        progress(0.05, "查询最新发行版…")
        url = _latest_chromium_url()
        progress(0.10, "下载 Chromium 扩展包（约 316MB，请稍候）…")
        buf = io.BytesIO()
        with httpx.Client(timeout=None, follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                got = 0
                for chunk in r.iter_bytes(1 << 20):
                    buf.write(chunk)
                    got += len(chunk)
                    if total:
                        progress(0.10 + 0.70 * got / total,
                                 f"下载 Chromium 扩展包… {got // 1048576}MB")
        progress(0.85, "解压到应用目录…")
        buf.seek(0)
        with zipfile.ZipFile(buf) as z:
            for member in z.namelist():
                rel = member[len("UtaLearnNext/"):] \
                    if member.startswith("UtaLearnNext/") else member
                if not rel.startswith("browsers/"):
                    continue
                target = APP_ROOT / rel
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        if not _chromium_pack_installed():
            raise RuntimeError("解压后未找到 browsers/chromium-* 目录")
        progress(0.98, "安装完成")
        return {"installed": True, "needs_restart": True,
                "path": str(_browsers_dir())}

    jobs.run(jid, work)
    return {"job_id": jid}


@app.get("/api/songs")
def api_songs():
    return list_datasets()


@app.get("/api/songs/{name}")
def api_song(name: str):
    path = dataset(name) / "song_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")
    return FileResponse(path, media_type="application/json", headers=NO_CACHE)


@app.delete("/api/songs/{name}")
def api_delete_song(name: str):
    if not re.fullmatch(r"[^/\\]+", name or "") or name.startswith("."):
        raise HTTPException(status_code=400, detail="bad song name")
    target = DATA_DIR / name
    if not target.is_dir() or not (target / "song_data.json").exists():
        raise HTTPException(status_code=404, detail="unknown song")
    shutil.rmtree(target)
    return {"deleted": name}


_WRITABLE_KEYS = {
    "id",
    "vocab_override",
    "grammar_extra",
    # stage-side lyric edits live in `lyric_override` (never overwrite the raw
    # `text`/`translation_zh`, so a cleared line can always be restored);
    # `hidden` skips a line entirely
    "lyric_override",
    "hidden",
}

# Song-wide settings that sit in `meta` rather than on a segment. The offset
# shifts the whole lyric timeline against the audio (positive = lyrics later);
# it lives in the dataset so the export recorder, which reloads song_data.json,
# plays with the same correction the user tuned by ear.
_META_KEYS = {"time_offset", "trans_hidden"}
TIME_OFFSET_MAX = 2.0


@app.patch("/api/songs/{name}")
def api_patch_song(name: str, patch: dict):
    """Persist card edits made on the stage.

    The payload is a partial `Segment` — only `vocab_override` and
    `grammar_extra` are writable through this route; everything else (text,
    timings, grammar) is derived data and stays authoritative.

    A payload without `id` carrying only song-wide keys (`time_offset`) updates
    `meta` instead.
    """
    if "id" not in patch and patch and set(patch.keys()) <= _META_KEYS:
        return _patch_meta(name, patch)
    bad = set(patch.keys()) - _WRITABLE_KEYS
    if bad:
        raise HTTPException(status_code=400, detail=f"只读字段: {sorted(bad)}")
    if "id" not in patch:
        raise HTTPException(status_code=400, detail="缺少 segment id")

    path = dataset(name) / "song_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")
    data = json.loads(path.read_text(encoding="utf-8"))

    for seg in data.get("segments", []):
        if seg.get("id") != patch["id"]:
            continue
        for key in _WRITABLE_KEYS - {"id"}:
            if key in patch:
                if patch[key] is None:
                    seg.pop(key, None)
                else:
                    seg[key] = patch[key]
        # A lyric edit changes the sung text, so the old per-word timings no
        # longer describe it. Rebuild the line's `words` (and grammar, since
        # that is computed off the same tokens) so the override still shows
        # furigana, romaji and a per-glyph wipe — just re-estimated, not the
        # stale source alignment. An emptied line drops both.
        if "lyric_override" in patch:
            ov = seg.get("lyric_override")
            if ov and ov.get("text") is not None:
                plain, marks = parse_reading_marks(ov["text"])
                words = retime_words(plain, seg["start"], seg["end"], marks)
                ov["words"] = words
                # keep the mark-up in the stored text so the editor re-shows
                # `[明日](あす)`, but a plain override stays verbatim
                ov["text"] = ov["text"] if marks else plain
                grammar = _reline_grammar(plain)
                if grammar is not None:
                    seg["grammar"] = grammar
                else:
                    seg.pop("grammar", None)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return seg

    raise HTTPException(status_code=404, detail="segment not found")


def _patch_meta(name: str, patch: dict) -> dict:
    path = dataset(name) / "song_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.setdefault("meta", {})
    if "time_offset" in patch:
        raw = patch["time_offset"]
        try:
            value = round(float(raw if raw is not None else 0.0), 1)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="时间偏移必须是数字") from None
        if not -TIME_OFFSET_MAX <= value <= TIME_OFFSET_MAX:
            raise HTTPException(status_code=400, detail="时间偏移须在 -2 到 2 秒之间")
        if value == 0:
            meta.pop("time_offset", None)
        else:
            meta["time_offset"] = value
    if "trans_hidden" in patch:
        if patch["trans_hidden"]:
            meta["trans_hidden"] = True
        else:
            meta.pop("trans_hidden", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"time_offset": meta.get("time_offset", 0.0),
            "trans_hidden": bool(meta.get("trans_hidden"))}


def _reline_grammar(text: str) -> list[dict] | None:
    """Grammar hits for a re-tokenised override line; None when there are none."""
    if not text.strip():
        return None
    tokens = analyze(text)
    if not tokens:
        return None
    enrich(tokens)
    hits = find_grammar(text, tokens)
    return hits or None


# --------------------------------------------------------------------------- #
# video export
# --------------------------------------------------------------------------- #
@app.get("/api/export/status")
def api_export_status():
    ok, why = export.available()
    return {"available": ok, "reason": why}


@app.get("/api/exports")
def api_exports():
    if not EXPORT_DIR.is_dir():
        return []
    out = []
    for f in sorted(EXPORT_DIR.glob("*.mp4"), key=lambda x: -x.stat().st_mtime):
        out.append({
            "file": f.name,
            "size": f.stat().st_size,
            "created": int(f.stat().st_mtime),
            "url": f"/api/exports/{f.name}",
        })
    return out


@app.post("/api/export")
async def api_export(payload: dict):
    """Record the stage for one dataset and mux its audio into an MP4."""
    name = (payload.get("song") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少 song")
    folder = dataset(name)
    data_path = folder / "song_data.json"
    if not data_path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")

    meta = json.loads(data_path.read_text(encoding="utf-8")).get("meta", {})
    audio = folder / "audio.mp3"
    audio = audio if audio.exists() else None

    # The recording has to last as long as the *audio*, not as long as the lyric
    # timeline: a trimmed intro or a different edit makes those differ by tens of
    # seconds, and recording to the lyric length silently cut the song short.
    timeline = float(meta.get("duration_seconds") or 0)
    duration = (_audio_duration(audio) if audio else 0.0) or timeline
    if duration <= 0:
        raise HTTPException(status_code=400, detail="这个数据集没有时间轴，无法导出")

    safe = re.sub(r"[^\w.\-]+", "-", name)[:60]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = EXPORT_DIR / f"{safe}-{stamp}.mp4"
    # the recorder opens a fresh browser profile that can't see the user's
    # localStorage — the hidden-cards flag has to be carried in the page URL
    hide_cards = bool(payload.get("hide_cards"))
    # translation visibility is a dataset-level choice the recorder's fresh
    # profile also has to see — read the flag the stage toggles, not the body
    hide_trans = _meta_flag(name, "trans_hidden")

    ok, why = export.available()
    if not ok:
        raise HTTPException(status_code=503, detail=f"导出不可用：{why}")

    jid = jobs.create("export")

    def work(progress):
        export.render(
            base_url=BASE_URL,
            song=name,
            audio=audio,
            out=out,
            duration=duration,
            progress=progress,
            extra_query=("&hidecards=1" if hide_cards else "")
            + ("&hidetrans=1" if hide_trans else ""),
        )
        return {"file": out.name, "url": f"/api/exports/{out.name}",
                "size": out.stat().st_size, "duration": duration,
                "dir": str(out.parent), "path": str(out), "fps": export.FPS}

    jobs.run(jid, work)
    return {"job_id": jid, "file": out.name}


@app.get("/api/exports/{filename}")
def api_export_file(filename: str):
    if not re.fullmatch(r"[\w.\-]+\.mp4", filename):
        raise HTTPException(status_code=400, detail="bad filename")
    path = EXPORT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)


@app.delete("/api/exports/{filename}")
def api_export_delete(filename: str):
    if not re.fullmatch(r"[\w.\-]+\.mp4", filename):
        raise HTTPException(status_code=400, detail="bad filename")
    path = EXPORT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    path.unlink()
    return {"deleted": filename}


# --------------------------------------------------------------------------- #
# playback (kept at /poc/* so the video renderer keeps working)
# --------------------------------------------------------------------------- #
@app.get("/")
def health():
    if (DIST_DIR / "index.html").exists():
        return FileResponse(DIST_DIR / "index.html", headers=NO_CACHE)
    return {"status": "ok", "songs": list_datasets()}


@app.get("/poc/songs")
def list_songs():
    return [s["name"] for s in list_datasets()]


@app.get("/poc/song")
def get_song(song: str | None = None):
    return api_song(song) if song else _default_song_file("song_data.json", "application/json")


@app.get("/poc/audio")
def get_audio(song: str | None = None):
    return api_audio(song) if song else _default_song_file("audio.mp3", "audio/mpeg")


@app.get("/api/audio/{name}")
def api_audio(name: str):
    path = dataset(name) / "audio.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="这个数据集没有音频")
    return FileResponse(path, media_type="audio/mpeg", headers=NO_CACHE)


def _default_song_file(filename: str, media: str):
    path = dataset(None) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} missing")
    return FileResponse(path, media_type=media, headers=NO_CACHE)


# --------------------------------------------------------------------------- #
# stage background
# --------------------------------------------------------------------------- #
# Kept on the server rather than in localStorage on purpose: the video export
# runs in a fresh headless browser profile, so a browser-local setting would not
# reach it and the exported video would silently lose the background.
UI_DIR = DATA_DIR / "_ui"
BG_META = UI_DIR / "background.json"
BG_MAX = 12 * 1024 * 1024
BG_MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}


def _bg_state() -> dict:
    try:
        meta = json.loads(BG_META.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"mode": "default", "url": None}
    name = meta.get("file") or ""
    path = UI_DIR / name
    if meta.get("mode") != "custom" or not name or not path.exists():
        return {"mode": "default", "url": None}
    return {"mode": "custom", "url": f"/api/ui/background/image?v={int(path.stat().st_mtime)}"}


@app.get("/api/ui/background")
def api_bg_get():
    return _bg_state()


@app.post("/api/ui/background")
async def api_bg_upload(file: UploadFile):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in BG_MEDIA:
        raise HTTPException(status_code=400, detail="请上传 jpg / png / webp 图片")
    UI_DIR.mkdir(parents=True, exist_ok=True)
    dest = UI_DIR / f"background{ext}"
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > BG_MAX:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="图片超过 12MB")
            fh.write(chunk)
    # a stale image of another extension would otherwise linger and could be
    # served by a later metadata read
    for other in BG_MEDIA:
        p = UI_DIR / f"background{other}"
        if p != dest and p.exists():
            p.unlink(missing_ok=True)
    BG_META.write_text(json.dumps({"mode": "custom", "file": dest.name}),
                       encoding="utf-8")
    return _bg_state()


@app.delete("/api/ui/background")
def api_bg_reset():
    for ext in BG_MEDIA:
        (UI_DIR / f"background{ext}").unlink(missing_ok=True)
    BG_META.unlink(missing_ok=True)
    return {"mode": "default", "url": None}


@app.get("/api/ui/background/image")
def api_bg_image():
    state = _bg_state()
    if not state["url"]:
        raise HTTPException(status_code=404, detail="还没有自定义背景")
    try:
        meta = json.loads(BG_META.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="还没有自定义背景") from None
    path = UI_DIR / (meta.get("file") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="还没有自定义背景")
    media = BG_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, headers=NO_CACHE)


# SPA last, so every /api and /poc route above wins
if (DIST_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="spa")
else:
    @app.get("/__no_dist")
    def _no_dist():  # pragma: no cover - dev only
        return JSONResponse({"detail": "frontend/dist 未构建，请用 dev.cmd 启动"},
                            status_code=503)
