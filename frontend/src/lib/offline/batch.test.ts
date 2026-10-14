import { expect, test } from 'vitest';
import type { Queue, QueueCard } from '$lib/api/client';
import { remaining, scopeOf, sized, stale } from './batch';

const card = (key: string) => ({ key }) as QueueCard;
const queue = (...keys: string[]) =>
	({ scheduler: 'fsrs', modes: ['typed'], distractor_scope: 'auto', cards: keys.map(card) }) as Queue;

test('a batch is remembered against what it was asked for', () => {
	expect(scopeOf('cat_1')).not.toBe(scopeOf('cat_2'));
	expect(scopeOf('cat_1', { fileId: 'df_1' })).not.toBe(scopeOf('cat_1'));
	expect(scopeOf('cat_1', { fileId: 'df_1', group: 'jobs' })).not.toBe(scopeOf('cat_1', { fileId: 'df_1' }));
	// Practising everything is one scope of its own, not the absence of a scope.
	expect(scopeOf(undefined)).toBe(scopeOf(undefined));
});

test('a second offline session does not hand back the same cards', () => {
	const left = remaining(queue('a:fwd', 'b:fwd', 'c:fwd'), new Set(['a:fwd', 'c:fwd']));
	expect(left.cards.map((c) => c.key)).toEqual(['b:fwd']);
});

test('nothing answered yet leaves the batch as it was', () => {
	const batch = queue('a:fwd', 'b:fwd');
	expect(remaining(batch, new Set()).cards).toHaveLength(2);
	expect(remaining(batch, new Set()).scheduler).toBe('fsrs');
});

test('a batch entirely answered is empty, not stale', () => {
	expect(remaining(queue('a:fwd'), new Set(['a:fwd'])).cards).toEqual([]);
});

test('a batch is topped up when there is none, too little, or it is yesterday', () => {
	const kept = (cards: number, at: string, taken = true) =>
		({ scope: '', at, taken, queue: queue(...Array.from({ length: cards }, (_, i) => `c${i}:fwd`)) }) as never;
	const now = new Date('2026-10-10T12:00:00Z').getTime();
	const today = '2026-10-10T09:00:00Z';

	expect(stale(null, 60, now)).toBe(true);
	expect(stale(kept(20, today), 60, now)).toBe(true);
	expect(stale(kept(80, '2026-10-08T09:00:00Z'), 60, now)).toBe(true);
	expect(stale(kept(80, today), 60, now)).toBe(false);
});

test('an ordinary queue that happened to be saved is not a batch to rely on', () => {
	// `taken: false` is what every plain page load writes; it is one session's
	// worth and says nothing about being ready to go away.
	const incidental = { scope: '', at: new Date().toISOString(), taken: false, queue: queue('a:fwd') } as never;
	expect(stale(incidental, 60)).toBe(true);
});

/** A batch arrives due-first, which is the order `sized` takes each side in. */
const batch = (seen: number, fresh: number) =>
	({
		scheduler: 'fsrs',
		modes: ['typed'],
		distractor_scope: 'auto',
		cards: [
			...Array.from({ length: seen }, (_, i) => ({ key: `s${i}`, is_new: false })),
			...Array.from({ length: fresh }, (_, i) => ({ key: `n${i}`, is_new: true }))
		] as QueueCard[]
	}) as Queue;

const counted = (queue: Queue) => [
	queue.cards.filter((c) => !c.is_new).length,
	queue.cards.filter((c) => c.is_new).length
];

test('a sitting taken from the batch is the size that was asked for', () => {
	expect(sized(batch(100, 60), 20).cards).toHaveLength(20);
	// A quarter of it is kept for words not met yet, as it is on the server.
	expect(counted(sized(batch(100, 60), 20))).toEqual([15, 5]);
});

test('whichever side the batch is short of, the other fills the room', () => {
	expect(counted(sized(batch(2, 60), 12))).toEqual([2, 10]);
	expect(counted(sized(batch(60, 1), 12))).toEqual([11, 1]);
});

test('a batch smaller than the sitting is left exactly as it is', () => {
	const kept = batch(3, 2);
	expect(sized(kept, 20)).toBe(kept);
	expect(sized(kept, null)).toBe(kept);
});
