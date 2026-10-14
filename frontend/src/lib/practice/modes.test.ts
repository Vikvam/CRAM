import { expect, test } from 'vitest';
import type { QueueCard } from '$lib/api/client';
import { canBuild, matchRound, modeFor, options, recognising, tiles } from './modes';

const ALL = ['flip', 'typed', 'choice', 'match', 'build'];

const card = (over: Partial<QueueCard> = {}): QueueCard => ({
	key: over.key ?? 'c1:fwd',
	note_id: over.note_id ?? 'n1',
	direction: 'fwd',
	prompt: '나라',
	answer: 'country',
	accepted: [],
	prompt_lang: 'ko',
	answer_lang: 'en',
	note: null,
	fields: null,
	group: null,
	data_file_id: 'df1',
	is_new: true,
	early: false,
	priority: 'normal',
	twice: false,
	state: null,
	modes: null,
	distractors: ['Korea', 'China', 'Japan'],
	suggest: 'choice',
	...over
});

test('a card is practised the way it asks to be', () => {
	expect(modeFor(card(), 'auto', ALL)).toBe('choice');
	expect(modeFor(card({ suggest: 'build', answer: '나라' }), 'auto', ALL)).toBe('build');
	expect(modeFor(card({ suggest: 'typed' }), 'auto', ALL)).toBe('typed');
});

test('a choice needs a full set of options, not merely one', () => {
	// The server's own threshold (`suggest_mode`). Below it a forced `choice`
	// would be two buttons, answerable by a coin — and capped at a day for it.
	expect(modeFor(card({ distractors: ['Korea'] }), 'choice', ALL)).toBe('typed');
	expect(modeFor(card({ distractors: ['Korea', 'China'] }), 'choice', ALL)).toBe('typed');
	expect(modeFor(card({ distractors: ['Korea', 'China', 'Japan'] }), 'choice', ALL)).toBe('choice');
});

test('forcing a mode beats the suggestion', () => {
	expect(modeFor(card({ suggest: 'choice' }), 'flip', ALL)).toBe('flip');
	expect(modeFor(card({ suggest: 'typed' }), 'choice', ALL)).toBe('choice');
});

test('a mode that cannot be shown falls back towards typing, never to nothing', () => {
	// Nothing to choose between.
	expect(modeFor(card({ distractors: [] }), 'choice', ALL)).toBe('typed');
	// One tile is not a puzzle.
	expect(modeFor(card({ answer: '가' }), 'build', ALL)).toBe('typed');
	// The note itself says flip only.
	expect(modeFor(card({ modes: ['flip'] }), 'choice', ALL)).toBe('flip');
	// The category allows nothing this card can do.
	expect(modeFor(card({ modes: ['build'], answer: '가' }), 'auto', ALL)).toBe('flip');
});

test('a matching round is never offered on its own', () => {
	expect(modeFor(card({ suggest: 'match' }), 'auto', ALL)).toBe('choice');
});

test('tiles are words when there are several, graphemes otherwise', () => {
	expect(tiles('저는 첸이에요')).toEqual(['저는', '첸이에요']);
	expect(tiles('나라')).toEqual(['나', '라']);
	expect(canBuild('나라')).toBe(true);
	expect(canBuild('가')).toBe(false);
	expect(canBuild('a '.repeat(9))).toBe(false);
});

test('the options are the answer plus its distractors, in no fixed place', () => {
	const subject = card();
	const shown = options(subject);
	expect(shown).toHaveLength(4);
	expect(shown).toContain('country');
	expect(new Set(shown).size).toBe(4);
	const places = new Set(Array.from({ length: 40 }, () => options(subject).indexOf('country')));
	expect(places.size).toBeGreaterThan(1);
});

const item = (over: Partial<QueueCard>, attempts = 0) => ({ card: card(over), attempts });
const keys = (round: { card: QueueCard }[]) => round.map((i) => i.card.key).sort();
/** A fixed sequence standing in for Math.random, so a round can be pinned. */
const seeded = (seed: number) => () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);

test('a matching round takes fresh cards that belong together', () => {
	const round = matchRound([
		item({ key: 'a', prompt: '나라', answer: 'country', group: { en: 'Countries' } }),
		item({ key: 'b', prompt: '한국', answer: 'Korea', group: { en: 'Countries' } }),
		item({ key: 'c', prompt: '중국', answer: 'China', group: { en: 'Countries' } }),
		item({ key: 'd', prompt: '일본', answer: 'Japan', group: { en: 'Countries' } }),
		item({ key: 'e', prompt: '의사', answer: 'doctor', group: { en: 'Jobs' } })
	]);
	expect(keys(round)).toEqual(['a', 'b', 'c', 'd']);
});

