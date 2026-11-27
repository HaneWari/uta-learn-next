import { useEffect } from "react";
import { SHORTCUTS } from "../lib/shortcuts";

const GROUPS = ["播放", "学习", "显示", "编辑"] as const;

const KEY_LABELS: Record<string, string> = {
  " ": "Space",
  ArrowLeft: "←",
  ArrowRight: "→",
  ArrowUp: "↑",
  ArrowDown: "↓",
  Escape: "Esc",
};

function combo(keys: string[], shift?: boolean, ctrl?: boolean) {
  const parts: string[] = [];
  if (ctrl) parts.push("Ctrl");
  if (shift) parts.push("Shift");
  // `keys` lists every accepted spelling (`r` and `R`); the sheet shows one,
  // uppercased, or the table reads like a chord nobody can press
  const raw = keys[0];
  const key = KEY_LABELS[raw] ?? raw.toUpperCase();
  parts.push(key);
  return parts.join(" + ");
}

/** The generated shortcut table, shared by the ? sheet and 设置 → 快捷键. */
export function ShortcutGroups() {
  return (
    <div className="keygrid">
      {GROUPS.map((group) => {
        const items = SHORTCUTS.filter((s) => s.group === group);
        if (!items.length) return null;
        return (
          <section key={group} className="keycol">
            <h3>{group}</h3>
            {items.map((s) => (
              <div className="keyrow" key={s.label}>
                <kbd>{combo(s.keys, s.shift, s.ctrl)}</kbd>
                <span>{s.label}</span>
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}

/** `?` opens this; the table is generated from the same list the handler uses. */
export function ShortcutHelp({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="bgmask" role="dialog" aria-modal="true" aria-label="快捷键">
      <div className="bgmodal keymodal">
        <header className="bghead">
          <h2>快捷键</h2>
          <button className="bgclose" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>
        <p className="bghint">
          编辑输入框时不响应单键快捷键，避免和打字冲突。
        </p>
        <ShortcutGroups />
      </div>
    </div>
  );
}
