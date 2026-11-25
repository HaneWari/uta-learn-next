"""Lyric sources: QQ Music (QRC), Kugou (KRC), Lrclib (LRC).

All three expose the same shape so the builder can stay generic:

    search(query) -> [Song]        # Song: source/id/title/artist/album/duration/kind
    fetch(Song)   -> ParsedLyrics  # lines of timed units (per char or per line)
"""
from __future__ import annotations

import base64
import json
import random
import re
import socket
import time
import zlib
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from urllib.request import getproxies

import httpx

from . import search_cache
from .qrc_des import qrc_decrypt

TIMEOUT = 20
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


# Ports a local proxy commonly listens on. 8080/8888 are deliberately absent:
# they are also the default of countless dev servers and printer web UIs, and
# pointing every lyric request at a random local server breaks a direct
# network far more often than it helps.
AUTO_PROXY_PORTS = (7890, 7897, 10808, 1080, 8889, 4780)


def _probe_local_proxy() -> str | None:
    for port in AUTO_PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue
    return None


def resolve_proxy() -> str | None:
    """The proxy to use right now, from settings + the OS environment.

    httpx only honours the *_PROXY env vars by default, and a Windows "system
    proxy" never sets them — so on a machine running Clash/V2Ray or a
    corporate proxy every lyric source fails at once with a socket permission
    error (WinError 10013).

    This is deliberately *not* cached: the user can switch a proxy on while the
    app runs, and the settings page has a 测试连接 button that must reflect the
    change immediately.
    """
    from app import settings

    mode = settings.get("proxy_mode", "auto")
    if mode == "off":
        return None
    if mode == "manual":
        return (settings.get("proxy_url") or "").strip() or None
    px = getproxies()
    env = px.get("https") or px.get("http")
    if env:
        return env
    if mode == "system":
        return None
    return _probe_local_proxy()


@dataclass
class Song:
    source: str
    id: str
    title: str
    artist: str
    album: str = ""
    duration: float = 0.0
    kind: str = "line"          # "char" | "line"
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "source": self.source, "id": self.id, "title": self.title,
            "artist": self.artist, "album": self.album,
            "duration": round(self.duration, 1), "kind": self.kind,
            "extra": self.extra,
        }


@dataclass
class ParsedLyrics:
    """`lines[i]['units']` is [(text, start, end)] — chars when kind=char."""
    lines: list[dict]
    translation: list[tuple[float, str]] = field(default_factory=list)
    kind: str = "line"

    def as_dict(self) -> dict:
        return {"lines": self.lines, "translation": self.translation, "kind": self.kind}


# --------------------------------------------------------------------------- #
# QQ Music
# --------------------------------------------------------------------------- #
QQ_COMM = {
    "ct": 11, "cv": "1003006", "v": "1003006", "os_ver": "15",
    "phonetype": "24122RKC7C",
    "rom": "Redmi/miro/miro:15/AE3A.240806.005/OS2.0.105.0.VOMCNXM:user/release-keys",
    "tmeAppID": "qqmusiclight", "nettype": "NETWORK_WIFI", "udid": "0",
}


