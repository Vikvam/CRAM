/**
 * Asking before something is taken away.
 *
 * `window.confirm` blocks the whole page, cannot say what the consequence is in
 * the app's own words, and on a phone appears as the browser's dialog rather
 * than the app's. This is the same question asked in the app: one `<Confirm />`
 * lives in the layout, and anything that needs an answer awaits `ask()`.
 */

export interface Question {
	/** The decision, as a question or a short statement. */
	title: string;
	/** What will actually happen — what is kept, what is lost. */
	detail?: string;
	/** The word on the button that goes ahead. A verb, never "OK". */
	confirm?: string;
	cancel?: string;
	/** Colours the action red and starts with the cancel button focused. */
	danger?: boolean;
}

interface Pending extends Question {
	settle: (answer: boolean) => void;
}

class Confirmer {
	pending = $state<Pending | null>(null);

	ask(question: Question): Promise<boolean> {
		// A second question while one is open would lose the first one's promise.
		this.pending?.settle(false);
		return new Promise((resolve) => {
			this.pending = { ...question, settle: resolve };
		});
	}

	/** Answered, or dismissed — whichever comes first wins, the rest is ignored. */
	answer(value: boolean) {
		const open = this.pending;
		if (!open) return;
		this.pending = null;
		open.settle(value);
	}
}

export const confirmer = new Confirmer();

/** `if (!(await ask({ title: 'Delete it?' }))) return;` */
export const ask = (question: Question) => confirmer.ask(question);
