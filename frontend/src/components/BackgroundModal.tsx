import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { StageBackground } from "../types";

interface Props {
  current: StageBackground;
  onClose: () => void;
  onApplied: (bg: StageBackground) => void;
}

/**
 * Stage background picker.
 *
 * The chosen image lives on the server (see /api/ui/background) rather than in
 * the browser, because the video export runs in a fresh headless profile and
 * would otherwise render the default paper theme no matter what the user picked.
 */
export function BackgroundModal({ current, onClose, onApplied }: Props) {
  const [mode, setMode] = useState<StageBackground["mode"]>(current.mode);
  const [preview, setPreview] = useState<string | null>(current.url);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Esc closes; the modal is a hard overlay so nothing behind it is reachable
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const chooseFile = async (file: File) => {
    setBusy(true);
    setErr(null);
    try {
      const bg = await api.setBackground(file);
      setMode("custom");
      setPreview(bg.url);
      onApplied(bg);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const useDefault = async () => {
    setBusy(true);
    setErr(null);
    try {
      const bg = await api.resetBackground();
      setMode("default");
      setPreview(null);
      onApplied(bg);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bgmask" role="dialog" aria-modal="true" aria-label="设置背景">
      <div className="bgmodal">
        <header className="bghead">
          <h2>设置背景</h2>
          <button className="bgclose" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <p className="bghint">
          只改展示页的背景，配置页和导航栏不变。自定义图片会自动模糊并压暗，
          页内文字和卡片会变成半透明，浮在背景上面。
        </p>

        <div className="bgoptions">
          <button
            className={`bgopt${mode === "default" ? " on" : ""}`}
            onClick={() => void useDefault()}
            disabled={busy}
          >
            <span className="bgopt-thumb paper" />
            <span className="bgopt-name">默认背景</span>
            <span className="bgopt-note">纸感米白</span>
          </button>

          <button
            className={`bgopt${mode === "custom" ? " on" : ""}`}
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            {preview ? (
              <span
                className="bgopt-thumb"
                style={{ backgroundImage: `url("${preview}")` }}
              />
            ) : (
              <span className="bgopt-thumb empty">＋</span>
            )}
            <span className="bgopt-name">自定义背景</span>
            <span className="bgopt-note">
              {preview ? "点击换一张" : "上传图片"}
            </span>
          </button>
        </div>

        <input
          ref={fileRef}
          className="bgfile"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void chooseFile(f);
            e.target.value = "";
          }}
        />

        {preview && (
          <div className="bgpreview">
            <span
              className="bgpreview-img"
              style={{ backgroundImage: `url("${preview}")` }}
            />
            <span className="bgpreview-note">
              模糊与压暗在这里实时预览，实际效果与导出视频一致
            </span>
          </div>
        )}

        {err && <p className="hint-warn">{err}</p>}

        <footer className="bgfoot">
          <span className="bgfoot-note">
            {busy ? "正在处理…" : "jpg / png / webp，最大 12MB"}
          </span>
          <button className="btn primary" onClick={onClose} disabled={busy}>
            完成
          </button>
        </footer>
      </div>
    </div>
  );
}
