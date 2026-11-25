/**
 * Keyboard shortcuts, defined once so the help sheet can't drift from the
 * handler. Typing in a field always wins — every single-key shortcut is off
 * while an input, textarea or contenteditable has focus.
 */

export interface Shortcut {
  /** the `KeyboardEvent.key` values that trigger it (single keys) */
  keys: string[];
  /** shown in the help sheet */
  label: string;
  /** grouped in the help sheet */
  group: "播放" | "显示" | "学习" | "编辑";
  /** also requires Shift */
  shift?: boolean;
  /** also requires Ctrl (or Cmd) */
  ctrl?: boolean;
  action: ShortcutAction;
}

export type ShortcutAction =
  | "toggle-play"
  | "seek-back"
  | "seek-forward"
  | "prev-line"
  | "next-line"
  | "rate-down"
  | "rate-up"
  | "loop-line"
  | "shadow"
  | "toggle-trans"
  | "toggle-cards"
  | "help"
  | "undo"
  | "close";

export const SHORTCUTS: Shortcut[] = [
  { keys: [" "], label: "播放 / 暂停", group: "播放", action: "toggle-play" },
  { keys: ["ArrowLeft"], label: "上一句", group: "播放", action: "prev-line" },
  { keys: ["ArrowRight"], label: "下一句", group: "播放", action: "next-line" },
  {
    keys: ["ArrowLeft"],
    shift: true,
    label: "后退 5 秒",
    group: "播放",
    action: "seek-back",
  },
  {
    keys: ["ArrowRight"],
    shift: true,
    label: "前进 5 秒",
    group: "播放",
    action: "seek-forward",
  },
  { keys: ["["], label: "降一档速度", group: "播放", action: "rate-down" },
  { keys: ["]"], label: "升一档速度", group: "播放", action: "rate-up" },
  { keys: ["r", "R"], label: "单句循环", group: "学习", action: "loop-line" },
  { keys: ["f", "F"], label: "跟读模式", group: "学习", action: "shadow" },
  { keys: ["t", "T"], label: "显示 / 隐藏翻译", group: "显示", action: "toggle-trans" },
  { keys: ["k", "K"], label: "显示 / 隐藏词条卡片", group: "显示", action: "toggle-cards" },
  { keys: ["?"], label: "快捷键一览", group: "编辑", action: "help" },
  {
    keys: ["z", "Z"],
    ctrl: true,
    label: "撤销上一次卡片编辑",
    group: "编辑",
    action: "undo",
  },
  { keys: ["Escape"], label: "关闭弹窗 / 退出编辑", group: "编辑", action: "close" },
];

export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable === true
  );
}

/** Resolve a key event to an action, honouring shift/ctrl and the typing guard. */
export function resolveShortcut(e: KeyboardEvent): ShortcutAction | null {
  if (isTyping(e.target)) return null;
  const ctrl = e.ctrlKey || e.metaKey;
  for (const s of SHORTCUTS) {
    if (!s.keys.includes(e.key)) continue;
    if (!!s.shift !== e.shiftKey) continue;
    if (!!s.ctrl !== ctrl) continue;
    return s.action;
  }
  return null;
}
