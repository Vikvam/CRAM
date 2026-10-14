<script lang="ts">
	/**
	 * One lesson in full: what it comes to, each heading as a bar that opens to
	 * its figures and a way to practise just that heading, then every word in
	 * the lesson under where it stands. One request for all of it.
	 */
	import { page } from '$app/state';
	import { api, type FileProgress, type GroupMastery, type Progress, type Word } from '$lib/api/client';
	import { labelBoth } from '$lib/tree';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import Figures from '$lib/components/progress/Figures.svelte';
	import MasteryBar from '$lib/components/progress/MasteryBar.svelte';
	import RuleHelp from '$lib/components/progress/RuleHelp.svelte';

	let data = $state<FileProgress | null>(null);
	let rule = $state<Progress['rule'] | null>(null);
	let error = $state<string | null>(null);

	const id = $derived(page.params.id ?? '');
	const file = $derived(data?.file ?? null);
	const practise = $derived(file ? `/practice/${file.category_id}?file=${file.data_file_id}` : '');
	/** Headings only earn a section when there is more than one way to cut the lesson. */
	const groups = $derived((data?.groups ?? []).length > 1 ? (data?.groups ?? []) : []);
	const heading = (group: GroupMastery) =>
		group.key === null ? 'Under no heading' : labelBoth(group.label, group.key);

	const BUCKETS = [
		{ bucket: 'mastered', what: 'Know well' },
		{ bucket: 'known', what: 'Known' },
		{ bucket: 'learning', what: 'Learning' },
		{ bucket: 'new', what: 'Not met yet' }
	] as const;
	const listed = (bucket: string): Word[] => data?.words[bucket] ?? [];

	$effect(() => {
		const wanted = id;
		data = null;
		error = null;
		api.fileProgress(wanted).then(
			(found) => {
				if (wanted === id) data = found;
			},
			(e) => (error = e instanceof Error ? e.message : String(e))
		);
	});

	// The rule's numbers live on the overview; the help is worth one more request.
	$effect(() => {
		if (rule) return;
		api.progress({ days: 1, limit: 1 }).then(
			(found) => (rule = found.rule),
			() => {}
		);
	});
</script>

<svelte:head><title>{file?.title ?? 'Lesson'} · CRAM</title></svelte:head>

<section class="stack">
	<a class="back" href={file ? `/progress/c/${file.category_id}` : '/progress'}>← Back</a>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if data === null && !error}
		<Skeleton lines={6} height="var(--space-6)" label="Loading the lesson" />
	{:else if file}
		<h1>{file.title ?? 'Untitled file'}</h1>
		<div class="actions">
			<a class="button small primary" href={practise}>Practise this file</a>
			<a class="button small" href="/files/{file.data_file_id}">Open the sheet</a>
		</div>

		<Figures row={file}>
			{#snippet help()}{#if rule}<RuleHelp {rule} />{/if}{/snippet}
		</Figures>

		{#if groups.length}
			<section class="part" aria-labelledby="headings">
				<h2 id="headings" class="label">Headings</h2>
				<ul class="rows">
					{#each groups as group (group.key ?? '')}
						<li>
							<details>
								<summary>
									<span class="name">{heading(group)}</span>
									<span class="bar"><MasteryBar row={group} /></span>
								</summary>
								<div class="open">
									<p class="muted small">
										{group.mastered} mastered · {group.known} known · {group.learning} learning ·
										{group.new} not met yet, of {group.notes}
									</p>
									{#if group.key !== null}
										<a class="button small" href="{practise}&group={encodeURIComponent(group.key)}">
											Practise this heading
										</a>
									{/if}
								</div>
							</details>
						</li>
					{/each}
				</ul>
			</section>
		{/if}

		<section class="part" aria-labelledby="words">
			<h2 id="words" class="label">Words</h2>
			<ul class="rows">
				{#each BUCKETS as { bucket, what } (bucket)}
					{#if listed(bucket).length}
						<li>
							<details>
								<summary>
									<span class="name">{what}</span>
									<span class="figure n tnum">{listed(bucket).length}</span>
								</summary>
								<ul class="words">
									{#each listed(bucket) as word (word.note_id)}
										<li>
											<a href="/files/{word.data_file_id}?note={word.note_id}">
												<b>{word.prompt}</b>
												{word.answer}
											</a>
										</li>
									{/each}
								</ul>
							</details>
						</li>
					{/if}
				{/each}
			</ul>
		</section>
	{/if}
</section>

<style>
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
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

	.rows > li {
		border-bottom: var(--border) solid var(--line-soft);
	}

	summary {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'name n'
			'bar bar';
		align-items: center;
		gap: var(--space-2) var(--space-4);
		min-height: var(--space-8);
		padding: var(--space-3) 0;
		cursor: pointer;
		list-style: none;
	}

	summary::-webkit-details-marker {
		display: none;
	}

	/* Open or shut, said by the same mark the other rows use to go somewhere. */
	summary::after {
		grid-area: n;
		justify-self: end;
		content: '›';
		font-size: var(--text-xl);
		color: var(--muted);
		transition: transform 0.15s;
	}

	details[open] > summary::after {
		transform: rotate(90deg);
	}

	summary:has(.n) {
		grid-template-columns: 1fr auto auto;
		grid-template-areas: 'name n go';
	}

	summary:has(.n)::after {
		grid-area: go;
	}

	@media (min-width: 560px) {
		summary {
			grid-template-columns: minmax(10rem, 22rem) 1fr auto;
			grid-template-areas: 'name bar n';
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

	.n {
		grid-area: n;
		font-size: var(--text-lg);
		color: var(--muted);
	}

	.open {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding: 0 0 var(--space-4);
	}

	.open p {
		margin: 0;
	}

	.words {
		margin: 0;
		padding: 0 0 var(--space-3);
		list-style: none;
	}

	.words a {
		display: block;
		padding: var(--space-2) 0;
		color: var(--muted);
		text-decoration: none;
	}

	.words b {
		font-size: var(--text-lg);
		font-weight: var(--heading-weight);
		color: var(--text);
		margin-right: var(--space-2);
	}

	.words a:hover b,
	.words a:focus-visible b {
		text-decoration: underline;
	}
</style>
