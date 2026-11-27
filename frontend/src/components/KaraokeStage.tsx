import { useEffect, useRef } from "react";
import type { CSSProperties, RefObject } from "react";
import type { Segment, WordTiming } from "../types";
import type { SyncState } from "../hooks/useSyncEngine";
import { useSettings } from "../lib/settings";
import { effectiveWords } from "../lib/words";
import { displayRomaji } from "../lib/romaji";
import { charState } from "../lib/charState";
import { shownText, shownZh } from "../lib/lyricText";
import type { WordHit } from "./WordPopover";
import { RubySurface } from "./RubySurface";
import { LineEditBox } from "./LineEditBox";
import { useLineEditor } from "./LineEditor";

/**
 * 卡拉OK样式,按经典点歌机的三区结构排版:
 *
 *   ① 顶部黑边   —— 整句中文翻译,已唱部分亮色、未唱部分压暗;
 *   ② 中间画面区 —— 当前句歌词压在画面上,已唱的字是主题色,
 *                   未唱的字是白字 + 硬描边,注音与罗马音跟着走;
 *   ③ 底部黑边   —— 下一句预告,统一用白字,作为接句视线落点。
 *
 * 换句规则也照点歌机:当前句唱完才整句切换,不做滚动;翻译跟当前句同步,
 * 下一句只在底部预告位置出现。这样导出成 MV 时,上下黑边就是天然的字幕带。
 *
 * 字形拆分、逐字状态、ruby 分组全部复用默认样式的同一套函数,
 * 所以两种样式的对轴结果永远一致。
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
  showTranslation = true,
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
  color?: "red" | "coral" | "blue" | "green";
  showFurigana?: boolean;
  showRomaji?: boolean;
  /** 顶部字幕带的翻译;默认样式的翻译开关同样作用于这里 */
  showTranslation?: boolean;
  /** 单击歌词查词;导出模式下为 undefined */
  onWordClick?: (hit: WordHit) => void;
  /** 数据集名,用于撤销栈;render 时为 undefined */
  song?: string;
  /** 与默认样式复用同一个编辑语义;render 时为 undefined */
  onPatch?: (segId: number, body: Partial<Segment>) => Segment | undefined;
  onNudgeLine?: (segmentId: number, delta: number) => void;
  onRealignLine?: (segmentId: number) => void;
  canRealign?: boolean;
  /** 右键菜单由外层统一提供(注音 / 罗马音 / 翻译) */
  onContextMenu?: (e: React.MouseEvent) => void;
}) {
  const [settings] = useSettings();
  const activeRef = useRef<HTMLSpanElement | null>(null);
  const pickTimerRef = useRef<number | null>(null);
  const cur = segments[syncState.displayIndex];
  const next = segments[syncState.displayIndex + 1] ?? null;
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

  // 逐字填充:整句共用一个 --p,只让当前字从主题色扫到白色
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
  }, [cur, syncState.activeSegmentId, aw, ak, audioRef, clockRef, offset, lineWords]);

  // 换句时清掉未触发的查词计时器,避免双击进编辑器后仍弹词卡
  useEffect(() => {
    if (pickTimerRef.current) {
      window.clearTimeout(pickTimerRef.current);
      pickTimerRef.current = null;
    }
  }, [cur?.id]);

  if (!cur) return null;

  const pickWord = onWordClick
    ? (word: WordTiming, e: React.MouseEvent) =>
        onWordClick({ word, segment: cur, x: e.clientX, y: e.clientY })
    : undefined;
  const zh = shownZh(cur);
  const nextZh = next ? shownZh(next) : undefined;

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
      {/* ① 顶部黑边:翻译字幕带 */}
      <div className="karaoke-top">
        <div className="karaoke-zh-row" key={`zh-${cur.id}`}>
          <span className="karaoke-zh cur">{showTranslation ? zh ?? "" : ""}</span>
          <span className="karaoke-zh next" aria-hidden={!nextZh}>
            {showTranslation ? nextZh ?? "" : ""}
          </span>
        </div>
      </div>

      {/* ② 中间画面区:当前句歌词压在画面下沿 */}
      <div className="karaoke-screen">
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
              showRomaji={showRomaji}
              settings={settings}
              onPick={pickWord}
              pickTimerRef={pickTimerRef}
            />
          )}
        </div>
      </div>

      {/* ③ 底部黑边:下一句白字预告 */}
      <div className="karaoke-bottom">
        {next && !editing ? (
          <KaraokeLine
            segment={next}
            syncState={syncState}
            words={effectiveWords(next)}
            activeRef={null}
            showFurigana={showFurigana}
            showRomaji={showRomaji}
            settings={settings}
            muted
          />
        ) : (
          <span className="karaoke-bottom-blank" aria-hidden />
        )}
      </div>
    </div>
  );
}

/**
 * 一整句:逐词 ruby 排版,每个字形按高亮状态着色。
 *
 * 当前句的红/主题色字用「白描边 + 红填充」,和点歌机一样在画面上跳出来;
 * 下一句是纯白字,永远不扫色,只作为接句提示。
 */
function KaraokeLine({
  segment,
  syncState,
  words,
  activeRef,
  showFurigana,
  showRomaji,
  settings,
  muted = false,
  onPick,
  pickTimerRef,
}: {
  segment: Segment;
  syncState: SyncState;
  words: ReturnType<typeof effectiveWords>;
  activeRef: RefObject<HTMLSpanElement | null> | null;
  showFurigana: boolean;
  showRomaji: boolean;
  settings: ReturnType<typeof useSettings>[0];
  muted?: boolean;
  onPick?: (word: WordTiming, e: React.MouseEvent) => void;
  pickTimerRef?: RefObject<number | null>;
}) {
  const chars = shownText(segment).replace(/\s/g, "").length || 1;
  return (
    <div
      className={`karaoke-line${muted ? " muted" : ""}`}
      style={{ "--chars": chars } as CSSProperties}
    >
      <div className="karaoke-text-row">
        {words.map((w, i) => (
          <WordRow
            key={i}
            word={w}
            segment={segment}
            wordIndex={i}
            syncState={syncState}
            activeRef={activeRef}
            showFurigana={showFurigana}
            muted={muted}
            onPick={onPick}
            pickTimerRef={pickTimerRef}
          />
        ))}
      </div>
      {showRomaji && (
        <div
          className="karaoke-romaji-row"
          style={{ "--chars": chars } as CSSProperties}
        >
          {words.map((w, i) => (
            <span className="kroma-word" key={`m-${i}`}>
              <RubySurface
                word={w}
                showFurigana={false}
                renderChar={(ch) => <span className="kch ghost">{ch}</span>}
              />
              <span className="kroma">{displayRomaji(w, settings)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
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
        showFurigana={showFurigana && !muted}
        renderChar={(ch, ci) => {
          const st = muted
            ? "upcoming"
            : charState(syncState, segment.id, wordIndex, ci);
          return (
            <span
              key={ci}
              className={`kch ${st}`}
              ref={!muted && st === "active" && activeRef
                ? (el) => {
                    activeRef.current = el;
                  }
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
