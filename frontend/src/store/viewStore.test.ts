import { beforeEach, describe, expect, it } from "vitest";
import { useViewStore } from "./viewStore";

beforeEach(() => {
  useViewStore.setState({
    choice: {},
    loopSegmentId: null,
    shadow: false,
    railOpen: false,
    song: null,
  });
});

describe("layer visibility", () => {
  it("falls back to the dataset value when the song was not touched", () => {
    const { hidden } = useViewStore.getState();
    expect(hidden("a", "cards", false)).toBe(false);
    expect(hidden("a", "cards", true)).toBe(true);
  });

  it("a toggle wins over the dataset value", () => {
    const { toggle } = useViewStore.getState();
    expect(toggle("a", "cards", false)).toBe(true);
    expect(useViewStore.getState().hidden("a", "cards", false)).toBe(true);
  });

  it("toggling twice returns to the dataset value", () => {
    const { toggle } = useViewStore.getState();
    toggle("a", "romaji", false);
    expect(toggle("a", "romaji", false)).toBe(false);
    expect(useViewStore.getState().hidden("a", "romaji", false)).toBe(false);
  });

  it("keeps songs independent", () => {
    const { toggle, hidden } = useViewStore.getState();
    toggle("a", "cards", false);
    expect(hidden("a", "cards", false)).toBe(true);
    expect(hidden("b", "cards", false)).toBe(false);
  });

  it("all five layers are addressable", () => {
    const { toggle } = useViewStore.getState();
    for (const key of ["cards", "translation", "furigana", "romaji", "next_line"] as const) {
      toggle("a", key, false);
      expect(useViewStore.getState().hidden("a", key, false)).toBe(true);
    }
  });
});

describe("song switch", () => {
  it("drops this song's overrides and the loop", () => {
    const s = useViewStore.getState();
    // a real session enters a song first, then edits it
    s.resetForSong("a");
    s.toggle("a", "cards", false);
    s.setLoop(7);
    s.resetForSong("b");
    const after = useViewStore.getState();
    expect(after.hidden("a", "cards", false)).toBe(false);
    expect(after.loopSegmentId).toBeNull();
  });

  it("is a no-op for the same song", () => {
    const s = useViewStore.getState();
    s.resetForSong("a");
    s.toggle("a", "cards", false);
    s.resetForSong("a");
    expect(useViewStore.getState().hidden("a", "cards", false)).toBe(true);
  });

  it("the first call adopts the song without wiping its overrides", () => {
    const s = useViewStore.getState();
    s.toggle("a", "cards", false);
    s.resetForSong("a");
    expect(useViewStore.getState().hidden("a", "cards", false)).toBe(true);
  });
});

describe("rail and shadow", () => {
  it("stores the rail state for the shortcut and the button", () => {
    useViewStore.getState().setRail(true);
    expect(useViewStore.getState().railOpen).toBe(true);
  });

  it("stores 跟读", () => {
    useViewStore.getState().setShadow(true);
    expect(useViewStore.getState().shadow).toBe(true);
  });
});
