import type { AppSettings } from "../types";

/**
 * Romaji is generated in the browser, never baked into a dataset.
 *
 * The backend stores both readings of a word (`romaji` = how it is sung,
 * `romaji_literal` = how it is spelled), so switching 助词读法 or 长音写法
 * takes effect immediately for every song, including ones generated before
 * the setting existed. Baking a single form into `song_data.json` would force
 * a regeneration per preference.
 */

const MACRONS: Record<string, string> = {
  a: "ā",
  i: "ī",
  u: "ū",
  e: "ē",
  o: "ō",
};

/** Rewrite long vowels: `toukyou` → `tōkyō` / `tookyoo`. */
export function restyleLongVowel(
  romaji: string,
  style: AppSettings["long_vowel"] = "ou",
): string {
  if (style === "ou" || !romaji) return romaji;
  let out = "";
  for (let i = 0; i < romaji.length; i += 1) {
    const ch = romaji[i];
    const next = romaji[i + 1];
    if ("aeiou".includes(ch) && next === "u") {
      if (style === "macron") out += MACRONS[ch] ?? ch;
      else out += ch === "o" ? "oo" : ch + ch;
      i += 1;
      continue;
    }
    out += ch;
  }
  return out;
}

interface RomajiWord {
  romaji?: string;
  romaji_literal?: string;
}

/** Pick the reading the user's settings ask for, then restyle its vowels. */
export function displayRomaji(
  word: RomajiWord,
  settings: Pick<AppSettings, "particle_reading" | "long_vowel">,
): string {
  const base =
    (settings.particle_reading === "literal"
      ? word.romaji_literal ?? word.romaji
      : word.romaji) ?? "";
  return restyleLongVowel(base, settings.long_vowel);
}

/** A whole line's romaji, one space per word, empty words dropped. */
export function lineRomaji(
  words: RomajiWord[],
  settings: Pick<AppSettings, "particle_reading" | "long_vowel">,
): string {
  return words
    .map((w) => displayRomaji(w, settings))
    .filter(Boolean)
    .join(" ");
}
