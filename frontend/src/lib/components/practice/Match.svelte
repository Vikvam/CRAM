<script lang="ts">
	/** `match` (PLAN 3.5): pair up a handful of prompts and answers.
	 *  One round answers several cards, so each pair is logged for its own card —
	 *  a word you paired straight away is not dragged down by one you fumbled. */
	import type { QueueCard } from '$lib/api/client';
	import type { Outcome } from '@memo/answer-check';
	import { renderInline } from '$lib/markdown';
	import { labelBoth } from '$lib/tree';
	import { tick } from 'svelte';
	import { selecting } from '$lib/selection';
	import { forPage } from '$lib/keys';
	import { next } from '$lib/roving';
	import { shuffled } from '$lib/practice/modes';

	let {
		cards,
		disabled = false,
		onresolved,
		oncomplete
	}: {
		cards: QueueCard[];
		disabled?: boolean;
		/** Once per card, as it is paired correctly. */
		onresolved: (card: QueueCard, outcome: Outcome) => void;
		/** When every pair is found. */
		oncomplete: () => void;
	} = $props();

	type Side = 'prompt' | 'answer';

	const prompts = $derived(shuffled(cards));
	const answers = $derived(shuffled(cards));
	const group = $derived(cards.find((c) => c.group)?.group ?? null);

	let chosen = $state<{ side: Side; key: string } | null>(null);
	let done = $state<string[]>([]);
	let missed = $state<string[]>([]);
	let wrong = $state<{ prompt: string; answer: string } | null>(null);

	const paired = (key: string) => done.includes(key);

	/**
	 * The two columns of buttons, so the arrows can move the real focus between
	 * them (roving.ts). Up and down walk a column, left and right cross over,
	 * and a pair that has been found is stepped over rather than landed on.
	 */
	let refs: (HTMLButtonElement | null)[][] = $state([[], []]);
	const shownIn = (col: number) => (col === 0 ? prompts : answers);
	const takenIn = (col: number) => (row: number) => paired(shownIn(col)[row]?.key ?? '');

	/** Which column and row has the focus, or null when nothing here does. */
	function cursor(): { col: number; row: number } | null {
		for (const col of [0, 1]) {
			const row = refs[col].findIndex((el) => el === document.activeElement);
			if (row >= 0) return { col, row };
		}
		return null;
	}

	function land(col: number, row: number) {
		refs[col][row]?.focus();
	}

	function keydown(event: KeyboardEvent) {
		if (disabled || !forPage(event)) return;
		const vertical = event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0;
		const across = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
		if (!vertical && !across) return; // Enter on a focused tile is the browser's
		event.preventDefault();
		const at = cursor();
		if (!at) {
			// Nothing focused yet: the first arrow starts at the top of the prompts.
			land(0, next(-1, 1, prompts.length, takenIn(0)));
			return;
		}
		if (vertical) {
			land(at.col, next(at.row, vertical, shownIn(at.col).length, takenIn(at.col)));
		} else {
			// Across keeps the row where it can, and slides to the nearest free one.
			const col = at.col === 0 ? 1 : 0;
			land(col, next(at.row, 0, shownIn(col).length, takenIn(col)));
		}
	}

	async function keepTheFocus(col: number, row: number) {
		// A found pair goes `disabled`, which drops the focus on the floor. Put it
		// on the next tile still in play, so the keyboard can carry on.
		await tick();
		if (done.length === cards.length) return; // the round is over; the page moves on
		land(col, next(row, 0, shownIn(col).length, takenIn(col)));
	}

	function tap(side: Side, card: QueueCard) {
		if (disabled || paired(card.key)) return;
		wrong = null;
		if (!chosen || chosen.side === side) {
			chosen = { side, key: card.key };
			return;
		}
		const promptKey = side === 'prompt' ? card.key : chosen.key;
		const answerKey = side === 'answer' ? card.key : chosen.key;
		chosen = null;

		if (promptKey === answerKey) {
			const from = cursor();
			done = [...done, promptKey];
			if (from) keepTheFocus(from.col, from.row);
			const match = cards.find((c) => c.key === promptKey)!;
			// First attempt decides it: finding it after a wrong guess is not knowing it.
			onresolved(match, missed.includes(promptKey) ? 'wrong' : 'correct');
			if (done.length === cards.length) oncomplete();
			return;
		}
		// Both halves of a wrong pairing are marked: you did not know either one.
		missed = [...new Set([...missed, promptKey, answerKey])];
		wrong = { prompt: promptKey, answer: answerKey };
	}

	const classes = (side: Side, card: QueueCard) => ({
		pairedUp: paired(card.key),
		picked: chosen?.side === side && chosen.key === card.key,
		missed: wrong?.[side === 'prompt' ? 'prompt' : 'answer'] === card.key
	});
