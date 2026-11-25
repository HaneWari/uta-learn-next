import { useEffect, useRef, useState } from "react";
import { SPEEDS } from "../hooks/usePlayback";
import type { RefObject, MouseEvent } from "react";

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
}: PlayerProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const knobRef = useRef<HTMLDivElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const [paused, setPaused] = useState(true);
  const [localRate, setLocalRate] = useState(1);
  const rate = controlledRate ?? localRate;
  const [speedOpen, setSpeedOpen] = useState(false);

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
      if (a) {
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

  const seek = (e: MouseEvent<HTMLDivElement>) => {
    const a = audioRef.current;
    if (!a || !a.duration) return;
    const r = e.currentTarget.getBoundingClientRect();
    a.currentTime = ((e.clientX - r.left) / r.width) * a.duration;
  };

  return (
    <>
      {hasAudio && (
        <audio
          ref={audioRef}
          src={audioSrc}
          preload="auto"
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
              <span className="hint">逐字同步 · 空格 播放/暂停 · ← → ±5s</span>
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
            <div className="progress" onClick={seek}>
              <div className="track" />
              <div className="fill" ref={barRef} />
              <div className="knob" ref={knobRef} />
            </div>
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