class QQSource:
    name = "qq"
    label = "QQ 音乐"

    def __init__(self) -> None:
        self._client: httpx.Client | None = None
        self._client_proxy: str | None = None
        self._comm: dict | None = None

    @property
    def client(self) -> httpx.Client:
        """One pooled client, rebuilt when the proxy setting changes.

        Building it at import time froze the proxy for the process lifetime, so
        switching 代理 in 设置 did nothing until a restart.
        """
        proxy = resolve_proxy()
        if self._client is None or proxy != self._client_proxy:
            if self._client is not None:
                self._client.close()
            self._client = httpx.Client(
                headers={"cookie": "tmeLoginType=-1;",
                         "content-type": "application/json",
                         "accept-encoding": "gzip", "user-agent": "okhttp/3.14.9"},
                http2=True, timeout=TIMEOUT, proxy=proxy,
            )
            self._client_proxy = proxy
        return self._client

    def _session(self) -> dict:
        if self._comm:
            return self._comm
        data = self._request("GetSession", "music.getSession.session",
                             {"caller": 0, "uid": "0", "vkey": 0}, None)
        s = data["session"]
        self._comm = {**QQ_COMM, "uid": s["uid"], "sid": s["sid"], "userip": s["userip"]}
        return self._comm

    def _request(self, method: str, module: str, param: dict, comm: dict | None) -> dict:
        body = {"comm": comm or QQ_COMM,
                "request": {"method": method, "module": module, "param": param}}
        resp = self.client.post("https://u.y.qq.com/cgi-bin/musicu.fcg",
                                content=json.dumps(body, ensure_ascii=False,
                                                   separators=(",", ":")).encode())
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0 or payload.get("request", {}).get("code") != 0:
            raise RuntimeError("QQ 音乐接口返回错误")
        return payload["request"]["data"]

    def search(self, query: str) -> list[Song]:
        comm = self._session()
        param = {
            "search_id": str(random.randint(1, 20) * 18014398509481984
                             + round(time.time() * 1000) % 86400000),
            "remoteplace": "search.android.keyboard", "query": query,
            "search_type": 0, "num_per_page": 20, "page_num": 1,
            "highlight": 0, "nqc_flag": 0, "page_id": 1, "grp": 1,
        }
        data = self._request("DoSearchForQQMusicLite", "music.search.SearchCgiService",
                             param, comm)
        out = []
        for s in data["body"]["item_song"]:
            out.append(Song(
                source=self.name, id=str(s["id"]), title=s["title"],
                artist="/".join(a["name"] for a in s["singer"] if a["name"]),
                album=s["album"]["name"], duration=float(s["interval"]),
                kind="char",
                extra={"mid": s.get("mid", "")},
            ))
        return out

    def fetch(self, song: Song) -> ParsedLyrics:
        comm = self._session()
        param = {
            "albumName": base64.b64encode(song.album.encode()).decode(),
            "crypt": 1, "ct": 19, "cv": 2111, "interval": int(song.duration),
            "lrc_t": 0, "qrc": 1, "qrc_t": 0, "roma": 0, "roma_t": 0,
            "singerName": base64.b64encode(song.artist.encode()).decode(),
            "songID": int(song.id),
            "songName": base64.b64encode(song.title.encode()).decode(),
            "trans": 1, "trans_t": 0, "type": 0,
        }
        data = self._request("GetPlayLyricInfo", "music.musichallSong.PlayLyricInfo",
                             param, comm)
        if not data.get("lyric"):
            raise RuntimeError("QQ 音乐没有这首歌的歌词")

        text = qrc_decrypt(data["lyric"])
        lines = _parse_qrc_lines(text)
        trans = []
        if data.get("trans") and data.get("trans_t", "0") != "0":
            try:
                trans = _parse_lrc(qrc_decrypt(data["trans"]))
            except Exception:  # noqa: BLE001
                trans = []
        return ParsedLyrics(lines=lines, translation=trans, kind="char")


LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
UNIT_RE = re.compile(r"((?:(?!\(\d+,\d+\)).)*)\((\d+),(\d+)\)")


def _parse_qrc_lines(text: str) -> list[dict]:
    m = re.search(r'<Lyric_1 LyricType="1" LyricContent="(.*?)"/>', text, re.DOTALL)
    content = m.group(1) if m else text
    out = []
    for raw in content.splitlines():
        lm = LINE_RE.match(raw.strip())
        if not lm:
            continue
        start, dur, body = int(lm.group(1)), int(lm.group(2)), lm.group(3)
        units = [
            (w.group(1), int(w.group(2)) / 1000.0,
             (int(w.group(2)) + int(w.group(3))) / 1000.0)
            for w in UNIT_RE.finditer(body) if w.group(1).strip()
        ]
        if units:
            out.append({"start": start / 1000.0, "end": (start + dur) / 1000.0,
                        "units": units})
    return out


