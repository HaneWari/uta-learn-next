import { useEffect, useState } from "react";

const MAX = 2;

interface Props {
  /** offset currently saved for this song */
  current: number;
  songTitle: string;
  /** apply a value to the stage without saving, so it can be tuned by ear */
  onPreview: (value: number) => void;
  onSave: (value: number) => Promise<void>;
  onClose: () => void;
}

function fmt(v: number): string {
  return v.toFixed(1);
}

/** Parse a draft; null while it is not (yet) a valid -2…2, one-decimal value. */
function parse(text: string): number | null {
  const t = text.trim();
  if (!/^[-+]?(\d+(\.\d)?|\.\d)$/.test(t)) return null;
  const v = Number(t);
  if (!Number.isFinite(v) || v < -MAX || v > MAX) return null;
  return Math.round(v * 10) / 10;
}

/**
 * Per-song lyric/audio offset.
 *
 * Every change previews live on the stage (the music keeps playing behind the
 * mask), so the user can nudge until the wipe lands on the voice; cancelling
 * puts the saved value back. The value is stored in the dataset, so the video
 * export uses it too.
 */
export function OffsetModal({ current, songTitle, onPreview, onSave, onClose }: Props) {
  // the preview writes straight into the song data, so `current` follows it;
  // remember what was saved when the dialog opened for 取消 to restore
  const [saved] = useState(current);
  const [draft, setDraft] = useState(fmt(saved));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const value = parse(draft);

  const cancel = () => {
    onPreview(saved);
    onClose();
  };

  const save = async () => {
    if (value === null) {
      setErr("请输入 -2 到 2 之间的数字，最多一位小数");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await onSave(value);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const set = (v: number) => {
    const clamped = Math.min(MAX, Math.max(-MAX, Math.round(v * 10) / 10));
    setDraft(fmt(clamped));
    setErr(null);
    onPreview(clamped);
  };

  const onType = (text: string) => {
    setDraft(text);
    setErr(null);
    const v = parse(text);
    if (v !== null) onPreview(v);
  };

  // Enter saves from anywhere in the dialog, Esc backs out
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        cancel();
      } else if (e.key === "Enter") {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const shown = value ?? 0;

  return (
    <div className="bgmask offsetmask" role="dialog" aria-modal="true" aria-label="时间偏移">
      <div className="bgmodal offsetmodal">
        <header className="bghead">
          <h2>时间偏移</h2>
          <button className="bgclose" onClick={cancel} aria-label="关闭">
            ×
          </button>
        </header>

        <p className="bghint" title={songTitle}>
          高亮比歌声<b>早</b>就填<b>正数</b>（延后），比歌声<b>晚</b>就填<b>负数</b>（提前）。
          边播放边调，立即生效；只影响这一首，导出视频同样生效。
        </p>

        <div className="offset-body">
          <div className="offset-row">
            <button className="btn" onClick={() => set(shown - 0.1)} disabled={busy || shown <= -MAX}>
              −0.1
            </button>
            <label className="offset-field">
              <input
                type="text"
                inputMode="decimal"
                value={draft}
                autoFocus
                onFocus={(e) => e.target.select()}
                onChange={(e) => onType(e.target.value)}
                aria-label="偏移秒数"
              />
              <span>秒</span>
            </label>
            <button className="btn" onClick={() => set(shown + 0.1)} disabled={busy || shown >= MAX}>
              +0.1
            </button>
          </div>

          <div className="offset-track">
            <input
              className="offset-slider"
              type="range"
              min={-MAX}
              max={MAX}
              step={0.1}
              value={shown}
              onChange={(e) => set(Number(e.target.value))}
              disabled={busy}
              aria-label="偏移滑块"
            />
            <div className="offset-scale">
              <span>−2 秒（提前）</span>
              <span className="offset-state">
                {value === null
                  ? "请输入 -2 到 2 之间的数字，最多一位小数"
                  : value === 0
                    ? "不偏移"
                    : value > 0
                      ? `高亮与切句延后 ${fmt(value)} 秒`
                      : `高亮与切句提前 ${fmt(-value)} 秒`}
              </span>
              <span>+2 秒（延后）</span>
            </div>
          </div>

          <span className="offset-actions">
            <button className="btn ghost" onClick={() => set(0)} disabled={busy}>
              归零
            </button>
            <button className="btn" onClick={cancel} disabled={busy}>
              取消
            </button>
            <button className="btn primary" onClick={() => void save()} disabled={busy || value === null}>
              {busy ? "保存中…" : "保存"}
            </button>
          </span>
        </div>

        {err && <p className="hint-warn">{err}</p>}
      </div>
    </div>
  );
}
