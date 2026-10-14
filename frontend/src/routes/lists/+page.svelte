<script lang="ts">
	/**
	 * The lists, and what each one's focus is doing.
	 *
	 * A list is the answer to "a test is coming and twenty words are on it". The
	 * mark on a word could not be that answer: it is permanent and global, so
	 * every test left sediment until more than half the collection was marked and
	 * the mark meant nothing. Here the urgency has a date on it and expires by
	 * itself, and the words keep their own marks either way.
	 */
	import { onMount } from 'svelte';
	import { api, type WordList } from '$lib/api/client';
	import { ask } from '$lib/confirm.svelte';
	import { sync } from '$lib/offline/sync.svelte';
	import Help from '$lib/components/Help.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';

	let lists = $state<WordList[] | null>(null);
	let error = $state<string | null>(null);
	let name = $state('');
	let until = $state('');
	let making = $state(false);

	async function load() {
		try {
			lists = (await api.lists()).lists;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			lists = [];
		}
	}

	async function make(event: SubmitEvent) {
		event.preventDefault();
		if (!name.trim()) return;
		making = true;
		try {
			// A date typed as a day means the end of that day: a test on Friday is
			// over by Friday evening, not at midnight the night before.
			await api.createList({
				name: name.trim(),
				focus_until: until ? new Date(`${until}T23:59:59`).toISOString() : null
			});
			name = '';
			until = '';
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			making = false;
		}
	}

	async function remove(item: WordList) {
		const yes = await ask({
			title: `Delete “${item.name}”?`,
			detail: `The ${item.count} word${item.count === 1 ? '' : 's'} on it stay in their lessons, with their marks and their history. Only the set is forgotten.`,
			confirm: 'Delete',
			danger: true
		});
		if (!yes) return;
		try {
			await api.deleteList(item.id);
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(load);

	const when = (item: WordList) => {
		if (!item.focus_until) return 'no date set';
		const date = new Date(item.focus_until);
		const day = date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
		return item.focused ? `leading sittings until ${day}` : `finished ${day}`;
	};
</script>

<svelte:head><title>Lists · CRAM</title></svelte:head>

<section class="stack">
	<div class="titling">
		<h1>
			Lists
			<Help label="What a list is for">
				Twenty words for a test, kept as a set. Give it a date and its words lead every sitting
				until the date passes — about half of one, so the rest of the collection still gets
				practised. Then the push stops by itself, with nothing to remember to undo, and the list
				stays so you can drill it again. Nothing moves out of its lesson, and no mark is written to
				any word.
			</Help>
		</h1>
		<a class="button" href="/">Collection</a>
	</div>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if lists === null}
		<Skeleton lines={3} height="var(--space-6)" label="Loading lists" />
	{:else if lists.length === 0}
		<p class="muted empty">No lists yet. Make one below, then search for its words.</p>
	{:else}
		<ul class="lists">
			{#each lists as item (item.id)}
				<li class:focused={item.focused}>
					<a class="name" href="/lists/{item.id}">{item.name}</a>
					<span class="count tnum">{item.count} word{item.count === 1 ? '' : 's'}</span>
					<span class="when muted small">{when(item)}</span>
					<button type="button" onclick={() => remove(item)} disabled={!sync.online}>Delete</button>
				</li>
			{/each}
		</ul>
	{/if}

	<div class="card stack">
		<h2>New list</h2>
		{#if !sync.online}<p class="muted small">Making a list needs the laptop.</p>{/if}
		<form class="stack tight" onsubmit={make}>
			<span class="control">
				<label class="sr-only" for="list-name">Name</label>
				<input id="list-name" type="text" bind:value={name} placeholder="Friday test" />
			</span>
			<span class="control">
				<label for="list-until">Leading sittings until</label>
				<input id="list-until" type="date" bind:value={until} />
			</span>
			<p class="muted small">
				Leave the date empty for a set you only want to drill when you choose.
			</p>
			<p>
				<button class="primary" type="submit" disabled={making || !name.trim() || !sync.online}>
					{making ? 'Making…' : 'Make the list'}
				</button>
			</p>
		</form>
	</div>
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

	h1 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.empty {
		padding: var(--space-6) 0;
	}

	.lists {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.lists li {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 0 var(--space-3);
		padding: var(--space-3) 0;
		border-bottom: var(--border) solid var(--line-soft);
	}

	.name {
		flex: 1 1 60%;
		min-width: 0;
		font-size: var(--text-lg);
		font-weight: var(--heading-weight);
		letter-spacing: var(--heading-tracking);
		color: var(--text);
	}

	/* A list that is leading sittings is the one you are working to. */
	.focused .name {
		color: var(--accent);
	}

	.count,
	.when {
		flex: 0 0 auto;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--muted);
	}

	.when {
		flex: 1 1 auto;
	}

	.lists button {
		flex: 0 0 auto;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
	}

	.control {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
	}

	.control input[type='text'] {
		flex: 1 1 auto;
		min-width: 0;
	}
</style>
