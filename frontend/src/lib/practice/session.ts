/**
 * The in-session learning loop (PLAN 3.5): a queue, not a scorekeeper.
 *
 * Anything not answered correctly comes back later in the same session, and a
 * card you missed has to be right twice in a row before it leaves. A card that
 * was right first time is done — unless it is one of the words marked to come up
 * more often, which is the one thing that asks for a card twice when nothing has
 * gone wrong. Lives in the client next to the checker, so it keeps working
 * offline later.
 *
 * That is one of two **ways a sitting runs**, and the other is a drill (`DRILL`
 * below): one pass through the scope, misses taken again at the end rather than
 * three cards later. It is the same cards, the same checker, the same grades and
 * the same scheduler — only the queue behaves differently. Nothing here reaches
 * `card_state`, which is why a style is not, and must never become, a scheduler:
 * that name is part of the stored key and would partition your history.
 */
import type { Outcome } from '@memo/answer-check';

/**
 * A gap wider than any queue: the card goes to the back of whatever is left.
 *
 * `reinsert` already clamps a gap to the queue length, so this needs no case of
 * its own — it is spelled out here only because `missGap: 2 ** 53` at a call
 * site reads like a mistake.
 */
export const AT_THE_END = Number.MAX_SAFE_INTEGER;

export interface SessionOptions<C = unknown> {
	/** Correct answers in a row a missed card needs before it leaves (default 2). */
	requiredStreak?: number;
	/** How many cards later a missed card comes back. */
	missGap?: number;
	/** How many cards later a missed-then-right card comes back for its next check. */
	confirmGap?: number;
	/**
	 * Which cards are asked a second time even when the first answer was right.
	 *
	 * A word marked to come up more often: asking it once and letting it go is
	 * the thing the mark was set to prevent. The server says which, because what
	 * a mark is worth depends on how well the card is already known — a predicate
	 * rather than a field so the loop stays about the loop.
	 */
	twice?: (card: C) => boolean;
	/**
	 * Whether `almost` lets a card go, instead of counting as a miss.
	 *
	 * Off for practice, where a near miss is the moment to look again. On for a
	 * drill, where the point is to keep moving: the answer is still *recorded*
	 * as `almost` and still reaches the scheduler as `Grade.HARD`, so the
	 * schedule knows about the wobble even though the queue let it pass.
	 */
	almostPasses?: boolean;
}

/**
 * How a drill runs, as the setup screen offers it.
 *
 * Coverage, not mastery: one correct retires a word rather than two in a row,
 * and anything that does come back comes back at the **end** of the queue, so a
 * word you keep missing can never cost you more than one extra ask per pass.
 * The loop as it stands is the opposite trade — measured over 2,460 answers it
 * spends 43% of a sitting on repeats, which is right when you are learning and
 * wrong when you are covering a list before a test.
 */
export const DRILL: Omit<SessionOptions<unknown>, 'twice'> = {
	requiredStreak: 1,
	missGap: AT_THE_END,
	confirmGap: AT_THE_END,
	almostPasses: true,
};

export interface Item<C> {
	card: C;
	attempts: number;
	streak: number;
	missed: boolean;
	done: boolean;
	/** Missed and let go for this session, by choice: it stays due. */
	setAside: boolean;
	outcomes: Outcome[];
}

export class Session<C> {
	readonly items: Item<C>[];
	private order: Item<C>[];
	private readonly required: number;
	private readonly missGap: number;
	private readonly confirmGap: number;
	private readonly twice: (card: C) => boolean;
	private readonly almostPasses: boolean;

	constructor(cards: C[], options: SessionOptions<C> = {}) {
		this.required = Math.max(1, options.requiredStreak ?? 2);
		this.missGap = Math.max(1, options.missGap ?? 3);
		this.confirmGap = Math.max(1, options.confirmGap ?? 5);
		this.twice = options.twice ?? (() => false);
		this.almostPasses = options.almostPasses ?? false;
		this.items = cards.map((card) => ({ card, attempts: 0, streak: 0, missed: false, done: false, setAside: false, outcomes: [] }));
		this.order = [...this.items];
	}

	get current(): Item<C> | undefined {
		return this.order[0];
	}

	get finished(): boolean {
		return this.order.length === 0;
	}

	get remaining(): number {
		return this.order.length;
	}

	/** The cards still queued, in the order they will be asked. */
	get pending(): Item<C>[] {
		return [...this.order];
	}

	/** Items this session is finished with — learned, or set aside. */
	get doneCount(): number {
		return this.items.filter((i) => i.done || i.setAside).length;
	}

	/** Items seen at least once — for the progress bar. */
	get seenCount(): number {
		return this.items.filter((i) => i.attempts > 0).length;
	}

	/**
	 * Record the outcome for the current card and move on. `almost` counts as
	 * "needs practice", exactly like `wrong`, inside the session.
	 * Returns the item that was answered.
	 */
	record(outcome: Outcome): Item<C> {
		const item = this.order[0];
		if (!item) throw new Error('session is finished');
		return this.recordItem(item, outcome);
	}

	/**
	 * Record an outcome for any item, not just the one at the front — a `match`
	 * round answers several cards at once, in whatever order they were paired.
	 */
	recordItem(item: Item<C>, outcome: Outcome): Item<C> {
		const at = this.order.indexOf(item);
		if (at >= 0) this.order.splice(at, 1);
		item.attempts += 1;
		item.outcomes.push(outcome);

		if (outcome === 'correct' || (this.almostPasses && outcome === 'almost')) {
			item.streak += 1;
			// Right first time is done — unless the card was missed earlier, or it is
			// one of the marked ones, which are asked twice however well they go.
			const needed = this.twice(item.card)
				? Math.max(2, this.required)
				: item.missed
					? this.required
					: 1;
			if (item.streak >= needed) {
				item.done = true;
				return item;
			}
			this.reinsert(item, this.confirmGap);
			return item;
		}

		item.missed = true;
		item.streak = 0;
		this.reinsert(item, this.missGap);
		return item;
	}

	/**
	 * Count the current card as missed and take it out of the session for good.
	 *
	 * For the word you know you do not have today: asking it twice more in a
	 * row only teaches the order of the queue. It is not done — the miss is
	 * recorded like any other, and the card stays due.
	 */
	setAside(): Item<C> {
		const item = this.order.shift();
		if (!item) throw new Error('session is finished');
		item.attempts += 1;
		item.outcomes.push('wrong');
		item.missed = true;
		item.streak = 0;
		item.setAside = true;
		return item;
	}

	/**
	 * Pull up to `size` items out of the queue to be answered together, keeping
	 * their order. They are off the queue while the round runs; recording an
	 * outcome puts a missed one back like any other.
	 */
	take(size: number, ok: (item: Item<C>) => boolean = () => true): Item<C>[] {
		const chosen = this.order.filter(ok).slice(0, size);
		this.order = this.order.filter((item) => !chosen.includes(item));
		return chosen;
	}

	/** Leave the session early; unfinished cards simply stay due. */
	stop(): void {
		this.order = [];
	}

	private reinsert(item: Item<C>, gap: number): void {
		// Never straight back to the front unless it is the only card left.
		const at = Math.min(gap, this.order.length);
		this.order.splice(at, 0, item);
	}
}
