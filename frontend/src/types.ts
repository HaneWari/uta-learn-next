/** One character with its own timing — the highlight granularity. */
/* The API surface itself is generated (see `api-types.ts`); the hand-written
   shapes below stay for the parts FastAPI cannot describe — the dataset file
   it returns verbatim, and the UI's own view state. `ApiSchema` is re-exported
   so a caller can type a response without importing the generated file. */
import type { components } from "./api-types";

export type ApiSchema = components["schemas"];

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
  /** romaji of the literal spelling: は → "ha" (particles differ from `romaji`) */
  romaji_literal?: string;
  /** sung reading of the word; particles keep their grammatical spelling */
  pron?: string;
  /** literal kana spelling (`kana` is the reading used for the wipe) */
  kana_literal?: string;
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
  /** this line's own offset against the audio, on top of `meta.time_offset`;
      set by 逐行微调 (§5.3.3) */
  line_offset?: number;
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
  /** whether the dataset actually carries an audio file */
  has_audio?: boolean;
  /** the audio file name inside the folder, e.g. audio.flac */
  audio_file?: string;
  /** seconds the lyric timeline is shifted against the audio; positive plays
   *  the highlight later, negative earlier (-2 … 2, one decimal) */
  time_offset?: number;
  trans_hidden?: boolean;
  /** song-wide display layers; a missing key means "visible" */
  view?: Record<string, boolean>;
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
  /** true when the duration is within 2 s of the uploaded audio */
  duration_match?: boolean;
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
  /** jobs v2 adds cancel + restart recovery to the old four states */
  status: "queued" | "running" | "done" | "error" | "canceled" | "interrupted";
  /** scheduler resource: cpu / export / net */
  resource?: string;
  /** human-readable step, e.g. 下载 / 转写 / 渲染 */
  stage?: string;
  progress: number;
  message: string;
  result: SongSummary & { segments: number } | null;
  error: string | null;
}

/* ---------- export environment ---------- */

export interface ExportEnv {
  ok: boolean;
  /** `no_recorder` no longer occurs: the frame renderer needs no recorder */
  state: "ok" | "no_playwright" | "no_browser" | "no_ffmpeg";
  checks: {
    playwright: boolean;
    browser_path: string | null;
    bundled_chromium: boolean;
    browser_launch: boolean;
    launch_error: string;
    /** whether 兼容模式 could record (not needed by the default path) */
    record_video: boolean;
    compat_ready?: boolean;
    record_error: string;
    ffmpeg: boolean;
    candidates: string[];
  };
}

/* ---------- stage background ---------- */

export interface StageBackground {
  /** "default" = the paper theme; "custom" = the user's own image */
  mode: "default" | "custom";
  /** cache-busted URL of the stored image, null in default mode */
  url: string | null;
}

/* ---------- settings ---------- */

export interface AppSettings {
  update_check: boolean;
  telemetry: boolean;
  confirm_close: boolean;
  particle_reading: "pron" | "literal";
  long_vowel: "ou" | "macron" | "oo";
  theme: "system" | "light" | "dark";
  reduce_motion: boolean;
  ui_font: "s" | "m" | "l";
  page_zoom: number;
  default_layers: {
    furigana: boolean;
    romaji: boolean;
    translation: boolean;
    next_line: boolean;
    cards: boolean;
  };
  jlpt_max: number;
  proxy_mode: "auto" | "system" | "manual" | "off";
  proxy_url: string;
  export_preset: "landscape" | "portrait" | "4k";
  export_pages: number;
  export_compat: boolean;
  install_id: string;
  telemetry_last_day: string;
}

export interface AboutInfo {
  name: string;
  version: string;
  python: string;
  os: string;
  hostname: string;
  paths: { app: string; data: string; exports: string };
  packs: { custom_lyrics: boolean; chromium: boolean };
  dev: boolean;
}

/** 设置 → 扩展包 的一行:装没装、占多大 */
export interface PackStatus {
  key: "custom_lyrics" | "chromium";
  installed: boolean;
  path: string;
  size: number;
}

/** one saved encounter in the personal word book */
export interface VocabEntry {
  song: string;
  song_title: string;
  segment_id: number;
  text: string;
  kana: string;
  romaji: string;
  pos: string;
  jlpt: string;
  zh: string;
  line: string;
  at: number;
  added_at: number;
}
