<script lang="ts">
	/**
	 * One category: what it comes to, then each category and lesson under it as
	 * a bar to tap into. Built from the same payload as /progress, which already
	 * counts every category and every lesson.
	 */
	import { page } from '$app/state';
	import { api, type Progress } from '$lib/api/client';
	import { childrenOf, parentOf } from '$lib/progress';
	import { labelText } from '$lib/tree';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import BucketLinks from '$lib/components/progress/BucketLinks.svelte';
	import Figures from '$lib/components/progress/Figures.svelte';
	import RuleHelp from '$lib/components/progress/RuleHelp.svelte';
	import ScopeRow from '$lib/components/progress/ScopeRow.svelte';

	let data = $state<Progress | null>(null);
	let error = $state<string | null>(null);

	const id = $derived(page.params.id ?? '');
	const rows = $derived(data?.mastery ?? []);
	const row = $derived(rows.find((r) => r.category_id === id) ?? null);
	const parent = $derived(row ? parentOf(rows, row) : null);
	const name = (r: { label?: Record<string, string> | null; path: string }) =>
		labelText(r.label, r.path.split('/').at(-1) ?? r.path);
	const children = $derived(row ? childrenOf(rows, row) : []);
	const lessons = $derived((data?.files ?? []).filter((file) => file.category_id === id));

	// Not `onMount`: going from a category to one under it is a navigation
	// inside this same page, and the data is the same for both.
	$effect(() => {
		if (data) return;
		api.progress().then(
			(found) => (data = found),
			(e) => (error = e instanceof Error ? e.message : String(e))
		);
	});
</script>

<svelte:head><title>{row ? name(row) : 'Category'} · CRAM</title></svelte:head>

<section class="stack">
	<a class="back" href={parent ? `/progress/c/${parent.category_id}` : '/progress'}>
		← {parent ? name(parent) : 'Progress'}
	</a>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if data === null && !error}
		<Skeleton lines={5} height="var(--space-6)" label="Loading" />
	{:else if data && !row}
		<h1>No such category</h1>
	{:else if row}
		<div class="title">
			<h1>{name(row)}</h1>
			<a class="button small primary" href="/practice/{row.category_id}">Practise</a>
		</div>

		<Figures {row}>
			{#snippet help()}<RuleHelp rule={data!.rule} />{/snippet}
		</Figures>
		<BucketLinks {row} scope="category={row.category_id}" />

		{#if children.length}
			<section class="part" aria-labelledby="inside">
				<h2 id="inside" class="label">Categories</h2>
				<ul class="rows">
					{#each children as child (child.category_id)}
						<ScopeRow href="/progress/c/{child.category_id}" name={name(child)} row={child} />
					{/each}
				</ul>
			</section>
		{/if}

		{#if lessons.length}
			<section class="part" aria-labelledby="lessons">
				<h2 id="lessons" class="label">Lessons</h2>
				<ul class="rows">
					{#each lessons as file (file.data_file_id)}
						<ScopeRow
							href="/progress/f/{file.data_file_id}"
							name={file.title ?? 'Untitled file'}
							row={file}
						/>
					{/each}
				</ul>
			</section>
		{/if}
	{/if}
</section>

<style>
	.title {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.title h1 {
		margin: 0;
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
</style>
