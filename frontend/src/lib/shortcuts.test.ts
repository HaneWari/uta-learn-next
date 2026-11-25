import { describe, expect, it } from "vitest";
import { isTyping, resolveShortcut, SHORTCUTS } from "./shortcuts";

function key(k: string, mods: Partial<KeyboardEvent> = {}) {
  return {
    key: k,
    target: document.createElement("div"),
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    ...mods,
  } as unknown as KeyboardEvent;
}

describe("resolveShortcut", () => {
  it("maps the basic playback keys", () => {
    expect(resolveShortcut(key(" "))).toBe("toggle-play");
    expect(resolveShortcut(key("ArrowLeft"))).toBe("prev-line");
    expect(resolveShortcut(key("ArrowRight"))).toBe("next-line");
  });

  it("distinguishes the shift-seek from the line step", () => {
    expect(resolveShortcut(key("ArrowLeft", { shiftKey: true }))).toBe("seek-back");
  });

  it("maps the learning toggles", () => {
    expect(resolveShortcut(key("r"))).toBe("loop-line");
    expect(resolveShortcut(key("F"))).toBe("shadow");
    expect(resolveShortcut(key("t"))).toBe("toggle-trans");
    expect(resolveShortcut(key("k"))).toBe("toggle-cards");
  });

  it("requires ctrl for undo", () => {
    expect(resolveShortcut(key("z", { ctrlKey: true }))).toBe("undo");
    expect(resolveShortcut(key("z"))).toBeNull();
  });

  it("maps the speed keys", () => {
    expect(resolveShortcut(key("["))).toBe("rate-down");
    expect(resolveShortcut(key("]"))).toBe("rate-up");
  });

  it("ignores everything while typing in a field", () => {
    const input = document.createElement("input");
    const event = { ...key(" "), target: input } as unknown as KeyboardEvent;
    expect(resolveShortcut(event)).toBeNull();
  });

  it("returns null for an unmapped key", () => {
    expect(resolveShortcut(key("q"))).toBeNull();
  });
});

describe("isTyping", () => {
  it("recognises inputs, textareas and selects", () => {
    for (const tag of ["input", "textarea", "select"]) {
      expect(isTyping(document.createElement(tag))).toBe(true);
    }
  });

  it("is false for a plain element", () => {
    expect(isTyping(document.createElement("div"))).toBe(false);
  });
});

describe("SHORTCUTS table", () => {
  it("has no duplicate action+modifier pairs", () => {
    const seen = new Set<string>();
    for (const s of SHORTCUTS) {
      const id = `${s.action}:${s.shift ? 1 : 0}:${s.ctrl ? 1 : 0}`;
      expect(seen.has(id)).toBe(false);
      seen.add(id);
    }
  });

  it("every entry has a label and a group", () => {
    for (const s of SHORTCUTS) {
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.group.length).toBeGreaterThan(0);
    }
  });
});
