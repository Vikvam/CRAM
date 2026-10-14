<script lang="ts">
	/** `choice` (PLAN 3.5): four options, one right. A wrong pick shows which was. */
	import type { QueueCard } from '$lib/api/client';
	import { renderInline } from '$lib/markdown';
	import { selecting } from '$lib/selection';
	import { forPage } from '$lib/keys';
	import { next } from '$lib/roving';
	import { CHOICE_OPTIONS, options } from '$lib/practice/modes';

	let {
		card,
		picked = $bindable(null),
		disabled = false,
		onpick
	}: {
		card: QueueCard;
		/** What was chosen, or null while the question is open. */
		picked?: string | null;
		disabled?: boolean;
		/** Called once, with whether the pick was the answer. */
		onpick: (chosen: string, correct: boolean) => void;
	} = $props();

	// Re-shuffled whenever the card changes — a card that comes back later in
	// the session must not be answerable from where the right option sat.
	const shown = $derived(options(card, CHOICE_OPTIONS));
	const correct = (option: string) => option === card.answer;

	/** The buttons themselves: the arrows move the real focus (roving.ts). */
	let refs: (HTMLButtonElement | null)[] = $state([]);

	function choose(option: string) {
		if (picked !== null || disabled) return;
		picked = option;
		onpick(option, correct(option));
	}

	function move(delta: number) {
		const at = refs.findIndex((el) => el === document.activeElement);
		refs[next(at, delta, shown.length)]?.focus();
	}

	function keydown(event: KeyboardEvent) {
		if (picked !== null || disabled || !forPage(event)) return;
		if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
			event.preventDefault();
			move(1);
			return;
		}
		if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
			event.preventDefault();
			move(-1);
			return;
		}
		// Enter and Space are the browser's job once an option has the focus.
		const n = Number(event.key);
		if (!Number.isInteger(n) || n < 1 || n > shown.length) return;
		event.preventDefault();
		choose(shown[n - 1]);
	}
</script>

<svelte:window onkeydown={keydown} />

<ul class="options" aria-label="Choose the answer">
	{#each shown as option, index (option)}
		<li>
			<button
				bind:this={refs[index]}
				class="option"
				class:right={picked !== null && correct(option)}
				class:mine={picked === option && !correct(option)}
				disabled={picked !== null || disabled}
				lang={card.answer_lang ?? undefined}
				onclick={(event) => {
					if (!selecting(event.currentTarget)) choose(option);
				}}
			>
				<span class="key" aria-hidden="true">{index + 1}</span>
				<span class="text">{@html renderInline(option)}</span>
				{#if picked !== null && correct(option)}<span class="mark">✓</span>{/if}
				{#if picked === option && !correct(option)}<span class="mark">✕</span>{/if}
			</button>
		</li>
	{/each}
</ul>

<style>
	.options {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--space-2);
	}

	.option {
		/* The one place the answer text lives, so it has to be copyable (selection.ts). */
		user-select: text;
		-webkit-user-select: text;
		width: 100%;
		justify-content: flex-start;
		gap: var(--space-3);
		text-align: left;
		min-height: calc(var(--tap) + var(--space-2));
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-md);
		line-height: var(--leading-snug);
		white-space: normal;
	}

	.option:disabled {
		opacity: 1; /* a finished question is still readable */
	}

	/* Furniture, kept out of whatever you copy. */
	.key,
	.mark {
		user-select: none;
		-webkit-user-select: none;
	}

	.key {
		flex: 0 0 var(--space-5);
		color: var(--muted);
		font-size: var(--text-xs);
	}

	.text {
		flex: 1 1 auto;
	}

	.right {
		border-width: var(--border-strong);
		border-color: var(--good);
		background: var(--good-soft);
		color: var(--good);
	}

	.mine {
		border-width: var(--border-strong);
		border-color: var(--bad);
		background: var(--bad-soft);
		color: var(--bad);
	}

	.mark {
		font-weight: var(--weight-bold);
	}

	/* No keyboard to press, so the numbers are only clutter. */
	@media (hover: none) {
		.key {
			display: none;
		}
	}
</style>
