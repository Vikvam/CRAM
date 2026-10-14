<script lang="ts">
	/**
	 * One word, as every list of words in this app shows it.
	 *
	 * The same shape the Progress strips settled on: what is asked, then what
	 * answers it, then where it came from. No counts, and no word "reverse" —
	 * except that a search result *is* the word rather than one direction of it,
	 * so the Korean always leads here and the two standings are shown instead.
	 *
	 * The lesson link carries `?note=`, so it lands on the row rather than on a
	 * fifty-six-row grid for you to search by eye.
	 */
	import type { NoteHit } from '$lib/api/client';
	import type { Snippet } from 'svelte';
	import { weakest } from '$lib/words';

	let { word, actions }: { word: NoteHit; actions?: Snippet<[NoteHit]> } = $props();

	/** Taken at its weaker direction — the hole is what a row should mark. */
	const standing = $derived(weakest(word.forward, word.reverse));
</script>

<li class:aside={word.suspended}>
	<span class="pair"><strong>{word.front}</strong> {word.back}</span>
	<a class="whence" href="/files/{word.data_file_id}?note={word.note_id}">
		{word.file_title ?? 'untitled file'}
	</a>
	{#if standing}<span class="tag standing {standing}">{standing}</span>{/if}
	{#if word.priority !== 'normal'}<span class="tag mark {word.priority}">{word.priority}</span>{/if}
	{#if word.suspended}<span class="tag">set aside</span>{/if}
	{@render actions?.(word)}
</li>

<style>
	/* Two lines a word at most, the same as every other list of words. */
	li {
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

	.tag {
		flex: 0 0 auto;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		color: var(--muted);
	}

	.standing.known,
	.standing.mastered {
		color: var(--good);
	}

	.mark.high,
	.mark.crucial {
		color: var(--almost);
	}

	/* A word left out of practice is still listed, just quietly. */
	.aside .pair strong {
		color: var(--muted);
	}
</style>
