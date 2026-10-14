/**
 * Which list is being filled, so every row in the app can offer to add to it.
 *
 * Nothing in this app has ever had a multi-select, and a test list is twenty
 * words out of two hundred that live in six different lessons — so the gesture
 * had to come from somewhere. This is the somewhere: turn a list on from its own
 * page, and until you turn it off, a search result and a sheet row grow a `+`.
 * One tap per word after one search, against twenty clicks across three lessons
 * found by memory.
 *
 * It survives navigation because filling a list *is* navigation: you search, you
 * open a lesson, you go back and search again. `localStorage`, which is this
 * device's and nobody else's, and wrapped because a private window can refuse
 * it — in which case collecting simply lasts as long as the page does.
 */

const KEY = 'memo.collecting';

export interface Collecting {
	id: string;
	name: string;
}

function remembered(): Collecting | null {
	try {
		const raw = localStorage.getItem(KEY);
		if (!raw) return null;
		const held = JSON.parse(raw) as Collecting;
		return held && typeof held.id === 'string' && typeof held.name === 'string' ? held : null;
	} catch {
		return null;
	}
}

class Collector {
	into = $state<Collecting | null>(null);
	/** Note ids put on the list since collecting started: what the `+` ticks off. */
	added = $state<Set<string>>(new Set());

	/** Called from the layout once the page exists, so SSR never touches storage. */
	start() {
		this.into = remembered();
	}

	collect(list: Collecting) {
		this.into = list;
		this.added = new Set();
		this.#keep();
	}

	stop() {
		this.into = null;
		this.added = new Set();
		this.#keep();
	}

	/** Remember that a word went on, so the row can say so without a refetch. */
	note(noteId: string) {
		this.added = new Set(this.added).add(noteId);
	}

	has(noteId: string): boolean {
		return this.added.has(noteId);
	}

	#keep() {
		try {
			if (this.into) localStorage.setItem(KEY, JSON.stringify(this.into));
			else localStorage.removeItem(KEY);
		} catch {
			// Refused storage: collecting lasts as long as this page, which is
			// still most of the way there.
		}
	}
}

export const collecting = new Collector();
