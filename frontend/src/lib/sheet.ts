/**
 * A data file read as a page instead of edited as a grid (PLAN 6, phase 4).
 *
 * The sheet follows the file's own order: headings in the order the notes under
 * them appear, so what you read matches the photo it came from. Nothing here
 * talks to the server — the rows are the ones the editor already loaded.
 */
import type { Group, Note } from '$lib/api/client';

export type Progress = 'new' | 'learning' | 'known' | 'mastered';

export interface Section {
	/** The heading, or null for notes that belong to none. */
	group: Group | null;
	notes: Note[];
}

//: Drawn in CSS rather than typed as ○ ◐ ● ◉, which not every font has.
export const MARKS: Record<Progress, string> = {
	new: 'not practised yet',
	learning: 'learning',
	known: 'known — answered right often enough',
	mastered: 'mastered — and written from memory'
};

//: What a mark on a word means, for the sheet's own marker. `normal` is absent
//: rather than a third entry, because an unmarked word draws nothing.
export const ASKED: Record<string, string> = {
	low: 'marked to come up less often',
	high: 'marked to come up more often',
	crucial: 'marked crucial — comes up first, even once mastered'
};

//: How a mark is written wherever it is shown: below, at and above normal.
//: A real minus sign, so the four line up in tabular figures.
export const PRIORITY_SHOWS: Record<string, string> = {
	low: '\u22121',
	normal: '0',
	high: '+1',
	crucial: '+2'
};

//: A note's accepted alternatives are a practice detail — "what, which" is
//: already the whole meaning, and "· what, which" under it is just noise. The
//: editor's ⋯ panel is where they are read and changed.

/**
 * The file in reading order, one section per heading.
 *
 * A heading taken up again further down — a word moved to it in the editor keeps
 * its place in the file — is gathered into its first section, so each heading
 * appears once and can key the sheet's sections.
 */
export function sections(notes: Note[], groups: Group[]): Section[] {
	const known = new Map(groups.map((g) => [g.key, g]));
	const byKey = new Map<string | null, Section>();
	const out: Section[] = [];
	for (const note of notes) {
		const key = note.group ?? null;
		const section = byKey.get(key);
		if (section) {
			section.notes.push(note);
			continue;
		}
		const fresh = { group: key === null ? null : (known.get(key) ?? { key, label: null, note: null }), notes: [note] };
		byKey.set(key, fresh);
		out.push(fresh);
	}
	return out;
}

/** How many of a set of rows are in each bucket, for the sheet's own summary.
 *
 *  The same rule as the server's Progress bars (`overview/progress.py:_count`):
 *  a known word marked low counts as mastered while anything else here is
 *  short of mastered. Each row's own marker still shows its real bucket. */
export function tally(notes: Note[]): Record<Progress, number> {
	const counts: Record<Progress, number> = { new: 0, learning: 0, known: 0, mastered: 0 };
	let lowKnown = 0;
	let othersDone = true;
	for (const note of notes) {
		const bucket = (note.progress ?? 'new') as Progress;
		const low = note.priority === 'low';
		counts[bucket] += 1;
		if (low && bucket === 'known') lowKnown += 1;
		else if (!low && bucket !== 'mastered') othersDone = false;
	}
	if (!othersDone) {
		counts.known -= lowKnown;
		counts.mastered += lowKnown;
	}
	return counts;
}
