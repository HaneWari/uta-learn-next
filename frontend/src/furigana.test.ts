import { describe, expect, it } from "vitest";
import { isKanji, rubyGroups } from "./furigana";

describe("isKanji", () => {
  it("accepts CJK ideographs and the iteration marks that act like them", () => {
    expect(isKanji("東")).toBe(true);
    expect(isKanji("々")).toBe(true);
    expect(isKanji("あ")).toBe(false);
    expect(isKanji("ア")).toBe(false);
    expect(isKanji("1")).toBe(false);
  });
});

describe("rubyGroups", () => {
  it("leaves a kana-only word without readings", () => {
    const groups = rubyGroups({ text: "あきらめる" });
    expect(groups.map((g) => g.chars.map((c) => c.ch).join(""))).toEqual([
      "あ", "き", "ら", "め", "る",
    ]);
    expect(groups.every((g) => g.reading === undefined)).toBe(true);
  });

  it("keeps okurigana bare and puts the reading on the kanji run", () => {
    const groups = rubyGroups({ text: "逃げ", kana: "にげ" });
    expect(groups).toHaveLength(2);
    expect(groups[0].chars.map((c) => c.ch).join("")).toBe("逃");
    expect(groups[0].reading).toBe("に");
    expect(groups[1].chars.map((c) => c.ch).join("")).toBe("げ");
    expect(groups[1].reading).toBeUndefined();
  });

  it("gives an all-kanji word one reading over the whole run", () => {
    const groups = rubyGroups({ text: "東京", kana: "とうきょう" });
    expect(groups).toHaveLength(1);
    expect(groups[0].reading).toBe("とうきょう");
    expect(groups[0].chars).toHaveLength(2);
  });

  it("merges split kanji runs into one span rather than guessing a split", () => {
    const groups = rubyGroups({ text: "話し合い", kana: "はなしあい" });
    expect(groups.map((g) => g.chars.map((c) => c.ch).join(""))).toEqual([
      "話し合", "い",
    ]);
    expect(groups[0].reading).toBe("はなしあ");
    expect(groups[1].reading).toBeUndefined();
  });

  it("falls back to plain per-character groups when no reading is known", () => {
    const groups = rubyGroups({ text: "東京" });
    expect(groups).toHaveLength(2);
    expect(groups.every((g) => g.reading === undefined)).toBe(true);
  });

  it("prefers explicit per-character timings from the dataset", () => {
    const groups = rubyGroups({
      text: "東京",
      kana: "とうきょう",
      chars: [
        { ch: "東", start: 1, end: 1.5 },
        { ch: "京", start: 1.5, end: 2 },
      ],
    });
    expect(groups[0].chars.map((c) => c.start)).toEqual([1, 1.5]);
  });
});
