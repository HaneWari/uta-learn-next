"""配置页 API:歌词源搜索、音频上传、按歌词源或自填歌词生成数据集。"""
from __future__ import annotations

import base64
import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app import fallback, jobs, local_lyrics
from app import translate as translate_mod
from app.builder import build as build_song
from app.datasets import (
    free_name as _free_name,
)
from app.datasets import (
    mmss as _mmss,
)
from app.datasets import (
    save_dataset as _save_dataset,
)
from app.datasets import (
    upload_path as _upload_path,
)
from app.paths import AUDIO_EXT, MAX_UPLOAD, UPLOAD_DIR
from app.schemas import (
    BuildLocalRequest,
    BuildRequest,
    BuildTextRequest,
    SearchRequest,
)
from app.sources import SOURCES, Song, get_source, search_all

router = APIRouter()
LYRICS_DIR = UPLOAD_DIR.parent / "_lyrics"


@router.get("/api/sources")
def api_sources():
    return [{"name": s.name, "label": s.label} for s in SOURCES.values()]


@router.post("/api/search")
async def api_search(payload: SearchRequest):
    query = (payload.query or "").strip()
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="请输入至少 2 个字符")
    names = payload.sources or None
    try:
        audio_duration = float(payload.duration or 0)
    except (TypeError, ValueError):
        audio_duration = 0.0
    results, errors, statuses = await run_in_threadpool(
        search_all, query, names, audio_duration)
    return {"results": results, "errors": errors, "statuses": statuses}


@router.post("/api/uploads")
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


@router.post("/api/build")
async def api_build(payload: BuildRequest):
    """Build a dataset from a lyric source, optionally against the user's audio.

    With no audio the source's own timestamps are authoritative (QQ/Kugou give
    per-character times). With audio, the source only supplies the *lyric text*
    and the timeline is estimated from that audio — otherwise a user whose file
    is a different edit (a TV-size cut, a live take) would get a dataset that is
    uniformly offset by the difference between the two recordings.
    """
    song = _song_from_payload(payload.song or {})
    upload_id = payload.upload_id
    title = (payload.title or song.title).strip()
    artist = (payload.artist or song.artist).strip()
    name = _free_name(f"{title} {artist}".strip())
    audio = _upload_path(upload_id) if upload_id else None
    label = get_source(song.source).label

    jid = jobs.create("build", "cpu")

    def work(progress):
        progress(0.08, f"从 {label} 取歌词…")
        parsed = get_source(song.source).fetch(song)
        if not parsed.lines:
            raise RuntimeError("这个来源没有可用的歌词")

        # A file whose length matches the source almost certainly *is* that
        # recording, and then the source's per-character timestamps beat any
        # estimate. Only re-align when the lengths disagree — that means a
        # different edit (TV size, live take, own cut).
        #
        # Manual version matching: the source's own per-character timeline is
        # authoritative, but a different edit (TV-size cut, a trimmed intro,
        # a live take) makes it disagree with the uploaded file. Rather than
        # auto-aligning (a whisper pass over a whole song just to learn an
        # offset), the user supplies the cut point for whichever side is
        # longer. `lyric_start` says where in the *source* timeline the audio
        # begins (source longer, intro skipped); `audio_start` says where in
        # the *audio* the lyric timeline begins (audio longer, instrumental
        # intro). Seconds are "m:ss" strings straight from the config page.
        lyric_start = _mmss(payload.lyric_start)
        audio_start = _mmss(payload.audio_start)

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


@router.post("/api/build-text")
async def api_build_text(payload: BuildTextRequest):
    """Estimate timing from an uploaded audio + the user's own lyric text."""
    upload_id = (payload.upload_id or "").strip()
    text = payload.lyrics or ""
    if not upload_id:
        raise HTTPException(status_code=400, detail="请先上传音频")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise HTTPException(status_code=400, detail="请粘贴歌词，每行一句（至少 2 行）")
    audio = _upload_path(upload_id)
    title = (payload.title or audio.stem).strip()
    artist = (payload.artist or "").strip()
    name = _free_name(f"{title} {artist}".strip())

    jid = jobs.create("custom", "cpu")

    def work(progress):
        data = fallback.build_from_audio(audio, lines, {
            "title": title, "artist": artist,
            "youtube_url": "", "language": "ja",
            "whisperx_model": "",
            "align_model": "whisper 切片转写 + 假名全局对齐 + 逐字锚定",
            "vocal_separation": "none",
            "source": "本地上传 + whisper",
            "source_kind": "estimated",
        }, progress=progress)
        # translation is part of the build job, not a separate step: it only
        # runs when the user asked for it, after the timing is already solved,
        # so a missing translate pack never wastes a whisper pass
        if payload.translate:
            progress(0.93, f"翻译 {len(data['segments'])} 行…")
            try:
                zh = translate_mod.translate_lines(
                    [s["text"] for s in data["segments"]])
                for seg, line in zip(data["segments"], zh, strict=False):
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


