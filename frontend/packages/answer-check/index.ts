/**
 * The answer checker — the single implementation (PLAN 5).
 *
 * Specified by `spec/answer-check.md`; `spec/answer-check.vectors.json` is the
 * test every implementation must pass. Language-neutral by construction
 * (PLAN 3.7): no script is special-cased, Hangul and accents fall out of NFD.
 *
 * Dependency-free and written in erasable TypeScript, so it runs in the
 * browser, in Node's test runner, and offline later, unchanged.
 */

export type Outcome = 'correct' | 'almost' | 'wrong';

export interface CheckResult {
	outcome: Outcome;
	/** The answer the typed text was closest to, for showing the diff. */
	closest: string;
	/** Edit distance to `closest` in NFD code points; 0 when correct. */
	distance: number;
}

export interface CheckOptions {
	/** Largest distance still `almost` for short answers (spec §3). */
	almostShort?: number;
	/** Largest distance still `almost` for long answers. */
	almostLong?: number;
	/** Length (NFD code points) above which an answer counts as long. */
	longThreshold?: number;
}

const DEFAULTS: Required<CheckOptions> = { almostShort: 1, almostLong: 2, longThreshold: 8 };

// Trailing punctuation, ASCII and full-width (spec §1.6). Never inner punctuation.
const TRAILING_PUNCTUATION = /[.,!?;:。，！？；：…]+$/u;

// Dashes nobody can type (spec §1.2): en, em, figure, non-breaking, minus sign,
// the small and full-width forms. U+30FC is left alone — it is a letter in Japanese.
const DASHES = /[\u2010-\u2015\u2212\u2043\u2E3A\u2E3B\uFE58\uFE63\uFF0D]/gu;
// Invisible, so it cannot be typed at all: it goes rather than becoming a hyphen.
const SOFT_HYPHEN = /\u00AD/gu;

/**
 * Every dash a book might print becomes a plain hyphen (spec §1.2). The card
 * keeps the typography it was imported with; only the comparison ignores it,
 * so an en dash in `–씨` does not cost you the answer.
 */
export function foldDashes(text: string): string {
	return text.replace(SOFT_HYPHEN, '').replace(DASHES, '-');
}

/** Remove Markdown/KaTeX markup so what is *read* is compared (spec §1.3). */
export function stripMarkup(text: string): string {
	return text
		.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1') // images → alt text
		.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1') // links → label
		.replace(/\$\$([\s\S]+?)\$\$/g, '$1') // display maths
		.replace(/\$([^$\n]+?)\$/g, '$1') // inline maths
		.replace(/`([^`]+)`/g, '$1') // code
		.replace(/\*\*([^*]+)\*\*/g, '$1') // bold
		.replace(/__([^_]+)__/g, '$1')
		.replace(/(^|[^\p{L}\p{N}])\*([^*\n]+)\*(?=$|[^\p{L}\p{N}])/gu, '$1$2') // italic
		.replace(/(^|[^\p{L}\p{N}])_([^_\n]+)_(?=$|[^\p{L}\p{N}])/gu, '$1$2');
}

/** Spec §1, in order: NFC, dashes, markup, whitespace, case, trailing punctuation. */
export function normalise(text: string): string {
	let out = text.normalize('NFC');
	out = foldDashes(out);
	out = stripMarkup(out);
	out = out.replace(/\s+/gu, ' ').trim();
	out = out.toLowerCase();
	out = out.replace(TRAILING_PUNCTUATION, '').trim();
	return out;
}

/** Code points in NFD — the unit of distance (spec §3, PLAN 3.7). */
export function units(text: string): string[] {
	return Array.from(text.normalize('NFD'));
}

/**
 * Damerau-Levenshtein (optimal string alignment): insertion, deletion,
 * substitution and adjacent transposition each cost one.
 */
export function distance(a: string[], b: string[]): number {
	const rows = a.length + 1;
	const cols = b.length + 1;
	const d: number[][] = Array.from({ length: rows }, () => new Array<number>(cols).fill(0));
	for (let i = 0; i < rows; i++) d[i][0] = i;
	for (let j = 0; j < cols; j++) d[0][j] = j;
	for (let i = 1; i < rows; i++) {
		for (let j = 1; j < cols; j++) {
			const cost = a[i - 1] === b[j - 1] ? 0 : 1;
			let best = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
			if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
				best = Math.min(best, d[i - 2][j - 2] + 1);
			}
			d[i][j] = best;
		}
	}
	return d[rows - 1][cols - 1];
}

/**
 * Judge a typed answer against the displayed answer and the explicit accept
 * list for that side. Never guesses alternatives (PLAN 3.5).
 */
export function check(
	answer: string,
	expected: string,
	accepted: readonly string[] = [],
	options: CheckOptions = {}
): CheckResult {
	const opts = { ...DEFAULTS, ...options };
	const typed = normalise(answer);
	const targets = [expected, ...accepted].filter((t) => normalise(t) !== '');

	if (typed === '' || targets.length === 0) {
		return { outcome: 'wrong', closest: expected, distance: Infinity };
	}

	for (const target of targets) {
		if (normalise(target) === typed) return { outcome: 'correct', closest: target, distance: 0 };
	}

	const typedUnits = units(typed);
	let best: CheckResult = { outcome: 'wrong', closest: expected, distance: Infinity };
	for (const target of targets) {
		const targetUnits = units(normalise(target));
		const dist = distance(typedUnits, targetUnits);
		const limit = targetUnits.length > opts.longThreshold ? opts.almostLong : opts.almostShort;
		const outcome: Outcome = dist <= limit ? 'almost' : 'wrong';
		const better =
			(outcome === 'almost' && best.outcome !== 'almost') ||
			(outcome === best.outcome && dist < best.distance);
		if (better) best = { outcome, closest: target, distance: dist };
	}
	return best;
}

/**
 * Split an answer into `build`-mode tiles (PLAN 3.7): several words → words,
 * otherwise grapheme clusters — one tile per Hangul syllable block, per letter
 * in Latin script, with no script special-cased.
 */
export function pieces(text: string, split: 'auto' | 'whitespace' | 'grapheme' = 'auto'): string[] {
	const clean = stripMarkup(text.normalize('NFC')).replace(/\s+/gu, ' ').trim();
	if (clean === '') return [];
	const words = clean.split(' ');
	if (split === 'whitespace' || (split === 'auto' && words.length > 1)) return words;
	const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
	return Array.from(segmenter.segment(clean), (s) => s.segment);
}
