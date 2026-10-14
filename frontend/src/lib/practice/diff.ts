/**
 * What to show after an `almost`: the typed answer against the expected one,
 * per grapheme, so a Hangul syllable or an accented letter is one unit on
 * screen (PLAN 3.7). Case differences are not shown as mistakes, because the
 * checker ignores case too.
 */
export type Segment = { text: string; kind: 'same' | 'extra' | 'missing' };

const graphemes = (text: string) =>
	Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(text.normalize('NFC')), (s) => s.segment);

export function diff(typed: string, expected: string): Segment[] {
	const a = graphemes(typed.trim());
	const b = graphemes(expected.trim());
	const eq = (x: string, y: string) => x.toLowerCase() === y.toLowerCase();

	// Longest common subsequence table.
	const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
	for (let i = a.length - 1; i >= 0; i--) {
		for (let j = b.length - 1; j >= 0; j--) {
			lcs[i][j] = eq(a[i], b[j]) ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
		}
	}

	const out: Segment[] = [];
	const push = (text: string, kind: Segment['kind']) => {
		const last = out.at(-1);
		if (last?.kind === kind) last.text += text;
		else out.push({ text, kind });
	};
	let i = 0;
	let j = 0;
	while (i < a.length && j < b.length) {
		if (eq(a[i], b[j])) {
			push(b[j], 'same');
			i++;
			j++;
		} else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
			push(a[i++], 'extra');
		} else {
			push(b[j++], 'missing');
		}
	}
	while (i < a.length) push(a[i++], 'extra');
	while (j < b.length) push(b[j++], 'missing');
	return out;
}
