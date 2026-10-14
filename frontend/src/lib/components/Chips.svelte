<script lang="ts">
	/** Editable list of explicit accepted answers (PLAN 3.5) — never guessed, always visible. */
	let {
		values = $bindable([]),
		label = 'Also accept',
		lang,
		onchange
	}: {
		values?: string[];
		label?: string;
		lang?: string | null;
		/** Called whenever the list changes, for parents that store it server-side. */
		onchange?: (values: string[]) => void;
	} = $props();

	function set(next: string[]) {
		values = next;
		onchange?.(next);
	}

	let draft = $state('');

	function add() {
		const v = draft.trim();
		if (v && !values.includes(v)) set([...values, v]);
		draft = '';
	}

	function keydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ',') {
			event.preventDefault();
			add();
		} else if (event.key === 'Backspace' && !draft && values.length) {
			set(values.slice(0, -1));
		}
	}
</script>

<div class="chips" role="group" aria-label={label}>
	<span class="muted label">{label}</span>
	{#each values as value, i (value)}
		<span class="chip" lang={lang ?? undefined}>
			{value}
			<button class="ghost" aria-label="Remove {value}" onclick={() => set(values.filter((_, j) => j !== i))}>✕</button>
		</span>
	{/each}
	<input
		type="text"
		bind:value={draft}
		onkeydown={keydown}
		onblur={add}
		placeholder={values.length ? '' : 'add…'}
		lang={lang ?? undefined}
		aria-label="Add an accepted answer"
	/>
</div>

<style>
	.chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}

	.chip {
		display: inline-flex;
		align-items: center;
		min-height: var(--tap-sm);
		padding: 0 0 0 var(--space-2);
		border-radius: var(--radius-pill);
		background: var(--accent-soft);
		color: var(--accent-ink);
	}

	.chip button {
		min-height: var(--tap-sm);
		min-width: var(--tap-sm);
		padding: 0;
		font-size: var(--text-xs);
		color: inherit;
	}

	input {
		width: 7rem;
		min-height: var(--tap-sm);
		padding: 0 var(--space-2);
		font-size: var(--text-sm);
		border-style: dashed;
		flex: 0 1 auto;
	}

</style>
