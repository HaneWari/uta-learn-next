import type { Segment } from "../types";

/** 默认样式与卡拉OK样式共用的歌词编辑窗。 */
export function LineEditBox({
  cur,
  draft,
  setDraft,
  onNudgeLine,
  onRealign,
  canRealign = false,
}: {
  cur: Segment;
  draft: { text: string; zh: string };
  setDraft: (d: { text: string; zh: string }) => void;
  onNudgeLine?: (segmentId: number, delta: number) => void;
  onRealign?: (segmentId: number) => void;
  canRealign?: boolean;
}) {
  return (
    <div className="lyr-edit">
      <input
        className="lyr-edit-text"
        value={draft.text}
        placeholder="日文歌词"
        autoFocus
        onChange={(e) => setDraft({ ...draft, text: e.target.value })}
      />
      <input
        className="lyr-edit-zh"
        value={draft.zh}
        placeholder="中文翻译（可留空）"
        onChange={(e) => setDraft({ ...draft, zh: e.target.value })}
      />
      <span className="lyr-edit-hint">
        回车或点击空白保存 · Esc 取消 · 改读音写作 <code>[汉字](读音)</code>
        ，如 <code>[明日](あす)</code>，假名/片假名/罗马音均可
      </span>

      <div className="lyr-tools">
        <span className="lyr-tool-label">本行时间</span>
        <button
          type="button"
          className="lyr-nudge"
          onClick={() => onNudgeLine?.(cur.id, -0.1)}
          title="这一行整体提前 0.1 秒"
        >
          -0.1s
        </button>
        <span className="lyr-offset">
          {(cur.line_offset ?? 0) > 0 ? "+" : ""}
          {(cur.line_offset ?? 0).toFixed(1)}s
        </span>
        <button
          type="button"
          className="lyr-nudge"
          onClick={() => onNudgeLine?.(cur.id, 0.1)}
          title="这一行整体延后 0.1 秒"
        >
          +0.1s
        </button>
        <button
          type="button"
          className="lyr-realign"
          onClick={() => onRealign?.(cur.id)}
          disabled={!canRealign}
          title={
            canRealign
              ? "只对这条前后 5 秒重新识别并对齐"
              : "需要自定义歌词扩展包(whisper)"
          }
        >
          重新对齐本行
        </button>
      </div>
    </div>
  );
}
