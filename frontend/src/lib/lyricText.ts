import type { AppSettings, Segment } from "../types";
import { lineRomaji } from "./romaji";

/**
 * 一句歌词“实际显示/编辑”的文本与译文的唯一来源。
 *
 * 两种播放样式、歌词列表和编辑框都从这里取,避免同一行在不同界面里
 * 出现“override 生效了一半”的分叉。读音标记 `[汉字](よみ)` 只是注记,
 * 永远不参与显示和字数统计。
 */
export const READING_MARK = /[【[](?:[^】\]]+)[】\]]\s*[((][^()()]*[))]/g;

export function stripMarks(text: string): string {
  return text.replace(READING_MARK, "$1");
}

export function shownText(seg: Segment): string {
  return stripMarks(seg.lyric_override?.text ?? seg.text ?? "");
}

export function shownZh(seg: Segment): string | undefined {
  return seg.lyric_override?.translation_zh ?? seg.translation_zh;
}

/** “下一句”/编辑后的整行罗马音:重建过的 override words 优先。 */
export function shownRomaji(
  seg: Segment,
  settings: Pick<AppSettings, "particle_reading" | "long_vowel">,
): string {
  const ov = seg.lyric_override?.words;
  if (ov?.length) return lineRomaji(ov, settings);
  return lineRomaji(seg.words, settings) || seg.romaji;
}
