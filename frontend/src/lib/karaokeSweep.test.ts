import { describe, expect, it } from "vitest";
import { buildLine, sweepAt } from "./karaokeSweep";
import type { WordTiming } from "../types";

const word = (over: Partial<WordTiming> = {}): WordTiming => ({
  text: "逃げ",
  kana: "にげ",
  romaji: "nige",
  start: 10,
  end: 11,
  score: 1,
  chars: [
    { ch: "逃", start: 10, end: 10.6 },
    { ch: "げ", start: 10.6, end: 11 },
  ],
  ...over,
});

describe("buildLine", () => {
  it("keeps every glyph and its ruby group", () => {
    const line = buildLine([word()]);
    expect(line.glyphs.map((g) => g.ch)).toEqual(["逃", "げ"]);
    expect(line.words[0].groups).toHaveLength(2);
    expect(line.words[0].groups[0].reading).toBe("に");
    expect(line.words[0].groups[1].reading).toBeUndefined();
  });

  it("splits the word's time evenly when chars carry no timing", () => {
    const line = buildLine([
      word({
        chars: [
          { ch: "逃", start: 0, end: 0 },
          { ch: "げ", start: 0, end: 0 },
        ],
      }),
    ]);
    expect(line.glyphs[0].start).toBeCloseTo(10);
    expect(line.glyphs[1].start).toBeCloseTo(10.5);
    expect(line.glyphs[1].end).toBeCloseTo(11);
  });

  it("falls back to an even split when chars are missing", () => {
    const line = buildLine([word({ chars: undefined })]);
    expect(line.glyphs).toHaveLength(2);
    expect(line.glyphs[0].start).toBeCloseTo(10);
    expect(line.glyphs[1].end).toBeCloseTo(11);
  });
});

describe("sweepAt", () => {
  const glyphs = buildLine([word()]).glyphs;

  it("clamps to the first glyph before the line starts", () => {
    expect(sweepAt(glyphs, 9)).toEqual({ index: 0, frac: 0, gap: false });
  });

  it("reports progress inside a glyph", () => {
    const pos = sweepAt(glyphs, 10.3);
    expect(pos.index).toBe(0);
    expect(pos.gap).toBe(false);
    expect(pos.frac).toBeCloseTo(0.5);
  });

  it("interpolates across the gap between two glyphs", () => {
    // 两个字之间人为留出 0.2s 的空隙
    const gapped = [
      { ch: "a", start: 0, end: 0.5 },
      { ch: "b", start: 0.7, end: 1.2 },
    ];
    const pos = sweepAt(gapped, 0.6);
    expect(pos.gap).toBe(true);
    expect(pos.index).toBe(0);
    expect(pos.frac).toBeCloseTo(0.5);
  });

  it("stays at the end once the line is finished", () => {
    expect(sweepAt(glyphs, 30)).toEqual({
      index: glyphs.length - 1,
      frac: 1,
      gap: false,
    });
  });

  it("handles an empty line", () => {
    expect(sweepAt([], 3)).toEqual({ index: 0, frac: 0, gap: false });
  });
});
