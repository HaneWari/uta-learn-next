import { useEffect, useState } from "react";
import type { GrammarHit, Segment, WordTiming } from "../types";

/** How many vocabulary cards the current window can carry. */
function useCardBudget() {
  const [budget, setBudget] = useState(() => compute(window.innerWidth));

  useEffect(() => {
    const onResize = () => setBudget(compute(window.innerWidth));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return budget;
}

function compute(width: number) {
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

/**
 * Choose which words get a card, and in what order.
 *
 * Selection prefers higher JLPT levels (that is what "优先高阶" means here), but
 * the cards are still shown in the order the words appear in the line: reordering
 * the row by difficulty would break the reader's eye movement across the lyric.
 */
function pickWords(segment: Segment | null, limit: number): WordTiming[] {
  if (!segment) return [];
  const scored = segment.words
    .filter((w) => w.content !== false && w.zh)
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

function VocabCard({ w, i }: { w: WordTiming; i: number }) {
  // Headline the dictionary form when the line uses an inflected one, so the
  // card matches what a learner would look up (逃げる, not 逃げ).
  const isLemma = !!w.lemma && w.lemma !== w.text;
  const head = isLemma ? w.lemma! : w.text;
  const raw = isLemma ? w.lemma_kana ?? w.kana : w.kana;
  // a word already written in kana must not repeat its reading beside itself
  const kana = raw && raw !== head ? raw : undefined;

  return (
    <article className="vcard" style={{ animationDelay: `${i * 70}ms` }}>
      <header className="vhead">
        <span className="vw">{head}</span>
        {kana && <span className="vkana">{kana}</span>}
        {w.jlpt && <span className="vtag">{w.jlpt}</span>}
      </header>
      <div className="vbody">
        {w.pos && <span className="vpos">{w.pos}</span>}
        <span className="vzh">{w.zh}</span>
      </div>
      <div className="vmeta">
        {w.romaji && <span className="vroma">{w.romaji}</span>}
        {isLemma && <span className="vused">歌中 {w.text}</span>}
      </div>
    </article>
  );
}

function GrammarCard({ g, i }: { g: GrammarHit; i: number }) {
  return (
    <article
      className="vcard gcard"
      style={{ animationDelay: `${i * 70}ms` }}
    >
      <header className="vhead">
        <span className="vw">{g.name}</span>
        {g.level && <span className="vtag gtag">{g.level}</span>}
      </header>
      <div className="vbody">
        <span className="vpos">句型</span>
        <span className="vzh">{g.z}</span>
      </div>
      <div className="vmeta">
        <span className="vused">{g.ex}</span>
      </div>
    </article>
  );
}

/**
 * Cards for the line on stage: real dictionary words (lemma + reading + POS +
 * Chinese gloss + JLPT) plus any grammar pattern the line contains.
 *
 * The count adapts to the window so the row never has to cover the lyrics.
 */
export function VocabCards({ segment }: { segment: Segment | null }) {
  const budget = useCardBudget();
  const grammar = segment?.grammar ?? [];
  // grammar gets one slot when present, leaving the rest for vocabulary
  const wordLimit = grammar.length ? Math.max(1, budget - 1) : budget;
  const words = pickWords(segment, wordLimit);
  const empty = !words.length && !grammar.length;

  return (
    <div className={`vocab${empty ? " empty" : ""}`}>
      {words.map((w, i) => (
        <VocabCard key={`w-${segment?.id}-${w.text}`} w={w} i={i} />
      ))}
      {grammar.slice(0, 1).map((g) => (
        <GrammarCard key={`g-${segment?.id}-${g.id}`} g={g} i={words.length} />
      ))}
    </div>
  );
}
