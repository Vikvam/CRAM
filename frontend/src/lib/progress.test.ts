import { describe, expect, test } from "vitest";
import {
  GRID_MINIMUM,
  GRID_WEEKS,
  bars,
  childrenOf,
  heatmap,
  parentOf,
  spanWeeks,
  streak,
  sum,
  weekday,
} from "./progress";
import type { Mastery } from "$lib/api/client";
import type { Day } from "$lib/api/client";

const day = (d: string, reviews: number, correct = reviews): Day => ({
  day: d,
  reviews,
  correct,
});

describe("how wide the grid should be", () => {
  test("half a year of columns for a fortnight of answers is mostly padding", () => {
    const fortnight = [day("2026-09-28", 5), day("2026-10-08", 5)];
    expect(spanWeeks(fortnight)).toBe(GRID_MINIMUM);
  });

  test("it grows with the history, up to the half year it used to always be", () => {
    expect(spanWeeks([day("2026-04-08", 1), day("2026-10-08", 1)])).toBe(
      GRID_WEEKS,
    );
    expect(spanWeeks([day("2024-01-01", 1), day("2026-10-08", 1)])).toBe(
      GRID_WEEKS,
    );
    const quarter = spanWeeks([day("2026-07-08", 1), day("2026-10-08", 1)]);
    expect(quarter).toBeGreaterThan(GRID_MINIMUM);
    expect(quarter).toBeLessThan(GRID_WEEKS);
  });

  test("a day with nothing on it does not start the grid", () => {
    // The server sends today even when it is empty, so it must not count.
    expect(spanWeeks([day("2026-04-08", 0), day("2026-10-08", 3)])).toBe(
      GRID_MINIMUM,
    );
  });

  test("no history at all is still a grid", () => {
    expect(spanWeeks([])).toBe(GRID_MINIMUM);
    expect(spanWeeks([day("2026-10-08", 0)])).toBe(GRID_MINIMUM);
  });
});

describe("the activity grid (PLAN 6, phase 4)", () => {
  test("a column is a week, Monday at the top", () => {
    // 2026-10-08 is a Thursday.
    expect(weekday("2026-10-05")).toBe(0);
    expect(weekday("2026-10-08")).toBe(3);
    const grid = heatmap([day("2026-10-08", 1)], { weeks: 3 });
    expect(grid).toHaveLength(3);
    expect(grid.every((column) => column.length === 7)).toBe(true);
    expect(grid.at(-1)![0].day).toBe("2026-10-05");
    expect(grid.at(-1)![3].day).toBe("2026-10-08");
  });

  test("the grid starts on a Monday however long it is", () => {
    for (const weeks of [1, 4, 26, 52]) {
      const grid = heatmap([day("2026-10-08", 1)], { weeks });
      expect(weekday(grid[0][0].day)).toBe(0);
    }
  });

  test("days with nothing answered are cells all the same", () => {
    const grid = heatmap([day("2026-10-08", 3)], { weeks: 1 });
    expect(grid[0].map((c) => c.reviews)).toEqual([0, 0, 0, 3, 0, 0, 0]);
    expect(grid[0][0].level).toBe(0);
  });

  test("the rest of this week is future, not failure", () => {
    const grid = heatmap([day("2026-10-08", 1)], {
      weeks: 1,
      today: "2026-10-08",
    });
    expect(grid[0].map((c) => c.future)).toEqual([
      false,
      false,
      false,
      false,
      true,
      true,
      true,
    ]);
  });

  test("shade runs from one to four against the busiest day shown", () => {
    const grid = heatmap(
      [
        day("2026-10-05", 1),
        day("2026-10-06", 20),
        day("2026-10-07", 40),
        day("2026-10-08", 0),
      ],
      { weeks: 1 },
    );
    expect(grid[0].slice(0, 4).map((c) => c.level)).toEqual([1, 2, 4, 0]);
  });

  test("nothing answered at all is a grid of empty days", () => {
    const grid = heatmap([day("2026-10-08", 0)], { weeks: 2 });
    expect(grid.flat().every((c) => c.level === 0)).toBe(true);
  });

  test("a streak counts back from today, and survives today being empty", () => {
    const days = [
      day("2026-10-05", 2),
      day("2026-10-06", 1),
      day("2026-10-07", 3),
      day("2026-10-08", 0),
    ];
    expect(streak(days, "2026-10-08")).toBe(3);
    expect(
      streak([...days.slice(0, 3), day("2026-10-08", 1)], "2026-10-08"),
    ).toBe(4);
  });

  test("a gap ends the streak", () => {
    const days = [
      day("2026-10-01", 5),
      day("2026-10-07", 1),
      day("2026-10-08", 1),
    ];
    expect(streak(days, "2026-10-08")).toBe(2);
    expect(
      streak([day("2026-10-01", 5), day("2026-10-08", 0)], "2026-10-08"),
    ).toBe(0);
  });
});

describe("mastery bars", () => {
  const row = (
    notes: number,
    mastered: number,
    known: number,
    learning: number,
    newer: number,
  ) => ({
    notes,
    mastered,
    known,
    learning,
    new: newer,
  });

  test("the strongest comes first and the parts fill the bar", () => {
    const out = bars(row(10, 2, 3, 3, 2));
    expect(out.map((b) => b.bucket)).toEqual([
      "mastered",
      "known",
      "learning",
      "new",
    ]);
    expect(out.map((b) => b.percent)).toEqual([20, 30, 30, 20]);
  });

  test("an empty category has an empty bar, not a division by zero", () => {
    expect(bars(row(0, 0, 0, 0, 0)).map((b) => b.percent)).toEqual([
      0, 0, 0, 0,
    ]);
  });
});

describe("the tree", () => {
  const category = (path: string, notes = 1): Mastery => ({
    category_id: path,
    path,
    label: null,
    depth: path.split("/").length - 1,
    notes,
    new: notes,
    learning: 0,
    known: 0,
    mastered: 0,
    settled: 0,
  });
  const rows = [
    category("korean", 3),
    category("korean/book1", 2),
    category("korean/book1/l1", 2),
    category("korean/book10", 1),
    category("korean/empty", 0),
    category("spanish", 4),
  ];

  test("the top is every root with something in it", () => {
    expect(childrenOf(rows, null).map((r) => r.path)).toEqual([
      "korean",
      "spanish",
    ]);
  });

  test("children are one level down, and a sibling with the same start is not one", () => {
    expect(childrenOf(rows, rows[0]).map((r) => r.path)).toEqual([
      "korean/book1",
      "korean/book10",
    ]);
    expect(childrenOf(rows, rows[1]).map((r) => r.path)).toEqual([
      "korean/book1/l1",
    ]);
  });

  test("a parent is one level up, and the top has none", () => {
    expect(parentOf(rows, rows[2])?.path).toBe("korean/book1");
    expect(parentOf(rows, rows[0])).toBeNull();
  });

  test("scopes add up", () => {
    expect(sum([rows[0], rows[5]])).toEqual({
      notes: 7,
      mastered: 0,
      known: 0,
      learning: 0,
      new: 7,
      settled: 0,
    });
  });
});
