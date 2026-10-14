/**
 * Taking cards along, without having had to think of it in advance.
 *
 * The phone can only practise what it has already been handed. It used to be a
 * button, which was both easy to miss and a decision the app can make for
 * itself; then it was a top-up after a practice screen loaded, which left a
 * phone that had only ever seen the home screen with nothing on it at all
 * (found on a real phone, 2026-10-10). So it also runs when the app opens.
 *
 * Kept out of `batch.ts` on purpose: that module is pure rules with unit tests,
 * and this one has to reach the network.
 */

import { api } from '$lib/api/client';
import { save, saved, scopeOf, stale, type Within } from './batch';

/** How many cards to keep on the device: several sessions, not one. */
export const TAKE_ALONG = 60;

/**
 * Keep a batch bigger than one session's worth for `scope`.
 *
 * Quiet by design — it is one GET against a server that is usually on the same
 * desk, and a failure means only that the batch already there still stands.
 * `force` asks again even when what is kept would have done, which is what the
 * button in Settings is for.
 */
export async function pack(
	categoryId?: string,
	within: Within = {},
	distractors?: string,
	force = false
): Promise<void> {
	const scope = scopeOf(categoryId, within);
	if (!force && !stale(await saved(scope), TAKE_ALONG)) return;
	try {
		// No `limit`: a batch is several sittings' worth, and capping it here would
		// quietly shrink what can be practised with no signal.
		const taken = await api.queue({
			categoryId,
			newLimit: TAKE_ALONG,
			distractorScope: distractors,
			within
		});
		await save(scope, taken, true);
	} catch {
		/* no signal, or nothing to spare — what is already kept still stands */
	}
}

/** How many cards are on this device, and when they were fetched. */
export async function onDevice(): Promise<{ cards: number; at: string } | null> {
	const kept = await saved(scopeOf());
	return kept ? { cards: kept.queue.cards.length, at: kept.at } : null;
}