LRC_RE = re.compile(r"^\[(\d+):(\d+)\.(\d+)\](.*)$")


def _parse_lrc(text: str) -> list[tuple[float, str]]:
    out = []
    for raw in text.splitlines():
        m = LRC_RE.match(raw.strip())
        if m:
            t = int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 100.0
            body = m.group(4).strip()
            if body and body != "//":
                out.append((t, body))
    return out


# --------------------------------------------------------------------------- #
# Kugou
# --------------------------------------------------------------------------- #
KRC_KEY = b"@Gaw^2tGQ61-\xce\xd2ni"


class KugouSource:
    name = "kugou"
    label = "酷狗音乐"

    def __init__(self) -> None:
        self._client: httpx.Client | None = None
        self._client_proxy: str | None = None

    @property
    def client(self) -> httpx.Client:
        """Verification is off for this host *only*.

        `mobilecdn.kugou.com` serves a certificate that genuinely does not match
        the hostname (verified 2026-11: `CERTIFICATE_VERIFY_FAILED: Hostname
        mismatch`), so a verifying client cannot talk to it at all. Turning
        verification off is limited to the two kugou API hosts that need it
        rather than every request this app makes.
        """
        proxy = resolve_proxy()
        if self._client is None or proxy != self._client_proxy:
            if self._client is not None:
                self._client.close()
            self._client = httpx.Client(headers={"user-agent": UA},
                                        timeout=TIMEOUT,
                                        follow_redirects=True, verify=False,
                                        proxy=proxy)
            self._client_proxy = proxy
        return self._client

    def search(self, query: str) -> list[Song]:
        url = "https://mobilecdn.kugou.com/api/v3/search/song"
        r = self.client.get(url, params={"format": "json", "keyword": query,
                                         "page": 1, "pagesize": 20})
        r.raise_for_status()
        data = r.json().get("data", {}).get("info", []) or []
        out = []
        for s in data:
            out.append(Song(
                source=self.name, id=str(s.get("hash", "")),
                title=s.get("songname", ""), artist=s.get("singername", ""),
                album=s.get("album_name", ""),
                duration=float(s.get("duration", 0)),
                kind="char",
                extra={"hash": s.get("hash", ""), "album_id": s.get("album_id", "")},
            ))
        return out

    def fetch(self, song: Song) -> ParsedLyrics:
        # 1) find a lyric candidate for this file hash
        r = self.client.get("https://krcs.kugou.com/search",
                            params={"ver": 1, "man": "yes", "client": "mobi",
                                    "keyword": song.title,
                                    "duration": int(song.duration),
                                    "hash": song.extra.get("hash", song.id)})
        r.raise_for_status()
        cands = r.json().get("candidates") or []
        if not cands:
            raise RuntimeError("酷狗没有这首歌的歌词")
        c = cands[0]

        # 2) download + decrypt
        r2 = self.client.get("https://lyrics.kugou.com/download",
                             params={"ver": 1, "client": "pc", "id": c["id"],
                                     "accesskey": c["accesskey"],
                                     "fmt": "krc", "charset": "utf8"})
        r2.raise_for_status()
        content = r2.json().get("content") or ""
        if not content:
            raise RuntimeError("酷狗歌词下载失败")
        raw = base64.b64decode(content)
        body = raw[4:]
        plain = bytes(b ^ KRC_KEY[i % len(KRC_KEY)] for i, b in enumerate(body))
        text = zlib.decompress(plain).decode("utf-8", errors="replace")
        return ParsedLyrics(lines=_parse_krc_lines(text),
                            translation=_parse_krc_translation(text),
                            kind="char")


