<script lang="ts">
	/**
	 * The whole of one of the lists Progress shows a glimpse of.
	 *
	 * One page for all of them, because they differ only in which words and in
	 * what the heading promises — and one of them, *set aside*, is the only way
	 * back to a word deliberately left out of practice.
	 */
	import { page } from '$app/state';
	import { api, type Word } from '$lib/api/client';
	import { ask } from '$lib/confirm.svelte';
	import Help from '$lib/components/Help.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import { labelText } from '$lib/tree';

	/** What each list is called, and what it claims. */
	const LISTS: Record<string, { title: string; help: string; empty: string }> = {
		mastered: {
			title: 'Words you know well',
			help: 'Earned enough points on the ladder, written at least once, and kept over more than one sitting — the newest first, so the top of this list is what you have just got the hang of.',
			empty: 'Nothing has got this far yet. It takes writing a word, not only recognising it, and on more than one day.'
		},
		known: {
			title: 'Words you know',
			help: 'Reliably right lately, but not yet written from memory often enough to count as kept. Newest first.',
			empty: 'Nothing here yet.'
		},
		learning: {
			title: 'Words you are learning',
			help: 'Answered at least once and not yet reliable — most of a collection lives here, and that is as it should be.',
			empty: 'Nothing here yet.'
		},
		new: {
			title: 'Words not met yet',
			help: 'In your lessons, never asked. They come up as a session makes room for them, in the order of the book.',
			empty: 'You have met every word there is. Add a lesson.'
		},
		'set-aside': {
			title: 'Words set aside',
			help: 'Left out of practice on purpose. They keep their history and their place in the lesson, and bringing one back puts it straight into the queue again.',
			empty: 'Nothing is set aside.'
		}
	};

	const bucket = $derived(page.params.bucket ?? 'mastered');
	const list = $derived(LISTS[bucket]);
	/** A list can be one lesson's or one category's, from the drill-down. */
	const file = $derived(page.url.searchParams.get('file') ?? undefined);
	const category = $derived(page.url.searchParams.get('category') ?? undefined);
	let categoryName = $state<string | null>(null);
	const back = $derived(
		file ? `/progress/f/${file}` : category ? `/progress/c/${category}` : '/progress'
	);

	let words = $state<Word[] | null>(null);
	const scope = $derived(file ? (words?.[0]?.file_title ?? null) : category ? categoryName : null);
	let total = $state(0);
	let error = $state<string | null>(null);
	/** Cards whose note has just been brought back, so the row can say so. */
	let returned = $state<Record<string, boolean>>({});

	async function load() {
		words = null;
		try {
			const found = await api.words(bucket, { limit: 500, file, category });
			words = found.words;
			total = found.total;
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	/** Put a word back into practice. Both its directions go together: it is one note. */
	async function bringBack(word: Word) {
		const ok = await ask({
			title: `Practise ${word.prompt} again?`,
			detail: 'It goes back into the queue with the history it already had.',
			confirm: 'Bring back'
		});
		if (!ok) return;
		try {
			await api.patchNote(word.note_id, { suspended: false });
			returned = { ...returned, [word.note_id]: true };
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	// Not `onMount`: changing bucket is a navigation inside the same page, and the
	// list has to follow it. The effect covers the first load as well.
	$effect(() => {
		void bucket;
		void file;
		void category;
		void load();
	});

	$effect(() => {
		if (!category) return;
		api.categories().then(
			(all) => {
				const found = all.find((c) => c.id === category);
				categoryName = found ? labelText(found.label, found.path.split('/').at(-1)) : null;
			},
			() => {}
		);
	});
</script>

<svelte:head><title>{list?.title ?? 'Words'} · CRAM</title></svelte:head>

<section class="stack">
	<a class="back" href={back}>← {file || category ? 'Back' : 'Progress'}</a>
	{#if !list}
		<h1>No such list</h1>
		<p class="muted">There is no list called “{bucket}”.</p>
	{:else}
		<h1>
			{list.title}
			{#if total}<span class="figure count">{total}</span>{/if}
			<Help label="What is on this list">{list.help}</Help>
		</h1>
		{#if scope}<p class="muted scope">in {scope}</p>{/if}

		{#if error}<p class="error" role="alert">{error}</p>{/if}

		{#if words === null && !error}
			<Skeleton lines={6} height="var(--space-6)" label="Loading" />
		{:else if words && !words.length}
			<p class="muted empty">{list.empty}</p>
		{:else if words}
			<ul class="words">
				{#each words as word (word.card_key)}
					<li>
						<span class="pair"><b>{word.prompt}</b> {word.answer}</span>
						<a class="whence" href="/files/{word.data_file_id}?note={word.note_id}">{word.file_title ?? 'untitled file'}</a>
						{#if bucket === 'set-aside'}
							{#if returned[word.note_id]}
								<span class="muted small done">back in practice</span>
							{:else}
								<button class="link" onclick={() => bringBack(word)}>Bring back</button>
							{/if}
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
</section>

<style>
	h1 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.scope {
		margin: 0;
	}

	.count {
		font-size: var(--text-lg);
		color: var(--muted);
	}

	.empty {
		padding: var(--space-6) 0;
	}

	.words {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	/* Two lines a word at most: what is asked and what answers it, then where it
	   came from and the one thing to do about it. It used to be six, and the
	   lesson's four names were louder than the word they belonged to. */
	.words li {
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

	.pair b {
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

	.words button,
	.done {
		flex: 0 0 auto;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
	}
</style>
