import { useEffect, useRef } from "react";
import type { CSSProperties, RefObject } from "react";
import type { Segment, WordTiming } from "../types";
import type { SyncState } from "../hooks/useSyncEngine";
import { rubyGroups } from "../furigana";

interface LyricsDisplayProps {
  segments: Segment[];
  syncState: SyncState;
  audioRef: RefObject<HTMLAudioElement | null>;
  /** timeline position when the dataset has no audio element */
  clockRef: RefObject<number>;
}

/**
 * Highlight unit is the character, not the word — the same model LDDC uses
 * (`LyricsWord(start, end, text)`): every glyph has its own start/end, so the
 * wipe advances glyph by glyph and follows held notes exactly.
 */
type CharState = "sung" | "active" | "upcoming";

function charState(
  syncState: SyncState,
  segmentId: number,
  wordIndex: number,
  charIndex: number,
): CharState {
  if (
    syncState.activeSegmentId === segmentId &&
    syncState.activeWordIndex === wordIndex &&
    syncState.activeKanaIndex === charIndex
  ) {
    return "active";
  }
  // anything already finished stays lit, so the line never flickers back
  if (syncState.sungSegmentId === segmentId && syncState.sungWordIndex !== null) {
    const sw = syncState.sungWordIndex;
    const sc = syncState.sungKanaIndex ?? -1;
    if (wordIndex < sw) return "sung";
    if (wordIndex === sw && charIndex <= sc) return "sung";
  }
  return "upcoming";
}

/** Furigana sits above a kanji run only; kana runs reserve the same height. */
function RubySurface({
  word,
  renderChar,
}: {
  word: WordTiming;
  renderChar: (ch: string, index: number) => React.ReactNode;
}) {
  let index = -1;
  return (
    <span className="surface">
      {rubyGroups(word).map((group, gi) => {
        const start = index + 1;
        index += group.chars.length;
        return (
          <span className="ruby-group" key={gi}>
            <span className={`furi${group.reading ? "" : " blank"}`}>
              {group.reading ?? ""}
            </span>
            <span className="ruby-chars">
              {group.chars.map((c, k) => renderChar(c.ch, start + k))}
            </span>
          </span>
        );
      })}
    </span>
  );
}

interface WordViewProps {
  word: WordTiming;
  segmentId: number;
  wordIndex: number;
  syncState: SyncState;
  activeRef: RefObject<HTMLSpanElement | null>;
}

function WordView({ word, segmentId, wordIndex, syncState, activeRef }: WordViewProps) {
  return (
    <span className="wordbox">
      <RubySurface
        word={word}
        renderChar={(ch, ci) => {
          const st = charState(syncState, segmentId, wordIndex, ci);
          return (
            <span
              key={ci}
              className={`ch ${st}`}
              ref={st === "active" ? (el) => { activeRef.current = el; } : undefined}
            >
              {ch}
            </span>
          );
        }}
      />
      <span
        className={`romaji${
          syncState.activeSegmentId === segmentId &&
          syncState.activeWordIndex === wordIndex
            ? " hot"
            : ""
        }`}
      >
        {word.romaji}
      </span>
    </span>
  );
}

/** The upcoming line: same ruby treatment, no timing state. */
function NextLine({ segment }: { segment: Segment }) {
  return (
    <span className="next-line">
      {segment.words.map((w, i) => (
        <span className="wordbox" key={i}>
          <RubySurface word={w} renderChar={(ch, ci) => (
            <span className="ch" key={ci}>{ch}</span>
          )} />
        </span>
      ))}
    </span>
  );
}

export function LyricsDisplay({ segments, syncState, audioRef, clockRef }: LyricsDisplayProps) {
  const activeRef = useRef<HTMLSpanElement | null>(null);
  const cur = segments[syncState.displayIndex];
  const next = segments[syncState.displayIndex + 1] ?? null;

  // drive the fill of the single active glyph, nothing else re-renders
  useEffect(() => {
    const el = activeRef.current;
    const audio = audioRef.current;
    const aw = syncState.activeWordIndex;
    const ak = syncState.activeKanaIndex;
    if (!el || !cur || aw === null || ak === null) return;

    const ch = cur.words[aw]?.chars?.[ak];
    if (!ch) return;

    let raf = 0;
    const span = Math.max(0.001, ch.end - ch.start);
    const loop = () => {
      // no audio element (lyrics-only dataset): follow the synthetic clock
      const now = audio ? audio.currentTime : clockRef.current ?? 0;
      const p = Math.min(1, Math.max(0, (now - ch.start) / span));
      el.style.setProperty("--p", p.toFixed(3));
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [cur, syncState.activeSegmentId, syncState.activeWordIndex, syncState.activeKanaIndex, audioRef, clockRef]);

  if (!cur) return null;

  return (
    <div className="stage">
      <div className={`next-block${next ? "" : " blank"}`}>
        <span className="next-label">{next ? "next" : ""}</span>
        {next ? (
          <div className="next-body" key={`n-${next.id}`}>
            {next.words.length ? (
              <NextLine segment={next} />
            ) : (
              <span className="next-line">{next.text}</span>
            )}
            <span className="next-romaji">{next.romaji}</span>
          </div>
        ) : (
          <div className="next-body" />
        )}
      </div>

      <div
        className="cur-block"
        key={`c-${cur.id}`}
        style={{
          "--chars": cur.text.replace(/\s/g, "").length || 1,
        } as CSSProperties}
      >
        <div className="cur-line">
          {cur.words.map((w, i) => (
            <WordView
              key={i}
              word={w}
              segmentId={cur.id}
              wordIndex={i}
              syncState={syncState}
              activeRef={activeRef}
            />
          ))}
        </div>
        {cur.translation_zh && <div className="zh-line">{cur.translation_zh}</div>}
      </div>
    </div>
  );
}
