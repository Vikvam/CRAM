import { describe, expect, it } from "vitest";
import { STANDINGS, weakest } from "./words";

describe("weakest", () => {
  it("takes the worse of the two directions", () => {
    expect(weakest("mastered", "learning")).toBe("learning");
    expect(weakest("learning", "mastered")).toBe("learning");
    expect(weakest("known", "known")).toBe("known");
  });

  it("ignores a direction the note has no card for", () => {
    expect(weakest("mastered", null)).toBe("mastered");
    expect(weakest(null, "new")).toBe("new");
  });

  it("says nothing at all about a note with no cards", () => {
    expect(weakest()).toBeNull();
    expect(weakest(null, undefined)).toBeNull();
  });

  it("agrees with the order the buckets are climbed in", () => {
    expect([...STANDINGS]).toEqual(["new", "learning", "known", "mastered"]);
    // Every pair: the earlier one always wins.
    for (const [i, worse] of STANDINGS.entries()) {
      for (const better of STANDINGS.slice(i)) {
        expect(weakest(worse, better)).toBe(worse);
      }
    }
  });
});
