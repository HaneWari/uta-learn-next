"""Dataset CRUD: list, read, delete and the stage's PATCH edits."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app import jobs, packs, realign, repo, vocab
from app.builder import retime_words
from app.datasets import dataset, find_audio, list_datasets
from app.dicts import analyze, enrich, find_grammar, parse_reading_marks
from app.paths import DATA_DIR, NO_CACHE
from app.schemas import VocabItem
from app.version import APP_VERSION

router = APIRouter()


@router.get("/api/songs")
def api_songs():
    return list_datasets()


@router.get("/api/songs/{name}")
def api_song(name: str):
    path = dataset(name) / "song_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")
    try:
        data = repo.read(path)
    except repo.SchemaTooNew as err:
        raise HTTPException(
            status_code=409,
            detail=f"这首歌由更新版本保存（schema {err.found}），请升级后再打开",
        ) from None
    return JSONResponse(data, headers=NO_CACHE)


@router.delete("/api/songs/{name}")
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
    # 5.3.3 逐行微调: this line's own offset against the audio, on top of the
    # song-wide `meta.time_offset`
    "line_offset",
}
LINE_OFFSET_MAX = 2.0

# Song-wide settings that sit in `meta` rather than on a segment. The offset
# shifts the whole lyric timeline against the audio (positive = lyrics later);
# it lives in the dataset so the export recorder, which reloads song_data.json,
# plays with the same correction the user tuned by ear.
# Song-wide view state. v1 kept these in two places (localStorage for the card
# row, meta for the gloss), so copying a dataset to another machine — or opening
# it in the pywebview window — lost one of them. `view` is the single copy now.
_VIEW_KEYS = {"cards", "translation", "furigana", "romaji", "next_line"}
_META_KEYS = {"time_offset", "trans_hidden", "view"}
TIME_OFFSET_MAX = 2.0


def _expected_revision(request: Request) -> int | None:
    """`If-Match: <revision>` → the revision the editor started from."""
    raw = request.headers.get("if-match")
    if not raw:
        return None
    try:
        return int(raw.strip().strip('"'))
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="If-Match 必须是整数 revision") from None


def _save_song(path: Path, mutate, expected: int | None) -> dict:
    """repo.update + the HTTP mapping for its two failure modes."""
    try:
        return repo.update(path, mutate, expected, APP_VERSION)
    except repo.RevisionConflict as err:
        raise HTTPException(
            status_code=409,
            detail=f"这首歌已在其他窗口修改（revision {err.current}），请刷新后重试",
        ) from None
    except repo.SchemaTooNew as err:
        raise HTTPException(
            status_code=409,
            detail=f"这首歌由更新版本保存（schema {err.found}），请升级后再编辑",
        ) from None


@router.patch("/api/songs/{name}")
def api_patch_song(name: str, patch: dict, request: Request):
    """Persist card edits made on the stage.

    The payload is a partial `Segment` — only `vocab_override` and
    `grammar_extra` are writable through this route; everything else (text,
    timings, grammar) is derived data and stays authoritative.

    A payload without `id` carrying only song-wide keys (`time_offset`) updates
    `meta` instead.
    """
    # A PATCH is a partial Segment with a caller-chosen key set, so it stays a
    # plain dict: the writable-key check below is stricter than any model would
    # be, and it produces the Chinese 只读字段 message the UI shows verbatim.
    if "id" not in patch and patch and set(patch.keys()) <= _META_KEYS:
        return _patch_meta(name, patch, request)
    bad = set(patch.keys()) - _WRITABLE_KEYS
    if bad:
        raise HTTPException(status_code=400, detail=f"只读字段: {sorted(bad)}")
    if "id" not in patch:
        raise HTTPException(status_code=400, detail="缺少 segment id")

    path = dataset(name) / "song_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")
    updated: dict = {}

    def mutate(data: dict) -> None:
        for seg in data.get("segments", []):
            if seg.get("id") != patch["id"]:
                continue
            for key in _WRITABLE_KEYS - {"id"}:
                if key in patch:
                    if key == "line_offset" and patch[key] is not None:
                        try:
                            value = round(float(patch[key]), 1)
                        except (TypeError, ValueError):
                            raise HTTPException(
                                status_code=400,
                                detail="本行偏移必须是数字") from None
                        if not -LINE_OFFSET_MAX <= value <= LINE_OFFSET_MAX:
                            raise HTTPException(
                                status_code=400,
                                detail=f"本行偏移须在 -{LINE_OFFSET_MAX:g} 到 "
                                       f"{LINE_OFFSET_MAX:g} 秒之间")
                        if value == 0:
                            seg.pop("line_offset", None)
                        else:
                            seg["line_offset"] = value
                        continue
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
            updated.update(seg)
            return
        raise HTTPException(status_code=404, detail="segment not found")

    _save_song(path, mutate, _expected_revision(request))
    return updated


def _patch_meta(name: str, patch: dict, request: Request) -> dict:
    path = dataset(name) / "song_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")
    result: dict = {}

    def mutate(data: dict) -> None:
        meta = data.setdefault("meta", {})
        if "time_offset" in patch:
            raw = patch["time_offset"]
            try:
                value = round(float(raw if raw is not None else 0.0), 1)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400,
                                    detail="时间偏移必须是数字") from None
            if not -TIME_OFFSET_MAX <= value <= TIME_OFFSET_MAX:
                raise HTTPException(status_code=400,
                                    detail="时间偏移须在 -2 到 2 秒之间")
            if value == 0:
                meta.pop("time_offset", None)
            else:
                meta["time_offset"] = value
        if "trans_hidden" in patch:
            if patch["trans_hidden"]:
                meta["trans_hidden"] = True
            else:
                meta.pop("trans_hidden", None)
        if "view" in patch:
            raw = patch["view"]
            if raw is None:
                meta.pop("view", None)
            elif isinstance(raw, dict):
                view = meta.setdefault("view", {})
                for key, value in raw.items():
                    if key not in _VIEW_KEYS:
                        continue
                    # a visible layer is the default, so only store the "off"
                    if value:
                        view.pop(key, None)
                    else:
                        view[key] = False
                if not view:
                    meta.pop("view", None)
            else:
                raise HTTPException(status_code=400, detail="view 必须是对象")
        result["time_offset"] = meta.get("time_offset", 0.0)
        result["trans_hidden"] = bool(meta.get("trans_hidden"))
        result["view"] = meta.get("view", {})
        result["revision"] = meta.get("revision", 0) + 1

    _save_song(path, mutate, _expected_revision(request))
    return result


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


@router.get("/api/vocab")
def api_vocab_list(song: str | None = None):
    """The personal word book, newest first; `song` narrows it to one dataset."""
    return {"items": vocab.list_all(song), "counts": vocab.count_by_song()}


@router.post("/api/vocab")
def api_vocab_add(item: VocabItem):
    try:
        return vocab.add(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/api/vocab/{song}/{segment_id}")
def api_vocab_delete(song: str, segment_id: int, text: str = ""):
    if not text:
        raise HTTPException(status_code=400, detail="缺少单词")
    if not vocab.remove(song, segment_id, text):
        raise HTTPException(status_code=404, detail="生词本里没有这一条")
    return {"deleted": True}


@router.delete("/api/vocab")
def api_vocab_clear(song: str | None = None):
    return {"removed": vocab.clear(song)}


@router.post("/api/songs/{name}/realign/{segment_id}")
def api_realign_line(name: str, segment_id: int):
    """Re-run alignment for one line against ±5 s of its own audio (5.3.3).

    Only the line's own word timings change; the transcript, the overrides and
    every other segment are untouched. Needs the custom-lyrics pack — without
    it the caller gets a 409 with the install hint the config page already uses.
    """
    if not packs.whisper_installed():
        raise HTTPException(
            status_code=409,
            detail="单行重新对齐需要自定义歌词扩展包,请先在自定义歌词页安装",
        )
    folder = dataset(name)
    audio = find_audio(folder)
    if audio is None:
        raise HTTPException(status_code=400, detail="这个数据集没有音频")
    path = folder / "song_data.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="song_data.json missing")

    data = repo.read(path)
    seg = next((s for s in data.get("segments", []) if s.get("id") == segment_id), None)
    if seg is None:
        raise HTTPException(status_code=404, detail="segment not found")
    # an edited line is what the user is looking at, so align that text
    text = (seg.get("lyric_override") or {}).get("text") or seg.get("text") or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="这一行没有文字,无法重新对齐")

    jid = jobs.create("realign", "cpu")

    def work(progress):
        progress(0.1, "准备音频窗口…")
        result = realign.realign_line(audio, text, seg["start"], seg["end"],
                                      progress)

        def mutate(current: dict) -> None:
            target = next(
                (s for s in current.get("segments", []) if s.get("id") == segment_id),
                None)
            if target is None:
                raise HTTPException(status_code=404, detail="segment not found")
            words = target.get("lyric_override", {}).get("words") or target.get("words") or []
            chars = result["chars"]
            # hand the new glyph times back to the words in order: every word
            # owns the run of characters it renders
            cursor = 0
            for word in words:
                length = len(word.get("text") or "")
                word["chars"] = chars[cursor:cursor + length]
                cursor += length
                if cursor >= len(chars):
                    break
            target["aligned_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        _save_song(path, mutate, None)
        progress(0.99, "完成")
        return {"segment_id": segment_id, **result}

    jobs.run(jid, work)
    return {"job_id": jid}
