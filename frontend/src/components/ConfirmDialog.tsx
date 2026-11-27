import { useEffect } from "react";
import { createPortal } from "react-dom";

/**
 * 应用内确认框。
 *
 * 浏览器自带的 `window.confirm` 在 pywebview 与各浏览器里样式都不一致，
 * 还会阻塞整个页面；删除扩展包这类不可逆动作统一走这里，视觉与其它弹窗一致。
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "确定",
  cancelLabel = "取消",
  danger = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, onConfirm]);

  // Portal into #root rather than body: 页面缩放 applies `zoom` to #root, and a
  // dialog outside it would render at a different scale than the settings page
  // it covers.
  const host = document.getElementById("root") ?? document.body;
  return createPortal(
    <div
      className="bgmask confirm-mask"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="bgmodal confirmmodal">
        <header className="bghead">
          <h2>{title}</h2>
          <button className="bgclose" onClick={onCancel} aria-label="关闭">
            ×
          </button>
        </header>
        <p className="confirm-msg">{message}</p>
        <footer className="confirm-actions">
          <button type="button" className="btn" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn${danger ? " danger" : " primary"}`}
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </footer>
      </div>
    </div>,
    host,
  );
}