@router.post("/api/uploads/lyrics")
async def api_upload_lyrics(file: UploadFile):
    """解析一个本地歌词文件,先给前端看预览再决定是否生成。

    这里只做解析和校验,不写数据集:用户可能选错文件,先让他看一眼行数、
    是否逐字,再决定要不要花几分钟建库。
    """
    name = file.filename or "lyrics"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件是空的")
    try:
        parsed = local_lyrics.parse(name, data)
    except local_lyrics.UnsupportedLyrics as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    units = sum(len(line.get("units") or []) for line in parsed.lines)
    return {
        "filename": name,
        "kind": parsed.kind,
        "lines": len(parsed.lines),
        "units": units,
        "translation": len(parsed.translation),
        "preview": [
            {"start": round(line["start"], 2), "end": round(line["end"], 2),
             "text": "".join(u[0] for u in line.get("units") or [])}
            for line in parsed.lines[:8]
        ],
        "token": _stage_lyrics(data, name),
    }


def _stage_lyrics(data: bytes, name: str) -> str:
    """暂存上传的歌词;生成时凭 token 取回,不信任客户端重传。"""
    token = uuid.uuid4().hex[:12]
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    (LYRICS_DIR / f"{token}.json").write_text(
        json.dumps({"name": name, "b64": base64.b64encode(data).decode()}),
        encoding="utf-8")
    return token


def _load_staged_lyrics(token: str) -> tuple[str, bytes]:
    if not re.fullmatch(r"[0-9a-f]{12}", token or ""):
        raise HTTPException(status_code=400, detail="bad lyrics token")
    path = LYRICS_DIR / f"{token}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="歌词文件已过期,请重新上传")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("name") or "lyrics", base64.b64decode(raw["b64"])


@router.post("/api/build-local")
async def api_build_local(payload: BuildLocalRequest):
    """用本地歌词文件 + 已上传的音频生成数据集(5.3.2)。"""
    token = (payload.lyrics_token or "").strip()
    upload_id = (payload.upload_id or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="请先选择歌词文件")
    if not upload_id:
        raise HTTPException(status_code=400, detail="请先上传音频")
    name_in, data = _load_staged_lyrics(token)
    try:
        parsed = local_lyrics.parse(name_in, data)
    except local_lyrics.UnsupportedLyrics as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    audio = _upload_path(upload_id)
    title = (payload.title or audio.stem).strip()
    artist = (payload.artist or "").strip()
    out_name = _free_name(f"{title} {artist}".strip())
    jid = jobs.create("custom", "cpu")

    def work(progress):
        progress(0.15, f"读取 {name_in} …")
        data_out = build_song(parsed, {
            "title": title, "artist": artist,
            "youtube_url": "", "language": "ja",
            "whisperx_model": "none",
            "align_model": f"本地歌词文件({name_in})",
            "vocal_separation": "none",
            "source": "本地歌词文件",
            "source_kind": parsed.kind,
        })
        if not data_out["segments"]:
            raise RuntimeError("歌词解析后为空")
        progress(0.7, "写入数据集…")
        _save_dataset(out_name, data_out, audio)
        return {"name": out_name, "title": title, "artist": artist,
                "segments": len(data_out["segments"]),
                "duration": data_out["meta"]["duration_seconds"],
                "has_audio": True}

    jobs.run(jid, work)
    return {"job_id": jid, "name": out_name}


@router.get("/api/jobs")
def api_jobs(active: bool = False):
    """All remembered jobs (this run + the last one), oldest first."""
    return jobs.list_jobs(active_only=active)


@router.get("/api/jobs/{jid}")
def api_job(jid: str):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return job


@router.post("/api/jobs/{jid}/cancel")
def api_job_cancel(jid: str):
    """Ask a running job to stop at its next cancellation point."""
    if not jobs.get(jid):
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if not jobs.cancel(jid):
        return {"canceled": False, "detail": "任务已经结束"}
    return {"canceled": True}


@router.get("/api/jobs/{jid}/events")
def api_job_events(jid: str):
    """Server-sent events: one `job` frame per state change, then a close.

    The client can fall back to polling if EventSource is unavailable — both
    paths read the same snapshot, so they can never disagree.
    """
    if not jobs.get(jid):
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    def frames():
        for item in jobs.events(jid):
            data = json.dumps(item["data"], ensure_ascii=False)
            yield f"event: {item['event']}\ndata: {data}\n\n"

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
