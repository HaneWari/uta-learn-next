import { useEffect, useRef } from "react";
import type { CSSProperties, RefObject } from "react";
import type { Segment, WordTiming } from "../types";
import type { SyncState } from "../hooks/useSyncEngine";
import { displayRomaji } from "../lib/romaji";
import { useSettings } from "../lib/settings";
import { effectiveWords } from "../lib/words";
import { shownRomaji, shownText, shownZh } from "../lib/lyricText";
import { charState } from "../lib/charState";
import type { WordHit } from "./WordPopover";
import { LineEditBox } from "./LineEditBox";
import { useLineEditor } from "./LineEditor";
import { RubySurface } from "./RubySurface";

interface LyricsDisplayProps {
  segments: Segment[];
  syncState: SyncState;
  audioRef: RefObject<HTMLAudioElement | null>;
  /** timeline position when the dataset has no audio element */
  clockRef: RefObject<number>;
  /** song-wide lyric delay against the audio, in seconds */
  offset?: number;
  /** stage edits: save a corrected line or hide it (disabled in render mode) */
  onPatch?: (segId: number, body: Partial<Segment>) => Segment | undefined;
  /** hide the Chinese gloss; the dataset flag is the default, the URL wins */
  transHidden?: boolean;
  /** click a word to look it up (disabled in render mode) */
  onWordClick?: (hit: WordHit) => void;
  /** dataset name, used to scope the undo stack per song */
  song?: string;
  /** per-song display layers (furigana / romaji / next line) */
  layers?: { showFurigana?: boolean; showRomaji?: boolean; showNext?: boolean };
  /** 5.3.3: move this line ±0.1 s against the audio (global offset stays) */
  onNudgeLine?: (segmentId: number, delta: number) => void;
  /** 5.3.3: re-align only this line (needs the whisper pack) */
  onRealign?: (segmentId: number) => void;
  /** false when the custom-lyrics pack is missing; the button greys out */
  canRealign?: boolean;
  /** 点击歌词行空白处跳到这一行开头播放 (§5.2.2) */
  onSeekLine?: (segment: Segment) => void;
}

interface WordViewProps {
  word: WordTiming;
  segmentId: number;
  wordIndex: number;
  syncState: SyncState;
  activeRef: RefObject<HTMLSpanElement | null>;
  romaji: string;
  showFurigana?: boolean;
  showRomaji?: boolean;
  /** null in export mode: the recorder must render, not interact */
  onPick?: (word: WordTiming, e: React.MouseEvent) => void;
  /** the pending lookup timer, so a dblclick can cancel it outright */
  pickTimerRef?: RefObject<number | null>;
}

function WordView({
  word,
  segmentId,
  wordIndex,
  syncState,
  activeRef,
  romaji,
  showFurigana = true,
  showRomaji = true,
  onPick,
  pickTimerRef,
}: WordViewProps) {
  const pick = onPick
    ? (e: React.MouseEvent) => {
        // a click on a glyph is a lookup; a double click is the line editor.
        // The browser fires `click` before `dblclick`, and the first click's
        // timer can expire before `dblclick` arrives. Cancelling it from the
        // dblclick handler (`startEdit`) is the only reliable order — a
        // "was a dblclick seen?" flag was set too late and also swallowed the
        // *next* legitimate single click.
        e.stopPropagation();
        const { clientX, clientY } = e;
        if (pickTimerRef?.current) window.clearTimeout(pickTimerRef.current);
        const timer = window.setTimeout(() => {
          if (pickTimerRef) pickTimerRef.current = null;
          onPick(word, { clientX, clientY } as React.MouseEvent);
        }, 220);
        if (pickTimerRef) pickTimerRef.current = timer;
      }
    : undefined;
  return (
    <span className="wordbox" onClick={pick}>
      <RubySurface
        word={word}
        showFurigana={showFurigana}
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
      {showRomaji && (
        <span
          className={`romaji${
            syncState.activeSegmentId === segmentId &&
            syncState.activeWordIndex === wordIndex
              ? " hot"
              : ""
          }`}
        >
          {romaji}
        </span>
      )}
    </span>
  );
}

/** The upcoming line: same ruby treatment, no timing state. */
function NextLine({ segment, showFurigana = true }: { segment: Segment; showFurigana?: boolean }) {
  // an edited line previews its *override* words, not the stale source tokens —
  // otherwise the upcoming lyric still shows the text the user just corrected
  const words = effectiveWords(segment);
  return (
    <span className="next-line">
      {words.map((w, i) => (
        <span className="wordbox" key={i}>
          <RubySurface word={w} showFurigana={showFurigana} renderChar={(ch, ci) => (
            <span className="ch" key={ci}>{ch}</span>
          )} />
        </span>
      ))}
    </span>
  );
}

