import { expect, test } from 'vitest';
import type { AnswerBody } from '$lib/api/client';
import { type Pending, type Report, asFile, inOrder, newId, pendingFor, settled, unique } from './outbox';

const body = (key: string): AnswerBody => ({
	card_key: key,
	mode: 'typed',
	outcome: 'correct',
	grade: null,
	overridden: false,
	raw_answer: 'country',
	duration_ms: 1200,
	scheduler: 'fsrs'
});

const row = (id: string, at: string): Pending => ({ ...body('n1:fwd'), client_id: id, at });

const report = (over: Partial<Report> = {}): Report => ({
	accepted: 0,
	duplicates: 0,
	unknown: [],
	rebuilt: 0,
	...over
});

test('an id is 26 characters, and a later answer sorts after an earlier one', () => {
	const early = newId(new Date('2026-10-09T08:00:00Z').getTime(), () => 0);
	const late = newId(new Date('2026-10-09T09:00:00Z').getTime(), () => 0);
	expect(early).toHaveLength(26);
	expect(early < late).toBe(true);
});

test('an id fits the column it is stored in', () => {
	// `review_log.client_id` is String(32) — a ULID has to stay well inside it.
	expect(newId().length).toBeLessThanOrEqual(32);
});

test('an answer keeps the moment it was answered, not the moment it was sent', () => {
	const at = new Date('2026-10-09T08:30:00Z');
	const pending = pendingFor(body('n1:fwd'), at);
	expect(pending.at).toBe('2026-10-09T08:30:00.000Z');
	expect(pending.raw_answer).toBe('country');
});

test('rows are handed over oldest first, which is how they are replayed', () => {
	const rows = [row('c', '2026-10-09T10:00:00Z'), row('a', '2026-10-08T10:00:00Z')];
	expect(inOrder(rows).map((r) => r.client_id)).toEqual(['a', 'c']);
});

test('two answers in the same millisecond still come out in a fixed order', () => {
	const same = '2026-10-09T10:00:00Z';
	expect(inOrder([row('b', same), row('a', same)]).map((r) => r.client_id)).toEqual(['a', 'b']);
});

test('the same row twice is one row', () => {
	const twice = [row('a', '2026-10-09T10:00:00Z'), row('a', '2026-10-09T10:00:00Z')];
	expect(unique(twice)).toHaveLength(1);
});

test('a reply settles the whole batch, however the rows were counted', () => {
	const rows = [row('a', '2026-10-09T10:00:00Z'), row('b', '2026-10-09T11:00:00Z')];
	expect(settled(rows, report({ accepted: 2 }))).toEqual(['a', 'b']);
	// Sent again after the file was imported: both are duplicates, both are done.
	expect(settled(rows, report({ duplicates: 2 }))).toEqual(['a', 'b']);
	// A card that has been deleted will never come back, so waiting is pointless.
	expect(settled(rows, report({ accepted: 1, unknown: ['n1:fwd'] }))).toEqual(['a', 'b']);
});

test('a row the server could make nothing of is settled, not kept for ever', () => {
	// This device cannot mend it and must be able to put it down; keeping it
	// would mean offering the same bad row on every flush until the app is wiped.
	const rows = [row('a', '2026-10-09T10:00:00Z'), row('b', '2026-10-09T11:00:00Z')];
	expect(settled(rows, report({ accepted: 1, rejected: ['b'] }))).toEqual(['a', 'b']);
});

test('no reply forgets nothing', () => {
	const rows = [row('a', '2026-10-09T10:00:00Z')];
	expect(settled(rows, null)).toEqual([]);
});

test('a reply that does not add up keeps the rows rather than losing them', () => {
	const rows = [row('a', '2026-10-09T10:00:00Z'), row('b', '2026-10-09T11:00:00Z')];
	expect(settled(rows, report({ accepted: 1 }))).toEqual([]);
});

test('the file is the shape `memo import-answers` reads', () => {
	const saved = JSON.parse(asFile([row('b', '2026-10-09T11:00:00Z'), row('a', '2026-10-09T10:00:00Z')]));
	expect(saved.format).toBe('memo.answers');
	expect(saved.rows.map((r: Pending) => r.client_id)).toEqual(['a', 'b']);
	expect(saved.rows[0]).toMatchObject({ card_key: 'n1:fwd', mode: 'typed', outcome: 'correct' });
});
