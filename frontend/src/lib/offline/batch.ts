/**
 * The cards taken along, for when there is no server to ask for more.
 *
 * A queue is the server's answer to "what should I practise now": which cards
 * are due, which distractors to show beside them, and what each one's state asks
 * to be practised as. None of that can be worked out here — it needs the whole
 * collection and the whole history. So the last answer is kept, and the phone
 * practises that when it cannot ask again.
 *
 * What is kept is therefore a photograph, not a feed: after a long stretch with
 * no signal the `suggest` on a card is behind what the card now deserves. The
 * answers are still graded and still replayed correctly; only the choice of
 * exercise is a little stale, which is the right thing to trade for a session on
 * a train.
 */

import type { Queue } from '$lib/api/client';
import { BATCH, all, get, put } from './db';

type Saved = {
	scope: string;
	/** When it was fetched, so the app can say how old what it is offering is. */
	at: string;
	/** Asked for, rather than merely passed through. See `save`. */
	taken: boolean;
	queue: Queue;
};

/** One lesson, or one heading of it — what a session was narrowed to. */
export type Within = { fileId?: string; group?: string };

/** What a queue was asked for, as one string: the key it is remembered under. */
export const scopeOf = (categoryId?: string, within: Within = {}) =>
	[categoryId ?? '', within.fileId ?? '', within.group ?? ''].join('|');

/**
 * Keep a queue for later.
 *
 * `taken` marks a batch fetched deliberately for being away, which is bigger
 * than a session's worth. Merely opening the page must not throw that away for
 * twenty ordinary due cards, so an incidental save never replaces one — only a
 * fresher deliberate batch does.
 */
export async function save(scope: string, queue: Queue, taken = false): Promise<void> {
	if (!taken) {
		const before = await saved(scope);
		if (before?.taken) return;
	}
	await put<Saved>(BATCH, { scope, at: new Date().toISOString(), taken, queue });
}

export const saved = (scope: string) => get<Saved>(BATCH, scope);

/** A batch worth topping up again: none, too small to last, or yesterday's. */
export function stale(kept: Saved | null, want: number, now: number = Date.now()): boolean {
	if (!kept?.taken) return true;
	if (kept.queue.cards.length < want) return true;
	return now - new Date(kept.at).getTime() > A_DAY;
}

const A_DAY = 24 * 60 * 60 * 1000;

/**
 * Anything at all to practise, when this scope has nothing of its own.
 *
 * Packing for the journey and then opening one lesson would otherwise be a dead
 * end: the batch is remembered against what was asked for, and one lesson is
 * not what was asked for. The widest batch there is covers more than the lesson
 * rather than less, so it is offered instead — and the page says so, because
 * being given other lessons' cards without explanation would be a bug.
 */
export async function widest(): Promise<Saved | null> {
	const every = await all<Saved>(BATCH);
	return every.reduce<Saved | null>(
		(best, one) => (!best || one.queue.cards.length > best.queue.cards.length ? one : best),
		null
	);
}

/**
 * The batch, with anything already answered dropped.
 *
 * Two offline sessions in a row would otherwise be handed the same cards, since
 * nothing has been able to tell the server they were answered. The outbox is the
 * record of what this device has done since, so it is what makes the second
 * session move on.
 */
export function remaining(queue: Queue, answered: ReadonlySet<string>): Queue {
	return { ...queue, cards: queue.cards.filter((card) => !answered.has(card.key)) };
}

/**
 * Of a batch kept on this device, one sitting of the size that was asked for.
 *
 * The server does this when it can be reached (`_shares` in
 * `practice/service.py`), and the rule is restated here rather than asked for,
 * the way the mode rules are: a phone with no signal has to be able to answer
 * the question by itself. A batch is several sittings' worth on purpose, so
 * without this a session on a train is the whole batch.
 *
 * `NEW_SHARE` is held back for cards not met yet — a pile of due cards would
 * otherwise own every offline sitting — and whichever side is short, the other
 * fills the room. The batch arrives due-first, so each side is taken in order.
 */
export const NEW_SHARE = 0.25;

export function sized(queue: Queue, limit: number | null): Queue {
	if (limit === null || queue.cards.length <= limit) return queue;
	const fresh = queue.cards.filter((card) => card.is_new);
	const seen = queue.cards.filter((card) => !card.is_new);
	const takeNew = Math.min(fresh.length, Math.floor(limit * NEW_SHARE));
	const takeSeen = Math.min(seen.length, limit - takeNew);
	return {
		...queue,
		cards: [...seen.slice(0, takeSeen), ...fresh.slice(0, limit - takeSeen)]
	};
}
