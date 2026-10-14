<script lang="ts">
	/**
	 * A rule you can ask about, rather than one you are told every time.
	 *
	 * The app used to explain itself on every screen — 521 words of it. The
	 * explanations that are genuinely load-bearing live in here instead: a
	 * small ? beside the heading they belong to. A native <details> does the
	 * work, so it opens with the keyboard and needs no state.
	 */
	let { label = 'What this means', children }: { label?: string; children: import('svelte').Snippet } = $props();
</script>

<details class="help no-print">
	<summary aria-label={label}>?</summary>
	<div class="body small muted">{@render children()}</div>
</details>

<style>
	.help {
		display: inline-block;
		vertical-align: middle;
	}

	summary {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: var(--tap-sm);
		height: var(--tap-sm);
		margin: calc(-1 * var(--space-2)) 0;
		border-radius: 50%;
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		color: var(--muted);
		cursor: pointer;
		list-style: none;
		transition: color var(--dur-fast) var(--ease);
	}

	summary::-webkit-details-marker {
		display: none;
	}

	summary::before {
		content: '';
		position: absolute;
		width: 1.35rem;
		height: 1.35rem;
		border: var(--border) solid var(--line);
		border-radius: 50%;
	}

	summary:hover {
		color: var(--text);
	}

	details[open] summary {
		color: var(--text);
	}

	.body {
		display: block;
		max-width: 44ch;
		margin-top: var(--space-2);
		padding-left: var(--space-3);
		border-left: var(--border) solid var(--line-soft);
	}
</style>
