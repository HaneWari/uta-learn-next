import { describe, expect, it } from "vitest";
import { effectiveWords, isBlankLine } from "./words";
import type { Segment, WordTiming } from "../types";

function word(text: string): WordTiming {
  return { text, romaji: "", start: 0, end: 1, score: 0 };
}

function segment(parts: Partial<Segment> = {}): Segment {
  return {
    id: 1,
    start: 0,
    end: 4,
    text: "テスト",
    romaji: "tesuto",
    words: [word("テスト")],
    ...parts,
  };
}

describe("effectiveWords", () => {
  it("uses the aligned words when nothing was edited", () => {
    expect(effectiveWords(segment()).map((w) => w.text)).toEqual(["テスト"]);
  });

  it("prefers the rebuilt override words", () => {
    const seg = segment({
      lyric_override: { text: "テスト", words: [word("テスト"), word("だ")] },
    });
    expect(effectiveWords(seg)).toHaveLength(2);
  });

  it("falls back to the aligned words when an override has no words", () => {
    const seg = segment({ lyric_override: { text: "テスト" } });
    expect(effectiveWords(seg)).toHaveLength(1);
  });

  it("treats a missing segment as empty", () => {
    expect(effectiveWords(null)).toEqual([]);
    expect(effectiveWords(undefined)).toEqual([]);
  });
});

describe("isBlankLine", () => {
  it("is false for a normal line", () => {
    expect(isBlankLine(segment())).toBe(false);
  });

  it("is true when the override cleared the text", () => {
    expect(isBlankLine(segment({ lyric_override: { text: "   " } }))).toBe(true);
  });

  it("ignores reading markup when deciding emptiness", () => {
    expect(isBlankLine(segment({ lyric_override: { text: "[明日](あす)" } }))).toBe(false);
  });

  it("is true for a missing segment", () => {
    expect(isBlankLine(null)).toBe(true);
  });
});
