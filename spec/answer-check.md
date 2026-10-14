# Answer checking — the spec

The checker has **one implementation**, in the TypeScript client (PLAN 5): checking must be
instant and must keep working offline. This file and `answer-check.vectors.json` are its
specification. Any other implementation — a Python port, a second client — must pass the same
vectors.

The result is **one of three outcomes, never a number** (PLAN 3.5). The goal is learning; scoring
is secondary.

## 1. Normalise both sides

In order:

1. Unicode **NFC**.
2. Fold every dash to a plain hyphen `-`: U+2010–2015 (hyphen, non-breaking hyphen, figure,
   en, em, horizontal bar), U+2212 minus sign, U+2043, U+2E3A–2E3B, U+FE58, U+FE63, U+FF0D.
   A soft hyphen (U+00AD) is removed. U+30FC is **not** folded — it is a letter in Japanese,
   not punctuation.
3. Strip Markdown and KaTeX markup: `**bold**`, `_italic_`, `` `code` ``, `$x$`, `$$x$$`, and
   image/link syntax — compare what is *read*, not how it is written.
4. Collapse every run of whitespace to one space; trim.
5. Case-fold.
6. Drop trailing punctuation (`. , ! ? ; :` and their full-width equivalents).

Nothing else. In particular, punctuation **inside** the answer is never *dropped*: `N이/가`
and `f(x) = 2x` must not be silently rewritten.

Step 2 is the one deliberate exception, and it removes nothing: a printed page may use any of a
dozen dashes and a keyboard offers one, so `–씨` typed as `-씨` is **correct**, not `almost`.
Which dash it is is never the thing being learned. The card itself keeps the dash it was
imported with — only the comparison ignores the difference.

## 2. `correct`

The normalised answer equals the normalised displayed answer, or any entry of the note's
`accept` list for that side (PLAN 3.5). Accepted answers are always explicit — from the import
or from the "that's the same thing" button — and are never guessed at runtime.

## 3. `almost`

Compare in Unicode **NFD**, so a Hangul syllable decomposes into jamo and `é` into `e` + accent.
Distance is Damerau-Levenshtein over code points: a transposition counts as **one**.

| length of the expected answer (NFD code points) | `almost` when distance is |
|---|---|
| ≤ 8 | 1 |
| > 8 | ≤ 2 |

The comparison runs against the displayed answer **and** every accepted answer; the smallest
distance wins. `학생` → `학샘` is one unit; `café` → `cafe` is one unit.

## 4. `wrong`

Everything else. An empty answer is always `wrong`, never `almost`.

## 5. What the app does with it

- `correct` — continue.
- `almost` — show the diff, requeue the card inside the session, offer "that's the same thing →
  add to accepted".
- `wrong` — show the answer, requeue.

Any outcome can be overridden by the user. The review log stores `raw_answer` and `outcome`, so a
past session can be re-judged if this spec ever changes.
