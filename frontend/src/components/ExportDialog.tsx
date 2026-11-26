import { useEffect, useMemo, useState } from "react";
import type { AppSettings } from "../types";

export interface ExportChoice {
  preset: string;
  clipStart: number;
  clipEnd: number;
}

const PRESETS = [
  { id: "landscape", label: "横屏 1080p", note: "1920×1080" },
  { id: "portrait", label: "竖屏 1080p", note: "1080×1920（短视频）" },
  { id: "4k", label: "4K 横屏", note: "3840×2160，较慢" },
] as const;

function fmt(t: number) {
  const total = Math.max(0, Math.round(t));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function parse(raw: string, fallback: number): number {
  const s = raw.trim();
  if (!s) return fallback;
  if (s.includes(":")) {
    const [m, sec] = s.split(":", 2);
    const value = Number(m) * 60 + Number(sec);
    return Number.isFinite(value) ? value : fallback;
  }
  const value = Number(s);
  return Number.isFinite(value) ? value : fallback;
}

/**
 * Pre-flight dialog for an export: preset, optional clip range, and a time
 * estimate. It is a separate step from the environment probe — the probe is
 * about whether a browser exists, this is about what the user wants to render.
 */
export function ExportDialog({
  duration,
  settings,
  onStart,
  onClose,
}: {
  duration: number;
  settings: AppSettings;
  onStart: (choice: ExportChoice) => void;
  onClose: () => void;
}) {
  const [preset, setPreset] = useState<string>(settings.export_preset);
  const [clip, setClip] = useState(false);
  const [startText, setStartText] = useState("0:00");
  const [endText, setEndText] = useState(fmt(duration));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const start = clip ? Math.min(duration, Math.max(0, parse(startText, 0))) : 0;
  const end = clip ? Math.min(duration, Math.max(start, parse(endText, duration))) : duration;
  const length = Math.max(0, end - start);

  const estimate = useMemo(() => {
    const perFrame = preset === "4k" ? 0.15 : 0.055;
    const seconds = (length * 60 * perFrame) / Math.max(1, settings.export_pages);
    return Math.max(10, Math.round(seconds));
  }, [length, preset, settings.export_pages]);

  const tooShort = length < 1;

  return (
    <div className="bgmask" role="dialog" aria-modal="true" aria-label="导出视频">
      <div className="bgmodal exportmodal">
        <header className="bghead">
          <h2>导出视频</h2>
          <button className="bgclose" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <p className="bghint">固定 60fps。导出在后台进行，可以关掉这个窗口。</p>

        <div className="preset-grid" role="radiogroup" aria-label="导出预设">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              role="radio"
              aria-checked={preset === p.id}
              className={`preset${preset === p.id ? " on" : ""}`}
              onClick={() => setPreset(p.id)}
            >
              <span className="preset-label">{p.label}</span>
              <span className="preset-note">{p.note}</span>
            </button>
          ))}
        </div>

        <div className="setrow">
          <span className="setlabel">
            只导出片段
            <span className="sethint">整首 {fmt(duration)}，留空即整首</span>
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={clip}
            aria-label="只导出片段"
            className={`switch${clip ? " on" : ""}`}
            onClick={() => setClip((v) => !v)}
          >
            <span className="switch-knob" />
          </button>
        </div>

        {clip && (
          <div className="clip-row">
            <label>
              起点
              <input
                className="setinput"
                value={startText}
                onChange={(e) => setStartText(e.target.value)}
                placeholder="0:00"
              />
            </label>
            <label>
              终点
              <input
                className="setinput"
                value={endText}
                onChange={(e) => setEndText(e.target.value)}
                placeholder={fmt(duration)}
              />
            </label>
            <span className="clip-len">{fmt(length)}</span>
          </div>
        )}

        <p className="setnote">
          预计约 {estimate >= 60 ? `${Math.round(estimate / 60)} 分钟` : `${estimate} 秒`}
          （并行 {settings.export_pages} 页，实际取决于机器）
        </p>

        <div className="exportmodal-foot">
          <button className="btn" onClick={onClose} type="button">
            取消
          </button>
          <button
            className="btn primary"
            type="button"
            disabled={tooShort}
            onClick={() => onStart({ preset, clipStart: start, clipEnd: end })}
          >
            {tooShort ? "片段至少 1 秒" : "开始导出"}
          </button>
        </div>
      </div>
    </div>
  );
}
