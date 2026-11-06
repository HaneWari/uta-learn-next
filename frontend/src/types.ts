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
  grammar?: GrammarHit[];
  words: WordTiming[];
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
