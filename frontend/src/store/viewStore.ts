import { create } from "zustand";

/**
 * Stage display state (§5.7): which lyric layers are visible, the loop mode,
 * and 跟读.
 *
 * This used to travel as a `layers={...}` object plus five `onToggle*`
 * callbacks through App → Stage → LyricsDisplay/VocabCards. With zustand each
 * component reads the slice it needs, and the "one place for the switches"
 * rule from the plan is enforced by the store rather than by passing props
 * correctly at every level.
 *
 * `meta.view` on the server stays the source of truth for persistence; the
 * store holds the session value and calls the PATCH route.
 */
export type LayerKey = "cards" | "translation" | "furigana" | "romaji" | "next_line";

export const LAYER_LABELS: Record<LayerKey, string> = {
  cards: "词条卡片",
  translation: "中文翻译",
  furigana: "注音",
  romaji: "罗马音",
  next_line: "下一句",
};

interface ViewState {
  /** per-song overrides for this session; absent = use the dataset's value */
  choice: Record<string, Record<string, boolean>>;
  loopSegmentId: number | null;
  shadow: boolean;
  railOpen: boolean;
  /** song the overrides belong to; switching songs clears them */
  song: string | null;
  hidden: (song: string, key: LayerKey, fromDataset: boolean) => boolean;
  toggle: (song: string, key: LayerKey, fromDataset: boolean) => boolean;
  setLoop: (segmentId: number | null) => void;
  setShadow: (on: boolean) => void;
  setRail: (open: boolean) => void;
  resetForSong: (song: string | null) => void;
}

export const useViewStore = create<ViewState>((set, get) => ({
  choice: {},
  loopSegmentId: null,
  shadow: false,
  railOpen: false,
  song: null,

  hidden: (song, key, fromDataset) => {
    const chosen = get().choice[song]?.[key];
    return chosen === undefined ? fromDataset : chosen;
  },

  toggle: (song, key, fromDataset) => {
    const current = get().hidden(song, key, fromDataset);
    const next = !current;
    set((s) => ({
      choice: { ...s.choice, [song]: { ...(s.choice[song] ?? {}), [key]: next } },
    }));
    return next;
  },

  setLoop: (segmentId) => set({ loopSegmentId: segmentId }),
  setShadow: (on) => set({ shadow: on }),
  setRail: (open) => set({ railOpen: open }),
  resetForSong: (song) => {
    const current = get().song;
    // the first call (no song yet) must adopt the song without wiping the
    // overrides that were already made for it
    if (current === song) return;
    if (current === null) {
      set({ song });
      return;
    }
    set({ song, choice: {}, loopSegmentId: null });
  },
}));
