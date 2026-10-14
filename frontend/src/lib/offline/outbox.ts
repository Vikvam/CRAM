/**
 * Answers waiting to be told to the server, and the rules for telling it.
 *
 * The checker runs here (PLAN 5), so a phone with no signal already knows
 * whether an answer was right. What it cannot do is schedule, because that needs
 * every other review, which the laptop holds. So an answer is written down with
 * its own id and the moment it happened, and handed over when that becomes
 * possible — over the wire, or in a file carried by hand. The id is what stops
 * those two paths counting one answer twice.
 *
 * Everything here is pure: the disk is in `db.ts` and the retrying is in
 * `sync.svelte.ts`, so the part with the rules in it can be tested on its own.
 */

import type { AnswerBody } from '$lib/api/client';

/** An answer as it waits: the body the server already understands, plus who and when. */
export type Pending = AnswerBody & {
	client_id: string;
	/** ISO 8601, by this device's clock. The server keeps it over the arrival time. */
	at: string;
};

/** What the server says it did with a batch. */
export type Report = {
	accepted: number;
	duplicates: number;
	unknown: string[];
	rebuilt: number;
	/** Rows the server could make nothing of. Settled: offering them again cannot help. */
	rejected?: string[];
};

/** Crockford base32, the same alphabet the backend's own ids use. */
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

/**
 * A ULID: ten characters of time, sixteen of chance.
 *
 * Sortable by when it was made, which is why it is a ULID and not a UUID — rows
 * read back off disk are then already in the order they happened. It has to be
 * unique only against this profile's other answers, and the random half is 80 bits.
 */
export function newId(now: number = Date.now(), random: () => number = Math.random): string {
	let time = '';
	for (let n = now, i = 0; i < 10; i++, n = Math.floor(n / 32)) time = ALPHABET[n % 32] + time;
	let tail = '';
	for (let i = 0; i < 16; i++) tail += ALPHABET[Math.floor(random() * 32)];
	return time + tail;
}

/** One answer, written down. */
export function pendingFor(body: AnswerBody, at: Date = new Date()): Pending {
	return { ...body, client_id: newId(at.getTime()), at: at.toISOString() };
}

/** Oldest first, which is the order the server replays them in. */
export const inOrder = (rows: readonly Pending[]): Pending[] =>
	[...rows].sort((a, b) => (a.at === b.at ? a.client_id.localeCompare(b.client_id) : a.at < b.at ? -1 : 1));

/** One row per id, the first seen winning, so a doubled file cannot inflate a batch. */
export function unique(rows: readonly Pending[]): Pending[] {
	const seen = new Map<string, Pending>();
	for (const row of rows) if (!seen.has(row.client_id)) seen.set(row.client_id, row);
	return [...seen.values()];
}

/**
 * Which ids can be forgotten, given what the server said.
 *
 * A reply means the batch was dealt with in one transaction: accepted and
 * duplicate both mean "it is in the log now", and a card the server no longer has
 * is settled too, because waiting will not bring it back. So is a row the server
 * could make nothing of — this device cannot mend it, and keeping it would mean
 * offering the same bad row for ever. So a reply settles everything that was
 * sent, and no reply settles nothing — those rows stay and are offered again. If
 * the numbers ever fail to account for the batch, the rows are kept rather than
 * quietly dropped.
 */
export function settled(sent: readonly Pending[], report: Report | null): string[] {
	if (!report) return [];
	const counted =
		report.accepted + report.duplicates + report.unknown.length + (report.rejected?.length ?? 0);
	return counted === sent.length ? sent.map((row) => row.client_id) : [];
}

/** The file the phone hands over by hand. Shaped so `memo import-answers` reads it. */
export const asFile = (rows: readonly Pending[]) =>
	JSON.stringify({ format: 'memo.answers', version: 1, rows: inOrder(unique(rows)) }, null, '\t');
