/**
 * Which widget a card is practised with (PLAN 3.5).
 *
 * The server sends a suggestion per card, from that card's own scheduler state;
 * this decides whether the suggestion (or the mode you forced for the session)
 * can actually be shown — a `build` needs an answer worth cutting up, a
 * `choice` needs wrong options to offer. The numbers mirror
 * `memo.practice.modes` on the server; they are stated in both places because
 * each side has to answer the question without asking the other.
 */
import { pieces } from '@memo/answer-check';
import type { QueueCard } from '$lib/api/client';

export type Mode = 'flip' | 'typed' | 'choice' | 'match' | 'build';
/** What the start screen offers: a mode, or letting each card decide. */
export type Answering = Mode | 'auto';

export const CHOICE_OPTIONS = 4;
export const MATCH_PAIRS = 5;
/** Below this a matching grid is just a list with the answers next to it. */
export const MATCH_MINIMUM = 4;
export const BUILD_WORDS: [number, number] = [2, 6];
export const BUILD_GRAPHEMES: [number, number] = [2, 12];

/** Every mode there is, in the order the UI lists them (mirrors `ALL_MODES`). */
export const ALL_MODES: Mode[] = ['flip', 'typed', 'choice', 'match', 'build'];

/** Modes you can ask for by name; `match` only ever arrives as a whole round. */
export const FORCEABLE: Mode[] = ['typed', 'flip', 'choice', 'build'];

export const LABELS: Record<Answering, { title: string; hint: string }> = {
	auto: {
		title: 'Let the card decide',
		hint: 'New words are recognised first, then typed, then built from pieces.',
	},
	typed: {
		title: 'Type the answer',
		hint: 'Checked for you; small slips are shown, not failed.',
	},
	flip: {
		title: 'Flip and judge yourself',
		hint: 'See the answer, then say how well you knew it.',
	},
	choice: {
		title: 'Pick the answer',
		hint: 'Four options, from the same lesson where possible.',
	},
	build: {
		title: 'Build from pieces',
		hint: 'Assemble the answer out of shuffled tiles.',
	},
	match: { title: 'Match pairs', hint: 'Pair five prompts with five answers.' },
};

export function tiles(answer: string): string[] {
	return pieces(answer);
}

export function canBuild(answer: string): boolean {
	const parts = tiles(answer);
	const [low, high] =
		parts.length > 1 && answer.trim().includes(' ')
			? BUILD_WORDS
			: BUILD_GRAPHEMES;
	return parts.length >= low && parts.length <= high;
}

/**
 * Whether there are enough wrong options to make this a question.
 *
 * The same threshold the server applies (`suggest_mode`, `practice/modes.py`):
 * a full set of options, not merely one. Below it a forced `choice` would render
 * a two-button question answerable by a coin, and — being a recognition mode —
 * cap the card at a day for its trouble.
 */
export function canChoose(card: QueueCard): boolean {
	return card.distractors.length >= CHOICE_OPTIONS - 1;
}

/** The modes this card allows: the session's, narrowed by the note's own list. */
export function allowedFor(card: QueueCard, allowed: string[]): Mode[] {
	const own = card.modes?.length ? card.modes : allowed;
	return allowed.filter((m) => own.includes(m)) as Mode[];
}

/**
 * The widget to show. `wanted` is the forced mode, or `auto` to follow the
 * card. Anything that cannot be rendered falls back the same way the server
 * chooses: towards typing, then flipping — never towards nothing.
 */
export function modeFor(
	card: QueueCard,
	wanted: Answering,
	allowed: string[],
): Mode {
	const usable = allowedFor(card, allowed);
	const first = wanted === 'auto' ? (card.suggest as Mode) : wanted;
	// `match` is a round of several cards; on its own it is a one-card choice.
	const order: Mode[] = [
		first === 'match' ? 'choice' : first,
		'typed',
		'flip',
		'choice',
		'build',
	];
	for (const mode of order) {
		if (!usable.includes(mode)) continue;
		if (mode === 'choice' && !canChoose(card)) continue;
		if (mode === 'build' && !canBuild(card.answer)) continue;
		return mode;
	}
	return 'flip';
}

