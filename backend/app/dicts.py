"""Morphology, dictionary and grammar lookup.

fugashi (UniDic) gives real word units — lemma, part of speech and kana
reading — instead of the hand-split phrases the old build used. Each token is
then enriched with a Chinese gloss from the bundled lightweight dictionary and,
at line level, with any grammar pattern it contains.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"

KANA_ROMAJI = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "o", "ん": "n",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa", "ー": "",
}
YOUS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "てぃ": "ti", "でぃ": "di", "ふぁ": "fa", "ふぃ": "fi",
    "ふぇ": "fe", "ふぉ": "fo", "うぇ": "we", "うぃ": "wi", "ゔ": "vu",
}


def to_romaji(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two in YOUS:
            out.append(YOUS[two])
            i += 2
            continue
        ch = text[i]
        if ch == "っ":
            nxt = text[i + 1:i + 2]
            r = YOUS.get(text[i + 1:i + 3]) or KANA_ROMAJI.get(nxt, "")
            if r:
                out.append(r[0])
            i += 1
            continue
        if ch in KANA_ROMAJI:
            out.append(KANA_ROMAJI[ch])
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s)


@lru_cache(maxsize=1)
def _tagger():
    import fugashi
    return fugashi.Tagger()


@lru_cache(maxsize=1)
def _dict() -> dict:
    return json.loads((DATA / "jadict.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _grammar() -> list[dict]:
    return json.loads((DATA / "grammar.json").read_text(encoding="utf-8"))["patterns"]


POS_MAP = {
    "名詞": "名词", "代名詞": "代词", "動詞": "动词", "形容詞": "形容词",
    "形状詞": "形容动词", "副詞": "副词", "接続詞": "接续词", "連体詞": "连体词",
    "感動詞": "感叹词", "助詞": "助词", "助動詞": "助动词", "接頭辞": "前缀",
    "接尾辞": "后缀", "記号": "标点", "補助記号": "标点", "空白": "空白",
}

PUNCT = set(" \u3000\t、。,.!?！？…「」『』()（）・~〜-—–:;\"'’“”　")


def is_punct(ch: str) -> bool:
    return ch in PUNCT


def mora_count(token: dict) -> int:
    """Sung length estimate for a word: kana in its reading, punctuation free."""
    reading = token.get("kana") or token["surface"]
    return sum(1 for c in reading if not is_punct(c))


def analyze(text: str) -> list[dict]:
    """Tokenise a line into real words with lemma / POS / kana."""
    tagger = _tagger()
    tokens, cursor = [], 0
    for w in tagger(text):
        surface = w.surface
        idx = text.find(surface, cursor)
        if idx < 0:
            idx = cursor
        start, end = idx, idx + len(surface)
        cursor = end
        f = w.feature
        pos1 = getattr(f, "pos1", "") or ""
        pos2 = getattr(f, "pos2", "") or ""
        lemma = getattr(f, "lemma", None) or surface
        # UniDic disambiguates homographs by suffixing the POS: 君-代名詞,
        # 空-名詞. Strip it so the lemma matches a dictionary headword.
        if "-" in lemma:
            head = lemma.split("-", 1)[0]
            if head:
                lemma = head
        kana = kata_to_hira(getattr(f, "kana", None) or "")
        if not surface.strip():
            continue
        tokens.append({
            "surface": surface,
            "lemma": lemma if lemma != "*" else surface,
            "pos": POS_MAP.get(pos1, pos1) + (f"·{pos2}" if pos2 and pos2 != "*" else ""),
            "pos1": pos1,
            "pos2": pos2,
            "kana": kana,
            "start": start,
            "end": end,
        })
    return tokens


def lookup(token: dict) -> dict | None:
    """Dictionary entry for a token: lemma, then reading, then surface."""
    d = _dict()
    for key in (token["lemma"], token["kana"], token["surface"]):
        if key and key in d and not key.startswith("_"):
            return d[key]
    return None


# Grammatical material never becomes a vocabulary card, and looking it up is
# actively harmful once the dictionary is large: the headwords は / に / の also
# exist as 羽 (feather) / 荷 (cargo) / 野 (field), so a homograph-blind lookup
# would gloss the particle as a noun.
GRAMMATICAL_POS = ("助詞", "助動詞", "記号", "補助記号", "空白")


def enrich(tokens: list[dict]) -> list[dict]:
    for t in tokens:
        if t["pos1"] not in GRAMMATICAL_POS:
            entry = lookup(t)
            if entry and _pos_conflict(t, entry):
                # Same spelling, different word class: ほら is an interjection in
                # a lyric but the dictionary headword is 洞 "cave". Showing the
                # noun gloss would be worse than showing nothing.
                entry = None
            if entry:
                # Prefer the gloss that belongs to this part of speech: one
                # headword can span homographs (ただ = 徒 "ordinary" as a noun,
                # 只 "only" as an adverb), and the line tells us which is meant.
                gloss = entry.get("z", "")
                by_pos = entry.get("s") or {}
                want = POS_MAP.get(t["pos1"], "")
                if want and want in by_pos:
                    gloss = by_pos[want]
                t["zh"] = gloss
                t["jlpt"] = entry.get("j", "")
                if entry.get("p"):
                    t["pos"] = entry["p"]
                # the dictionary form's own reading, so a card can headline
                # 逃げる / にげる instead of the inflected 逃げ / にげ
                if entry.get("k"):
                    t["lemma_kana"] = entry["k"]
        t["romaji"] = to_romaji(t["kana"] or t["surface"])
    return tokens


def _pos_conflict(token: dict, entry: dict) -> bool:
    """True when the entry's word class contradicts the token's.

    Only checked for interjections: they are the class most often stolen by a
    same-spelling noun (ほら/洞, おや/親), and a noun gloss on an interjection is
    always wrong. Other classes are handled by the per-POS gloss table.
    """
    if token["pos1"] != "感動詞":
        return False
    have = entry.get("p") or ""
    if have == "感叹词":
        return False
    by_pos = entry.get("s") or {}
    return "感叹词" not in by_pos


LEVEL_SCORE = {"N1": 5, "N2": 4, "N3": 3, "N4": 2, "N5": 1}


def level_score(level: str | None) -> int:
    """Rank a JLPT label so higher levels sort first (N1 strongest)."""
    return LEVEL_SCORE.get((level or "").upper(), 0)


def find_grammar(text: str, tokens: list[dict] | None = None) -> list[dict]:
    """Grammar patterns present in the line, with the matched substring.

    Matching runs on the hiragana-normalised line so a katakana spelling in the
    lyrics (コト, トキ) still hits a pattern written in kana, while `matched`
    slices the original text so the UI can show what was actually written.

    When `tokens` is given, a hit that sits entirely inside a single content
    word is dropped: 「さよなら」 must not report 〜なら, and 「頑張って」 must not
    report 〜て. Particles and auxiliaries are exempt, because those *are* the
    pattern's own material.
    """
    line = kata_to_hira(text)
    hits: list[dict] = []
    for p in _grammar():
        pattern = kata_to_hira(p["match"])
        if "*" not in pattern:
            idx = line.find(pattern)
            if idx < 0:
                continue
            span = (idx, idx + len(pattern))
        else:
            # `しか*ない` → `しか.{0,6}ない`, matched anywhere in the line
            rx = ".{0,6}".join(re.escape(part) for part in pattern.split("*") if part)
            m = re.search(rx, line)
            if not m or len(m.group(0)) < 2:
                continue
            span = m.span()
        if tokens and _inside_content_word(span, tokens):
            continue
        # A hit that begins in the middle of a word is a coincidence of two
        # neighbouring words (きっと + かなう → とか), not a pattern.
        if tokens and not _starts_on_boundary(span, tokens):
            continue
        hits.append({
            **{k: p[k] for k in ("id", "name", "level", "z", "ex")},
            "matched": text[span[0]:span[1]],
            "at": span[0],
        })
    # drop patterns fully contained in a longer hit, then prefer the higher
    # level: the point of the card row is to teach something new, so an N1
    # pattern is worth a slot over an N5 one the learner already knows
    hits.sort(key=lambda h: (-len(h["matched"]), h["at"]))
    kept: list[dict] = []
    for h in hits:
        if any(h["matched"] in o["matched"] for o in kept):
            continue
        kept.append(h)
    kept.sort(key=lambda h: (-level_score(h.get("level")),
                             -len(h["matched"]), h["at"]))
    return kept[:3]


def _starts_on_boundary(span: tuple[int, int], tokens: list[dict]) -> bool:
    """True when the span begins at a token boundary."""
    a = span[0]
    return any(t["start"] == a for t in tokens)


def _inside_content_word(span: tuple[int, int], tokens: list[dict]) -> bool:
    """True when the span lies wholly inside one non-particle token."""
    a, b = span
    for t in tokens:
        if t["start"] <= a and b <= t["end"] and (t["end"] - t["start"]) > (b - a):
            if t["pos1"] in ("助詞", "助動詞", "記号", "補助記号"):
                return False
            return True
    return False


def is_content(token: dict) -> bool:
    """Worth showing as a vocabulary card?

    Grammatical material is excluded: particles, auxiliaries, punctuation, and
    the 形容動詞語幹 of よう/そう, which is the ように pattern rather than the
    noun 様 "appearance".
    """
    if token["pos1"] in ("助詞", "助動詞", "記号", "補助記号", "空白", "接続詞"):
        return False
    if token.get("pos2") in ("助動詞語幹", "非自立可能"):
        return False
    if token["surface"] in ("よう", "そう"):
        # ように / そうだ are patterns, not the nouns 様 / 相
        return False
    return len(token["surface"]) >= 1 and bool(token.get("zh"))
