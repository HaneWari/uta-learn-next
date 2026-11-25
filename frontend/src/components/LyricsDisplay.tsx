import { useEffect, useRef, useState } from "react";
import type { CSSProperties, RefObject } from "react";
import type { AppSettings, Segment, WordTiming } from "../types";
import type { SyncState } from "../hooks/useSyncEngine";
import { rubyGroups } from "../furigana";
import { displayRomaji, lineRomaji } from "../lib/romaji";
import { useSettings } from "../lib/settings";
import { effectiveWords } from "../lib/words";
import { pushUndo } from "../lib/saveQueue";
import type { WordHit } from "./WordPopover";

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

/** The text the listener actually sees: the override wins over the aligned
    original, and an emptied override hides the line's text without deleting
    the underlying words. Reading marks `[汉字](よみ)` are markup, never sung —
    strip them for display / char counting (full-width brackets too). */
const READING_MARK = /[【[](?:[^】\]]+)[】\]]\s*[（(][^（）()]*[)）]/g;
function stripMarks(text: string): string {
  return text.replace(READING_MARK, "$1");
}

function shownText(seg: Segment): string {
  return stripMarks(seg.lyric_override?.text ?? seg.text ?? "");
}

function shownZh(seg: Segment): string | undefined {
  return seg.lyric_override?.translation_zh ?? seg.translation_zh;
}

/** The romaji under an upcoming/edited line: rebuilt override words win, so a
    custom reading the user typed shows up in next too. */
function shownRomaji(
  seg: Segment,
  settings: Pick<AppSettings, "particle_reading" | "long_vowel">,
): string {
  const ov = seg.lyric_override?.words;
  if (ov?.length) return lineRomaji(ov, settings);
  return lineRomaji(seg.words, settings) || seg.romaji;
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
  showFurigana = true,
}: {
  word: WordTiming;
  renderChar: (ch: string, index: number) => React.ReactNode;
  /** the 注音 layer can be switched off per song; the glyphs stay put */
  showFurigana?: boolean;
}) {
  // The glyph offset of each ruby group, computed without a mutable counter —
  // the compiler rejects a variable reassigned during render because children
  // callbacks are deferred. Groups are tiny, so the quadratic prefix sum is
  // irrelevant next to the clarity of staying immutable.
  const groups = rubyGroups(word);
  const offsets = groups.map((_, i) =>
    groups.slice(0, i).reduce((n, g) => n + g.chars.length, 0),
  );
  return (
    <span className={`surface${showFurigana ? "" : " no-furi"}`}>
      {groups.map((group, gi) => (
        <span className="ruby-group" key={gi}>
          <span className={`furi${group.reading && showFurigana ? "" : " blank"}`}>
            {group.reading ?? ""}
          </span>
          <span className="ruby-chars">
            {group.chars.map((c, k) => renderChar(c.ch, offsets[gi] + k))}
          </span>
        </span>
      ))}
    </span>
  );
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
}: WordViewProps) {
  const pick = onPick
    ? (e: React.MouseEvent) => {
        // a click on a glyph is a lookup; a double click is still the line
        // editor, so stop the first click from also seeking
        e.stopPropagation();
        onPick(word, e);
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
      // snapshot the line before the write so Ctrl+Z can restore it; the
      // re-tokenised `words` are derived by the PATCH route, so restoring the
      // override (or its absence) is enough
      if (textChanged || zhChanged) {
        pushUndo({
          song: song ?? "",
          label: textChanged ? "歌词编辑" : "翻译编辑",
          segmentId: cur.id,
          restore: { lyric_override: cur.lyric_override ?? null },
        });
      }
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
      const now = audio ? audio.currentTime - offset : clockRef.current ?? 0;
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
        <span className="next-label">{next ? "next" : ""}</span>
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
            <span className="lyr-edit-hint">
              回车或点击空白保存 · Esc 取消 · 改读音写作 <code>[汉字](读音)</code>
              ，如 <code>[明日](あす)</code>，假名/片假名/罗马音均可
            </span>

            <div className="lyr-tools">
              <span className="lyr-tool-label">本行时间</span>
              <button
                type="button"
                className="lyr-nudge"
                onClick={() => onNudgeLine?.(cur.id, -0.1)}
                title="这一行整体提前 0.1 秒"
              >
                -0.1s
              </button>
              <span className="lyr-offset">
                {(cur.line_offset ?? 0) > 0 ? "+" : ""}
                {(cur.line_offset ?? 0).toFixed(1)}s
              </span>
              <button
                type="button"
                className="lyr-nudge"
                onClick={() => onNudgeLine?.(cur.id, 0.1)}
                title="这一行整体延后 0.1 秒"
              >
                +0.1s
              </button>
              <button
                type="button"
                className="lyr-realign"
                onClick={() => onRealign?.(cur.id)}
                disabled={!canRealign}
                title={
                  canRealign
                    ? "只对这条前后 5 秒重新识别并对齐"
                    : "需要自定义歌词扩展包(whisper)"
                }
              >
                重新对齐本行
              </button>
            </div>
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
