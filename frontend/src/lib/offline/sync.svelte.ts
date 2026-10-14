/**
 * Whether this device is on speaking terms with the laptop, and what it owes it.
 *
 * One owner for the outbox, so the count in the header and the flush after an
 * answer cannot disagree. Recording an answer never waits for the network and
 * never fails: it goes to disk, and the handing over happens when it can. That
 * is what makes a session with no signal feel like a session.
 */

import { api } from '$lib/api/client';
import type { AnswerBody } from '$lib/api/client';
import { OUTBOX, all, put, remove } from './db';
import { type Pending, asFile, inOrder, pendingFor, settled, unique } from './outbox';

/** Sent at once. The server takes far more; this keeps one failure cheap to retry. */
const CHUNK = 250;

class Sync {
	/** What the browser believes. Optimistic: it says nothing about the laptop being up. */
	online = $state(true);
	/** Answers written down but not yet acknowledged. */
	waiting = $state(0);
	/** True while a flush is in flight, so the indicator can say "sending" once. */
	sending = $state(false);
	/** Why the last flush got nowhere, for the banner. Null when all is well. */
	stuck = $state<string | null>(null);

	/** Begin watching. Returns the undo, as the other stores here do. */
	start(): () => void {
		if (typeof window === 'undefined') return () => {};
		this.online = navigator.onLine;
		const back = () => {
			this.online = true;
			void this.flush();
		};
		const gone = () => {
			this.online = false;
		};
		window.addEventListener('online', back);
		window.addEventListener('offline', gone);
		void this.count().then(() => this.flush());
		return () => {
			window.removeEventListener('online', back);
			window.removeEventListener('offline', gone);
		};
	}

	async count(): Promise<number> {
		this.waiting = (await all<Pending>(OUTBOX)).length;
		return this.waiting;
	}

	/** Write an answer down, then try to hand it over. Never throws; never blocks a card. */
	async record(body: AnswerBody): Promise<void> {
		const row = pendingFor(body);
		await put(OUTBOX, row);
		this.waiting += 1;
		void this.flush();
	}

	/** Card keys this device has answered since the server last heard from it. */
	async answered(): Promise<Set<string>> {
		return new Set((await all<Pending>(OUTBOX)).map((row) => row.card_key));
	}

	/** Everything still waiting, as the file `memo import-answers` reads. */
	async file(): Promise<string> {
		return asFile(await all<Pending>(OUTBOX));
	}

	/**
	 * Hand over what is waiting.
	 *
	 * Nothing is deleted until the server has said what it did with it, and a
	 * batch it never saw stays exactly as it was — being handed over twice is
	 * cheap (`client_id` catches it), being lost is not.
	 */
	async flush(again = true): Promise<void> {
		if (this.sending) return;
		const rows = inOrder(unique(await all<Pending>(OUTBOX)));
		if (!rows.length) {
			this.waiting = 0;
			this.stuck = null;
			return;
		}
		this.sending = true;
		try {
			for (let at = 0; at < rows.length; at += CHUNK) {
				const batch = rows.slice(at, at + CHUNK);
				const report = await api.uploadAnswers(batch);
				await remove(OUTBOX, settled(batch, report));
			}
			this.stuck = null;
		} catch (e) {
			// Offline, asleep, signed out: all the same answer — keep them and wait.
			this.stuck = e instanceof Error ? e.message : String(e);
		} finally {
			this.sending = false;
			const left = await this.count();
			// An answer recorded while this flush was in the air was turned away at
			// the top, and nothing else would have come back for it: the last answer
			// of a sitting would sit here until the app was reopened. One more go,
			// and only one, so a batch the server keeps refusing cannot spin.
			if (again && left && !this.stuck) void this.flush(false);
		}
	}
}

export const sync = new Sync();
