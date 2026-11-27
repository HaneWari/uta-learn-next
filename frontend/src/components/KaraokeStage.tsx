import { useEffect, useMemo, useRef } from "react";
import type { CSSProperties, RefObject } from "react";
import type { Segment, WordTiming } from "../types";
import type { SyncState } from "../hooks/useSyncEngine";
import { useSettings } from "../lib/settings";
import { effectiveWords } from "../lib/words";
import { displayRomaji } from "../lib/romaji";
import { shownText, shownZh } from "../lib/lyricText";
import { buildLine, sweepAt } from "../lib/karaokeSweep";
import type { SweepGlyph, SweepWord } from "../lib/karaokeSweep";
import { karaokePalette } from "../lib/karaokeStyle";
import type { KaraokePalette } from "../lib/karaokeStyle";
import type { WordHit } from "./WordPopover";
import { RubySurface } from "./RubySurface";
import { LineEditBox } from "./LineEditBox";
import { useLineEditor } from "./LineEditor";

/**
 * 卡拉OK样式,按经典点歌机的三区结构排版:
 *
 *   1 顶部黑边   —— 整句中文翻译,当前句用主题色、下一句用白色;
 *   2 中间画面区 —— 当前句压在画面上,整行只有一条向右推进的扫字锋面;
 *   3 底部黑边   —— 下一句预告,作为接句视线落点。
 *
 * 参考 karaoke-studio 的 `wipe.py` / `scanline.py`:
 * - 已唱层不是逐字变色,而是用锋面横坐标裁出「从左到当前」的一整条带;
 * - 字与字之间、词与词之间由锋面平滑穿过,不会一格一格跳;
 * - 锋面上再叠一条只在字形内可见的羽化高光带。
 */

const FONT_STACKS: Record<KaraokePalette["font"], string> = {
  gothic:
    '"Hiragino Kaku Gothic ProN", "Yu Gothic", "Meiryo", "Noto Sans JP", "Microsoft YaHei", sans-serif',
  mincho:
    '"Hiragino Mincho ProN", "Yu Mincho", "Noto Serif JP", "SimSun", serif',
  rounded:
    '"Hiragino Maru Gothic ProN", "M PLUS Rounded 1c", "Yu Gothic", "Microsoft YaHei", sans-serif',
};

