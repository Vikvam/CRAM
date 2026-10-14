/**
 * The last collection this device was shown.
 *
 * Opening the app with the laptop asleep used to give an empty collection and
 * the line "Can't reach the laptop" — true, but it left no way to reach the
 * cards sitting on the device, because every route into a session is a link in
 * the category tree and the tree is `/api/` only. Keeping it means the home
 * screen looks and works as it always does; only the things that genuinely need
 * the laptop are out of reach, and they say so.
 *
 * Each list is its own row. The tree is loaded by the page and the files by
 * whichever node is expanded, so one row per list means neither can overwrite
 * the other's half of the picture.
 */

import type { Category, DataFileSummary } from '$lib/api/client';
import { KEPT, get, put } from './db';

type Kept<T> = {
	name: string;
	/** When it was last true, for anything that wants to say how old it is. */
	at: string;
	rows: T;
};

const CATEGORIES = 'categories';
const filesOf = (categoryId: string) => `files:${categoryId}`;

/**
 * Whatever the caller holds, as something IndexedDB will take.
 *
 * Both callers hand over Svelte state, and state is a `Proxy` — which the
 * structured clone algorithm refuses with `DataCloneError`. `db.ts` answers a
 * failed write with `null` rather than throwing, by design, so the result was a
 * store that stayed empty with nothing anywhere to say why. These rows are
 * plain JSON from the API, so a round-trip is both safe and cheap, and doing it
 * here means no caller has to remember.
 */
const plain = <T>(rows: T): T => JSON.parse(JSON.stringify(rows)) as T;

async function keep<T>(name: string, rows: T): Promise<void> {
	await put<Kept<T>>(KEPT, { name, at: new Date().toISOString(), rows: plain(rows) });
}

async function kept<T>(name: string): Promise<T | null> {
	const row = await get<Kept<T>>(KEPT, name);
	return row?.rows ?? null;
}

export const keepCategories = (rows: Category[]) => keep(CATEGORIES, rows);
export const keptCategories = () => kept<Category[]>(CATEGORIES);

export const keepFiles = (categoryId: string, rows: DataFileSummary[]) => keep(filesOf(categoryId), rows);
export const keptFiles = (categoryId: string) => kept<DataFileSummary[]>(filesOf(categoryId));
