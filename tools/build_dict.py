"""Build the bundled JA->ZH dictionary from the Tomoshi open data layer.

Source: tomoshi-dict-open.db (CC BY-SA 4.0), derived from JMdict/KANJIDIC2
(EDRDG) plus Tomoshi's Chinese translations.

Output shape is the one `app/dicts.py` already expects:
    {"lemma": {"k": kana, "p": pos_zh, "j": "N4", "z": "中文释义"}, ...}

Hand-written entries in the existing file are kept and win over generated ones,
because they were reviewed against actual lyrics.
"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The source database is not committed (620 MB). See tools/README.md.
DB = Path(os.environ.get("UTALEARN_TOMOSHI_DB", ROOT / "tools/_source/tomoshi-dict-open.db"))
OUT = ROOT / "backend/app/data/jadict.json"
# Read the reviewed entries from the pristine snapshot, never from OUT: OUT is
# overwritten by every run, so reading it would treat generated entries as
# hand-written and make the build non-reproducible.
HAND = Path(__file__).resolve().parent / "jadict.hand.json"

# JMdict reports part of speech as long English names ("adjective (keiyoushi)",
# "Godan verb with 'ru' ending"), so match on substrings in this order rather
# than trying to enumerate all 52 spellings. Order matters: "adjectival nouns"
# must be tested before "adjective", and "adverb" before "noun".
POS_RULES = [
    ("auxiliary", "助动词"),
    ("copula", "助动词"),
    ("adjectival nouns", "形容动词"),
    ("'taru' adjective", "形容动词"),
    ("adjective", "形容词"),
    ("pre-noun adjectival", "连体词"),
    ("adverb", "副词"),
    ("expressions", "惯用"),
    ("conjunction", "接续词"),
    ("interjection", "感叹词"),
    ("pronoun", "代词"),
    ("particle", "助词"),
    ("counter", "量词"),
    ("numeric", "数词"),
    ("prefix", "前缀"),
    ("suffix", "后缀"),
    ("verb", "动词"),
    ("noun", "名词"),
]

# A gloss longer than this stops being a card and becomes a paragraph.
MAX_GLOSS = 30
MAX_GLOSSES = 2


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def pick_pos(senses: list[dict]) -> str:
    tags = [t for s in senses for t in (s.get("pos") or [])]
    for needle, label in POS_RULES:
        if any(needle in t for t in tags):
            return label
    return ""


def pick_gloss(senses: list[dict]) -> str:
    """The first couple of distinct Chinese senses, for a one-line card.

    A single JMdict gloss often packs several senses behind `；`, and different
    senses repeat each other (さよなら → "再见", "告别", "告别；结束"), so split on
    the separator and dedupe across senses before taking the first two.
    """
    parts: list[str] = []
    for s in senses:
        for g in s.get("glosses") or []:
            if g.get("lang") != "zho":
                continue
            text = clean(g.get("text", ""))
            text = re.sub(r"^\d+[.)]\s*", "", text)
            for piece in re.split(r"[；;]", text):
                piece = piece.strip(" 、，,。")
                if piece and piece not in parts:
                    parts.append(piece)
            if len(parts) >= MAX_GLOSSES:
                break
        if len(parts) >= MAX_GLOSSES:
            break
    joined = "；".join(parts[:MAX_GLOSSES])
    if len(joined) > MAX_GLOSS:
        joined = joined[:MAX_GLOSS].rstrip("；、 ") + "…"
    return joined


def main() -> int:
    if not DB.exists():
        print(f"缺少源数据库：{DB}\n"
              f"下载方式见 tools/README.md，或用 UTALEARN_TOMOSHI_DB 指定路径。",
              file=sys.stderr)
        return 2
    existing = json.loads(HAND.read_text(encoding="utf-8"))
    note = existing.get("_note", "")
    hand = {k: v for k, v in existing.items() if not k.startswith("_")}
    print(f"hand-written entries kept: {len(hand)}")

    db = sqlite3.connect(DB)
    jlpt = dict(db.execute("SELECT entry_id, level FROM vocab_jlpt"))
    rank = dict(db.execute("SELECT entry_id, rank FROM freq_rank"))

    built: dict[str, dict] = {}
    stats = {"common": 0, "jlpt": 0, "skipped": 0}

    # Every JLPT word, plus the most frequent common words. Taking all 30k
    # common entries ballooned the file to 8MB / 68k keys for a lot of words a
    # lyric is unlikely to use; this keeps the useful coverage at a third of it.
    TOP_RANK = 12000
    rows = db.execute(
        "SELECT id, is_common, data FROM entries WHERE is_common = 1"
    )
    for eid, is_common, data in rows:
        if eid not in jlpt and rank.get(eid, 10**9) > TOP_RANK:
            continue
        e = json.loads(data)
        senses = e.get("senses") or []
        gloss = pick_gloss(senses)
        if not gloss:
            stats["skipped"] += 1
            continue
        kanji = [k["text"] for k in (e.get("kanji") or []) if k.get("text")]
        kana = [k["text"] for k in (e.get("kana") or []) if k.get("text")]
        if not kana and not kanji:
            stats["skipped"] += 1
            continue
        head = kanji[0] if kanji else kana[0]
        # A headword with no kanji is its own reading; don't repeat it.
        reading = kana[0] if kana else ""
        level = jlpt.get(eid, "")
        if is_common:
            stats["common"] += 1
        if level:
            stats["jlpt"] += 1
        entry = {
            "k": reading,
            "p": pick_pos(senses),
            "j": level,
            "z": gloss,
        }
        if rank.get(eid):
            entry["r"] = rank[eid]
        # Keep one gloss per part of speech too. A single JMdict entry can span
        # homographs (ただ = 徒 "ordinary" / 只 "only" / 但 "however"), and which
        # one applies depends on how the word is used in the line -- only the
        # caller knows that, so `enrich` picks from here.
        by_pos: dict[str, str] = {}
        for sn in senses:
            label = pick_pos([sn])
            g = pick_gloss([sn])
            if label and g and label not in by_pos:
                by_pos[label] = g
        if len(by_pos) > 1:
            entry["s"] = by_pos
        # every written form becomes a key, so an inflected surface still hits
        for form in kanji + kana:
            if form and form not in built:
                built[form] = entry

    merged = dict(built)
    merged.update(hand)          # reviewed entries win
    out = {"_note": note or "轻量日汉词典", **merged}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True),
                   encoding="utf-8")

    size = OUT.stat().st_size
    print(f"generated keys: {len(built)}  common {stats['common']}  "
          f"jlpt {stats['jlpt']}  skipped {stats['skipped']}")
    print(f"final entries: {len(merged)}  file {size/1048576:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
