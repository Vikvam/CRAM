<script lang="ts">
	/**
	 * Hear it — one tap, the device's own voice.
	 *
	 * Draws nothing at all unless this device can actually say this language, so
	 * a laptop with no voices installed simply has no button rather than a dead
	 * one. Only the language memo is not written in is offered: the phone has an
	 * English voice too, and a speaker beside every English answer is noise.
	 */
	import { plain } from '$lib/markdown';
	import { foreign, speech } from '$lib/speech.svelte';

	let { text, lang, what = 'it' }: { text: string; lang?: string | null; what?: string } = $props();

	const words = $derived(plain(text));
	const offer = $derived(words !== '' && foreign(lang) && speech.can(lang));
	const saying = $derived(speech.saying === words);
</script>

{#if offer}
	<button
		type="button"
		class="small ghost speak no-print"
		class:saying
		aria-label={saying ? 'Stop' : `Hear ${what}`}
		onclick={() => speech.speak(words, lang)}
	>
		<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
			<path d="M8.5 2.6 4.6 5.5H2.2v5h2.4l3.9 2.9z" fill="currentColor" />
			<path
				d="M11 5.6a3.4 3.4 0 0 1 0 4.8M13.2 3.4a6.5 6.5 0 0 1 0 9.2"
				fill="none"
				stroke="currentColor"
				stroke-width="1.4"
				stroke-linecap="round"
			/>
		</svg>
	</button>
{/if}

<style>
	/* `small ghost` already gives the size, the muted colour and the hover; this
	   only makes it round and square. */
	.speak {
		width: var(--tap-sm);
		padding: 0;
		border-radius: 50%;
	}

	.saying {
		color: var(--accent);
	}
</style>
