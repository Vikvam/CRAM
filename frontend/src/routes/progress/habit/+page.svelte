<script lang="ts">
	/** Whether you are keeping it up: the run of days and the grid of them.
	 *  Moved off /progress, which now leads with the collection. */
	import { onMount } from 'svelte';
	import { api, type Progress } from '$lib/api/client';
	import { heatmap, spanWeeks, streak, WEEKDAYS } from '$lib/progress';
	import Skeleton from '$lib/components/Skeleton.svelte';

	let data = $state<Progress | null>(null);
	let error = $state<string | null>(null);
	let heat = $state<HTMLDivElement | null>(null);

	// Half a year is wider than a phone: start at the end, where this week is.
	$effect(() => {
		if (heat && data) heat.scrollLeft = heat.scrollWidth;
	});

	const grid = $derived(heatmap(data?.activity ?? [], { weeks: spanWeeks(data?.activity ?? []) }));
	const today = $derived(grid.flat().filter((cell) => !cell.future).at(-1)?.day);
	const days = $derived(streak(data?.activity ?? []));
	const answered = $derived((data?.activity ?? []).reduce((n, day) => n + day.reviews, 0));

	const when = (iso: string) =>
		new Date(`${iso}T12:00:00Z`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

	onMount(async () => {
		try {
			data = await api.progress();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	});
</script>

<svelte:head><title>When you practised · CRAM</title></svelte:head>

<section class="stack">
	<a class="back" href="/progress">← Progress</a>
	<h1>When you practised</h1>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if data === null && !error}
		<Skeleton lines={3} height="var(--space-6)" label="Loading" />
	{:else if data}
		<p class="run">
			{#if days}<span class="figure big">{days}</span> <span class="of">day{days === 1 ? '' : 's'} in a row</span>
			{:else}<span class="of">Not today, yet</span>{/if}
		</p>
		<div class="heat" bind:this={heat} role="img" aria-label="{answered} answers over the last {grid.length} weeks">
			<div class="weekdays" aria-hidden="true">
				{#each WEEKDAYS as name, index (name)}
					<span>{index % 2 === 0 ? name : ''}</span>
				{/each}
			</div>
			{#each grid as week (week[0].day)}
				<div class="week">
					{#each week as cell (cell.day)}
						<span
							class="cell level-{cell.level}"
							class:future={cell.future}
							class:today={cell.day === today}
							title={cell.future ? '' : `${when(cell.day)} — ${cell.reviews} answered`}
						></span>
					{/each}
				</div>
			{/each}
		</div>
		<p class="muted small">
			{answered} answers in {grid.length} week{grid.length === 1 ? '' : 's'}
		</p>
	{/if}
</section>

<style>
	.run {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		margin: 0;
	}

	.big {
		font-size: var(--text-3xl);
	}

	.of {
		font-family: var(--font-ui);
		font-size: var(--text-md);
		color: var(--muted);
	}

	.heat {
		display: flex;
		gap: 3px;
		overflow-x: auto;
		padding-bottom: var(--space-1);
	}

	/* Half a year scrolls sideways; the day names stay where they can be read. */
	.weekdays {
		position: sticky;
		left: 0;
		z-index: var(--z-sticky);
		background: var(--bg);
		padding-right: 1px;
		display: grid;
		grid-template-rows: repeat(7, 1fr);
		gap: 3px;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--muted);
		margin-right: var(--space-1);
	}

	.weekdays span {
		line-height: 13px;
	}

	.week {
		display: grid;
		grid-template-rows: repeat(7, 1fr);
		gap: 3px;
	}

	.cell {
		width: 13px;
		height: 13px;
		border-radius: 2px;
		background: var(--sunken);
	}

	.cell.future {
		background: transparent;
	}

	.cell.today {
		outline: 1.5px solid var(--muted);
		outline-offset: 1px;
	}

	.cell.level-1 {
		background: color-mix(in srgb, var(--known) 30%, var(--sunken));
	}

	.cell.level-2 {
		background: color-mix(in srgb, var(--known) 58%, var(--sunken));
	}

	.cell.level-3 {
		background: color-mix(in srgb, var(--known) 80%, var(--sunken));
	}

	.cell.level-4 {
		background: var(--known);
	}
</style>
