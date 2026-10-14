<script lang="ts">
	/** The one dialog, in the layout, for every question `ask()` poses.
	 *  A native <dialog> is used for what it gives for free: the page behind it
	 *  goes inert, Escape dismisses, and focus returns where it came from. */
	import { confirmer } from '$lib/confirm.svelte';

	let dialog = $state<HTMLDialogElement | null>(null);
	let go = $state<HTMLButtonElement | null>(null);
	let stay = $state<HTMLButtonElement | null>(null);

	const question = $derived(confirmer.pending);

	$effect(() => {
		if (!dialog) return;
		if (question && !dialog.open) {
			dialog.showModal();
			// The safe answer is the one under your finger when it opens.
			(question.danger ? stay : go)?.focus();
		} else if (!question && dialog.open) {
			dialog.close();
		}
	});
</script>

<dialog bind:this={dialog} aria-labelledby="confirm-title" onclose={() => confirmer.answer(false)}>
	{#if question}
		<h2 id="confirm-title">{question.title}</h2>
		{#if question.detail}<p class="muted">{question.detail}</p>{/if}
		<div class="row buttons">
			<button bind:this={stay} onclick={() => confirmer.answer(false)}>{question.cancel ?? 'Cancel'}</button>
			<button
				bind:this={go}
				class={question.danger ? 'danger' : 'primary'}
				onclick={() => confirmer.answer(true)}>{question.confirm ?? 'Yes'}</button
			>
		</div>
	{/if}
</dialog>

<style>
	h2 {
		margin-bottom: var(--space-2);
	}

	.buttons {
		justify-content: flex-end;
		margin-top: var(--space-5);
	}
</style>
