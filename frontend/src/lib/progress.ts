/**
 * Laying out what the overview endpoint sends (PLAN 6, phase 4).
 *
 * The server counts; this only arranges. Days arrive as plain `YYYY-MM-DD`
 * strings already shifted into the client's own timezone, so everything here
 * is string arithmetic at UTC noon — no local-midnight surprises.
 */
import type { Day, Mastery } from "$lib/api/client";

export const GRID_WEEKS = 26;
/** Narrow as the grid gets, never narrower: a fortnight of squares is not a habit. */
export const GRID_MINIMUM = 8;
/** Monday first: a week of study reads better starting where the week does. */
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const LEVELS = 4;

export interface Cell {
  day: string;
  reviews: number;
  correct: number;
  /** 0 for a day with nothing, then 1…4 against the busiest day shown. */
  level: number;
  /** The tail of the current week: part of the grid, not yet a day you missed. */
  future: boolean;
}

const asDate = (iso: string) => new Date(`${iso}T12:00:00Z`);
const asIso = (date: Date) => date.toISOString().slice(0, 10);

function shift(iso: string, days: number): string {
  const date = asDate(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return asIso(date);
}

/** Monday-first weekday index of an ISO day. */
export function weekday(iso: string): number {
  return (asDate(iso).getUTCDay() + 6) % 7;
}

/**
 * The activity grid: one column per week, seven rows, oldest week first.
 *
 * `today` is the last day the grid reaches — the server's last row, which is
 * always the client's today even when nothing was answered on it.
 */
export function heatmap(
  days: Day[],
  options: { weeks?: number; today?: string } = {},
): Cell[][] {
  const columns = Math.max(1, options.weeks ?? GRID_WEEKS);
  const today = options.today ?? days.at(-1)?.day ?? asIso(new Date());
  const counts = new Map(days.map((d) => [d.day, d]));
  const busiest = Math.max(
    0,
    ...days.filter((d) => d.day <= today).map((d) => d.reviews),
  );
  const start = shift(today, -weekday(today) - 7 * (columns - 1));

  return Array.from({ length: columns }, (_, column) =>
    Array.from({ length: 7 }, (_, row) => {
      const day = shift(start, column * 7 + row);
      const found = counts.get(day);
      const reviews = found?.reviews ?? 0;
      return {
        day,
        reviews,
        correct: found?.correct ?? 0,
        level: reviews && busiest ? Math.ceil((LEVELS * reviews) / busiest) : 0,
        future: day > today,
      };
    }),
  );
}

/**
 * How many weeks of grid this history is worth.
 *
 * Half a year of columns for a fortnight of practice is nine-tenths empty
 * padding, and it makes a real run of days look like an accident. So the grid
 * starts where the answers start — or `GRID_MINIMUM` weeks back, whichever is
 * further, so the first week is still drawn as part of something.
 */
export function spanWeeks(days: Day[], today = days.at(-1)?.day): number {
  const first = days.find((day) => day.reviews > 0)?.day;
  if (!first || !today) return GRID_MINIMUM;
  const span =
    (asDate(today).getTime() - asDate(first).getTime()) /
    (7 * 24 * 3600 * 1000);
  return Math.min(GRID_WEEKS, Math.max(GRID_MINIMUM, Math.ceil(span) + 1));
}

/** Days answered on, and the longest run of them ending today or yesterday. */
export function streak(days: Day[], today = days.at(-1)?.day): number {
  if (!today) return 0;
  const active = new Set(days.filter((d) => d.reviews > 0).map((d) => d.day));
  let from = active.has(today) ? today : shift(today, -1);
  if (!active.has(from)) return 0;
  let length = 0;
  while (active.has(from)) {
    length += 1;
    from = shift(from, -1);
  }
  return length;
}

export interface Bar {
  bucket: "mastered" | "known" | "learning" | "new";
  count: number;
  percent: number;
}

/** Counted in notes: a word asked both ways is one, at its weaker direction. */
export type Counted = {
  notes: number;
  mastered: number;
  known: number;
  learning: number;
  new: number;
  settled?: number;
};

/** The four parts of one mastery bar, strongest first — widths, not a score.
 *  Takes anything counted in buckets: a category, a lesson or a heading. */
export function bars(row: Counted): Bar[] {
  const total = row.notes || 1;
  return (["mastered", "known", "learning", "new"] as const).map((bucket) => ({
    bucket,
    count: row[bucket],
    percent: (100 * row[bucket]) / total,
  }));
}

/**
 * What one clean answer is worth, in the order the ladder climbs.
 *
 * Mirrors `POINTS` in `memo/overview/progress.py` — stated in both places
 * because the page has to explain the rule without asking the server to write
 * its prose. The thresholds themselves do come from the server (`rule`), since
 * those are the numbers a reader will argue with.
 */
export const LADDER: { points: number; what: string }[] = [
  { points: 1, what: "picking what a word means" },
  { points: 2, what: "picking the word itself, or judging a flip" },
  { points: 3, what: "writing what a word means, or building it from pieces" },
  { points: 4, what: "writing the word from memory" },
];

/** Several scopes added up — the whole collection is its top-level categories. */
export function sum(rows: Counted[]): Required<Counted> {
  return rows.reduce<Required<Counted>>(
    (total, row) => ({
      notes: total.notes + row.notes,
      mastered: total.mastered + row.mastered,
      known: total.known + row.known,
      learning: total.learning + row.learning,
      new: total.new + row.new,
      settled: total.settled + (row.settled ?? 0),
    }),
    { notes: 0, mastered: 0, known: 0, learning: 0, new: 0, settled: 0 },
  );
}

/**
 * The categories directly under `parent` — or the top of the tree for null —
 * that have anything in them to learn. The server sends the whole tree flat,
 * in path order, each row already counting everything beneath it.
 */
export function childrenOf(rows: Mastery[], parent: Mastery | null): Mastery[] {
  return rows.filter(
    (row) =>
      row.notes > 0 &&
      (parent === null
        ? row.depth === 0
        : row.depth === parent.depth + 1 &&
          row.path.startsWith(`${parent.path}/`)),
  );
}

/** The category one level up, or null at the top. */
export function parentOf(rows: Mastery[], row: Mastery): Mastery | null {
  const path = row.path.split("/").slice(0, -1).join("/");
  return path ? (rows.find((other) => other.path === path) ?? null) : null;
}
