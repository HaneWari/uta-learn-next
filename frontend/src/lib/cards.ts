import type { GrammarHit, Segment, WordTiming } from "../types";

/**
 * Pure card logic: which words earn a card, how overrides reshape the row, and
 * how the row is ordered. Kept out of the component so it can be unit-tested
 * without mounting React.
 */

/** How many vocabulary cards a stage width can carry. */
export function computeCardBudget(width: number) {
  if (width < 900) return 2;
  if (width < 1300) return 3;
  return 4;
}

/** JLPT weight: the card row should teach upward, so N1 outranks N5 by a lot. */
const LEVEL_SCORE: Record<string, number> = {
  N1: 5,
  N2: 4,
  N3: 3,
  N4: 2,
  N5: 1,
};

function levelScore(level?: string) {
  return LEVEL_SCORE[(level ?? "").toUpperCase()] ?? 0;
}

export interface VocabCardData {
  key: string;
  kind: "word";
  /** stable identity within the segment: word index, or extra index + 10000 */
  id: number;
  w: WordTiming;
}

export interface GrammarCardData {
  key: string;
  kind: "grammar";
  /** grammar id from the source, or `__extra_${i}` */
  id: string;
  g: GrammarHit;
}

export type CardData = VocabCardData | GrammarCardData;

export const EXTRA_BASE = 10000;

/** Move `dragKey` to where `overKey` sits in the visible row. */
export function reorderPreview(keys: string[], dragKey: string, overKey: string) {
  const rest = keys.filter((k) => k !== dragKey);
  const at = rest.indexOf(overKey);
  if (at < 0) return rest.concat(dragKey);
  rest.splice(at, 0, dragKey);
  return rest;
}

export function normOverride(ov?: Segment["vocab_override"]) {
  return {
    hide: ov?.hide ?? [],
    replace: ov?.replace ?? {},
    extra: ov?.extra ?? [],
    order: ov?.order ?? [],
  };
}

export function normGrammar(ov?: Segment["grammar_extra"]) {
  return {
    remove: ov?.remove ?? [],
    replace: ov?.replace ?? {},
    extra: ov?.extra ?? [],
  };
}

/** Merge generated picks + overrides into the final visible cards. */
export function computeCards(
  segment: Segment | null,
  budget: number,
  jlptMax = 0,
): CardData[] {
  if (!segment) return [];
  const ov = normOverride(segment.vocab_override);
  const gov = normGrammar(segment.grammar_extra);

  // ask for one extra word so hiding a card can be backfilled, like before
  const generated = pickWords(segment, budget + 1, jlptMax);
  const shown = generated.filter(
    (w) => !ov.hide.includes(segment.words.indexOf(w)),
  );
  const genCards: VocabCardData[] = shown.map((w) => {
    const idx = segment.words.indexOf(w);
    return {
      key: `w${idx}`,
      kind: "word",
      id: idx,
      w: { ...w, ...ov.replace[idx] },
    };
  });
  const extraCards: VocabCardData[] = ov.extra.map((w, i) => ({
    key: `wx${i}`,
    kind: "word",
    id: EXTRA_BASE + i,
    w,
  }));

  const grammar: GrammarCardData[] = [
    ...(segment.grammar ?? [])
      .filter((g) => !gov.remove.includes(g.id))
      .map(
        (g): GrammarCardData => ({
          key: `g-${g.id}`,
          kind: "grammar",
          id: g.id,
          g: { ...g, ...gov.replace[g.id] },
        }),
      )
      .slice(0, 1),
    ...gov.extra.map(
      (g, i): GrammarCardData => ({
        key: `gx${i}`,
        kind: "grammar",
        id: `__extra_${i}`,
        g,
      }),
    ),
  ];

  // One ordering for the whole row. Newer saves store every card's `key`
  // (`w${index}` / `wx${i}` / `g-${id}` / `gx${i}`); older saves only listed
  // generated word indexes, which are normalised to `w${index}` keys first.
  const all: CardData[] = [...genCards, ...extraCards, ...grammar];
  const byKey = new Map(all.map((c) => [c.key, c] as const));
  const defaultKeys = all.map((c) => c.key);
  const storedKeys = ov.order.map((o) =>
    typeof o === "number" ? `w${o}` : o,
  );
  const orderedKeys = storedKeys.length
    ? [
        ...storedKeys.filter((k) => byKey.has(k)),
        ...defaultKeys.filter((k) => !storedKeys.includes(k)),
      ]
    : defaultKeys;

  // Fit the ordered row into the budget. A grammar card always keeps one
  // reserved slot (it is the line's pattern, not just another word), so word
  // cards fill `budget - gSlots` and never push the grammar card out — while
  // still letting the user drag it anywhere in the row.
  const ordered = orderedKeys
    .map((k) => byKey.get(k))
    .filter((c): c is CardData => !!c);
  const gSlots = Math.min(1, ordered.filter((c) => c.kind === "grammar").length);
  const wordBudget = budget - gSlots;
  let wTaken = 0;
  let gTaken = 0;
  return ordered.filter((c) =>
    c.kind === "word" ? wTaken++ < wordBudget : gTaken++ < gSlots,
  );
}

/**
 * Choose which words get a card, and in what order.
 *
 * Selection prefers higher JLPT levels (that is what "优先高阶" means here), but
 * the cards are still shown in the order the words appear in the line: reordering
 * the row by difficulty would break the reader's eye movement across the lyric.
 */
/** `jlptMax` is the hardest level the user still wants (1 = N1 only, 5 = all,
 *  0 = no filter). Lowering it removes the easy words that make a card row
 *  feel noisy — の / する / こと at N5 crowd out the words worth learning. */
export function pickWords(
  segment: Segment | null,
  limit: number,
  jlptMax = 0,
): WordTiming[] {
  if (!segment) return [];
  const scored = segment.words
    .filter((w) => {
      if (w.content === false || !w.zh) return false;
      if (!jlptMax) return true;
      const level = levelScore(w.jlpt);
      // no JLPT tag: keep it, the dictionary simply lacks a rating
      return level === 0 || level >= 6 - jlptMax;
    })
    .map((w, index) => {
      // level dominates: 3 points per JLPT step means an N2 noun always beats
      // an N5 noun, which is the behaviour the "prefer harder words" ask wants
      let score = levelScore(w.jlpt) * 3;
      if (w.pos1 === "名詞" || w.pos1 === "動詞" || w.pos1 === "形容詞") score += 2;
      score += Math.min(3, w.text.length);
      if (w.kana) score += 1;
      return { w, score, index };
    })
    .sort((a, b) => b.score - a.score || a.index - b.index);

  // never show the same surface twice on one line
  const seen = new Set<string>();
  const chosen: { w: WordTiming; index: number }[] = [];
  for (const { w, index } of scored) {
    if (seen.has(w.text)) continue;
    seen.add(w.text);
    chosen.push({ w, index });
    if (chosen.length === limit) break;
  }

  // back to reading order for display
  chosen.sort((a, b) => a.index - b.index);
  return chosen.map((c) => c.w);
}
