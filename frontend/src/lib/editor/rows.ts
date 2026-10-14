/** The grid editor's rows: what the server knows, plus what is being typed. */
import type { Note, NotePatch } from '$lib/api/client';

export interface Row {
	/** Stable key for `{#each}` — a row keeps it from blank to saved. */
	key: number;
	/** The server's copy, or null while the row has never been saved. */
	note: Note | null;
	front: string;
	back: string;
	group: string;
	saving: boolean;
	error: string | null;
}

let nextKey = 1;

export function blankRow(group = ''): Row {
	return { key: nextKey++, note: null, front: '', back: '', group, saving: false, error: null };
}

export function toRow(note: Note): Row {
	return {
		key: nextKey++,
		note,
		front: note.front ?? '',
		back: note.back ?? '',
		group: note.group ?? '',
		saving: false,
		error: null
	};
}

export const isBlank = (row: Row) => !row.front.trim() && !row.back.trim();

/** Only what the user actually changed, so a patch never overwrites a field it did not touch. */
export function changes(row: Row): NotePatch {
	const patch: NotePatch = {};
	const note = row.note;
	const group = row.group.trim() || null;
	if ((note?.front ?? '') !== row.front) patch.front = row.front;
	if ((note?.back ?? '') !== row.back) patch.back = row.back;
	if ((note?.group ?? null) !== group) patch.group = group;
	return patch;
}

export const dirty = (row: Row) => Object.keys(changes(row)).length > 0;

/** The note text as the practice screen will show it, for the "saved" tick and previews. */
export function pair(row: Row): [string | null, string | null] {
	return [row.front.trim() || null, row.back.trim() || null];
}
