<script lang="ts">
	/** The words behind a scope's figures, one link per bucket. */
	import type { Counted } from '$lib/progress';

	let { row, scope }: { row: Counted; scope: string } = $props();

	const LINKS = [
		{ bucket: 'mastered', what: 'Know well' },
		{ bucket: 'known', what: 'Known' },
		{ bucket: 'learning', what: 'Learning' },
		{ bucket: 'new', what: 'Not met yet' }
	] as const;
	/** A known low word is counted as mastered on the bar but listed where it is. */
	const count = (bucket: (typeof LINKS)[number]['bucket']) =>
		bucket === 'mastered'
			? row.mastered - (row.settled ?? 0)
			: bucket === 'known'
				? row.known + (row.settled ?? 0)
				: row[bucket];
</script>

<ul class="links">
	{#each LINKS as link (link.bucket)}
		{#if count(link.bucket)}
			<li>
				<a href="/progress/words/{link.bucket}?{scope}">
					<span class="what">{link.what}</span>
					<span class="figure n tnum">{count(link.bucket)}</span>
				</a>
			</li>
		{/if}
	{/each}
</ul>

<style>
	.links {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-5);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	a {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-2);
		min-height: 48px;
		align-items: center;
		color: var(--text);
		text-decoration: underline;
		text-decoration-color: var(--line);
	}

	a:hover,
	a:focus-visible {
		text-decoration-color: currentcolor;
	}

	.what {
		font-family: var(--font-ui);
		font-size: var(--text-sm);
	}

	.n {
		font-size: var(--text-md);
		color: var(--muted);
	}
</style>
