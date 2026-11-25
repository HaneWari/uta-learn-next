import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Segment, WordTiming } from "../types";

/**
 * Click-a-word lookup: reading, dictionary form, POS, JLPT and gloss — all of
 * which the dataset already carries, so no network call is needed to show it.
 *
 * The popover is a single document-level layer rather than a per-word one:
 * lyrics are rendered a glyph at a time, and attaching state to every glyph
 * made the whole line re-render on hover.
 */
export interface WordHit {
  word: WordTiming;
  segment: Segment;
  /** where to anchor, in viewport coordinates */
  x: number;
  y: number;
}

export function WordPopover({
  hit,
  song,
  songTitle,
  onClose,
  onSeek,
}: {
  hit: WordHit;
  song: string;
  songTitle: string;
  onClose: () => void;
  /** jump to the line this word came from */
  onSeek: () => void;
}) {
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const { word, segment } = hit;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [onClose]);

  async function addToBook() {
    setErr(null);
    try {
      await api.addVocab({
        song,
        song_title: songTitle,
        segment_id: segment.id,
        text: word.text,
        kana: word.kana ?? "",
        romaji: word.romaji,
        pos: word.pos ?? "",
        jlpt: word.jlpt ?? "",
        zh: word.zh ?? "",
        line: segment.text,
        at: segment.start,
      });
      setSaved(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  // keep the card on screen when the word is near an edge
  const left = Math.min(Math.max(12, hit.x - 130), window.innerWidth - 292);
  const top = Math.min(hit.y + 14, window.innerHeight - 240);

  return (
    <div
      ref={ref}
      className="wordpop"
      style={{ left, top }}
      role="dialog"
      aria-label={`${word.text} 的词条`}
    >
      <header className="wordpop-head">
        <span className="wordpop-word">{word.lemma ?? word.text}</span>
        {word.kana && word.kana !== (word.lemma ?? word.text) && (
          <span className="wordpop-kana">{word.kana}</span>
        )}
        {word.jlpt && <span className="wordpop-tag">{word.jlpt}</span>}
      </header>
      {word.romaji && <span className="wordpop-romaji">{word.romaji}</span>}
      <div className="wordpop-body">
        {word.pos && <span className="wordpop-pos">{word.pos}</span>}
        <span className="wordpop-zh">{word.zh || "（这个词没有释义）"}</span>
      </div>
      {word.lemma && word.lemma !== word.text && (
        <p className="wordpop-used">歌中形：{word.text}</p>
      )}
      {err && <p className="wordpop-err">{err}</p>}
      <footer className="wordpop-foot">
        <button className="btn" onClick={onSeek} type="button">
          从这句播放
        </button>
        <button
          className="btn primary"
          onClick={() => void addToBook()}
          type="button"
          disabled={saved}
        >
          {saved ? "已加入生词本" : "加入生词本"}
        </button>
      </footer>
    </div>
  );
}