export function KaraokeStage({
  segments,
  syncState,
  audioRef,
  clockRef,
  offset = 0,
  color = "red",
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
  const pickTimerRef = useRef<number | null>(null);
  const cur = segments[syncState.displayIndex];
  const next = segments[syncState.displayIndex + 1] ?? null;
  const lineWords = useMemo(() => effectiveWords(cur), [cur]);
  const palette = useMemo(() => karaokePalette(settings), [settings]);
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

  const theme = {
    "--k-color": palette.after,
    "--k-before": palette.before,
    "--k-after": palette.after,
    "--k-before-stroke": palette.beforeStroke,
    "--k-after-stroke": palette.afterStroke,
    "--k-stroke-w": `${palette.strokeWidth}px`,
    "--k-glow": palette.glow,
    "--k-scan": palette.scanlineColor,
    "--k-font": FONT_STACKS[palette.font],
  } as CSSProperties;

  return (
    <div
      className="karaoke-stage"
      data-color={color}
      style={theme}
      onContextMenu={onContextMenu}
      onDoubleClick={() => {
        // 编辑框里的双击是选词,不应把正在编辑的草稿重置回原文
        if (!editing) startEdit();
      }}
    >
      {/* 1 顶部黑边:翻译字幕带 */}
      <div className="karaoke-top">
        <div className="karaoke-zh-row" key={`zh-${cur.id}`}>
          <span className="karaoke-zh cur">{showTranslation ? zh ?? "" : ""}</span>
          <span className="karaoke-zh next" aria-hidden={!nextZh}>
            {showTranslation ? nextZh ?? "" : ""}
          </span>
        </div>
      </div>

      {/* 2 中间画面区:当前句歌词压在画面下沿 */}
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
              words={lineWords}
              palette={palette}
              showFurigana={showFurigana}
              showRomaji={showRomaji}
              settings={settings}
              audioRef={audioRef}
              clockRef={clockRef}
              offset={offset}
              syncState={syncState}
              onPick={pickWord}
              pickTimerRef={pickTimerRef}
            />
          )}
        </div>
      </div>

      {/* 3 底部黑边:下一句白字预告 */}
      <div className="karaoke-bottom">
        {next && !editing ? (
          <KaraokeLine
            segment={next}
            words={effectiveWords(next)}
            palette={palette}
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
 * 一整句:三层完全相同的 ruby 排版叠在一起。
 *
 *   before —— 未唱配色,永远完整可见,也是唯一接收点击的层;
 *   after  —— 已唱配色,按整行唯一的锋面横坐标裁切;
 *   scan   —— 白色高光,用一条横向渐变 mask 只露出锋面附近的一小段。
 *
 * 三层共用同一份 DOM 尺寸,所以注音、字距和换行不会错位。
 */
function KaraokeLine({
  segment,
  words,
  palette,
  showFurigana,
  showRomaji,
  settings,
  muted = false,
  audioRef,
  clockRef,
  offset = 0,
  syncState,
  onPick,
  pickTimerRef,
}: {
  segment: Segment;
  words: WordTiming[];
  palette: KaraokePalette;
  showFurigana: boolean;
  showRomaji: boolean;
  settings: ReturnType<typeof useSettings>[0];
  muted?: boolean;
  audioRef?: RefObject<HTMLAudioElement | null>;
  clockRef?: RefObject<number>;
  offset?: number;
  syncState?: SyncState;
  onPick?: (word: WordTiming, e: React.MouseEvent) => void;
  pickTimerRef?: RefObject<number | null>;
}) {
  const { words: sweepWords, glyphs } = useMemo(
    () => buildLine(words),
    [words],
  );
  const beforeRef = useRef<HTMLDivElement | null>(null);
  const afterRef = useRef<HTMLDivElement | null>(null);
  const scanRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef(0);
  const chars = shownText(segment).replace(/\s/g, "").length || 1;
  const hasClock = Boolean(syncState);

  useEffect(() => {
    if (muted || !audioRef || !clockRef || !hasClock) return;
    const before = beforeRef.current;
    const after = afterRef.current;
    const scan = scanRef.current;
    if (!before || !after || !scan || !glyphs.length) return;

    // 字形盒子只在换行/改字号时变化,不必每一帧都量。
    let boxes: { left: number; right: number; height: number }[] = [];
    const measure = () => {
      const root = before.getBoundingClientRect();
      // 描边宽度以 1080p 字幕为基准:字号变大(4K 导出 / 大屏)时同比放大,
      // 否则 4K 下 2px 描边会细得几乎看不见。
      const fontPx = parseFloat(getComputedStyle(before).fontSize) || 108;
      before.parentElement?.style.setProperty(
        "--k-scale",
        (fontPx / 108).toFixed(3),
      );
      boxes = Array.from(
        before.querySelectorAll<HTMLElement>("[data-gi]"),
      ).map((el) => {
        const r = el.getBoundingClientRect();
        return {
          left: r.left - root.left,
          right: r.right - root.left,
          height: r.height,
        };
      });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(before);
    void document.fonts?.ready.then(measure);

    const shift = segment.line_offset ?? 0;
    const loop = () => {
      const audio = audioRef.current;
      const now =
        (audio && isFinite(audio.duration) && audio.duration > 0
          ? audio.currentTime - offset
          : clockRef.current ?? 0) - shift;
      const pos = sweepAt(glyphs, now);
      const first = boxes[0];
      const last = boxes[boxes.length - 1];
      if (!first || !last) {
        rafRef.current = requestAnimationFrame(loop);
        return;
      }

      let x = first.left;
      if (pos.gap) {
        const a = boxes[pos.index] ?? first;
        const b = boxes[pos.index + 1] ?? last;
        x = a.right + (b.left - a.right) * pos.frac;
      } else {
        const box = boxes[pos.index] ?? first;
        x = box.left + (box.right - box.left) * pos.frac;
      }
      if (now >= glyphs[glyphs.length - 1].end) x = last.right;
      if (now <= glyphs[0].start) x = first.left;

      const width = before.clientWidth;
      const right = Math.max(0, width - x);
      after.style.clipPath = `inset(0 ${right.toFixed(2)}px 0 0)`;

      // 只在锋面真正移动时显示高光带;唱完或还没开始时让它消失。
      const moving =
        now >= glyphs[0].start && now < glyphs[glyphs.length - 1].end;
      if (!moving || !palette.scanline) {
        scan.style.opacity = "0";
      } else {
        const scale = Math.max(0.45, Math.min(2.4, (first.height || 96) / 108));
        const half = (palette.scanlineWidth * scale) / 2;
        const feather = Math.min(half * 0.75, 8 * scale);
        scan.style.opacity = "1";
        scan.style.setProperty("--sweep-l", `${(x - half).toFixed(2)}px`);
        scan.style.setProperty(
          "--sweep-li",
          `${(x - half + feather).toFixed(2)}px`,
        );
        scan.style.setProperty(
          "--sweep-ri",
          `${(x + half - feather).toFixed(2)}px`,
        );
        scan.style.setProperty("--sweep-r", `${(x + half).toFixed(2)}px`);
      }
      rafRef.current = requestAnimationFrame(loop);
    };
    loop();
    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
    };
  }, [
    segment.id,
    segment.line_offset,
    glyphs,
    muted,
    audioRef,
    clockRef,
    offset,
    palette.scanline,
    palette.scanlineWidth,
    hasClock,
  ]);

  const pick = (word: WordTiming, e: React.MouseEvent) => {
    if (!onPick) return;
    e.stopPropagation();
    if (pickTimerRef?.current) window.clearTimeout(pickTimerRef.current);
    const { clientX, clientY } = e;
    const timer = window.setTimeout(() => {
      if (pickTimerRef) pickTimerRef.current = null;
      onPick(word, { clientX, clientY } as React.MouseEvent);
    }, 240);
    if (pickTimerRef) pickTimerRef.current = timer;
  };

  if (muted) {
    return (
      <div
        className="karaoke-line muted"
        style={{ "--chars": chars } as CSSProperties}
      >
        <SweepLayer
          words={sweepWords}
          glyphs={glyphs}
          wordTimes={words}
          showFurigana={showFurigana}
          muted
        />
        {showRomaji && (
          <RomajiRow words={words} settings={settings} chars={chars} muted />
        )}
      </div>
    );
  }

  return (
    <div className="karaoke-line" style={{ "--chars": chars } as CSSProperties}>
      <div className="karaoke-sweep">
        <div className="karaoke-layer before" ref={beforeRef}>
          <SweepLayer
            words={sweepWords}
            glyphs={glyphs}
            wordTimes={words}
            showFurigana={showFurigana}
            onPick={pick}
          />
        </div>
        <div className="karaoke-layer after" ref={afterRef} aria-hidden>
          <SweepLayer
            words={sweepWords}
            glyphs={glyphs}
            wordTimes={words}
            showFurigana={showFurigana}
          />
        </div>
        <div className="karaoke-layer scan" ref={scanRef} aria-hidden>
          <SweepLayer
            words={sweepWords}
            glyphs={glyphs}
            wordTimes={words}
            showFurigana={showFurigana}
          />
        </div>
      </div>
      {showRomaji && (
        <RomajiRow words={words} settings={settings} chars={chars} />
      )}
    </div>
  );
}

function SweepLayer({
  words,
  glyphs,
  wordTimes,
  showFurigana,
  muted = false,
  onPick,
}: {
  words: SweepWord[];
  glyphs: SweepGlyph[];
  wordTimes: WordTiming[];
  showFurigana: boolean;
  muted?: boolean;
  onPick?: (word: WordTiming, e: React.MouseEvent) => void;
}) {
  return (
    <div className="karaoke-text-row">
      {words.map((word, wi) => (
        <span
          className="kword"
          key={wi}
          data-wi={wi}
          onClick={
            onPick && wordTimes[wi]
              ? (e) => onPick(wordTimes[wi], e)
              : undefined
          }
        >
          <span className="surface">
            {word.groups.map((group, gi) => (
              <span className="ruby-group" key={gi}>
                <span
                  className={`furi${group.reading && showFurigana ? "" : " blank"}`}
                >
                  {group.reading && showFurigana ? group.reading : ""}
                </span>
                <span className="ruby-chars">
                  {glyphs.slice(group.from, group.to).map((ch, k) => (
                    <span
                      className={`kch${muted ? " muted" : ""}`}
                      key={k}
                      data-gi={group.from + k}
                    >
                      {ch.ch}
                    </span>
                  ))}
                </span>
              </span>
            ))}
          </span>
        </span>
      ))}
    </div>
  );
}

function RomajiRow({
  words,
  settings,
  chars,
  muted = false,
}: {
  words: WordTiming[];
  settings: ReturnType<typeof useSettings>[0];
  chars: number;
  muted?: boolean;
}) {
  return (
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
          <span className={`kroma${muted ? " muted" : ""}`}>
            {displayRomaji(w, settings)}
          </span>
        </span>
      ))}
    </div>
  );
}
