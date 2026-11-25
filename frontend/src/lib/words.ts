import type { Segment, WordTiming } from "../types";

/**
 * The word list a line should be rendered and highlighted with.
 *
 * Both were read straight off the segment before: the sync engine indexed
 * `seg.words`, while the display rendered `seg.lyric_override.words` when the
 * user had edited the line. Those two lists differ in length as soon as an
 * edit adds or drops a word, so the wipe could land on the wrong glyph — or run
 * past the end of the rendered line. One selector fixes both sides.
 */
export function effectiveWords(seg: Segment | null | undefined): WordTiming[] {
  if (!seg) return [];
  const override = seg.lyric_override?.words;
  if (override && override.length) return override;
  return seg.words ?? [];
}

/** True when the line shows no text at all (the user cleared it). */
export function isBlankLine(seg: Segment | null | undefined): boolean {
  if (!seg) return true;
  const text = seg.lyric_override?.text ?? seg.text ?? "";
  return !text.replace(/[[【][^\]】]+[\]】]\s*[((][^)）]*[)）]/g, "$1").trim();
}