/** Where the randomness comes from; a test passes its own to pin a round. */
export type Pick = () => number;

/** The modes that only ask you to recognise an answer, not to produce it. */
const RECOGNITION: Mode[] = ['choice', 'match'];

/**
 * Whether this card is still at the stage where recognising it is the exercise.
 *
 * Read off the server's own suggestion, which is a function of how long the card
 * has been held (`suggest_mode`, switching to `typed` at a day). It matters
 * because a recognition answer may never push a card past one day
 * (`RECOGNITION_CAP`): a word you have known for a fortnight, dropped into a
 * matching grid, is pinned there and comes back every single day. On the real
 * collection that was 72 of the 98 cards never once answered wrong.
 */
export function recognising(card: QueueCard): boolean {
	return RECOGNITION.includes(card.suggest as Mode);
}

/**
 * Cards that can be laid out as one matching round: same group where possible,
 * never two with the same prompt or the same answer (the pairing would be
 * ambiguous), only cards not yet answered this session — a card you have
 * already missed comes back on its own, not hidden in a grid — and only cards
 * still being recognised, which is what the line below this one used to claim
 * and did not do.
 *
 * Which cards is left loose on purpose. Scope still narrows the same way, but
 * inside it a heading of twelve words would otherwise always give up the same
 * five, and two headings that could both fill a grid would always be settled by
 * whichever is longer — so a session repeats itself. Both are drawn instead.
 */
export function matchRound<T extends { card: QueueCard; attempts: number }>(
	items: T[],
	size = MATCH_PAIRS,
	pick: Pick = Math.random
): T[] {
	const fresh = items.filter(
		(i) =>
			i.attempts === 0 &&
			recognising(i.card) &&
			i.card.prompt.trim() &&
			i.card.answer.trim(),
	);
	// Tightest scope first, the way distractors widen: a grid of one heading is
	// the best round, one lesson is still a good one, and a session that mixes
	// lessons is better matched than not matched at all.
	const scopes = [
		(c: QueueCard) => `${c.data_file_id}/${c.direction}/${JSON.stringify(c.group ?? '')}`,
		(c: QueueCard) => `${c.data_file_id}/${c.direction}`,
		(c: QueueCard) => c.direction
	];
	for (const scope of scopes) {
		const pockets = new Map<string, T[]>();
		for (const item of fresh) {
			const key = scope(item.card);
			pockets.set(key, [...(pockets.get(key) ?? []), item]);
		}
		// Any pocket with a whole round in it is as good as any other, so they are
		// tried in a random order; the short ones keep the longest-first rule,
		// where picking the biggest is the only way to reach four pairs at all.
		const all = [...pockets.values()];
		const full = shuffled(all.filter((p) => p.length >= size), pick);
		const partial = all.filter((p) => p.length < size).sort((a, b) => b.length - a.length);
		for (const pocket of [...full, ...partial]) {
			const chosen: T[] = [];
			const seen = new Set<string>();
			for (const item of shuffled(pocket, pick)) {
				const prompt = item.card.prompt.trim().toLowerCase();
				const answer = item.card.answer.trim().toLowerCase();
				if (seen.has(prompt) || seen.has(answer)) continue;
				seen.add(prompt);
				seen.add(answer);
				chosen.push(item);
				if (chosen.length === size) break;
			}
			if (chosen.length >= MATCH_MINIMUM) return chosen;
		}
	}
	return [];
}

/** Fisher-Yates, so option order says nothing about which one is right. */
export function shuffled<T>(values: readonly T[], pick: Pick = Math.random): T[] {
	const out = [...values];
	for (let i = out.length - 1; i > 0; i--) {
		const j = Math.floor(pick() * (i + 1));
		[out[i], out[j]] = [out[j], out[i]];
	}
	return out;
}

/** The options for one `choice` card: the answer plus its best distractors. */
export function options(card: QueueCard, count = CHOICE_OPTIONS): string[] {
	return shuffled([
		card.answer,
		...card.distractors.slice(0, Math.max(0, count - 1)),
	]);
}
