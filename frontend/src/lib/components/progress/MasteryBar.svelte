<script lang="ts">
	/**
	 * One mastery bar: four parts, strongest first, widths rather than a score.
	 * The same bar for the whole collection, a category, a lesson or a heading;
	 * only its thickness says how big a thing it stands for.
	 */
	import { bars, type Counted } from '$lib/progress';

	let { row, size = 'md' }: { row: Counted; size?: 'sm' | 'md' | 'lg' } = $props();
</script>

<span class="bar {size}" aria-hidden="true">
	{#each bars(row) as part (part.bucket)}
		{#if part.percent}<span class={part.bucket} style="width: {part.percent}%"></span>{/if}
	{/each}
</span>

<style>
	.bar {
		display: flex;
		height: var(--space-2);
		border-radius: var(--radius-sm);
		overflow: hidden;
		background: var(--unseen);
	}

	.sm {
		height: var(--space-1);
	}

	.lg {
		height: var(--space-3);
	}

	.mastered {
		background: var(--mastered);
	}

	.known {
		background: var(--known);
	}

	.learning {
		background: var(--learning);
	}

	.new {
		background: var(--unseen);
	}
</style>
