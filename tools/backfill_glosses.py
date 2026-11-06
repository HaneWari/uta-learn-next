"""Backfill Chinese glosses / JLPT levels into already-built datasets.

Datasets bake `zh` / `jlpt` in at build time, so expanding the dictionary does
not reach songs that already exist. This adds the missing fields in place and
never touches timings, text, or anything else.

Safety: only fills EMPTY glosses, skips grammatical material, and requires a
high-confidence match (see `confident`). Dry-run unless --apply is passed, and a
.bak is written next to each file it changes.
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app import dicts  # noqa: E402

DATA = Path(os.environ.get("UTALEARN_DATA_DIR", ROOT / "localdata"))
DRY = "--apply" not in sys.argv

POS_FAMILY = {
    "名詞": "名词", "代名詞": "代词", "動詞": "动词", "形容詞": "形容词",
    "形状詞": "形容动词", "副詞": "副词", "接続詞": "接续词",
    "連体詞": "连体词", "感動詞": "感叹词", "接頭辞": "前缀",
    "接尾辞": "后缀", "数詞": "数词",
}


def confident(w: dict) -> dict | None:
    """Only accept a gloss we can actually stand behind.

    The dictionary is large enough that a loose lookup starts returning
    homographs: a mis-split 蜃気 (from 蜃気楼) matched a word meaning "new", and
    楼 matched 労働. So require (1) the lemma to be a real headword, (2) the
    reading to agree, and (3) the part of speech to be in the same family.
    """
    d = dicts._dict()
    lemma = w.get("lemma") or w["text"]
    entry = d.get(lemma)
    if not entry or lemma.startswith("_") or not entry.get("z"):
        return None
    reading = w.get("kana") or ""
    if reading and entry.get("k") and reading != entry["k"]:
        return None
    want = POS_FAMILY.get(w.get("pos1", ""))
    have = entry.get("p") or ""
    if want and have and want != have:
        return None
    # same rule as dicts.enrich: the part of speech decides the sense
    by_pos = entry.get("s") or {}
    if want and want in by_pos:
        entry = {**entry, "z": by_pos[want]}
    return entry


def recompute_content(data: dict) -> int:
    """Mark words that sit inside a detected grammar pattern as non-content.

    Only the character offsets can answer this, and the stored word start/end
    are seconds. The words are in reading order and concatenate to the line, so
    walking them rebuilds the offsets. Skipped when they do not line up.
    """
    changed = 0
    for seg in data.get("segments", []):
        text = seg.get("text", "")
        spans = [(g["at"], g["at"] + len(g["matched"]))
                 for g in seg.get("grammar", []) if isinstance(g.get("at"), int)]
        if not spans:
            continue
        pos = 0
        ok = True
        offsets = []
        for w in seg.get("words", []):
            offsets.append((pos, pos + len(w.get("text", ""))))
            pos += len(w.get("text", ""))
        if pos != len(text):
            ok = False
        if not ok:
            continue
        for w, (a, b) in zip(seg.get("words", []), offsets):
            if any(a < y and x < b for x, y in spans) and w.get("content") is not False:
                w["content"] = False
                changed += 1
    return changed


def backfill(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    filled = 0
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            if w.get("zh"):
                continue
            if w.get("pos1", "") in dicts.GRAMMATICAL_POS:
                continue
            entry = confident(w)
            if not entry:
                continue
            w["zh"] = entry["z"]
            if entry.get("j"):
                w["jlpt"] = entry["j"]
            if entry.get("k"):
                w.setdefault("lemma_kana", entry["k"])
            if entry.get("p"):
                w["pos"] = entry["p"]
            w["content"] = True
            filled += 1

    changed = recompute_content(data)

    if (filled or changed) and not DRY:
        shutil.copy2(path, path.with_suffix(".json.bak"))
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return filled, changed


def main() -> int:
    total = 0
    for entry in sorted(DATA.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        f = entry / "song_data.json"
        if not f.exists():
            continue
        filled, changed = backfill(f)
        total += filled
        print(f"{entry.name}: 回填 {filled} 个词，句型内标记 {changed} 个")
    print(f"\n合计 {total} 个词{'（演练模式，加 --apply 写入）' if DRY else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
