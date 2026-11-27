import { useEffect, useRef } from "react";
import type { Segment } from "../types";
import { effectiveWords } from "../lib/words";

/**
 * 歌词列表：贴在右侧的悬浮窗。
 *
 * 三个入口保持一致：
 *   * 指针移进右侧触发条 → 展开；移出列表/触发条 → 自动收回；
 *   * 贴边的纵向小书签保留，点击展开（展开后书签隐藏）；
 *   * 右上角叉号或点击列表外页面 → 收回。
 *
 * 常驻的只有 18px 触发条，面板在指针靠近时才滑出，不遮挡舞台。
 */
export function LyricsRail({
  segments,
  activeId,
  open,
  onOpen,
  onClose,
  onSeek,
}: {
  segments: Segment[];
  activeId: number | null;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  onSeek: (segment: Segment) => void;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef<HTMLButtonElement | null>(null);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);

  const cancelTimers = () => {
    if (openTimer.current !== null) window.clearTimeout(openTimer.current);
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    openTimer.current = null;
    closeTimer.current = null;
  };

  const scheduleOpen = () => {
    cancelTimers();
    if (open) return;
    openTimer.current = window.setTimeout(onOpen, 120);
  };

  const scheduleClose = () => {
    cancelTimers();
    closeTimer.current = window.setTimeout(onClose, 220);
  };

  useEffect(
    () => () => {
      if (openTimer.current !== null) window.clearTimeout(openTimer.current);
      if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    },
    [],
  );

  useEffect(() => {
    if (!open) return;
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeId, open]);

  // 点击列表外的任意位置收回；点击列表内部（含滚动条）不处理。
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest(".lyrics-rail, .rail-toggle, .rail-zone")) return;
      onClose();
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open, onClose]);

  return (
    <>
      {!open && (
        <button
          className="rail-toggle"
          onClick={onOpen}
          onMouseEnter={scheduleOpen}
          title="展开歌词列表"
          aria-expanded={false}
        >
          歌词列表
        </button>
      )}
      {/* 隐形的贴边触发条：指针进入就展开，不挡舞台内容 */}
      <div
        className={`rail-zone${open ? " open" : ""}`}
        onMouseEnter={scheduleOpen}
        onMouseLeave={scheduleClose}
        aria-hidden
      />
      <aside
        className={`lyrics-rail${open ? "" : " hidden"}`}
        aria-hidden={!open}
        onMouseEnter={cancelTimers}
        onMouseLeave={scheduleClose}
      >
        <header className="rail-head">
          <h3>歌词列表</h3>
          <button className="bgclose" onClick={onClose} aria-label="收回歌词列表">
            ×
          </button>
        </header>
        <div className="rail-list" ref={listRef}>
          {segments.map((seg) => {
            const text =
              (seg.lyric_override?.text ?? seg.text) ||
              effectiveWords(seg)
                .map((w) => w.text)
                .join("");
            return (
              <button
                key={seg.id}
                ref={seg.id === activeId ? activeRef : undefined}
                className={`rail-line${seg.id === activeId ? " on" : ""}`}
                onClick={() => onSeek(seg)}
                title={text}
              >
                {text || "（空行）"}
              </button>
            );
          })}
        </div>
      </aside>
    </>
  );
}
