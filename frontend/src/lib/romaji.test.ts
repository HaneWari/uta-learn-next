import { describe, expect, it } from "vitest";
import { displayRomaji, lineRomaji, restyleLongVowel } from "./romaji";

const pron = { particle_reading: "pron", long_vowel: "ou" } as const;
const literal = { particle_reading: "literal", long_vowel: "ou" } as const;

describe("restyleLongVowel", () => {
  it("leaves ou untouched", () => {
    expect(restyleLongVowel("toukyou", "ou")).toBe("toukyou");
  });

  it("rewrites to macrons", () => {
    expect(restyleLongVowel("toukyou", "macron")).toBe("tōkyō");
  });

  it("rewrites to doubled vowels", () => {
    expect(restyleLongVowel("toukyou", "oo")).toBe("tookyoo");
  });

  it("does not touch a short vowel pair that is not a long o/u", () => {
    expect(restyleLongVowel("sakura", "macron")).toBe("sakura");
  });

  it("handles an empty string", () => {
    expect(restyleLongVowel("", "oo")).toBe("");
  });
});

describe("displayRomaji", () => {
  const particle = { romaji: "e", romaji_literal: "he" };

  it("prefers the sung reading by default", () => {
    expect(displayRomaji(particle, pron)).toBe("e");
  });

  it("switches to the literal spelling", () => {
    expect(displayRomaji(particle, literal)).toBe("he");
  });

  it("falls back when a dataset predates the literal field", () => {
    expect(displayRomaji({ romaji: "e" }, literal)).toBe("e");
  });

  it("applies the long-vowel style after choosing the reading", () => {
    expect(
      displayRomaji(
        { romaji: "toukyou" },
        { particle_reading: "pron", long_vowel: "macron" },
      ),
    ).toBe("tōkyō");
  });
});

describe("lineRomaji", () => {
  it("joins words with single spaces and drops empties", () => {
    expect(
      lineRomaji(
        [{ romaji: "toukyou" }, { romaji: "" }, { romaji: "e" }, { romaji: "ikou" }],
        pron,
      ),
    ).toBe("toukyou e ikou");
  });

  it("returns an empty string for an empty line", () => {
    expect(lineRomaji([], pron)).toBe("");
  });
});
