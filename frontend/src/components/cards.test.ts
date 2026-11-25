import { describe, expect, it } from "vitest";
import {
  computeCardBudget,
  computeCards,
  pickWords,
  reorderPreview,
} from "../lib/cards";
import type { GrammarHit, Segment, WordTiming } from "../types";

function word(text: string, extra: Partial<WordTiming> = {}): WordTiming {
  return {
    text,
    romaji: "",
    start: 0,
    end: 0,
    score: 0,
    content: true,
    zh: "译",
    ...extra,
  };
}

function grammar(id: string, name = id): GrammarHit {
  return { id, name, level: "N4", z: "解释", ex: "例句", matched: name, at: 0 };
}

function segment(parts: Partial<Segment> = {}): Segment {
  return {
    id: 1,
    start: 0,
    end: 4,
    text: "テスト",
    romaji: "tesuto",
    words: [],
    ...parts,
  };
}

describe("computeCardBudget", () => {
  it("follows the four-up / three-up / two-up breakpoints", () => {
    expect(computeCardBudget(899)).toBe(2);
    expect(computeCardBudget(900)).toBe(3);
    expect(computeCardBudget(1299)).toBe(3);
    expect(computeCardBudget(1300)).toBe(4);
  });
});

describe("pickWords", () => {
  it("returns picks in reading order, not difficulty order", () => {
    const seg = segment({
      words: [
        word("猫", { jlpt: "N5", pos1: "名詞" }),
        word("経済", { jlpt: "N1", pos1: "名詞" }),
        word("走る", { jlpt: "N4", pos1: "動詞" }),
      ],
    });
    expect(pickWords(seg, 3).map((w) => w.text)).toEqual(["猫", "経済", "走る"]);
  });

  it("prefers harder words when the budget is smaller than the line", () => {
    const seg = segment({
      words: [
        word("猫", { jlpt: "N5", pos1: "名詞" }),
        word("経済", { jlpt: "N1", pos1: "名詞" }),
      ],
    });
    expect(pickWords(seg, 1).map((w) => w.text)).toEqual(["経済"]);
  });

  it("never shows the same surface twice", () => {
    const seg = segment({
      words: [word("夢", { jlpt: "N3" }), word("夢", { jlpt: "N3" })],
    });
    expect(pickWords(seg, 2)).toHaveLength(1);
  });

  it("skips function words and words without a gloss", () => {
    const seg = segment({
      words: [
        word("の", { content: false }),
        word("夢", { zh: "" }),
        word("空", {}),
      ],
    });
    expect(pickWords(seg, 4).map((w) => w.text)).toEqual(["空"]);
  });

  it("returns nothing for a missing segment", () => {
    expect(pickWords(null, 4)).toEqual([]);
    expect(computeCards(null, 4)).toEqual([]);
  });
});

describe("pickWords JLPT filter", () => {
  const line = segment({
    words: [
      word("の", { jlpt: "N5", pos1: "助詞", content: false }),
      word("こと", { jlpt: "N5", pos1: "名詞" }),
      word("経済", { jlpt: "N1", pos1: "名詞" }),
      word("謎語", { pos1: "名詞" }), // no JLPT rating at all
    ],
  });

  it("keeps everything when the filter is off", () => {
    expect(pickWords(line, 4, 0).map((w) => w.text)).toEqual([
      "こと", "経済", "謎語",
    ]);
  });

  it("drops N5 words once the user asks for N3 and harder", () => {
    expect(pickWords(line, 4, 3).map((w) => w.text)).toEqual(["経済", "謎語"]);
  });

  it("keeps unrated words — the dictionary simply has no level", () => {
    expect(pickWords(line, 4, 1)).toEqual(
      expect.arrayContaining([expect.objectContaining({ text: "謎語" })]),
    );
  });

  it("N1-only keeps just the hardest word", () => {
    expect(pickWords(line, 4, 1).map((w) => w.text)).toEqual(["経済", "謎語"]);
  });
});

describe("computeCards", () => {
  const fourWords = [
    word("一", { jlpt: "N5" }),
    word("二", { jlpt: "N4" }),
    word("三", { jlpt: "N3" }),
    word("四", { jlpt: "N2" }),
  ];

  it("shows three words plus the grammar card in a four-card row", () => {
    const cards = computeCards(segment({ words: fourWords, grammar: [grammar("g1")] }), 4);
    expect(cards.map((c) => c.kind)).toEqual(["word", "word", "word", "grammar"]);
  });

  it("keeps the grammar slot reserved and fills the rest with words", () => {
    const cards = computeCards(segment({ words: fourWords }), 4);
    expect(cards).toHaveLength(4);
    expect(cards.every((c) => c.kind === "word")).toBe(true);
  });

  it("backfills a hidden generated word instead of leaving a gap", () => {
    const cards = computeCards(
      segment({ words: fourWords, vocab_override: { hide: [0] } }),
      3,
    );
    expect(cards.map((c) => (c.kind === "word" ? c.w.text : c.g.name))).toEqual([
      "二", "三", "四",
    ]);
  });

  it("honours a stored key order across word and grammar cards", () => {
    const cards = computeCards(
      segment({
        words: fourWords,
        grammar: [grammar("g1")],
        vocab_override: { order: ["g-g1", "w1", "w0", "w2"] },
      }),
      4,
    );
    expect(cards.map((c) => c.key)).toEqual(["g-g1", "w1", "w0", "w2"]);
  });

  it("normalises a legacy numeric order to word keys", () => {
    const cards = computeCards(
      segment({ words: fourWords, vocab_override: { order: [2, 1] } }),
      2,
    );
    expect(cards.map((c) => c.key)).toEqual(["w2", "w1"]);
  });

  it("appends hand-made cards after the generated ones", () => {
    const cards = computeCards(
      segment({
        words: [fourWords[0]],
        vocab_override: { extra: [word("手作り")] },
      }),
      4,
    );
    expect(cards.map((c) => c.key)).toEqual(["w0", "wx0"]);
  });

  it("applies a per-word replacement to the displayed copy", () => {
    const cards = computeCards(
      segment({
        words: fourWords,
        vocab_override: { replace: { 1: { zh: "自定义" } } },
      }),
      4,
    );
    const second = cards[1];
    expect(second.kind === "word" && second.w.zh).toBe("自定义");
  });

  it("drops a removed grammar pattern", () => {
    const cards = computeCards(
      segment({
        words: fourWords,
        grammar: [grammar("g1")],
        grammar_extra: { remove: ["g1"] },
      }),
      4,
    );
    expect(cards.some((c) => c.kind === "grammar")).toBe(false);
  });
});

describe("reorderPreview", () => {
  it("moves the dragged key to the target position", () => {
    expect(reorderPreview(["w0", "w1", "w2"], "w2", "w0")).toEqual([
      "w2", "w0", "w1",
    ]);
  });

  it("appends when the target is unknown", () => {
    expect(reorderPreview(["w0", "w1"], "w1", "nope")).toEqual(["w0", "w1"]);
  });
});
