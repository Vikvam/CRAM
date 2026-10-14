<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		type Category,
		type DataFile,
		type DataFileSummary,
		type DraftNote,
		type Duplicate,
		type ImportJob
	} from '$lib/api/client';
	import { ask } from '$lib/confirm.svelte';
	import { labelBoth, labelText } from '$lib/tree';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import Chips from '$lib/components/Chips.svelte';
	import CategoryPicker from '$lib/components/CategoryPicker.svelte';

	/** Below this, a row is highlighted for a second look (PLAN 3.2: confidence). */
	const LOW_CONFIDENCE = 0.7;

	const id = $derived(page.params.id);
	let job = $state<ImportJob | null>(null);
	let draft = $state<DataFile | null>(null);
	let error = $state<string | null>(null);
	let saving = $state(false);
	let dirty = $state(false);
	let showPhotos = $state(true);
	/** The page being looked at full size, in a modal that Escape can leave. */
	let zoomed = $state<string | null>(null);
	const isPdf = (path: string) => path.toLowerCase().endsWith('.pdf');
	let zoom = $state<HTMLDialogElement | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;
	/** The destination, changeable until the moment it is committed. */
	let categories = $state<Category[]>([]);
	let siblings = $state<DataFileSummary[]>([]);
	let moving = $state(false);
	/** Set when these pages were uploaded as the next pages of a file. */
	const into = $derived(siblings.find((f) => f.id === job?.target_data_file_id) ?? null);
	const destination = $derived(categories.find((c) => c.id === job?.category_id) ?? null);
	/** Rows already somewhere in the collection, by their index in the draft. */
	let duplicates = $state<Record<number, Duplicate[]>>({});

	const working = $derived(job?.status === 'pending' || job?.status === 'running');
	const unreadable = $derived((draft?.extra?.unreadable as string[] | undefined) ?? []);
	const flagged = $derived(draft ? draft.notes.filter((n) => flags(n).length).length : 0);

	/** Rows under their headings, in page order; ungrouped rows last. */
	const sections = $derived.by(() => {
		if (!draft) return [];
		const known = new Set(draft.groups.map((g) => g.id));
		const out = draft.groups.map((g) => ({
			id: g.id ?? '',
			label: labelBoth(g.label, g.id ?? ''),
			rows: draft!.notes.map((note, index) => ({ note, index })).filter(({ note }) => note.group === g.id)
		}));
		const loose = draft.notes.map((note, index) => ({ note, index })).filter(({ note }) => !note.group || !known.has(note.group));
		if (loose.length || !out.length) out.push({ id: '', label: out.length ? 'Not under a heading' : '', rows: loose });
		return out;
	});

	function flags(note: DraftNote): { text: string; kind: 'bad' | 'warn' }[] {
		const out: { text: string; kind: 'bad' | 'warn' }[] = [];
		if (!note.front?.trim()) out.push({ text: 'front is empty', kind: 'bad' });
		if (!note.back?.trim()) out.push({ text: 'back is empty', kind: 'bad' });
		if (note.confidence != null && note.confidence < LOW_CONFIDENCE) out.push({ text: 'check this row', kind: 'warn' });
		return out;
	}

	async function load() {
		clearTimeout(timer);
		try {
			const next = await api.importJob(id!);
			job = next;
			if (next.draft && (!draft || !dirty)) draft = structuredClone(next.draft) as unknown as DataFile;
			error = null;
			if (next.status === 'pending' || next.status === 'running') timer = setTimeout(load, 2000);
			else if (draft) await checkDuplicates();
			if (next.status !== 'committed' && next.category_id) {
				if (!categories.length) categories = await api.categories();
				siblings = await api.files(next.category_id);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	/** What of this page is already in the collection (PLAN 6: warn, never block). */
	async function checkDuplicates() {
		if (!draft) return;
		const pairs = draft.notes.map((n) => [n.front ?? null, n.back ?? null] as [string | null, string | null]);
		if (!pairs.length) return;
		const result = await api.checkDuplicates(pairs);
		const found: Record<number, Duplicate[]> = {};
		for (const row of result.rows) found[row.index] = row.matches;
		duplicates = found;
	}

	function changed() {
		dirty = true;
	}

	function accepted(note: DraftNote, side: 'front' | 'back'): string[] {
		return note.accept?.[side] ?? [];
	}

	function setAccepted(note: DraftNote, side: 'front' | 'back', values: string[]) {
		note.accept = { ...(note.accept ?? {}), [side]: values.length ? values : null };
		changed();
	}

	function removeRow(index: number) {
		draft!.notes.splice(index, 1);
		changed();
	}

	function addRow(group: string) {
		const at = draft!.notes.findLastIndex((n) => (n.group ?? '') === group) + 1 || draft!.notes.length;
		draft!.notes.splice(at, 0, { front: '', back: '', group: group || null, status: 'unverified', confidence: 1 });
		changed();
	}

	async function save(): Promise<boolean> {
		if (!draft || !job) return false;
		saving = true;
		try {
			job = await api.saveDraft(job.id, $state.snapshot(draft) as DataFile);
			dirty = false;
			error = null;
			return true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			return false;
		} finally {
			saving = false;
		}
	}

	async function commit() {
		if (!job || !(await save())) return;
		saving = true;
		try {
			await api.commitImport(job.id);
			await goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			saving = false;
		}
	}

	/** Where this import lands, decided here rather than by the row you came from. */
	async function moveTo(categoryId: string) {
		if (!job || categoryId === job.category_id) return;
		moving = true;
		try {
			job = await api.patchImport(job.id, { category_id: categoryId });
			siblings = await api.files(categoryId);
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			moving = false;
		}
	}

	async function joinFile(fileId: string) {
		if (!job) return;
		moving = true;
		try {
			job = await api.patchImport(job.id, { target_data_file_id: fileId || null });
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			moving = false;
		}
	}

	async function discard() {
		if (!job) return;
		const ok = await ask({
			title: 'Throw this import away?',
			detail: 'The pages it was read from go with it. Nothing of this import is in your collection yet.',
			confirm: 'Discard',
			danger: true
		});
		if (!ok) return;
		saving = true;
		try {
			await api.discardImport(job.id);
			await goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			saving = false;
		}
	}

	async function retry() {
		if (!job) return;
		job = await api.retryImport(job.id);
		draft = null;
		dirty = false;
		load();
	}

	function beforeUnload(event: BeforeUnloadEvent) {
		if (dirty) event.preventDefault();
	}

	$effect(() => {
		if (!zoom) return;
		if (zoomed && !zoom.open) zoom.showModal();
		else if (!zoomed && zoom.open) zoom.close();
	});

	onMount(load);
	onDestroy(() => clearTimeout(timer));
</script>

<svelte:window onbeforeunload={beforeUnload} />

<svelte:head><title>{job?.status === 'review' ? 'Review the import' : 'Import'} · CRAM</title></svelte:head>

<section class="stack">
	<a class="back" href="/">← Collection</a>

	{#if error}<p class="error" role="alert">{error}</p>{/if}

	{#if !job}
		<div class="card"><Skeleton lines={4} height="var(--space-5)" label="Loading the import" /></div>
	{:else if working}
		<div class="card stack center">
			<h1>Reading {job.pages.length} page{job.pages.length === 1 ? '' : 's'}…</h1>
			<p class="muted">You can leave and come back.</p>
			<div class="thumbs">
				{#each job.pages as p (p.id)}
					{#if p.path && isPdf(p.path)}<span class="pdf-tile small">PDF</span>
					{:else if p.path}<img src={api.rawUrl(p.path)} alt="Page {p.position + 1}" />{/if}
				{/each}
			</div>
		</div>
	{:else if job.status === 'committed'}
		<div class="card stack">
			<h1>Already added</h1>
			<p>This import is in your collection. <a href="/files/{job.target_data_file_id}">Open the data file</a></p>
		</div>
	{:else}
		{#if job.status === 'failed'}
			<div class="error stack" role="alert">
				<p><strong>Reading failed.</strong> {job.error}</p>
				<button onclick={retry}>Try again</button>
			</div>
		{/if}

		{#if draft}
			<div class="spread">
				<div>
					<h1>{draft.title || 'Review the import'}</h1>
					<p class="muted">
						{draft.notes.length} rows{#if flagged}&nbsp;· <span class="pill warn">{flagged} to check</span>{/if}
						{#if Object.keys(duplicates).length}&nbsp;· <span class="pill warn">{Object.keys(duplicates).length} already in the collection</span>{/if}
						{#if job.importer}&nbsp;· read as <code>{job.importer}</code>{/if}
						{#if job.router_reason}<span title={job.router_reason}> (why?)</span>{/if}
					</p>
				</div>
				<button class="small" onclick={() => (showPhotos = !showPhotos)}>{showPhotos ? 'Hide' : 'Show'} photos</button>
			</div>

			<div class="card destination">
				<label class="stack tight dest-field">
					<span class="muted small">Category</span>
					<CategoryPicker value={job.category_id ?? ''} bind:categories disabled={moving} onpick={moveTo} />
				</label>
				<label class="stack tight dest-field">
					<span class="muted small">Data file</span>
					<select
						value={job.target_data_file_id ?? ''}
						disabled={moving}
						aria-label="Data file"
						onchange={(e) => joinFile((e.currentTarget as HTMLSelectElement).value)}
					>
						<option value="">A new data file</option>
						{#each siblings as file (file.id)}
							<option value={file.id}>Add to {file.title || 'Untitled file'} ({file.notes} notes)</option>
						{/each}
					</select>
				</label>
				{#if into}
					<p class="muted small note">
						Joins <a href="/files/{into.id}">{into.title || 'an existing file'}</a> · {into.notes} notes already
					</p>
				{/if}
			</div>

			{#if unreadable.length}
				<div class="card warnbox">
					<strong>Couldn't read confidently:</strong>
					<ul>{#each unreadable as u}<li>{u}</li>{/each}</ul>
				</div>
			{/if}

			<div class="layout" class:with-photos={showPhotos}>
				{#if showPhotos}
					<aside class="photos">
						{#each job.pages as p (p.id)}
							{#if p.path && isPdf(p.path)}
								<!-- A PDF opens in the browser's own viewer: it has pages of its own to turn. -->
								<a class="photo pdf" href={api.rawUrl(p.path)} target="_blank" rel="noopener">
									<span class="pdf-tile">PDF</span>
									<span class="pill">{p.path.split('/').pop()?.replace(/^\d{2}-/, '')}{p.page_number ? ` · from page ${p.page_number}` : ''}{p.status === 'failed' ? ' · failed' : ''}</span>
								</a>
							{:else if p.path}
								<button class="photo" onclick={() => (zoomed = p.path)}>
									<img src={api.rawUrl(p.path)} alt="Page {p.page_number ?? p.position + 1}" />
									<span class="pill">page {p.page_number ?? p.position + 1}{p.status === 'failed' ? ' · failed' : ''}</span>
								</button>
							{/if}
						{/each}
					</aside>
				{/if}

				<div class="rows stack">
					{#each sections as section (section.id)}
						<div class="card section">
							{#if section.label}<h2>{section.label}</h2>{/if}
							{#each section.rows as { note, index } (note.id ?? `new-${index}`)}
								{@const f = flags(note)}
								<div class="note" class:bad={f.some((x) => x.kind === 'bad')} class:warn={f.some((x) => x.kind === 'warn')}>
									<div class="sides">
										<input
											type="text"
											bind:value={note.front}
											oninput={changed}
											lang={draft.front_lang ?? undefined}
											aria-label="Front"
											placeholder="front"
										/>
										<input
											type="text"
											bind:value={note.back}
											oninput={changed}
											lang={draft.back_lang ?? undefined}
											aria-label="Back"
											placeholder="back"
										/>
										<button class="small ghost" onclick={() => removeRow(index)} aria-label="Reject this row">✕</button>
									</div>
									<div class="details">
										<Chips
											bind:values={() => accepted(note, 'back'), (v) => setAccepted(note, 'back', v)}
											label="Also accept for back"
											lang={draft.back_lang}
										/>
										<Chips
											bind:values={() => accepted(note, 'front'), (v) => setAccepted(note, 'front', v)}
											label="for front"
											lang={draft.front_lang}
										/>
									</div>
									{#if note.note !== undefined && note.note !== null}
										<textarea rows="2" bind:value={note.note} oninput={changed} aria-label="Note"></textarea>
									{/if}
									<div class="row meta">
										{#each f as flag}<span class="pill {flag.kind}">{flag.text}</span>{/each}
										{#each duplicates[index] ?? [] as match (match.note_id)}
											<span class="pill warn" title="{match.front} · {match.back}">
												{match.by === 'back'
													? `same meaning as ${match.front} in`
													: match.same_back
														? 'already in'
														: 'same prompt in'}
												{match.category_path}
											</span>
										{/each}
										{#if note.note == null}
											<button class="small ghost" onclick={() => { note.note = ''; changed(); }}>+ note</button>
										{/if}
									</div>
								</div>
							{/each}
							<button class="small" onclick={() => addRow(section.id)}>+ Add a row</button>
						</div>
					{/each}
				</div>
			</div>

			<div class="actions">
				<button class="ghost danger" onclick={discard} disabled={saving}>Discard import</button>
				<button onclick={save} disabled={saving || !dirty}>{dirty ? 'Save draft' : 'Saved'}</button>
				<button class="primary" onclick={commit} disabled={saving || draft.notes.length === 0}>
					Add {draft.notes.length} to{#if destination}&nbsp;{labelText(destination.label, destination.path)}{:else}
						&nbsp;collection{/if}
				</button>
			</div>
		{/if}
	{/if}
</section>

<dialog class="zoom" bind:this={zoom} onclose={() => (zoomed = null)} aria-label="Page, full size">
	{#if zoomed}
		<button class="shade" onclick={() => (zoomed = null)} aria-label="Close">
			<img src={api.rawUrl(zoomed)} alt="Page, full size" />
		</button>
		<button class="close small" onclick={() => (zoomed = null)}>Close</button>
	{/if}
</dialog>

<style>
	.center {
		text-align: center;
	}

	.thumbs {
		display: flex;
		gap: var(--space-2);
		justify-content: center;
		flex-wrap: wrap;
	}

	.thumbs img {
		height: 120px;
		border-radius: var(--space-2);
		opacity: 0.7;
	}

	.warnbox {
		background: var(--almost-soft);
		color: var(--almost);
	}

	.layout {
		display: grid;
		gap: var(--space-4);
	}

	@media (min-width: 900px) {
		.layout.with-photos {
			grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
		}

		.photos {
			position: sticky;
			top: var(--space-2);
			align-self: start;
			max-height: calc(100vh - var(--space-4));
			overflow: auto;
		}
	}

	.photos {
		display: grid;
		gap: var(--space-2);
	}

	.photo {
		display: block;
		position: relative;
		padding: 0;
		min-height: 0;
		border-radius: var(--radius);
		overflow: hidden;
	}

	.photo img {
		display: block;
		width: 100%;
	}

	.pdf-tile {
		display: grid;
		place-items: center;
		aspect-ratio: 3 / 4;
		width: 100%;
		background: var(--sunken);
		color: var(--muted);
		font-family: var(--font-ui);
		font-weight: var(--weight-semibold);
		letter-spacing: 0.05em;
	}

	.thumbs .pdf-tile {
		width: auto;
		height: 120px;
		border-radius: var(--space-2);
	}

	.photo .pill {
		position: absolute;
		left: var(--space-2);
		bottom: var(--space-2);
	}

	.section h2 {
		font-size: var(--text-md);
	}

	.note {
		padding: var(--space-2);
		margin: 0 calc(-1 * var(--space-2));
		border-radius: var(--space-2);
		border-left: 3px solid transparent;
	}

	.note + .note {
		border-top: var(--border) solid var(--line);
	}

	.note.warn {
		border-left-color: var(--almost);
		background: var(--almost-soft);
	}

	.note.bad {
		border-left-color: var(--bad);
		background: var(--bad-soft);
	}

	.sides {
		display: grid;
		grid-template-columns: 1fr 1fr auto;
		gap: var(--space-2);
	}

	.details {
		display: flex;
		gap: var(--space-3);
		flex-wrap: wrap;
		margin-top: var(--space-2);
	}

	.meta {
		margin-top: var(--space-1);
	}

	.meta:empty {
		display: none;
	}

	textarea {
		margin-top: var(--space-1);
		font-size: var(--text-sm);
	}

	.destination {
		display: grid;
		grid-template-columns: minmax(12rem, 1fr) minmax(12rem, 1fr);
		gap: var(--space-3);
		align-items: end;
	}

	.dest-field {
		min-width: 0;
	}

	.dest-field select {
		width: 100%;
	}

	.destination .note {
		grid-column: 1 / -1;
		margin: 0;
	}

	.danger {
		margin-right: auto;
	}

	@media (max-width: 640px) {
		.destination {
			grid-template-columns: 1fr;
		}
	}

	/* The three answers to "is this right?" stay in reach of the rows they are
	   about, however long the list is. */
	.actions {
		position: sticky;
		bottom: 0;
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
		padding: var(--space-3) 0;
		background: linear-gradient(to top, var(--bg) 70%, transparent);
	}

	.zoom {
		max-width: 100vw;
		width: 100vw;
		max-height: 100dvh;
		height: 100dvh;
		padding: 0;
		border: 0;
		border-radius: 0;
		background: transparent;
		box-shadow: none;
	}

	.zoom::backdrop {
		background: rgb(0 0 0 / 0.85);
	}

	/* The picture itself is the way out, as it was before Escape also worked. */
	.shade {
		display: block;
		width: 100%;
		height: 100%;
		padding: var(--space-4);
		border: 0;
		border-radius: 0;
		background: transparent;
		overflow: auto;
	}

	.shade img {
		max-width: 100%;
	}

	.close {
		position: fixed;
		top: var(--space-3);
		right: var(--space-3);
	}
</style>
