import { describe, expect, it } from "vitest";

/**
 * The AB-loop range rules, extracted so they can be checked without a DOM.
 * `usePlayback` applies exactly this clamp before storing the range.
 */
function normalise(start: number, end: number) {
  const lo = Math.max(0, Math.min(start, end));
  const hi = Math.max(start, end);
  return hi - lo >= 1 ? { start: lo, end: hi } : null;
}

describe("AB loop range", () => {
  it("keeps a dragged forward range", () => {
    expect(normalise(10, 16)).toEqual({ start: 10, end: 16 });
  });

  it("tolerates dragging backwards", () => {
    expect(normalise(16, 10)).toEqual({ start: 10, end: 16 });
  });

  it("clamps a negative start to zero", () => {
    expect(normalise(-3, 4)).toEqual({ start: 0, end: 4 });
  });

  it("rejects a range shorter than a second", () => {
    expect(normalise(10, 10.4)).toBeNull();
  });

  it("keeps a range of exactly one second", () => {
    expect(normalise(10, 11)).toEqual({ start: 10, end: 11 });
  });
});

describe("逐行微调 clamping", () => {
  const clamp = (value: number) =>
    Math.max(-2, Math.min(2, Math.round(value * 10) / 10));

  it("rounds to one decimal", () => {
    expect(clamp(0.30000000000000004)).toBe(0.3);
  });

  it("never leaves the ±2 s window", () => {
    expect(clamp(2.5)).toBe(2);
    expect(clamp(-2.5)).toBe(-2);
  });
});
