import { beforeEach, describe, expect, it } from "vitest";
import { clearUndo, popUndo, pushUndo, undoDepth } from "./saveQueue";

function entry(song: string, label = "词条编辑") {
  return { song, label, segmentId: 1, restore: { hidden: null } };
}

beforeEach(() => clearUndo());

describe("undo stack", () => {
  it("pops the newest entry first", () => {
    pushUndo(entry("a", "first"));
    pushUndo(entry("a", "second"));
    expect(popUndo("a")?.label).toBe("second");
    expect(popUndo("a")?.label).toBe("first");
  });

  it("only returns entries from the requested song", () => {
    pushUndo(entry("a"));
    pushUndo(entry("b"));
    expect(popUndo("a")?.song).toBe("a");
    expect(popUndo("a")).toBeNull();
    expect(undoDepth("b")).toBe(1);
  });

  it("returns the newest overall when no song is given", () => {
    pushUndo(entry("a"));
    pushUndo(entry("b"));
    expect(popUndo()?.song).toBe("b");
  });

  it("is empty after clearing", () => {
    pushUndo(entry("a"));
    clearUndo();
    expect(undoDepth()).toBe(0);
    expect(popUndo("a")).toBeNull();
  });

  it("keeps at most 20 steps", () => {
    for (let i = 0; i < 25; i += 1) pushUndo(entry("a", `step-${i}`));
    expect(undoDepth("a")).toBe(20);
    expect(popUndo("a")?.label).toBe("step-24");
  });
});
