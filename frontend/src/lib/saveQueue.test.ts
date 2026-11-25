import { describe, expect, it } from "vitest";
import { clearFailure, enqueue, onSaveFailure, reportFailure } from "./saveQueue";

describe("enqueue", () => {
  it("runs tasks for the same song one after another", async () => {
    const order: string[] = [];
    const slow = enqueue("a", async () => {
      await new Promise((r) => setTimeout(r, 30));
      order.push("first");
    });
    const fast = enqueue("a", async () => {
      order.push("second");
    });
    await Promise.all([slow, fast]);
    expect(order).toEqual(["first", "second"]);
  });

  it("keeps independent songs independent", async () => {
    const order: string[] = [];
    await Promise.all([
      enqueue("a", async () => {
        await new Promise((r) => setTimeout(r, 30));
        order.push("a");
      }),
      enqueue("b", async () => order.push("b")),
    ]);
    expect(order).toEqual(["b", "a"]);
  });

  it("a rejected task does not stall the queue", async () => {
    const order: string[] = [];
    await enqueue("c", async () => {
      throw new Error("boom");
    }).catch(() => undefined);
    await enqueue("c", async () => order.push("after"));
    expect(order).toEqual(["after"]);
  });
});

describe("failure reporting", () => {
  it("delivers the failure and the retry", () => {
    const seen: string[] = [];
    onSaveFailure((f) => {
      if (f) seen.push(f.message);
    });
    reportFailure("HTTP 409", () => seen.push("retry"));
    expect(seen).toEqual(["HTTP 409"]);
    clearFailure();
    onSaveFailure(null);
  });

  it("clearing is a no-op without a listener", () => {
    onSaveFailure(null);
    expect(() => clearFailure()).not.toThrow();
  });
});
