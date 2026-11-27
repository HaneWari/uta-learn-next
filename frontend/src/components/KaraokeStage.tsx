import { useEffect, useRef } from "react";
import type { CSSProperties, RefObject } from "react";
import type { Segment, WordTiming } from "../types";
import type { SyncState } from "../hooks/useSyncEngine";
import { useSettings } from "../lib/settings";
import { effectiveWords } from "../lib/words";
import type { WordHit } from "./WordPopover";
import { charState } from "../lib/charState";
import { RubySurface } from "./RubySurface";
import { shownRomaji, shownText } from "../lib/lyricText";
import { LineEditBox } from "./LineEditBox";
import { useLineEditor } from "./LineEditor";

/**
 * 卡拉OK样式的字幕板。
 *
 * 参考主流卡拉OK播放器(LDDC / 各家用点歌机)的排版约定:
 *  - 舞台中央是一块深色半透明的字幕板,只有当前句和下一句;
 *  - 唱到的字被主色覆盖(逐字扫过),没唱的字是描边的白色字;
 *  - 注音在汉字上方、罗马音在整句下方,都跟着主色走;
 *  - 句子切换用淡入 + 轻微上移,不做逐行滚动,避免长句抖动。
 *
 * 与默认样式的差别只在排版和配色:字形拆分、逐字状态、ruby 分组全部复用
 * `LyricsDisplay` 里的同一套函数,所以两种样式的对轴结果永远一致。
 */