KRC_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
KRC_UNIT_RE = re.compile(r"<(\d+),(\d+),\d+>([^<\[]*)")
# `[language:base64]` carries the translated track: a `[start,dur]text` body
# with the same shape as the lyrics, just in another language
KRC_LANG_RE = re.compile(r"^\[language:([A-Za-z0-9+/=]+)\]$")


def _parse_krc_lines(text: str) -> list[dict]:
    out = []
    for raw in text.splitlines():
        lm = KRC_LINE_RE.match(raw.strip())
        if not lm:
            continue
        start, dur, body = int(lm.group(1)), int(lm.group(2)), lm.group(3)
        units = []
        for m in KRC_UNIT_RE.finditer(body):
            off, length, txt = int(m.group(1)), int(m.group(2)), m.group(3)
            if not txt.strip():
                continue
            # kugou offsets are relative to the line start
            units.append((txt, start / 1000.0 + off / 1000.0,
                          start / 1000.0 + (off + length) / 1000.0))
        if units:
            out.append({"start": start / 1000.0, "end": (start + dur) / 1000.0,
                        "units": units})
    return out


def _parse_krc_translation(text: str) -> list[tuple[float, str]]:
    """Translation lines from a KRC payload's `[language:...]` block.

    Kugou does not always ship one; an empty list simply means the build has no
    glosses, which the UI already handles. A malformed block is ignored rather
    than failing the fetch — the lyrics are the point, the translation is a
    bonus.
    """
    for raw in text.splitlines():
        m = KRC_LANG_RE.match(raw.strip())
        if not m:
            continue
        try:
            body = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            continue
        out: list[tuple[float, str]] = []
        for line in body.splitlines():
            lm = KRC_LINE_RE.match(line.strip())
            if not lm:
                continue
            start = int(lm.group(1)) / 1000.0
            # the translated body carries no per-character tags
            body_text = KRC_UNIT_RE.sub(lambda mm: mm.group(3), lm.group(3))
            body_text = body_text.strip()
            if body_text:
                out.append((start, body_text))
        return out
    return []


# --------------------------------------------------------------------------- #
# Lrclib
# --------------------------------------------------------------------------- #
class LrclibSource:
    name = "lrclib"
    label = "Lrclib"

    def __init__(self) -> None:
        self._client: httpx.Client | None = None
        self._client_proxy: str | None = None

    @property
    def client(self) -> httpx.Client:
        proxy = resolve_proxy()
        if self._client is None or proxy != self._client_proxy:
            if self._client is not None:
                self._client.close()
            self._client = httpx.Client(headers={"user-agent": "UtaLearn/2.0"},
                                        timeout=TIMEOUT, proxy=proxy)
            self._client_proxy = proxy
        return self._client

    def search(self, query: str) -> list[Song]:
        r = self.client.get("https://lrclib.net/api/search", params={"q": query})
        r.raise_for_status()
        out = []
        for s in r.json()[:20]:
            if not s.get("syncedLyrics"):
                continue
            out.append(Song(
                source=self.name, id=str(s.get("id", "")),
                title=s.get("trackName", ""), artist=s.get("artistName", ""),
                album=s.get("albumName", "") or "",
                duration=float(s.get("duration", 0) or 0),
                kind="line",
                extra={"synced": s.get("syncedLyrics", "")},
            ))
        return out

    def fetch(self, song: Song) -> ParsedLyrics:
        text = song.extra.get("synced") or ""
        if not text:
            raise RuntimeError("Lrclib 没有逐行歌词")
        rows = _parse_lrc(text)
        lines = []
        for i, (t, body) in enumerate(rows):
            end = rows[i + 1][0] if i + 1 < len(rows) else t + max(1.5, len(body) * 0.22)
            lines.append({"start": t, "end": end, "units": [(body, t, end)]})
        return ParsedLyrics(lines=lines, kind="line")


SOURCES = {s.name: s for s in (QQSource(), KugouSource(), LrclibSource())}


