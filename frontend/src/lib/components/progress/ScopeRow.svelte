<script lang="ts">
	/**
	 * A category, lesson or heading as a row of the drill-down: its name and its
	 * bar, nothing else. The figures are on the screen the row opens — by the
	 * user's choice, so a list of twenty lessons reads as twenty bars, not as a
	 * table of numbers.
	 */
	import MasteryBar from './MasteryBar.svelte';
	import type { Counted } from '$lib/progress';

	let { href, name, row, lang }: { href: string; name: string; row: Counted; lang?: string } = $props();
</script>

<li>
	<a {href}>
		<span class="name" {lang}>{name}</span>
		<span class="bar"><MasteryBar {row} /></span>
		<span class="go" aria-hidden="true">›</span>
		<span class="sr-only">{row.mastered} of {row.notes} mastered, {row.known} known</span>
	</a>
</li>

<style>
	a {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'name go'
			'bar go';
		align-items: center;
		gap: var(--space-2) var(--space-4);
		min-height: var(--space-8);
		padding: var(--space-3) 0;
		border-bottom: var(--border) solid var(--line-soft);
		color: var(--text);
		text-decoration: none;
	}

	@media (min-width: 560px) {
		a {
			grid-template-columns: minmax(10rem, 22rem) 1fr auto;
			grid-template-areas: 'name bar go';
		}
	}

	.name {
		grid-area: name;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.bar {
		grid-area: bar;
	}

	.go {
		grid-area: go;
		font-size: var(--text-xl);
		color: var(--muted);
	}

	a:hover .go,
	a:focus-visible .go {
		color: var(--text);
	}
</style>
