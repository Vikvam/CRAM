/**
 * How a list of words reads a word (PLAN 6, phase 4).
 *
 * A search result is a *word*, not one direction of it, so unlike a Progress row
 * it has two standings to show and has to choose. It takes the worse one, which
 * is the same rule the server's `weakest` keeps and for the same reason: a word
 * you can read but cannot write is not a word you know, and the row should mark
 * the hole rather than flatter it.
 */

/** Weakest first, which is also the order they are climbed in. */
export const STANDINGS = ["new", "learning", "known", "mastered"] as const;

export type Standing = (typeof STANDINGS)[number];

/**
 * The worse of a note's two directions, or null when it has no cards at all.
 *
 * Nulls are dropped rather than counted as `new`: a directional note has no
 * reverse card, and calling the missing half "not learned" would put every
 * one-way word in the collection at the bottom of the pile for ever.
 */
export function weakest(
  ...of: (Standing | null | undefined)[]
): Standing | null {
  const known = of.filter((one): one is Standing => one != null);
  if (!known.length) return null;
  return known.reduce((a, b) =>
    STANDINGS.indexOf(a) <= STANDINGS.indexOf(b) ? a : b,
  );
}
