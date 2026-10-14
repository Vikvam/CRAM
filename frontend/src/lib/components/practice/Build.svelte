<script lang="ts">
	/** `build` (PLAN 3.5): assemble the answer from shuffled pieces.
	 *  Words when there are several, grapheme clusters otherwise (PLAN 3.7) —
	 *  one tile per Hangul syllable, one per Latin letter, no script special-cased. */
	import { tick } from 'svelte';
	import { tiles, shuffled } from '$lib/practice/modes';
	import { selecting } from '$lib/selection';
	import { forPage } from '$lib/keys';
	import { next } from '$lib/roving';

	let {
		card,
		assembled = $bindable(''),
		disabled = false,
		oncheck
	}: {
		card: { answer: string; answer_lang?: string | null };
		/** What has been assembled so far, for the page to check. */
		assembled?: string;
		disabled?: boolean;
		/** Called when you say you are done, with the assembled text. */
		oncheck: (text: string) => void;
	} = $props();

	interface Tile {
		id: number;
		text: string;
	}

	// One entry per piece, so two identical syllables stay two tiles.
	const pool = $derived(shuffled(tiles(card.answer).map((text, id) => ({ id, text }))));
	const separator = $derived(card.answer.trim().includes(' ') ? ' ' : '');
	let used = $state<Tile[]>([]);

	// A new card clears whatever was being built.
	$effect(() => {
		pool;
		used = [];
	});

	$effect(() => {
		assembled = used.map((t) => t.text).join(separator);
	});

	const left = $derived(pool.filter((tile) => !used.some((u) => u.id === tile.id)));

	/** The pool's buttons, and the Check button the last piece hands over to. */
	let refs: (HTMLButtonElement | null)[] = $state([]);
	let checkTo: HTMLButtonElement | null = $state(null);

	/** Where the focus is in the pool, or -1 when it is somewhere else entirely. */
	const focused = () => refs.findIndex((el) => el === document.activeElement);

	async function add(tile: Tile) {
		if (disabled) return;
		const at = focused();
		used = [...used, tile];
		if (at < 0) return; // placed with a tap: nothing was focused, nothing to move
		await tick();
		// The pool is one shorter, so stay in the same slot; when it empties the
		// only thing left to do is check, which is where the focus belongs.
		if (left.length) refs[next(at, 0, left.length)]?.focus();
		else checkTo?.focus();
	}

	async function undo(tile: Tile) {
		if (disabled) return;
		const from = checkTo === document.activeElement;
		used = used.filter((u) => u.id !== tile.id);
		if (!from) return;
		await tick(); // the pool has a piece back and Check is no longer the only move
		refs[next(-1, 1, left.length)]?.focus();
	}

	function keydown(event: KeyboardEvent) {
		if (disabled || !forPage(event)) return;
		if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
			event.preventDefault();
			refs[next(focused(), 1, left.length)]?.focus();
		} else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
			event.preventDefault();
			refs[next(focused(), -1, left.length)]?.focus();
		} else if (event.key === 'Backspace' && used.length) {
			event.preventDefault();
			used = used.slice(0, -1);
		} else if (event.key === 'Enter' && used.length && focused() < 0) {
			// A focused piece is placed by the browser itself; Enter only checks
			// when the keyboard is not sitting on one.
			event.preventDefault();
			oncheck(used.map((t) => t.text).join(separator));
		}
	}
</script>

<svelte:window onkeydown={keydown} />

<div class="build stack">
	<div class="line" lang={card.answer_lang ?? undefined} aria-label="Your answer so far" aria-live="polite">
		{#each used as tile (tile.id)}
			<button
				class="tile placed"
				{disabled}
				onclick={(event) => {
					if (!selecting(event.currentTarget)) undo(tile);
				}}>{tile.text}</button>
		{/each}
		{#if !used.length}<span class="muted">Tap the pieces in order</span>{/if}
	</div>

	<div class="line pool" lang={card.answer_lang ?? undefined} aria-label="Pieces">
		{#each left as tile, index (tile.id)}
			<button
				bind:this={refs[index]}
				class="tile"
				{disabled}
				onclick={(event) => {
					if (!selecting(event.currentTarget)) add(tile);
				}}>{tile.text}</button>
		{/each}
	</div>

	<div class="row split">
		<button class="ghost" {disabled} onclick={() => oncheck('')}>I don't know</button>
		<button
			bind:this={checkTo}
			class="primary"
			disabled={disabled || !used.length}
			onclick={() => oncheck(assembled)}>Check</button
		>
	</div>
</div>

<style>
	.line {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
		min-height: var(--space-8);
		padding: var(--space-2);
		border: var(--border) dashed var(--line);
		border-radius: var(--radius);
	}

	.pool {
		border-style: solid;
		background: var(--sunken);
	}

	.tile {
		/* A drag across the pieces copies the line you have built (selection.ts). */
		user-select: text;
		-webkit-user-select: text;
		font-size: var(--text-lg);
		min-height: var(--tap);
		padding: 0 var(--space-3);
	}

	.placed {
		border-color: var(--accent);
		background: var(--accent-soft);
		color: var(--accent-ink);
	}

	.split {
		justify-content: space-between;
	}
</style>