</script>

<svelte:window onkeydown={keydown} />

<div class="match stack">
	<p class="muted small head">
		{#if group}{labelBoth(group)} ·{/if}
		{done.length} of {cards.length} paired
	</p>

	<div class="columns">
		<ul aria-label="Prompts">
			{#each prompts as card, index (card.key)}
				{@const state = classes('prompt', card)}
				<li>
					<button
						bind:this={refs[0][index]}
						class="tile"
						class:done={state.pairedUp}
						class:picked={state.picked}
						class:wrong={state.missed}
						aria-pressed={state.picked}
						disabled={disabled || state.pairedUp}
						lang={card.prompt_lang ?? undefined}
						onclick={(event) => {
							if (!selecting(event.currentTarget)) tap('prompt', card);
						}}
					>
						{@html renderInline(card.prompt)}
						{#if state.pairedUp}<span class="mark" aria-hidden="true">✓</span>{/if}
					</button>
				</li>
			{/each}
		</ul>

		<ul aria-label="Answers">
			{#each answers as card, index (card.key)}
				{@const state = classes('answer', card)}
				<li>
					<button
						bind:this={refs[1][index]}
						class="tile"
						class:done={state.pairedUp}
						class:picked={state.picked}
						class:wrong={state.missed}
						aria-pressed={state.picked}
						disabled={disabled || state.pairedUp}
						lang={card.answer_lang ?? undefined}
						onclick={(event) => {
							if (!selecting(event.currentTarget)) tap('answer', card);
						}}
					>
						{@html renderInline(card.answer)}
						{#if state.pairedUp}<span class="mark" aria-hidden="true">✓</span>{/if}
					</button>
				</li>
			{/each}
		</ul>
	</div>

	{#if wrong}<p class="small bad" role="status">Not a pair — try again.</p>{/if}
</div>

<style>
	.head {
		margin: 0;
	}

	.columns {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
	}

	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-2);
		align-content: start;
	}

	.tile {
		/* Both columns are study text, so they have to be copyable (selection.ts). */
		user-select: text;
		-webkit-user-select: text;
		width: 100%;
		min-height: var(--space-8);
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-md);
		line-height: var(--leading-snug);
		justify-content: space-between;
		gap: var(--space-2);
		white-space: normal;
		text-align: left;
	}

	.picked {
		border-color: var(--accent);
		background: var(--accent-soft);
		color: var(--accent-ink);
		font-weight: var(--weight-semibold);
	}

	.done {
		border-color: var(--good);
		background: var(--good-soft);
		color: var(--good);
		opacity: 1;
	}

	.wrong {
		border-color: var(--bad);
		background: var(--bad-soft);
		color: var(--bad);
	}

	.bad {
		color: var(--bad);
		margin: 0;
	}

	.mark {
		font-weight: var(--weight-bold);
		user-select: none;
		-webkit-user-select: none;
	}

	@media (max-width: 420px) {
		.tile {
			font-size: var(--text-base);
			padding: var(--space-2);
		}
	}
</style>