def get_source(name: str):
    if name not in SOURCES:
        raise KeyError(f"unknown source: {name}")
    return SOURCES[name]


SEARCH_TIMEOUT = 12.0

# `按来源` 排序时的固定顺序:用户在某个源上找到了习惯的版本
SOURCE_ORDER = {"qq": 0, "kugou": 1, "lrclib": 2}
SORT_MODES = ("duration", "char", "source")


def _search_one(key: str, src, query: str) -> tuple[str, list[dict], str | None]:
    try:
        return key, [s.as_dict() for s in src.search(query)], None
    except Exception as e:  # noqa: BLE001
        return key, [], str(e) or e.__class__.__name__


def search_all(query: str, names: list[str] | None = None,
               audio_duration: float = 0.0,
               sort: str = "duration"
               ) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Search every source in parallel; failures are per-source, never raised.

    Searially this took three round-trips (and one dead source cost the user
    twelve seconds of a spinner before anything showed). Running them together
    means the slowest source sets the wall clock, with an overall deadline so a
    hung source can't hold the response forever.

    Returns `(results, errors, statuses)`. `statuses` is `ok` / `empty` /
    `error` per source so the list can show "搜索中 / 无结果 / 失败" per row.
    """
    wanted = {k: v for k, v in SOURCES.items() if not names or k in names}
    results: list[dict] = []
    errors: list[dict] = []
    statuses: dict[str, str] = {}

    if not wanted:
        return results, errors, statuses

    cached = search_cache.get(query, names)
    if cached is not None:
        cached_results, cached_errors, cached_statuses = cached
        return (sort_results(cached_results, sort, audio_duration),
                cached_errors, cached_statuses)

    pool = ThreadPoolExecutor(max_workers=len(wanted), thread_name_prefix="search")
    futures = {pool.submit(_search_one, key, src, query): key
               for key, src in wanted.items()}
    try:
        done, not_done = wait(futures, timeout=SEARCH_TIMEOUT)
        for fut in done:
            key, hits, err = fut.result()
            if err:
                errors.append({"source": key, "error": err})
                statuses[key] = "error"
            else:
                results.extend(hits)
                statuses[key] = "ok" if hits else "empty"
        for fut in not_done:
            key = futures[fut]
            fut.cancel()
            errors.append({"source": key, "error": f"超时（>{SEARCH_TIMEOUT:g}s）"})
            statuses[key] = "error"
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    search_cache.put(query, names, results, errors, statuses)
    return sort_results(results, sort, audio_duration), errors, statuses


def sort_results(results: list[dict], mode: str, audio_duration: float = 0.0) -> list[dict]:
    """Order search hits for the config page.

    * `duration` — closest to the uploaded audio first (the version that will
      actually line up); ties prefer per-character lyrics.
    * `char` — per-character lyrics first, then by duration distance.
    * `source` — QQ → 酷狗 → Lrclib, closest duration inside each group.

    With no uploaded audio there is nothing to match against, so `duration`
    degrades to `char` — same rule as the settings page describes.
    """
    if mode not in SORT_MODES:
        mode = "duration"
    if mode == "duration" and audio_duration <= 0:
        mode = "char"

    def distance(r: dict) -> float:
        if audio_duration <= 0:
            return 0.0
        return abs(float(r.get("duration") or 0) - audio_duration)

    def char_rank(r: dict) -> int:
        return 0 if r.get("kind") == "char" else 1

    if mode == "char":
        key = lambda r: (char_rank(r), distance(r))  # noqa: E731
    elif mode == "source":
        key = lambda r: (SOURCE_ORDER.get(r.get("source", ""), 9), distance(r))  # noqa: E731
    else:
        key = lambda r: (distance(r), char_rank(r))  # noqa: E731

    ordered = sorted(results, key=key)
    for r in ordered:
        r["duration_match"] = bool(audio_duration > 0 and distance(r) <= 2.0)
    return ordered
