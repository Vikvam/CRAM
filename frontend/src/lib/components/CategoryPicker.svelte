<script lang="ts">
	/** Choose a category — one that exists, or one you type here and now.
	 *  Used wherever something has to land somewhere: an upload, a review, a data file. */
	import { api, type Category } from '$lib/api/client';
	import { labelText } from '$lib/tree';

	const NEW = '\u0000new';

	let {
		value = $bindable(''),
		categories = $bindable<Category[]>([]),
		disabled = false,
		onpick
	}: {
		/** The chosen category's id. */
		value?: string;
		/** Every category. A new one is added here too, so the caller sees it. */
		categories?: Category[];
		disabled?: boolean;
		/** Called after a pick, including a freshly made category. */
		onpick?: (id: string) => void;
	} = $props();

	let typing = $state(false);
	let path = $state('');
	let busy = $state(false);
	let error = $state<string | null>(null);

	const sorted = $derived([...categories].sort((a, b) => a.path.localeCompare(b.path)));
	const name = (c: Category) => (labelText(c.label) ? `${c.path} — ${labelText(c.label)}` : c.path);

	function choose(event: Event) {
		const chosen = (event.currentTarget as HTMLSelectElement).value;
		if (chosen === NEW) {
			typing = true;
			return;
		}
		value = chosen;
		onpick?.(chosen);
	}

	async function create() {
		// A path, so "korean/book1/03-shopping" makes whatever is missing above it.
		const wanted = path.trim().replace(/^\/+|\/+$/g, '');
		if (!wanted) return;
		busy = true;
		error = null;
		try {
			const made = await api.createCategory(wanted);
			categories = [...categories.filter((c) => c.id !== made.id), made];
			value = made.id;
			typing = false;
			path = '';
			onpick?.(made.id);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="stack tight">
	{#if typing}
		<div class="row tight">
			<!-- svelte-ignore a11y_autofocus -->
			<input
				bind:value={path}
				placeholder="korean/book1/03-shopping"
				aria-label="Path of the new category"
				autofocus
				onkeydown={(e) => e.key === 'Enter' && create()}
			/>
			<button class="small primary" disabled={busy || !path.trim()} onclick={create}>Create</button>
			<button class="small ghost" disabled={busy} onclick={() => ((typing = false), (error = null))}>Cancel</button>
		</div>
	{:else}
		<select {value} {disabled} onchange={choose} aria-label="Category">
			{#each sorted as category (category.id)}
				<option value={category.id}>{name(category)}</option>
			{/each}
			<option value={NEW}>+ New category…</option>
		</select>
	{/if}
	{#if error}<p class="error small">{error}</p>{/if}
</div>

<style>
	select,
	input {
		width: 100%;
	}

	.row input {
		flex: 1 1 auto;
		min-width: 0;
	}
</style>
