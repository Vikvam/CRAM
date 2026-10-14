<script lang="ts">
	/**
	 * The collection as it stands (PLAN 6, phase 4). It leads with the tree —
	 * each category a bar to tap into, down to a lesson and its headings —
	 * because "which parts have I got" is the question this page is for. The
	 * lists of words follow, and the practice habit is a screen of its own.
	 */
	import { onMount } from 'svelte';
	import { api, type Progress, type Word } from '$lib/api/client';
	import { childrenOf, streak, sum } from '$lib/progress';
	import { labelText } from '$lib/tree';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import Figures from '$lib/components/progress/Figures.svelte';
	import RuleHelp from '$lib/components/progress/RuleHelp.svelte';
	import ScopeRow from '$lib/components/progress/ScopeRow.svelte';

	/** Words in one strip. Mirrors `STRIP` on the server, which fills two of them. */
	const STRIP = 6;

	let data = $state<Progress | null>(null);
	let error = $state<string | null>(null);

	const roots = $derived(childrenOf(data?.mastery ?? [], null));
	const total = $derived(sum(roots));
	/** The troublesome strip: the same list, cut to a glimpse of it. */
	const troublesome = $derived<Word[]>(
		(data?.weak ?? []).slice(0, STRIP).map((card) => ({
			card_key: card.card_key,
			note_id: card.note_id,
			direction: card.direction,
			prompt: card.prompt,
			answer: card.answer,
			data_file_id: card.data_file_id,
			file_title: card.file_title,
			group: card.group,
			group_key: card.group_key,
			since: null
		}))
	);
	const days = $derived(streak(data?.activity ?? []));

	onMount(async () => {
		try {
			data = await api.progress();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	});
</script>

<svelte:head><title>Progress · CRAM</title></svelte:head>

<section class="stack">
	<h1>Progress</h1>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if data === null && !error}
		<Skeleton lines={4} height="var(--space-6)" label="Loading your progress" />
	{:else if data && !total.notes}
		<p class="muted empty">Nothing to measure yet. Import or type some notes and this fills in as you practise.</p>
	{:else if data}
		<Figures row={total}>
			{#snippet help()}<RuleHelp rule={data!.rule} />{/snippet}
		</Figures>

		<section class="part" aria-labelledby="collection">
			<h2 id="collection" class="label">Collection</h2>
			<ul class="rows">
				{#each roots as row (row.category_id)}
					<ScopeRow
						href="/progress/c/{row.category_id}"
						name={labelText(row.label, row.path)}
						{row}
					/>
				{/each}
			</ul>
		</section>

		<nav class="deeper part" aria-labelledby="words">
			<h2 id="words" class="label">Words</h2>
			<a href="/progress/words/mastered">
				<span class="what">Know well</span>
				<span class="figure count">{total.mastered - total.settled}</span>
				<!-- `?? []`: a server older than this page sends no words, and the
				     strip is the part that can be done without rather than the page. -->
				{@render strip(data.mastered ?? [])}
			</a>
			<a href="/progress/weak">
				<span class="what">Troublesome</span>
				<span class="figure count">{data.weak.length}</span>
				{@render strip(troublesome)}
			</a>
			<a href="/progress/words/new">
				<span class="what">Not met yet</span>
				<span class="figure count">{total.new}</span>
				{@render strip(data.unseen ?? [])}
			</a>
			{#if data.set_aside ?? 0}
				<a href="/progress/words/set-aside">
					<span class="what">Set aside</span>
					<span class="figure count">{data.set_aside ?? 0}</span>
				</a>
			{/if}
			<a href="/progress/habit">
				<span class="what">When you practised</span>
				<span class="count streak">
					{#if days}{days} day{days === 1 ? '' : 's'} in a row{:else}not today, yet{/if}
				</span>
			</a>
		</nav>
	{/if}
</section>

<!-- A few of a list's words, to show what it is made of. -->
{#snippet strip(words: Word[])}
	{#if words.length}
		<span class="words">
			{#each words as word, at (word.card_key)}
				{#if at}<span class="dot" aria-hidden="true">·</span>{/if}
				<span class="pair"><b>{word.prompt}</b> {word.answer}</span>
			{/each}
		</span>
	{/if}
{/snippet}

<style>
	.empty {
		padding: var(--space-6) 0;
	}

	.part {
		margin-top: var(--space-section);
	}

	.rows {
		margin: 0;
		padding: 0;
		list-style: none;
		border-top: var(--border) solid var(--line);
	}

	/* The lists this page is a glimpse of. Each one shows its own words, so the
	   page is about the collection rather than about four numbers. */
	.deeper {
		display: grid;
		gap: 0;
	}

	.deeper h2 {
		padding-bottom: var(--space-2);
		border-bottom: var(--border) solid var(--line);
	}

	.deeper a {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'what count'
			'words words';
		align-items: center;
		gap: 0 var(--space-4);
		padding: var(--space-3) 0;
		min-height: var(--space-8);
		border-bottom: var(--border) solid var(--line-soft);
		color: var(--text);
		text-decoration: none;
	}

	.words {
		grid-area: words;
		font-size: var(--text-sm);
		line-height: 1.7;
		color: var(--muted);
		/* Two lines of words; a third would be a list, which is the page behind it. */
		overflow: hidden;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
	}

	.pair b {
		font-weight: inherit;
		color: var(--text);
	}

	.dot {
		color: var(--line);
		margin: 0 var(--space-1);
	}

	.deeper a:hover .what {
		color: var(--text);
	}

	.what {
		grid-area: what;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
	}

	.count {
		grid-area: count;
		font-size: var(--text-xl);
		color: var(--muted);
	}

	.count.streak {
		font-family: var(--font-ui);
		font-size: var(--text-sm);
	}
</style>
