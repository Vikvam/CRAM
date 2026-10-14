<script lang="ts">
	/**
	 * What one scope comes to: mastered and known side by side, never merged
	 * into a single "learned" figure (the user's choice), then the bar and what
	 * is left. Counted in words — a word asked both ways is one, at its weaker
	 * direction, the same rule as the dot on each sheet row.
	 */
	import type { Snippet } from 'svelte';
	import MasteryBar from './MasteryBar.svelte';
	import type { Counted } from '$lib/progress';

	let { row, help }: { row: Counted; help?: Snippet } = $props();
</script>

<div class="figures">
	<p class="headline">
		<span class="pair"><span class="figure big tnum">{row.mastered}</span><span class="of">mastered</span></span>
		<span class="pair"><span class="figure big tnum">{row.known}</span><span class="of">known</span></span>
		<span class="of total">of {row.notes} word{row.notes === 1 ? '' : 's'}</span>
		{@render help?.()}
	</p>
	<MasteryBar {row} size="lg" />
	<p class="muted small legend">
		{row.learning} learning · {row.new} not met yet{#if row.settled}
			· {row.settled} low-priority known counted as mastered{/if}
	</p>
</div>

<style>
	.headline {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-5);
		margin: 0 0 var(--space-3);
	}

	.pair {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-2);
	}

	.big {
		font-size: var(--text-3xl);
	}

	.of {
		font-family: var(--font-ui);
		font-size: var(--text-md);
		color: var(--muted);
	}

	.legend {
		margin: var(--space-2) 0 0;
	}
</style>