export function LyricsDisplay({ segments, syncState, audioRef, clockRef, offset = 0, onPatch, transHidden = false, onWordClick, song, layers, onNudgeLine, onRealign, canRealign = false, onSeekLine }: LyricsDisplayProps) {
  const [settings] = useSettings();
  // the three presentation layers are per-song switches in `meta.view`;
  // the shell passes them down so a change is visible without a reload
  const { showFurigana = true, showRomaji = true, showNext = true } =
    layers ?? {};
  const activeRef = useRef<HTMLSpanElement | null>(null);
  const cur = segments[syncState.displayIndex];
  const next = segments[syncState.displayIndex + 1] ?? null;
  // one word list for both the render and the highlight index
  const lineWords = effectiveWords(cur);
  /* ---- lyric editing: double-click to fix the line, right-click to hide it.
     Only the sung text and its Chinese gloss are editable — romaji and the
     word timings come from alignment and are left alone. ---- */
  // a dblclick always starts with a click; the pending lookup is cancelled
  // here so entering the editor never flashes a word card
  const pickTimerRef = useRef<number | null>(null);
  const { editing, draft, setDraft, startEdit } = useLineEditor({
    cur,
    song,
    onPatch,
    beforeStart: () => {
      if (pickTimerRef.current) {
        window.clearTimeout(pickTimerRef.current);
        pickTimerRef.current = null;
      }
    },
  });

  // drive the fill of the single active glyph, nothing else re-renders
  useEffect(() => {
    const el = activeRef.current;
    const audio = audioRef.current;
    const aw = syncState.activeWordIndex;
    const ak = syncState.activeKanaIndex;
    if (!el || !cur || aw === null || ak === null) return;

    const ch = effectiveWords(cur)[aw]?.chars?.[ak];
    if (!ch) return;

    let raf = 0;
    // 逐行微调 shifts the whole line on the timeline (useSyncEngine adds it to
    // every kana), so the fill has to compare against the same shifted clock.
    // Without this the wipe finished in one frame — "高亮变成瞬发".
    const shift = cur.line_offset ?? 0;
    const span = Math.max(0.001, ch.end - ch.start);
    const loop = () => {
      // no audio element (lyrics-only dataset): follow the synthetic clock
      const now = (audio ? audio.currentTime - offset : clockRef.current ?? 0) - shift;
      const p = Math.min(1, Math.max(0, (now - ch.start) / span));
      el.style.setProperty("--p", p.toFixed(3));
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [cur, syncState.activeSegmentId, syncState.activeWordIndex, syncState.activeKanaIndex, audioRef, clockRef, offset]);

  if (!cur) return null;

  return (
    <div
      className="stage"
    >
      {/* the 下一句 layer is a per-song switch; hiding it also stops the row
          from reserving vertical space, so the current line can breathe */}
      <div className={`next-block${next && showNext ? "" : " blank"}`}>
        <span className="next-label">{next && showNext ? "next" : ""}</span>
        {next && showNext ? (
          <div className="next-body" key={`n-${next.id}`}>
            {next.words.length ? (
              <NextLine segment={next} showFurigana={showFurigana} />
            ) : (
              <span className="next-line">{shownText(next)}</span>
            )}
            {showRomaji && (
              <span className="next-romaji">{shownRomaji(next, settings)}</span>
            )}
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
        onClick={(e) => {
          // a click that did not land on a word means "jump to this line";
          // a word has its own handler and stops propagation
          if (editing) return;
          if ((e.target as HTMLElement).closest(".wordbox")) return;
          onSeekLine?.(cur);
        }}
      >
        {editing ? (
          <LineEditBox
            cur={cur}
            draft={draft}
            setDraft={setDraft}
            onNudgeLine={onNudgeLine}
            onRealign={onRealign}
            canRealign={canRealign}
          />
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
                {lineWords.length ? (
                  // an edited line carries its re-tokenised words: furigana,
                  // romaji and a re-estimated wipe, not the stale alignment
                  lineWords.map((w, i) => (
                    <WordView
                      key={i}
                      word={w}
                      segmentId={cur.id}
                      wordIndex={i}
                      syncState={syncState}
                      activeRef={activeRef}
                      romaji={displayRomaji(w, settings)}
                      showFurigana={showFurigana}
                      showRomaji={showRomaji}
                      pickTimerRef={pickTimerRef}
                      onPick={
                        onWordClick && cur
                          ? (word, e) =>
                              onWordClick({
                                word,
                                segment: cur,
                                x: e.clientX,
                                y: e.clientY,
                              })
                          : undefined
                      }
                    />
                  ))
                ) : cur.lyric_override?.text != null ? (
                  // override exists but no words were rebuilt (very short or
                  // unanalysable text) — show it verbatim, still clickable
                  <span className="cur-line-text">{shownText(cur)}</span>
                ) : null}
              </div>
            )}
            {shownZh(cur) && !transHidden && <div className="zh-line">{shownZh(cur)}</div>}
          </>
        )}
      </div>
    </div>
  );
}
