import { useEffect, useRef } from "react";
import type { Segment } from "../types";
import { effectiveWords } from "../lib/words";

/**
 * The whole song's lyrics in a collapsible rail (5.2.2).
 *
 * Purpose is navigation, not reading: the current line is highlighted and
 * scrolled into view, and clicking any line jumps there. It is off by default
 * so the stage keeps its clean look — the plan is explicit that learning
 * features must not cover the stage.
 */
export function LyricsRail({
  segments,
  activeId,
  open,
  onToggle,
  onSeek,
}: {
  segments: Segment[];
  activeId: number | null;
  open: boolean;
  onToggle: () => void;
  onSeek: (segment: Segment) => void;
}) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeId, open]);

  return (
    <>
      <button
        className="rail-toggle"
        onClick={onToggle}
        title={open ? "收起整首歌词" : "展开整首歌词"}
        aria-expanded={open}
      >
        歌词
      </button>
      <aside className={`lyrics-rail${open ? "" : " hidden"}`} aria-hidden={!open}>
        <header className="rail-head">
          <h3>整首歌词</h3>
          <button className="bgclose" onClick={onToggle} aria-label="收起">
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
