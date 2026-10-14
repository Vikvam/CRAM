<script lang="ts">
	/**
	 * One line, when the laptop cannot be reached or still owes a sync.
	 *
	 * Nothing is lost in either state, so this is not an error and is not drawn
	 * as one: it is the app saying where your answers are. It appears only when
	 * there is something to say, and never while a card is on screen — a session
	 * is the one thing in this app that gets the whole page (`chrome.svelte.ts`).
	 */
	import { sync } from '$lib/offline/sync.svelte';
	import { immersion } from '$lib/chrome.svelte';

	const waiting = $derived(sync.waiting);
	const away = $derived(!sync.online || (sync.stuck !== null && waiting > 0));
	const show = $derived(!immersion.on && (away || waiting > 0));

	const answers = (n: number) => `${n} ${n === 1 ? 'answer' : 'answers'}`;
</script>

{#if show}
	<p class="offline small no-print" role="status">
		{#if away}
			<strong>Offline.</strong>
			{#if waiting}
				{answers(waiting)} kept here, and sent when the laptop is back.
			{:else}
				Cards taken along can still be practised.
			{/if}
		{:else if sync.sending}
			Sending {answers(waiting)}…
		{:else}
			{answers(waiting)} waiting to be sent.
			<button class="link" onclick={() => sync.flush()}>Try now</button>
		{/if}
	</p>
{/if}

<style>
	.offline {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
		margin: 0 0 var(--space-4);
		padding: var(--space-2) var(--space-3);
		border-left: var(--border-strong) solid var(--line);
		background: var(--surface);
		color: var(--muted);
	}

	strong {
		color: var(--text);
		font-weight: var(--weight-bold);
	}
</style>
