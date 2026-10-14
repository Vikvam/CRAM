<script lang="ts">
	/** The shape of what is being fetched, so the page does not jump when it
	 *  arrives and the wait is not the word "Loading…". */
	let {
		lines = 3,
		height = 'var(--space-4)',
		label = 'Loading'
	}: { lines?: number; height?: string; label?: string } = $props();

	/** Unequal widths read as text rather than as a stack of bars. */
	const WIDTHS = ['100%', '82%', '91%', '74%', '96%'];
</script>

<div class="lines" role="status" aria-busy="true" aria-label={label}>
	{#each { length: lines } as _, i}
		<span class="skeleton" style="height: {height}; width: {WIDTHS[i % WIDTHS.length]}"></span>
	{/each}
</div>

<style>
	.lines {
		display: grid;
		gap: var(--space-3);
	}
</style>
