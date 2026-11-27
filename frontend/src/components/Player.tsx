import { useEffect, useRef, useState } from "react";
import { SPEEDS } from "../hooks/usePlayback";
import type { RefObject } from "react";

interface PlayerProps {
  audioRef: RefObject<HTMLAudioElement | null>;
  audioSrc: string;
  hasAudio?: boolean;
  /** current speed, owned by the stage so `[` / `]` can change it too */
  rate?: number;
  onRate?: (value: number) => void;
  /** single-line loop is on */
  looping?: boolean;
  onToggleLoop?: () => void;
  /** 跟读 mode is on */
  shadow?: boolean;
  onToggleShadow?: () => void;
  /** dragged AB loop range, if any */
  abLoop?: { start: number; end: number } | null;
  onAbLoop?: (range: { start: number; end: number } | null) => void;
}

function fmt(t: number) {
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function Player({
  audioRef,
  audioSrc,
  hasAudio = true,
  rate: controlledRate,
  onRate,
  looping = false,
  onToggleLoop,
  shadow = false,
  onToggleShadow,
  abLoop = null,
  onAbLoop,
}: PlayerProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const knobRef = useRef<HTMLDivElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const [paused, setPaused] = useState(true);
  const [localRate, setLocalRate] = useState(1);
  const rate = controlledRate ?? localRate;
  const [speedOpen, setSpeedOpen] = useState(false);

  /* Pointer drag on the progress bar:
     - a plain drag scrubs in real time (live audio seek + time bubble);
     - Shift + drag still defines an AB loop range;
     - pointer capture keeps the gesture alive after the pointer leaves the
       bar, so the user can drag anywhere on the page until they let go. */
  const dragMode = useRef<"seek" | "ab" | null>(null);
  const dragStart = useRef<number | null>(null);
  const abDragging = useRef(false);
  const pointerId = useRef<number | null>(null);
  const scrubbing = useRef(false);
  const previewRef = useRef<{ start: number; end: number } | null>(null);
  const [scrub, setScrub] = useState<{ pct: number; time: number } | null>(null);
  const [preview, setPreview] = useState<{ start: number; end: number } | null>(null);
  const abRange = abLoop ?? preview;

  // the duration lives in state as well as the element: reading it during
  // render would touch a ref, which the hooks lint rejects (and React may
  // render before the media element has metadata anyway)
  const [duration, setDuration] = useState(0);
  const ratio = (t: number) =>
    duration ? Math.min(100, Math.max(0, (t / duration) * 100)) : 0;

  const timeAt = (clientX: number, el: HTMLElement) => {
    const d = duration;
    const r = el.getBoundingClientRect();
    const pct = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    return pct * d;
  };

  const paint = (t: number) => {
    const pct = ratio(t);
    if (barRef.current) barRef.current.style.width = `${pct}%`;
    if (knobRef.current) knobRef.current.style.left = `${pct}%`;
    if (timeRef.current) timeRef.current.textContent = `${fmt(t)} / ${fmt(duration)}`;
  };

  const seekTo = (t: number) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(duration || a.duration || 0, t));
  };

  const beginDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const a = audioRef.current;
    if (!a || !duration) return;
    const el = e.currentTarget;
    // capture is what keeps pointermove/pointerup coming after the pointer
    // leaves the bar; without it the drag died at the edge
    el.setPointerCapture?.(e.pointerId);
    pointerId.current = e.pointerId;
    const t = timeAt(e.clientX, el);
    if (e.shiftKey) {
      dragMode.current = "ab";
      dragStart.current = t;
      abDragging.current = false;
      return;
    }
    dragMode.current = "seek";
    scrubbing.current = true;
    setScrub({ pct: ratio(t), time: t });
    paint(t);
    seekTo(t);
    e.preventDefault();
  };

  const moveDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragMode.current) return;
    const el = e.currentTarget;
    const t = timeAt(e.clientX, el);
    if (dragMode.current === "seek") {
      setScrub({ pct: ratio(t), time: t });
      paint(t);
      seekTo(t);
      return;
    }
    if (dragStart.current === null) return;
    if (Math.abs(t - dragStart.current) < 0.4) return;
    abDragging.current = true;
    const next = {
      start: Math.min(dragStart.current, t),
      end: Math.max(dragStart.current, t),
    };
    previewRef.current = next;
    setPreview(next);
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragMode.current) return;
    const el = e.currentTarget;
    if (pointerId.current !== null) {
      try {
        el.releasePointerCapture(pointerId.current);
      } catch {
        // capture was already lost (window blur, element unmount)
      }
      pointerId.current = null;
    }
    if (dragMode.current === "ab") {
      const moved = abDragging.current;
      const range = previewRef.current;
      dragStart.current = null;
      abDragging.current = false;
      previewRef.current = null;
      if (moved && range) onAbLoop?.(range);
      setPreview(null);
    } else {
      scrubbing.current = false;
      setScrub(null);
    }
    dragMode.current = null;
  };

  // the controlled value can change from a shortcut, so mirror it onto the
  // element rather than relying on the click handler alone
  useEffect(() => {
    const a = audioRef.current;
    if (a) a.playbackRate = rate;
  }, [audioRef, rate]);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const a = audioRef.current;
      if (a && !scrubbing.current) {
        const d = a.duration || 0;
        const pct = d ? Math.min(100, (a.currentTime / d) * 100) : 0;
        if (barRef.current) barRef.current.style.width = `${pct}%`;
        if (knobRef.current) knobRef.current.style.left = `${pct}%`;
        if (timeRef.current) {
          timeRef.current.textContent = `${fmt(a.currentTime)} / ${fmt(d)}`;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [audioRef]);

  const changeRate = (r: number) => {
    setLocalRate(r);
    onRate?.(r);
  };

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) a.play();
    else a.pause();
  };

  return (
    <>
      {hasAudio && (
        <audio
          ref={audioRef}
          src={audioSrc}
          preload="auto"
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
          onPlay={() => setPaused(false)}
          onPause={() => setPaused(true)}
        />
      )}

      <div className="dock">
        {hasAudio ? (
          <>
            <div className="dock-row">
              <button className="playbtn" onClick={toggle} aria-label="play/pause">
                <span className={`glyph ${paused ? "play" : "pause"}`} />
              </button>
              <span className="hint">
                空格 播放/暂停 · ← → 上/下一句 · Shift + ← → 后退/前进 3 秒
              </span>
              <button
                className={`modetoggle${looping ? " on" : ""}`}
                onClick={onToggleLoop}
                aria-pressed={looping}
                title="单句循环 (R)"
              >
                单句循环
              </button>
              <button
                className={`modetoggle${shadow ? " on" : ""}`}
                onClick={onToggleShadow}
                aria-pressed={shadow}
                title="跟读模式 (F)"
              >
                跟读
              </button>
              <div className={`speeds${speedOpen ? " open" : ""}`}>
                <button
                  className="speed-toggle"
                  onClick={() => setSpeedOpen((v) => !v)}
                  aria-expanded={speedOpen}
                  aria-label="播放速度"
                  title="播放速度"
                >
                  {rate}×
                </button>
                <div className="speed-list" role="group" aria-label="播放速度选项">
                  {SPEEDS.map((r) => (
                    <button
                      key={r}
                      className={`speed${rate === r ? " on" : ""}`}
                      onClick={() => {
                        changeRate(r);
                        setSpeedOpen(false);
                      }}
                      title={`${r} 倍速`}
                    >
                      {r}×
                    </button>
                  ))}
                </div>
              </div>
              <span className="time" ref={timeRef}>
                0:00 / 0:00
              </span>
            </div>
            {/* drag across the bar to loop that range (AB 循环). A plain click
                still seeks, so the two gestures do not fight. */}
            <div
              className={`progress${scrub ? " scrubbing" : ""}`}
              title="拖动定位；Shift + 拖动设置 AB 循环"
              onPointerDown={beginDrag}
              onPointerMove={moveDrag}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onLostPointerCapture={(e) => {
                if (dragMode.current) endDrag(e);
              }}
            >
              <div className="track" />
              {abRange && (
                <div
                  className="ab-band"
                  style={{
                    left: `${ratio(abRange.start)}%`,
                    width: `${Math.max(0.4, ratio(abRange.end) - ratio(abRange.start))}%`,
                  }}
                />
              )}
              <div className="fill" ref={barRef} />
              <div className="knob" ref={knobRef} />
              {scrub && (
                <div
                  className="scrub-tip"
                  style={{ left: `${Math.min(96, Math.max(4, scrub.pct))}%` }}
                >
                  {fmt(scrub.time)}
                </div>
              )}
            </div>
            {abRange && (
              <button
                className="ab-clear"
                type="button"
                onClick={() => onAbLoop?.(null)}
                title="取消 AB 循环"
              >
                AB {fmt(abRange.start)}–{fmt(abRange.end)} · 清除
              </button>
            )}
          </>
        ) : (
          <div className="dock-row">
            <span className="no-audio">
              这个数据集只有歌词，没有音频 —— 回到「配置」上传音频后重新生成
            </span>
          </div>
        )}
      </div>
    </>
  );
}
