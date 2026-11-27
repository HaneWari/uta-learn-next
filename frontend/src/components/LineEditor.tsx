import { useEffect, useState } from "react";
import type { Segment } from "../types";
import { pushUndo } from "../lib/saveQueue";
import { shownText, shownZh } from "../lib/lyricText";

/**
 * 单句歌词编辑器,默认样式与卡拉OK样式共用。
 *
 * 两种样式只是排版不同,编辑语义必须完全一致(否则同一个数据集在两种样式下
 * 会写出不同结果):翻译单改不动高亮、改文本才重新分词、Enter/点空白保存、
 * Esc 取消、Ctrl+Z 可撤销。
 */

export function useLineEditor({
  cur,
  song,
  onPatch,
  beforeStart,
}: {
  cur: Segment | undefined;
  song?: string;
  onPatch?: (segId: number, body: Partial<Segment>) => Segment | undefined;
  /** 双击同时会触发一次单击查词,进入编辑前先取消它 */
  beforeStart?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ text: "", zh: "" });

  // a new line scrolls in — drop any half-finished edit so it can't leak
  // onto the next segment
  useEffect(() => {
    setEditing(false);
  }, [cur?.id]);

  function startEdit() {
    if (!cur || !onPatch) return;
    beforeStart?.();
    setDraft({ text: shownText(cur), zh: shownZh(cur) ?? "" });
    setEditing(true);
  }

  function commitEdit() {
    if (cur && onPatch) {
      const newText = draft.text.trim();
      const newZh = draft.zh.trim();
      // Only a real text change rewrites `lyric_override.text`: entering edit
      // mode and leaving, or touching just the translation, must keep the
      // per-glyph wipe (it still matches the words). A changed text is what
      // drops the highlight onto the verbatim line.
      const textChanged = newText !== (cur.lyric_override?.text ?? cur.text);
      const prevZh = cur.lyric_override?.translation_zh;
      const zhChanged = newZh !== (prevZh ?? cur.translation_zh ?? "");
      // snapshot the line before the write so Ctrl+Z can restore it; the
      // re-tokenised `words` are derived by the PATCH route, so restoring the
      // override (or its absence) is enough
      if (textChanged || zhChanged) {
        pushUndo({
          song: song ?? "",
          label: textChanged ? "歌词编辑" : "翻译编辑",
          segmentId: cur.id,
          restore: { lyric_override: cur.lyric_override ?? null },
        });
      }
      onPatch(cur.id, {
        // an emptied line still plays on its timing — it just shows nothing
        lyric_override: {
          // keep the old override text when it wasn't edited, and never
          // introduce `text` on a translation-only edit
          text: textChanged ? newText : cur.lyric_override?.text,
          translation_zh: zhChanged ? newZh : prevZh,
        },
      });
    }
    setEditing(false);
  }

  // Enter commits from anywhere while editing — not just when a field is
  // focused — and a click on empty space saves too. Esc cancels.
  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commitEdit();
      }
      if (e.key === "Escape") setEditing(false);
    };
    const onDown = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest(".lyr-edit")) return;
      commitEdit();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, draft, cur]);

  return { editing, draft, setDraft, startEdit, commitEdit, setEditing };
}

