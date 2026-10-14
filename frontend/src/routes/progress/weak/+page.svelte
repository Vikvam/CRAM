<script lang="ts">
	/** The cards that keep going wrong, and the one thing to do about them. */
	import { onMount } from 'svelte';
	import { api, type Progress, type WeakCard } from '$lib/api/client';
	import { ask } from '$lib/confirm.svelte';
	import Help from '$lib/components/Help.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';

	let data = $state<Progress | null>(null);
	let error = $state<string | null>(null);
	/** Notes just set aside, so the row can say so instead of vanishing under you. */
	let aside = $state<Record<string, boolean>>({});

	/**
	 * Leave a word out of practice.
	 *
	 * A word that has been missed every week since you met it is not learning
	 * anything from coming round again; this is the one thing the list could
	 * never do about that. It is a note, not a card, so both directions go — and
	 * nothing is lost: the history stays and `/progress/words/set-aside` is the
	 * way back.
	 */
	async function setAside(card: WeakCard) {
		const ok = await ask({
			title: `Set ${card.prompt} aside?`,
			detail: 'It leaves practice both ways round, keeps its history, and can be brought back.',
			confirm: 'Set aside'
		});
		if (!ok) return;
		try {
			await api.patchNote(card.note_id, { suspended: true });
			aside = { ...aside, [card.note_id]: true };
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(async () => {
		try {
			data = await api.progress();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	});
</script>

<svelte:head><title>Going wrong · CRAM</title></svelte:head>

<section class="stack">
	<a class="back" href="/progress">← Progress</a>
	<h1>
		Going wrong
		<Help label="How this list is ordered">
			<p>
				The words you have missed in the last {data?.window_days ?? 30} days, most-missed first. Only
				recent misses count, so a word that went badly in the spring and has been right ever since is
				not on it.
			</p>
			<p>
				Which way round a card is asked is which side leads: the word first when you are asked for its
				meaning, the meaning first when you are asked for the word.
			</p>
		</Help>
	</h1>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if data === null && !error}
		<Skeleton lines={5} height="var(--space-6)" label="Loading" />
	{:else if data && !data.weak.length}
		<p class="muted empty">Nothing has gone wrong in the last {data.window_days} days.</p>
	{:else if data}
		<ul class="weak">
			{#each data.weak as card (card.card_key)}
				<li>
					<span class="pair"><strong>{card.prompt}</strong> {card.answer}</span>
					<a class="whence" href="/files/{card.data_file_id}?note={card.note_id}">{card.file_title ?? 'untitled file'}</a>
					{#if aside[card.note_id]}
						<span class="muted small done">set aside</span>
					{:else}
						<button class="link" onclick={() => setAside(card)}>Set aside</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	h1 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.empty {
		padding: var(--space-6) 0;
	}

	.weak {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	/* Two lines a word at most: what is asked and what answers it, then where it
	   came from and the one thing to do about it. It used to be six, and the
	   lesson's four names were louder than the word they belonged to. */
	.weak li {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 0 var(--space-3);
		padding: var(--space-3) 0;
		border-bottom: var(--border) solid var(--line-soft);
	}

	.pair {
		flex: 1 1 100%;
		min-width: 0;
		font-size: var(--text-md);
		color: var(--muted);
	}

	.pair strong {
		font-size: var(--text-lg);
		font-weight: var(--heading-weight);
		letter-spacing: var(--heading-tracking);
		color: var(--text);
		margin-right: var(--space-2);
	}

	/* One line, cut off rather than wrapped: it is a label, not a sentence. */
	.whence {
		flex: 1 1 auto;
		min-width: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--muted);
	}

	.weak button,
	.done {
		flex: 0 0 auto;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
	}
</style>