test('a card past the recognition stage is never put in a grid', () => {
	// `RECOGNITION_CAP` means a matched answer can never push a card past a day,
	// so matching a word you have held for a fortnight pins it there for good.
	const mature = [
		item({ key: 'a', suggest: 'typed' }),
		item({ key: 'b', prompt: '한국', answer: 'Korea', suggest: 'typed' }),
		item({ key: 'c', prompt: '중국', answer: 'China', suggest: 'build' }),
		item({ key: 'd', prompt: '일본', answer: 'Japan', suggest: 'typed' })
	];
	expect(matchRound(mature)).toEqual([]);
	expect(recognising(card({ suggest: 'typed' }))).toBe(false);
	expect(recognising(card({ suggest: 'choice' }))).toBe(true);
	expect(recognising(card({ suggest: 'match' }))).toBe(true);
});

test('a new word still is, which is what a grid is for', () => {
	const round = matchRound([
		item({ key: 'a', suggest: 'choice' }),
		item({ key: 'b', prompt: '한국', answer: 'Korea', suggest: 'choice' }),
		item({ key: 'c', prompt: '중국', answer: 'China', suggest: 'match' }),
		item({ key: 'd', prompt: '일본', answer: 'Japan', suggest: 'choice' }),
		item({ key: 'e', prompt: '의사', answer: 'doctor', suggest: 'typed' })
	]);
	expect(keys(round)).toEqual(['a', 'b', 'c', 'd']);
});

test('a card already answered this session is not hidden in a grid', () => {
	const seen = [
		item({ key: 'a' }, 1),
		item({ key: 'b', prompt: '한국', answer: 'Korea' }),
		item({ key: 'c', prompt: '중국', answer: 'China' }),
		item({ key: 'd', prompt: '일본', answer: 'Japan' })
	];
	expect(matchRound(seen)).toEqual([]);
});

test('too few pairs is not a round', () => {
	expect(
		matchRound([item({ key: 'a' }), item({ key: 'b', prompt: '한국', answer: 'Korea' })])
	).toEqual([]);
});

test('a prompt that is also an answer would be ambiguous, so it is left out', () => {
	const round = matchRound([
		item({ key: 'a', prompt: 'no', answer: 'yes' }),
		item({ key: 'b', prompt: 'yes', answer: 'no' }),
		item({ key: 'c', prompt: '한국', answer: 'Korea' }),
		item({ key: 'd', prompt: '중국', answer: 'China' }),
		item({ key: 'e', prompt: '일본', answer: 'Japan' })
	]);
	// Whichever of the two conflicting cards is drawn first keeps its place.
	expect(round).toHaveLength(4);
	expect(keys(round)).toContain('c');
	expect(keys(round).filter((k) => k === 'a' || k === 'b')).toHaveLength(1);
});

test('a round widens to the lesson, and then to the session, to find five', () => {
	// One card per heading: no grid is possible inside a group, but the file has five.
	const spread = ['나라', '물건', '장소', '수', '질문'].map((g, i) =>
		item({ key: `k${i}`, prompt: `p${i}`, answer: `a${i}`, group: { ko: g } })
	);
	expect(keys(matchRound(spread))).toEqual(['k0', 'k1', 'k2', 'k3', 'k4']);

	// And when even the files differ, the session itself is the last scope.
	const files = spread.map((i, n) => ({ ...i, card: { ...i.card, data_file_id: `df${n}` } }));
	expect(matchRound(files)).toHaveLength(5);
});

const heading = (name: string, n: number, from = 0) =>
	Array.from({ length: n }, (_, i) =>
		item({ key: `${name}${from + i}`, prompt: `p${name}${from + i}`, answer: `a${name}${from + i}`, group: { en: name } })
	);

test('a long heading does not give up the same five every time', () => {
	const long = heading('Countries', 12);
	const rounds = new Set(Array.from({ length: 30 }, () => keys(matchRound(long)).join()));
	expect(rounds.size).toBeGreaterThan(1);
	for (const round of rounds) expect(round.split(',')).toHaveLength(5);
});

test('two headings that can both fill a grid both get used', () => {
	const both = [...heading('Countries', 6), ...heading('Jobs', 8)];
	const seen = new Set(
		Array.from({ length: 40 }, () => matchRound(both)[0].card.group?.en ?? '')
	);
	expect(seen).toEqual(new Set(['Countries', 'Jobs']));
});

test('the longest pocket still wins when none of them holds a whole round', () => {
	// Four is a round, three is not: here only the biggest heading can be used.
	const short = [...heading('Countries', 4), ...heading('Jobs', 3), ...heading('Places', 2)];
	for (let i = 0; i < 20; i++) {
		expect(matchRound(short).every((r) => r.card.group?.en === 'Countries')).toBe(true);
	}
});

test('the same draw gives the same round', () => {
	const long = heading('Countries', 12);
	expect(keys(matchRound(long, 5, seeded(7)))).toEqual(keys(matchRound(long, 5, seeded(7))));
});
