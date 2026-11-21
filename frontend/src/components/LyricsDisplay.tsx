import { useEffect, useRef, useState } from "react";
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
  /** stage edits: save a corrected line or hide it (disabled in render mode) */
  onPatch?: (segId: number, body: Partial<Segment>) => Segment | undefined;
}

/** The text the listener actually sees: the override wins over the aligned
    original, and an emptied override hides the line's text without deleting
    the underlying words. */
function shownText(seg: Segment): string {
  return seg.lyric_override?.text ?? seg.text ?? "";
}

function shownZh(seg: Segment): string | undefined {
  return seg.lyric_override?.translation_zh ?? seg.translation_zh;
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

export function LyricsDisplay({ segments, syncState, audioRef, clockRef, onPatch }: LyricsDisplayProps) {
  const activeRef = useRef<HTMLSpanElement | null>(null);
  const cur = segments[syncState.displayIndex];
  const next = segments[syncState.displayIndex + 1] ?? null;

  /* ---- lyric editing: double-click to fix the line, right-click to hide it.
     Only the sung text and its Chinese gloss are editable — romaji and the
     word timings come from alignment and are left alone. ---- */
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ text: "", zh: "" });

  // a new line scrolls in — drop any half-finished edit so it can't leak
  // onto the next segment
  useEffect(() => {
    setEditing(false);
  }, [cur?.id]);

  function startEdit() {
    if (!cur || !onPatch) return;
    setDraft({ text: shownText(cur), zh: shownZh(cur) ?? "" });
    setEditing(true);
  }

  // Enter commits from anywhere while editing — not just when a field is
  // focused — and a click on empty space saves too. Esc cancels.
  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commitEdit();
      }
      if (e.key === "Escape") setEditing(false);
    };
    const onDown = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest(".lyr-edit")) return;
      commitEdit();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, draft, cur]);

  function commitEdit() {
    if (cur && onPatch) {
      const newText = draft.text.trim();
      const newZh = draft.zh.trim();
      // Only a real text change rewrites `lyric_override.text`: entering edit
      // mode and leaving, or touching just the translation, must keep the
      // per-glyph wipe (it still matches the words). A changed text is what
      // drops the highlight onto the verbatim line.
      const textChanged = newText !== (cur.lyric_override?.text ?? cur.text);
      const prevZh = cur.lyric_override?.translation_zh;
      const zhChanged = newZh !== (prevZh ?? cur.translation_zh ?? "");
      onPatch(cur.id, {
        // an emptied line still plays on its timing — it just shows nothing
        lyric_override: {
          // keep the old override text when it wasn't edited, and never
          // introduce `text` on a translation-only edit
          text: textChanged ? newText : cur.lyric_override?.text,
          translation_zh: zhChanged ? newZh : prevZh,
        },
      });
    }
    setEditing(false);
  }

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
              <span className="next-line">{shownText(next)}</span>
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
          "--chars": shownText(cur).replace(/\s/g, "").length || 1,
        } as CSSProperties}
        onDoubleClick={startEdit}
      >
        {editing ? (
          <div className="lyr-edit">
            <input
              className="lyr-edit-text"
              value={draft.text}
              placeholder="日文歌词"
              autoFocus
              onChange={(e) => setDraft({ ...draft, text: e.target.value })}
            />
            <input
              className="lyr-edit-zh"
              value={draft.zh}
              placeholder="中文翻译（可留空）"
              onChange={(e) => setDraft({ ...draft, zh: e.target.value })}
            />
            <span className="lyr-edit-hint">回车或点击空白保存 · Esc 取消</span>
          </div>
        ) : (
          <>
            {/* a cleared lyric keeps its timing but shows no text or wipe */}
            {shownText(cur).trim() === "" ? (
              // empty by the listener's own edit — keep a faint, still
              // double-clickable placeholder so the line can be brought back
              onPatch && (
                <span className="cur-line-empty" title="双击恢复歌词">
                  ···
                </span>
              )
            ) : (
              <div className="cur-line">
                {cur.lyric_override?.text != null ? (
                  // a hand-edited line no longer matches the word timings —
                  // show the corrected text verbatim instead of the stale
                  // per-glyph wipe
                  <span className="cur-line-text">{shownText(cur)}</span>
                ) : (
                  cur.words.map((w, i) => (
                    <WordView
                      key={i}
                      word={w}
                      segmentId={cur.id}
                      wordIndex={i}
                      syncState={syncState}
                      activeRef={activeRef}
                    />
                  ))
                )}
              </div>
            )}
            {shownZh(cur) && <div className="zh-line">{shownZh(cur)}</div>}
          </>
        )}
      </div>
    </div>
  );
}
