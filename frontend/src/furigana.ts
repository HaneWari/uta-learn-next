import type { KanaChar } from "./types";

/** Kanji (and the iteration marks that behave like one). */
const KANJI = /[\u3400-\u4dbf\u4e00-\u9fff々〆ヵヶ]/;

export const isKanji = (ch: string) => KANJI.test(ch);

/** One ruby unit: a run of characters sharing a single reading above them. */
export interface RubyGroup {
  /** shown above the group; absent for kana-only groups */
  reading?: string;
  chars: KanaChar[];
}

interface WordLike {
  text: string;
  kana?: string;
  chars?: KanaChar[];
}

interface Draft extends RubyGroup {
  kanji: boolean;
}

function charsOf(word: WordLike): KanaChar[] {
  if (word.chars && word.chars.length) return word.chars;
  return [...word.text].map((ch) => ({ ch, start: 0, end: 0 }));
}

/**
 * Split a word into ruby groups so only kanji carry a reading.
 *
 * Japanese lyrics spell plenty of words in kana (あきらめる, コト). Annotating
 * those with the identical kana above them is pure noise, so a kana-only word
 * gets no reading at all, and inside a mixed word the okurigana is left bare
 * while the kanji run keeps its reading.
 *
 *   逃げ / にげ        →  [逃:に] [げ]
 *   東京 / とうきょう   →  [東京:とうきょう]
 *   あきらめる         →  [あ] [き] [ら] [め] [る]   (no readings)
 */
export function rubyGroups(word: WordLike): RubyGroup[] {
  const chars = charsOf(word);
  const surface = chars.map((c) => c.ch).join("");
  const reading = word.kana ?? "";

  const plain = (): RubyGroup[] => chars.map((c) => ({ chars: [c] }));

  if (!reading || ![...surface].some(isKanji)) return plain();

  // Strip the kana that surface and reading share at both ends; what is left
  // is the reading of the kanji run(s) alone.
  const s = [...surface];
  let lo = 0;
  let rlo = 0;
  while (lo < s.length && rlo < reading.length && s[lo] === reading[rlo]) {
    lo += 1;
    rlo += 1;
  }
  let hi = s.length;
  let rhi = reading.length;
  while (hi > lo && rhi > rlo && s[hi - 1] === reading[rhi - 1]) {
    hi -= 1;
    rhi -= 1;
  }
  const core = reading.slice(rlo, rhi);

  // Maximal runs of "kanji" and "not kanji".
  const drafts: Draft[] = [];
  let i = 0;
  while (i < chars.length) {
    const kanji = isKanji(chars[i].ch);
    let j = i + 1;
    while (j < chars.length && isKanji(chars[j].ch) === kanji) j += 1;
    drafts.push({ chars: chars.slice(i, j), kanji });
    i = j;
  }

  const kanjiRuns = drafts.filter((d) => d.kanji);
  if (!kanjiRuns.length || !core) return plain();

  if (kanjiRuns.length === 1) {
    kanjiRuns[0].reading = core;
    return drafts.map((d) => ({ chars: d.chars, reading: d.reading }));
  }

  // Several kanji runs (話し合い, 打ち合わせ, 食べ物). Splitting the reading
  // between them by character count is guesswork and gets it wrong: 話し合い
  // would hand しあ to 合 when 合 is only あ. Merge the whole span from the
  // first to the last kanji into one group — the reading really does cover
  // exactly that span, so it is coarse but never wrong.
  const first = drafts.findIndex((d) => d.kanji);
  let last = drafts.length - 1;
  while (last > first && !drafts[last].kanji) last -= 1;

  const merged: Draft = {
    kanji: true,
    reading: core,
    chars: drafts.slice(first, last + 1).flatMap((d) => d.chars),
  };

  const out: RubyGroup[] = drafts
    .slice(0, first)
    .map((d) => ({ chars: d.chars, reading: d.reading }));
  out.push({ chars: merged.chars, reading: merged.reading });
  out.push(
    ...drafts.slice(last + 1).map((d) => ({ chars: d.chars, reading: d.reading })),
  );
  return out;
}
