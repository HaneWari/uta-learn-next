import { useEffect, useRef, useState } from "react";
import type { RefObject, MouseEvent } from "react";

interface PlayerProps {
  audioRef: RefObject<HTMLAudioElement | null>;
  audioSrc: string;
  hasAudio?: boolean;
}

function fmt(t: number) {
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function Player({ audioRef, audioSrc, hasAudio = true }: PlayerProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const knobRef = useRef<HTMLDivElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const [paused, setPaused] = useState(true);
  const [rate, setRate] = useState(1);
  const [speedOpen, setSpeedOpen] = useState(false);

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

  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];

  const changeRate = (r: number) => {
    setRate(r);
    const a = audioRef.current;
    if (a) a.playbackRate = r;
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
