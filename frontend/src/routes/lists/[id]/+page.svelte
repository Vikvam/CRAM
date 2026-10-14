<script lang="ts">
	/**
	 * One list: its words, its focus, and the two things to do with it.
	 *
	 * *Drill* asks every word on it whether or not the scheduler wanted it today,
	 * because a test next Friday is not something the schedule knows about. It
	 * cannot cost you anything: an answer given well ahead of a card's own date is
	 * counted without rescheduling it, so drilling a word you already know keeps
	 * the interval it earned.
	 */
	import { page } from '$app/state';
	import { api, type WordListWords } from '$lib/api/client';
	import { ask } from '$lib/confirm.svelte';
	import { collecting } from '$lib/collecting.svelte';
	import { sync } from '$lib/offline/sync.svelte';
	import Help from '$lib/components/Help.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import WordRow from '$lib/components/WordRow.svelte';

	let held = $state<WordListWords | null>(null);
	let error = $state<string | null>(null);
	let until = $state('');

	const id = $derived(page.params.id ?? '');
	const filling = $derived(collecting.into?.id === id);

	// An effect rather than onMount, so moving between two lists refetches.
	$effect(() => {
		const wanted = id;
		if (!wanted) return;
		api
			.list(wanted)
			.then((found) => {
				held = found;
				until = found.focus_until ? found.focus_until.slice(0, 10) : '';
				error = null;
			})
			.catch((e) => {
				error = e instanceof Error ? e.message : String(e);
			});
	});

	async function refocus(value: string | null) {
		try {
			const saved = await api.patchList(id, { focus_until: value });
			if (held) held = { ...held, ...saved };
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function take(noteId: string) {
		try {
			const saved = await api.removeFromList(id, noteId);
			if (held) {
				held = { ...held, ...saved, words: held.words.filter((w) => w.note_id !== noteId) };
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function clearFocus() {
		const yes = await ask({
			title: 'Stop this list leading sittings?',
			detail: 'Its words go back to their ordinary place in the queue. The list itself stays.',
			confirm: 'Stop'
		});
		if (yes) await refocus(null);
	}
</script>

<svelte:head><title>{held?.name ?? 'List'} · CRAM</title></svelte:head>

<section class="stack">
	<div class="titling">
		<h1>{held?.name ?? 'List'}</h1>
		<a class="button" href="/lists">Lists</a>
	</div>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if held === null}
		<Skeleton lines={4} height="var(--space-6)" label="Loading the list" />
	{:else}
		<p class="status">
			{held.count} word{held.count === 1 ? '' : 's'}
			{#if held.focused}
				· leading sittings until {new Date(held.focus_until!).toLocaleDateString(undefined, {
					day: 'numeric',
					month: 'short'
				})}
			{:else if held.focus_until}
				· finished
			{/if}
			<Help label="What leading a sitting means">
				About half of each sitting goes to this list and the rest to whatever is due, so a week of
				revising does not leave a backlog behind it. A word already mastered is not pushed — a
				test needs the ones you have not got.
			</Help>
		</p>

		<div class="doing">
			{#if held.count}
				<a class="button primary" href="/practice/all?list={id}">Drill these {held.count}</a>
			{/if}
			{#if filling}
				<button type="button" onclick={() => collecting.stop()}>Done adding</button>
			{:else}
				<button
					type="button"
					onclick={() => collecting.collect({ id, name: held!.name })}
					disabled={!sync.online}
				>
					Add words
				</button>
			{/if}
			{#if held.focused}
				<button type="button" onclick={clearFocus} disabled={!sync.online}>Stop leading</button>
			{/if}
		</div>

		{#if filling}
			<p class="muted small">
				Now <a href="/?q=">search the collection</a> and tap <strong>+ list</strong> on a word — or
				open a lesson and add a whole heading.
			</p>
		{/if}

		<div class="card stack tight">
			<span class="control">
				<label for="until">Lead sittings until</label>
				<input id="until" type="date" bind:value={until} disabled={!sync.online} />
				<button
					type="button"
					disabled={!sync.online}
					onclick={() => refocus(until ? new Date(`${until}T23:59:59`).toISOString() : null)}
				>
					Save
				</button>
			</span>
		</div>

		{#if held.words.length === 0}
			<p class="muted empty">No words on it yet. <strong>Add words</strong>, then search.</p>
		{:else}
			<ul class="words">
				{#each held.words as word (word.note_id)}
					<WordRow {word}>
						{#snippet actions(hit)}
							<button type="button" onclick={() => take(hit.note_id)} disabled={!sync.online}>
								Remove
							</button>
						{/snippet}
					</WordRow>
				{/each}
			</ul>
		{/if}
	{/if}
</section>

<style>
	.titling {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-4);
		flex-wrap: wrap;
		padding-bottom: var(--space-4);
		border-bottom: var(--border-strong) solid var(--text);
	}

	.status {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-family: var(--font-ui);
		font-size: var(--text-sm);
		color: var(--muted);
	}

	.doing {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
	}

	.empty {
		padding: var(--space-6) 0;
	}

	.words {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.control {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		font-family: var(--font-ui);
		font-size: var(--text-sm);
	}
</style>