export function KaraokeStage({
  segments,
  syncState,
  audioRef,
  clockRef,
  offset = 0,
  color = "coral",
  showFurigana = true,
  showRomaji = true,
  onWordClick,
  onPatch,
  song,
  onNudgeLine,
  onRealignLine,
  canRealign = false,
  onContextMenu,
}: {
  segments: Segment[];
  syncState: SyncState;
  audioRef: RefObject<HTMLAudioElement | null>;
  clockRef: RefObject<number>;
  offset?: number;
  color?: "coral" | "blue" | "green";
  showFurigana?: boolean;
  showRomaji?: boolean;
  /** 单击歌词查词;导出模式下为 undefined */
  onWordClick?: (hit: WordHit) => void;
  /** 数据集名,用于撤销栈;render 时为 undefined */
  song?: string;
  /** 与默认样式复用同一个编辑语义;render 时为 undefined */
  onPatch?: (segId: number, body: Partial<Segment>) => Segment | undefined;
  onNudgeLine?: (segmentId: number, delta: number) => void;
  onRealignLine?: (segmentId: number) => void;
  canRealign?: boolean;
  /** 右键菜单由外层统一提供(注音 / 罗马音) */
  onContextMenu?: (e: React.MouseEvent) => void;
}) {
  const [settings] = useSettings();
  const activeRef = useRef<HTMLSpanElement | null>(null);
  const pickTimerRef = useRef<number | null>(null);
  const cur = segments[syncState.displayIndex];
  const next = segments[syncState.displayIndex + 1] ?? null;
  // 提前 1 句滚动的“下一句”只在真的有下一句时占位
  const showNext = !!next && syncState.displayIndex + 1 < segments.length;
  const lineWords = effectiveWords(cur);
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

  // 逐字扫色:和默认样式共用 --p 变量的写法,CSS 决定用主色画到哪里
  const aw = syncState.activeWordIndex;
  const ak = syncState.activeKanaIndex;
  useEffect(() => {
    const el = activeRef.current;
    const audio = audioRef.current;
    if (!cur || aw === null || ak === null) return;
    const ch = effectiveWords(cur)[aw]?.chars?.[ak];
    if (!el || !ch) return;
    let raf = 0;
    const shift = cur.line_offset ?? 0;
    const span = Math.max(0.001, ch.end - ch.start);
    const loop = () => {
      const now = (audio ? audio.currentTime - offset : clockRef.current ?? 0) - shift;
      const p = Math.min(1, Math.max(0, (now - ch.start) / span));
      el.style.setProperty("--p", p.toFixed(3));
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [
    cur,
    syncState.activeSegmentId,
    aw,
    ak,
    audioRef,
    clockRef,
    offset,
    lineWords,
  ]);

  // 换句时清掉未触发的查词计时器,避免双击进编辑器后仍弹词卡
  useEffect(() => {
    if (pickTimerRef.current) {
      window.clearTimeout(pickTimerRef.current);
      pickTimerRef.current = null;
    }
  }, [cur?.id]);

  if (!cur) return null;

  const pickWord =
    onWordClick && cur
      ? (word: WordTiming, e: React.MouseEvent) =>
          onWordClick({ word, segment: cur, x: e.clientX, y: e.clientY })
      : undefined;

  return (
    <div
      className="karaoke-stage"
      data-color={color}
      onContextMenu={onContextMenu}
      onDoubleClick={() => {
        // 编辑框里的双击是选词,不应把正在编辑的草稿重置回原文
        if (!editing) startEdit();
      }}
    >
      <div className="karaoke-board">
        <div className="karaoke-next" aria-hidden={!showNext}>
          {showNext && next ? (
            <>
              <span className="karaoke-next-line">
                <KaraokeLine
                  segment={next}
                  syncState={syncState}
                  words={effectiveWords(next)}
                  activeRef={null}
                  showFurigana={showFurigana}
                  muted
                />
              </span>
              {showRomaji && (
                <span className="karaoke-next-romaji">
                  {shownRomaji(next, settings)}
                </span>
              )}
            </>
          ) : (
            <span className="karaoke-next-line" />
          )}
        </div>

        <div className="karaoke-cur" key={`k-${cur.id}`}>
          {editing ? (
            <LineEditBox
              cur={cur}
              draft={draft}
              setDraft={setDraft}
              onNudgeLine={onNudgeLine}
              onRealign={onRealignLine}
              canRealign={canRealign}
            />
          ) : shownText(cur).trim() === "" ? (
            <span className="karaoke-empty">···</span>
          ) : (
            <KaraokeLine
              segment={cur}
              syncState={syncState}
              words={lineWords}
              activeRef={activeRef}
              showFurigana={showFurigana}
              onPick={pickWord}
              pickTimerRef={pickTimerRef}
            />
          )}
          {!editing && showRomaji && shownText(cur).trim() !== "" && (
            <span className="karaoke-romaji">{shownRomaji(cur, settings)}</span>
          )}
        </div>
      </div>
    </div>
  );
}

/** 一整句:逐词 ruby 排版,渲染的字形仍按字符状态着色。 */
function KaraokeLine({
  segment,
  syncState,
  words,
  activeRef,
  showFurigana,
  muted = false,
  onPick,
  pickTimerRef,
}: {
  segment: Segment;
  syncState: SyncState;
  words: ReturnType<typeof effectiveWords>;
  activeRef: RefObject<HTMLSpanElement | null> | null;
  showFurigana: boolean;
  muted?: boolean;
  onPick?: (word: WordTiming, e: React.MouseEvent) => void;
  pickTimerRef?: RefObject<number | null>;
}) {
  return (
    <span
      className={`karaoke-line${muted ? " muted" : ""}`}
      style={{ "--chars": shownText(segment).replace(/\s/g, "").length || 1 } as CSSProperties}
    >
      {words.map((w, i) => (
        <WordRow
          key={i}
          word={w}
          segment={segment}
          wordIndex={i}
          syncState={syncState}
          activeRef={activeRef}
          showFurigana={showFurigana}
          onPick={onPick}
          pickTimerRef={pickTimerRef}
          muted={muted}
        />
      ))}
    </span>
  );
}

function WordRow({
  word,
  segment,
  wordIndex,
  syncState,
  activeRef,
  showFurigana,
  muted,
  onPick,
  pickTimerRef,
}: {
  word: WordTiming;
  segment: Segment;
  wordIndex: number;
  syncState: SyncState;
  activeRef: RefObject<HTMLSpanElement | null> | null;
  showFurigana: boolean;
  muted?: boolean;
  onPick?: (word: WordTiming, e: React.MouseEvent) => void;
  pickTimerRef?: RefObject<number | null>;
}) {
  const pick = onPick
    ? (e: React.MouseEvent) => {
        e.stopPropagation();
        if (pickTimerRef?.current) window.clearTimeout(pickTimerRef.current);
        const { clientX, clientY } = e;
        const timer = window.setTimeout(() => {
          if (pickTimerRef) pickTimerRef.current = null;
          onPick(word, { clientX, clientY } as React.MouseEvent);
        }, 240);
        if (pickTimerRef) pickTimerRef.current = timer;
      }
    : undefined;

  return (
    <span className={`kword${muted ? " muted" : ""}`} onClick={pick}>
      <RubySurface
        word={word}
        showFurigana={showFurigana}
        renderChar={(ch, ci) => {
          const st = muted
            ? "upcoming"
            : charState(syncState, segment.id, wordIndex, ci);
          return (
            <span
              key={ci}
              className={`kch ${st}`}
              ref={!muted && st === "active" && activeRef
                ? (el) => { activeRef.current = el; }
                : undefined}
            >
              {ch}
            </span>
          );
        }}
      />
    </span>
  );
}
