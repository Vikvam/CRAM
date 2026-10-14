<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type Category, type DataFileSummary } from '$lib/api/client';
	import { ask } from '$lib/confirm.svelte';
	import { keepFiles, keptFiles } from '$lib/offline/collection';
	import { ALL_MODES, LABELS, type Mode } from '$lib/practice/modes';
	import { labelText, type TreeNode } from '$lib/tree';
	import Self from './TreeNode.svelte';

	let {
		node,
		open = $bindable({}),
		categories = [],
		onchanged,
		offline = false
	}: {
		node: TreeNode;
		open?: Record<string, boolean>;
		/** Every category, for the "move to" list. */
		categories?: Category[];
		/** Called after a rename, move, delete or new file, so the page can reload. */
		onchanged?: () => void;
		/** No laptop to reach: practising still works, changing anything does not. */
		offline?: boolean;
	} = $props();

	const id = $derived(node.category.id);
	const name = $derived(labelText(node.category.label, node.category.slug));
	const expanded = $derived(open[id] ?? node.depth === 0);
	let files = $state<DataFileSummary[] | null>(null);
	let filesError = $state<string | null>(null);
	/** A guard, not UI: two loads of the same list would race. */
	let loadingFiles = false;

	let editing = $state(false);
	// All of these are filled by edit() when the panel opens.
	let slug = $state('');
	let pairs = $state<{ lang: string; text: string }[]>([]);
	let parentId = $state('');
	/** Practice settings: `inherit` means this category says nothing of its own. */
	let ownModes = $state(false);
	let modes = $state<string[]>([]);
	let scope = $state('');
	let error = $state<string | null>(null);
	let busy = $state(false);

	/** Nothing below this node — moving a category into itself is not a move. */
	const elsewhere = $derived(
		categories.filter((c) => c.id !== id && !c.path.startsWith(`${node.category.path}/`))
	);

	async function toggle() {
		open[id] = !expanded;
		if (open[id] && files === null) await loadFiles();
	}

	// The roots start expanded without anyone clicking them, and a click was the
	// only thing that used to fetch the list — so a top-level category showed its
	// note count and nothing underneath, as if the import had gone nowhere.
	$effect(() => {
		if (expanded && files === null) loadFiles();
	});

	async function loadFiles() {
		if (loadingFiles) return;
		loadingFiles = true;
		// Last time's list first, so a node opens at once rather than after a
		// round trip — or, with the laptop asleep, after waiting for a timeout.
		if (files === null) {
			const last = await keptFiles(id);
			if (last && files === null) files = last;
		}
		try {
			files = await api.files(id);
			filesError = null;
			void keepFiles(id, files);
		} catch (e) {
			// What this device last saw, so a lesson can still be found and
			// practised with nothing to reach. Failing that, leave `files` null —
			// an empty list here would read as "nothing in here".
			const last = await keptFiles(id);
			files = last;
			filesError = last ? null : e instanceof Error ? e.message : String(e);
		} finally {
			loadingFiles = false;
		}
	}

	function edit() {
		editing = !editing;
		if (!editing) return;
		slug = node.category.slug;
		parentId = node.category.parent_id ?? '';
		pairs = Object.entries(node.category.label ?? {}).map(([lang, text]) => ({ lang, text }));
		if (!pairs.length) pairs = [{ lang: 'en', text: '' }];
		ownModes = !!node.category.practice.modes?.length;
		// Unticked, the checkboxes still show what is inherited, so turning them
		// on starts from what this category actually does today.
		modes = [...(node.category.practice.modes ?? node.category.practice_resolved.modes)];
		scope = node.category.practice.distractor_scope ?? '';
		error = null;
	}

	const inheritedModes = $derived(
		node.category.practice_resolved.modes.map((m) => LABELS[m as Mode].title.toLowerCase()).join(', ')
	);

	function toggleMode(mode: string, on: boolean) {
		modes = on ? [...modes, mode] : modes.filter((m) => m !== mode);
	}

	async function save() {
		busy = true;
		error = null;
		const label = Object.fromEntries(
			pairs.filter((p) => p.lang.trim() && p.text.trim()).map((p) => [p.lang.trim(), p.text.trim()])
		);
		try {
			if (parentId !== (node.category.parent_id ?? '')) {
				await api.patchCategory(id, { parent_id: parentId || null });
			}
			await api.patchCategory(id, {
				slug,
				label,
				practice: { modes: ownModes ? modes : null, distractor_scope: scope || null }
			});
			editing = false;
			onchanged?.();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function remove() {
		const ok = await ask({
			title: `Delete ${name}?`,
			detail: 'A category can only be deleted once nothing is inside it — no data files, no categories.',
			confirm: 'Delete',
			danger: true
		});
		if (!ok) return;
		busy = true;
		error = null;
		try {
			await api.deleteCategory(id);
			onchanged?.();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function newFile() {
		busy = true;
		try {
			const file = await api.createFile(id, { front_lang: null, back_lang: null });
			await goto(`/files/${file.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			busy = false;
		}
	}
</script>

<li>
	<div class="node">
		<button class="ghost name" onclick={toggle} aria-expanded={expanded}>
			<span class="chev" aria-hidden="true">{node.children.length || node.category.notes ? (expanded ? '▾' : '▸') : '·'}</span>
			<span class="named">{name}</span>
		</button>
		<div class="counts">
			{#if node.totals.notes}<span class="figure" title="{node.totals.notes} notes">{node.totals.notes}</span>{/if}
			<button
				class="small ghost settings-button"
				aria-label="Edit {name}"
				aria-expanded={editing}
				disabled={offline}
				title={offline ? 'Needs the laptop' : undefined}
				onclick={edit}>⋯</button
			>
		</div>
		<div class="actions">
			{#if offline}
				<button class="small" disabled title="Needs the laptop">Add pages</button>
			{:else}
				<a class="button small" href="/upload/{id}">Add pages</a>
			{/if}
			{#if node.totals.cards}
				<a class="button small primary" href="/practice/{id}">Practise</a>
			{/if}
		</div>
	</div>

	{#if editing}
		<div class="edit card stack">
			{#if error}<p class="error small">{error}</p>{/if}
			<label class="field">
				<span>name in the path</span>
				<input bind:value={slug} aria-label="Path segment" />
			</label>
			<div class="field">
				<span>labels</span>
				<div class="stack tight">
					{#each pairs as pair, i (i)}
						<div class="row tight">
							<input class="lang" bind:value={pair.lang} aria-label="Language code" placeholder="en" />
							<input bind:value={pair.text} aria-label="Label in {pair.lang || 'that language'}" placeholder="shown in the tree" />
						</div>
					{/each}
					<button class="small ghost left" onclick={() => (pairs = [...pairs, { lang: '', text: '' }])}
						>+ another language</button
					>
				</div>
			</div>
			<label class="field">
				<span>inside</span>
				<select bind:value={parentId} aria-label="Parent category">
					<option value="">— top level —</option>
					{#each elsewhere as option (option.id)}
						<option value={option.id}>{option.path}</option>
					{/each}
				</select>
			</label>
			<div class="field">
				<span>practice modes</span>
				<div class="stack tight">
					<label class="inline">
						<input type="checkbox" bind:checked={ownModes} />
						set here{#if !ownModes}
							<span class="muted">— inherited: {inheritedModes}</span>
						{/if}
					</label>
					{#if ownModes}
						<div class="row tight wrap">
							{#each ALL_MODES as option (option)}
								<label class="inline">
									<input
										type="checkbox"
										checked={modes.includes(option)}
										onchange={(e) => toggleMode(option, e.currentTarget.checked)}
									/>
									{LABELS[option].title.toLowerCase()}
								</label>
							{/each}
						</div>
					{/if}
				</div>
			</div>
			<label class="field">
				<span>options come from</span>
				<select bind:value={scope} aria-label="Where distractors come from">
					<option value="">inherited — {node.category.practice_resolved.distractor_scope}</option>
					<option value="auto">auto — the nearest words that fill four options</option>
					<option value="group">this heading</option>
					<option value="file">this data file</option>
					<option value="category">anywhere in this category</option>
				</select>
			</label>
			<div class="row">
				<button class="primary small" disabled={busy} onclick={save}>Save</button>
				<button class="small" disabled={busy} onclick={newFile}>New data file</button>
				<button class="small" disabled={busy} onclick={remove}>Delete</button>
				<button class="small ghost" onclick={() => (editing = false)}>Cancel</button>
			</div>
		</div>
	{/if}

	{#if expanded}
		{#if filesError}
			<p class="error small empty">{filesError}</p>
		{/if}
		{#if files?.length}
			<ul class="files">
				{#each files as file (file.id)}
					<li>
						{#if offline}
							<span title="Reading a file needs the laptop; Practise does not">
								{file.title || 'Untitled file'}
							</span>
						{:else}
							<a href="/files/{file.id}">{file.title || 'Untitled file'}</a>
						{/if}
						<span class="count tnum">{file.notes}</span>
					</li>
				{/each}
			</ul>
		{:else if files !== null && !node.children.length}
			{#if offline}
				<p class="muted small empty">No data files yet.</p>
			{:else}
				<p class="muted small empty">No data files yet — <button class="link" onclick={newFile}>add one by hand</button> or add pages.</p>
			{/if}
		{/if}
		{#if node.children.length}
			<ul>
				{#each node.children as child (child.category.id)}
					<Self node={child} bind:open {categories} {onchanged} {offline} />
				{/each}
			</ul>
		{/if}
	{/if}
</li>

<style>
	li {
		list-style: none;
	}

	ul {
		margin: 0;
		padding-left: var(--space-5);
	}

	.node {
		display: grid;
		grid-template-columns: 1fr auto;
		grid-template-areas:
			'name count'
			'actions actions';
		align-items: center;
		gap: var(--space-2) var(--space-4);
		padding: var(--space-4) 0 var(--space-3);
		border-bottom: var(--border) solid var(--line-soft);
	}

	.name {
		grid-area: name;
		justify-content: flex-start;
		padding: 0;
		border: 0;
		background: transparent;
		min-height: 0;
		min-width: 0;
		font-family: var(--font-read);
		font-size: var(--text-xl);
		font-weight: var(--heading-weight);
		text-transform: var(--heading-case);
		letter-spacing: var(--heading-tracking);
		color: var(--text);
	}

	.name:hover {
		background: transparent;
	}

	.named {
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.counts {
		grid-area: count;
		justify-self: end;
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.counts .figure {
		color: var(--muted);
	}

	.actions {
		grid-area: actions;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		justify-content: flex-start;
	}

	.settings-button {
		min-width: var(--tap-sm);
		padding: 0;
		border: 0;
		background: transparent;
		font-size: var(--text-md);
	}

	@media (min-width: 641px) {
		.node {
			grid-template-columns: 1fr auto auto;
			grid-template-areas: 'name count actions';
		}

		.actions {
			justify-content: flex-end;
			margin-left: var(--space-5);
		}
	}

	.chev {
		width: var(--space-4);
		color: var(--muted);
		font-size: var(--text-sm);
	}

	/* The lessons under a category: a title, and how much is in it. */
	.files {
		padding: 0 0 var(--space-3) var(--space-5);
	}

	.files li {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-4);
		min-height: var(--tap);
		padding: var(--space-1) 0;
		border-bottom: var(--border) solid var(--line-soft);
	}

	.files li:last-child {
		border-bottom: 0;
	}

	.files a {
		min-width: 0;
		color: var(--text);
		text-decoration: none;
	}

	.files a:hover {
		text-decoration: underline;
	}

	.count {
		flex: 0 0 auto;
		white-space: nowrap;
		font-family: var(--font-ui);
		font-size: var(--text-sm);
		color: var(--muted);
	}

	.empty {
		margin: var(--space-2) 0 var(--space-3) var(--space-5);
	}

	.edit {
		margin: 0 0 var(--space-4) var(--space-5);
		padding: var(--space-4) 0 0;
		border-top: var(--border) solid var(--line-soft);
		background: transparent;
	}

	.field {
		display: grid;
		grid-template-columns: 8rem 1fr;
		align-items: baseline;
		gap: var(--space-3);
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
	}

	.field input,
	.field select {
		width: 100%;
	}

	.lang {
		flex: 0 0 4rem;
	}

	.wrap {
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}

	.inline {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--tap-sm);
		font-size: var(--text-sm);
		font-weight: 400;
		letter-spacing: 0;
		text-transform: none;
	}

	.inline input {
		width: auto;
		min-height: 0;
	}

	.left {
		justify-content: flex-start;
		padding: 0;
		border: 0;
	}

	@media (max-width: 640px) {
		.field {
			grid-template-columns: 1fr;
		}
	}
</style>
