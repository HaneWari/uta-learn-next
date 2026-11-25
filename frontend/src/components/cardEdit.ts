import type { GrammarHit, WordTiming } from "../types";

/* Editable card model. Kept apart from the components so the component
   file exports only components — react-refresh needs that to hot-reload.
   The converters translate between a `WordTiming` / `GrammarHit` and the
   flat string fields the editor shows. */

export interface VocabEdit {
  text: string;
  kana: string;
  romaji: string;
  pos: string;
  zh: string;
  jlpt: string;
  /** the form actually sung — only kept when it differs from `text` */
  used: string;
}

export interface GrammarEdit {
  name: string;
  level: string;
  z: string;
  ex: string;
}

export function wordToEdit(w: WordTiming): VocabEdit {
  const isLemma = !!w.lemma && w.lemma !== w.text;
  const head = isLemma ? w.lemma! : w.text;
  const raw = isLemma ? w.lemma_kana ?? w.kana : w.kana;
  return {
    text: head,
    kana: raw && raw !== head ? raw : "",
    romaji: w.romaji ?? "",
    pos: w.pos ?? "",
    zh: w.zh ?? "",
    jlpt: w.jlpt ?? "",
    used: isLemma ? w.text : "",
  };
}

export function editToWord(e: VocabEdit): WordTiming {
  const used = e.used.trim();
  return {
    text: used || e.text,
    lemma: used && used !== e.text ? e.text : e.text,
    kana: e.kana || undefined,
    lemma_kana: used && used !== e.text ? e.kana || undefined : undefined,
    romaji: e.romaji,
    pos: e.pos || undefined,
    zh: e.zh,
    jlpt: e.jlpt || undefined,
    content: true,
    start: 0,
    end: 0,
    score: 0,
  };
}

export function grammarToEdit(g: GrammarHit): GrammarEdit {
  return { name: g.name, level: g.level ?? "", z: g.z, ex: g.ex ?? "" };
}
