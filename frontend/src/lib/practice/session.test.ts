import { describe, expect, test } from 'vitest';
import { AT_THE_END, DRILL, Session } from './session';

const drain = (session: Session<string>, answer: (card: string, n: number) => 'correct' | 'almost' | 'wrong') => {
	const seen: string[] = [];
	for (let guard = 0; !session.finished && guard < 1000; guard++) {
		const card = session.current!.card;
		seen.push(card);
		session.record(answer(card, seen.filter((c) => c === card).length));
	}
	return seen;
};

describe('the learning loop (PLAN 3.5)', () => {
	test('a card right first time is done', () => {
		const s = new Session(['a', 'b']);
		expect(drain(s, () => 'correct')).toEqual(['a', 'b']);
		expect(s.doneCount).toBe(2);
	});

	test('a missed card comes back and must be right twice', () => {
		const s = new Session(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']);
		const seen = drain(s, (card, n) => (card === 'a' && n === 1 ? 'wrong' : 'correct'));
		expect(seen.filter((c) => c === 'a')).toHaveLength(3);
		expect(seen[0]).toBe('a');
		expect(seen.indexOf('a', 1)).toBe(4); // three cards later, not immediately
	});

	test('almost counts as needing practice, not as done', () => {
		const s = new Session(['a']);
		const seen = drain(s, (_, n) => (n === 1 ? 'almost' : 'correct'));
		expect(seen).toEqual(['a', 'a', 'a']);
	});

	test('a streak is broken by a miss', () => {
		const s = new Session(['a']);
		const answers = ['wrong', 'correct', 'wrong', 'correct', 'correct'] as const;
		const seen = drain(s, (_, n) => answers[n - 1]);
		expect(seen).toHaveLength(5);
	});

	test('the only card left comes straight back', () => {
		const s = new Session(['a']);
		s.record('wrong');
		expect(s.current?.card).toBe('a');
	});

	test('the required streak is configurable', () => {
		const s = new Session(['a'], { requiredStreak: 3 });
		const seen = drain(s, (_, n) => (n === 1 ? 'wrong' : 'correct'));
		expect(seen).toHaveLength(4);
	});

	test('a marked word is asked twice even when it goes right', () => {
		const s = new Session(['a', 'b', 'c', 'd', 'e', 'f', 'g'], { twice: (card) => card === 'a' });
		const seen = drain(s, () => 'correct');
		expect(seen.filter((c) => c === 'a')).toHaveLength(2);
		expect(seen.indexOf('a', 1)).toBe(6); // not straight back: the confirmation gap, five cards
		expect(seen.filter((c) => c === 'b')).toHaveLength(1);
	});

	test('a marked word that was missed is not asked a third time for it', () => {
		const s = new Session(['a', 'b', 'c', 'd'], { twice: () => true });
		const seen = drain(s, (card, n) => (card === 'a' && n === 1 ? 'wrong' : 'correct'));
		expect(seen.filter((c) => c === 'a')).toHaveLength(3); // the miss, then right twice
	});

	test('a card set aside is missed, and not asked again this session', () => {
		const s = new Session(['a', 'b', 'c', 'd', 'e']);
		const item = s.setAside();
		expect(item).toMatchObject({ card: 'a', missed: true, done: false, setAside: true, outcomes: ['wrong'] });
		expect(drain(s, () => 'correct')).toEqual(['b', 'c', 'd', 'e']);
		expect(s.doneCount).toBe(5);
	});

	test('stopping leaves nothing queued', () => {
		const s = new Session(['a', 'b']);
		s.stop();
		expect(s.finished).toBe(true);
		expect(s.doneCount).toBe(0);
	});

	test('recording past the end is an error, not a silent no-op', () => {
		const s = new Session<string>([]);
		expect(() => s.record('correct')).toThrow();
	});
});

test('a round of cards can be answered in any order', () => {
	const session = new Session(['a', 'b', 'c', 'd', 'e'], { missGap: 2 });
	const round = session.take(3);
	expect(round.map((i) => i.card)).toEqual(['a', 'b', 'c']);
	expect(session.current?.card).toBe('d');

	session.recordItem(round[2], 'correct');
	session.recordItem(round[0], 'wrong');
	expect(round[2].done).toBe(true);
	expect(round[0].missed).toBe(true);
	// The missed one is back in the queue; the right one is gone for good.
	expect(session.items.filter((i) => !i.done).length).toBe(4);
	expect(session.remaining).toBe(3);
});

test('a round only takes cards that pass the test', () => {
	const session = new Session(['a', 'b', 'c']);
	session.record('wrong'); // 'a' comes back, having been attempted
	const round = session.take(3, (i) => i.attempts === 0);
	expect(round.map((i) => i.card)).toEqual(['b', 'c']);
});

describe('a drill runs the same cards differently', () => {
	const cards = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];

	test('a missed word comes back at the end, not three cards later', () => {
		const s = new Session(cards, DRILL);
		const seen = drain(s, (card, n) => (card === 'a' && n === 1 ? 'wrong' : 'correct'));
		expect(seen.slice(0, 8)).toEqual(cards); // the whole pass first
		expect(seen).toHaveLength(9); // then the one miss, once
		expect(seen[8]).toBe('a');
	});

	test('one correct retires a missed word', () => {
		const s = new Session(cards, DRILL);
		const seen = drain(s, (card, n) => (card === 'a' && n === 1 ? 'wrong' : 'correct'));
		expect(seen.filter((c) => c === 'a')).toHaveLength(2); // practice asks three times
		expect(s.doneCount).toBe(8);
	});

	test('almost lets a word go, and is still recorded as almost', () => {
		const s = new Session(['a', 'b'], DRILL);
		s.record('almost');
		expect(s.items[0].done).toBe(true);
		expect(s.items[0].outcomes).toEqual(['almost']); // the grade still says HARD
		expect(s.items[0].missed).toBe(false);
		expect(drain(s, () => 'correct')).toEqual(['b']);
	});

	test('a word missed every time costs one ask per pass, never a lock-in', () => {
		// The complaint this exists for: 영화관 took 15 of 151 slots in one sitting,
		// nine wrong in a row at a constant four-card spacing.
		const s = new Session(cards, DRILL);
		const seen: { card: string; waiting: number }[] = [];
		for (let guard = 0; !s.finished && guard < 40; guard++) {
			const card = s.current!.card;
			seen.push({ card, waiting: s.remaining });
			if (card === 'a' && seen.filter((x) => x.card === 'a').length <= 3) s.record('wrong');
			else s.record('correct');
		}
		const asks = seen.filter((x) => x.card === 'a');
		// Three misses, so three returns — each behind everything still queued.
		expect(asks).toHaveLength(4);
		expect(seen.findIndex((x, i) => i > 0 && x.card === 'a')).toBe(8);
		// Back-to-back only once nothing else is left to interleave with: that is
		// the floor of the idea, not a lock-in, and one correct answer ends it.
		for (const [i, x] of seen.entries()) {
			if (x.card === 'a' && seen[i + 1]?.card === 'a') expect(x.waiting).toBe(1);
		}
	});

	test('a marked word is still asked twice, at the end of the pass', () => {
		const s = new Session(cards, { ...DRILL, twice: (card) => card === 'a' });
		const seen = drain(s, () => 'correct');
		expect(seen.filter((c) => c === 'a')).toHaveLength(2);
		expect(seen[seen.length - 1]).toBe('a');
	});

	test('AT_THE_END on the last card left is simply the last card', () => {
		const s = new Session(['a'], DRILL);
		expect(drain(s, (_card, n) => (n === 1 ? 'wrong' : 'correct'))).toEqual(['a', 'a']);
		expect(AT_THE_END).toBeGreaterThan(1000);
	});

	test('practice is untouched by any of this', () => {
		const s = new Session(cards);
		const seen = drain(s, (card, n) => (card === 'a' && n === 1 ? 'wrong' : 'correct'));
		expect(seen.filter((c) => c === 'a')).toHaveLength(3);
		expect(seen.indexOf('a', 1)).toBe(4);
	});
});
