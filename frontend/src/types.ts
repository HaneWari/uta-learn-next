/** One character with its own timing — the highlight granularity. */
export interface KanaChar {
  ch: string;
  start: number;
  end: number;
}

/** A grammar pattern found in a line. */
export interface GrammarHit {
  id: string;
  name: string;
  level: string;
  z: string;
  ex: string;
  matched: string;
  at?: number;
}

export interface WordTiming {
  text: string;
  romaji: string;
  lemma?: string; // dictionary form, e.g. 逃げた → 逃げる
  kana?: string; // reading, e.g. "にげた" over 逃げた
  lemma_kana?: string; // reading of the dictionary form
  chars?: KanaChar[]; // per-character timings
  start: number;
  end: number;
  score: number;
  pos?: string; // 动词 / 名词·固有名詞 …
  pos1?: string; // raw UniDic POS1
  content?: boolean; // worth a vocabulary card?
  jlpt?: string;
  zh?: string;
}

export interface Segment {
  id: number;
  start: number;
  end: number;
  text: string;
  romaji: string;
  translation_zh?: string;
  gloss_en?: string;
  /** user hid this lyric line — it stays in the dataset but is skipped on
      stage and in the video export */
  hidden?: boolean;
  /** stage edits to the sung line + its Chinese gloss, layered over the raw
      text so clearing a field never destroys the aligned original */
  lyric_override?: {
    text?: string;
    translation_zh?: string;
    /** re-tokenised words for an edited text: carries its own furigana,
        romaji and a re-estimated per-glyph wipe when the text changed */
    words?: WordTiming[];
  } | null;
  grammar?: GrammarHit[];
  words: WordTiming[];
  /** stage edits: which word indexes get a card, and hand-made extra cards */
  vocab_override?: {
    hide?: number[];
    /** per generated word index: replacement fields */
    replace?: Record<number, Partial<WordTiming>>;
    extra?: WordTiming[];
    /** display order of all cards (word + grammar), stored as card keys:
        `w${index}` / `wx${i}` for words, `g-${id}` / `gx${i}` for grammar.
        Legacy saves may hold generated word indexes (numbers) instead. */
    order?: Array<number | string>;
  } | null;
  /** stage edits: replacements + hand-made grammar cards */
  grammar_extra?: {
    remove?: string[];   // grammar ids to hide
    replace?: Record<string, Partial<GrammarHit>>;
    extra?: GrammarHit[];
  } | null;
}

export interface SongMeta {
  title: string;
  artist: string;
  youtube_url: string;
  language: string;
  duration_seconds: number;
  generated_at: string;
  whisperx_model: string;
  align_model: string;
  vocal_separation?: string;
  source?: string;
  source_kind?: string;
  /** whether audio.mp3 actually exists for this dataset */
  has_audio?: boolean;
  /** seconds the lyric timeline is shifted against the audio; positive plays
   *  the highlight later, negative earlier (-2 … 2, one decimal) */
  time_offset?: number;
  trans_hidden?: boolean;
}

export interface SongData {
  meta: SongMeta;
  segments: Segment[];
}

/* ---------- config API ---------- */

export interface SearchHit {
  source: string;
  id: string;
  title: string;
  artist: string;
  album: string;
  duration: number;
  kind: "char" | "line";
  extra: Record<string, unknown>;
}

export interface SongSummary {
  name: string;
  title: string;
  artist: string;
  duration: number;
  has_audio: boolean;
  source: string;
}

export interface UploadInfo {
  id: string;
  filename: string;
  duration: number;
  size: number;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  result: SongSummary & { segments: number } | null;
  error: string | null;
}

/* ---------- stage background ---------- */

export interface StageBackground {
  /** "default" = the paper theme; "custom" = the user's own image */
  mode: "default" | "custom";
  /** cache-busted URL of the stored image, null in default mode */
  url: string | null;
}
