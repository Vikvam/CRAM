<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, type Category, type DataFileSummary, type Importer } from '$lib/api/client';
	import { labelText } from '$lib/tree';
	import CategoryPicker from '$lib/components/CategoryPicker.svelte';
	import Help from '$lib/components/Help.svelte';
	import {
		clampCrop,
		cropFromCorners,
		FULL,
		isFullCrop,
		rotatedSize,
		transform,
		type Crop
	} from '$lib/editor/image';

	interface Picked {
		file: File;
		/** An object URL for a photo; data files show their name instead. */
		url: string | null;
		key: number;
		/** Quarter turns and a crop, applied just before the upload. */
		rotation: number;
		crop: Crop;
		/** The photo's own size, so the preview can be exactly its shape. */
		natural: { width: number; height: number } | null;
	}

	/** Files that say what their fronts and backs are — read without the model. */
	const DATA_FILES = ['.json', '.csv', '.tsv', '.txt', '.md', '.apkg', '.colpkg'];
	const isDataFile = (file: File) => DATA_FILES.some((s) => file.name.toLowerCase().endsWith(s));
	/** A PDF goes to the model, like a photo, but is not a picture to crop. */
	const isPdf = (file: File) => file.name.toLowerCase().endsWith('.pdf');

	const categoryId = $derived(page.params.categoryId);
	/** Where these pages land. The URL only proposes it — it is a choice until you upload. */
	let destination = $state('');
	let categories = $state<Category[]>([]);
	const category = $derived(categories.find((c) => c.id === destination) ?? null);
	let importers = $state<Importer[]>([]);
	let files = $state<DataFileSummary[]>([]);
	/** Empty means a new data file; otherwise these pages join that one. */
	let target = $state('');
	let picked = $state<Picked[]>([]);
	let importer = $state('');
	/** Fills the reader's "My instructions" (docs/llm-prompt.md); the category's languages go in by themselves. */
	let instructions = $state('');
	/** How a PDF reaches the model: its text layer, or pictures of its pages. */
	let pdfMode = $state<'text' | 'images'>('text');
	let firstPage = $state<number | null>(null);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let llmConfigured = $state(true);
	let nextKey = 0;

	const dataFiles = $derived(picked.filter((p) => isDataFile(p.file)).length);
	const pdfs = $derived(picked.filter((p) => isPdf(p.file)).length);
	const photos = $derived(picked.length - dataFiles - pdfs);
	/** Photos and PDFs need a provider; a CSV reads itself. */
	const needsLLM = $derived(photos + pdfs > 0);
	const mixed = $derived(dataFiles > 0 && needsLLM);
	/** With only the general reader installed there is nothing to choose. */
	const readers = $derived(importers.filter((i) => i.kinds.includes('image')));

	onMount(() => {
		(async () => {
			try {
				const [all, list, settings, existing] = await Promise.all([
					api.categories(),
					api.importers(),
					api.settings(),
					api.files(categoryId!)
				]);
				categories = all;
				destination = categoryId ?? '';
				importers = list;
				files = existing;
				llmConfigured = settings.llm_configured;
				if (!category) error = 'No such category.';
			} catch (e) {
				error = e instanceof Error ? e.message : String(e);
			}
		})();
		return () => picked.forEach((p) => p.url && URL.revokeObjectURL(p.url));
	});

	/** Another category has its own data files — what these pages could join changes with it. */
	async function pickCategory(id: string) {
		destination = id;
		target = '';
		try {
			files = await api.files(id);
			error = null;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	function add(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		for (const file of Array.from(input.files ?? [])) {
			picked.push({
				file,
				url: isDataFile(file) || isPdf(file) ? null : URL.createObjectURL(file),
				key: nextKey++,
				rotation: 0,
				crop: { ...FULL },
				natural: null
			});
		}
		input.value = ''; // the same photo can be picked again
	}

	function move(index: number, by: number) {
		const to = index + by;
		if (to < 0 || to >= picked.length) return;
		const [item] = picked.splice(index, 1);
		picked.splice(to, 0, item);
	}

	function remove(index: number) {
		const [item] = picked.splice(index, 1);
		if (item.url) URL.revokeObjectURL(item.url);
	}

	/** The preview is the picture's own shape, so a crop drawn on it is the crop
	 *  that gets made — no letterboxing to guess around. */
	function frameRatio(item: Picked): string {
		if (!item.natural) return '3 / 4';
		const [width, height] = rotatedSize(item.natural.width, item.natural.height, item.rotation);
		return `${width} / ${height}`;
	}

	const measure = (item: Picked, img: HTMLImageElement) =>
		(item.natural = { width: img.naturalWidth, height: img.naturalHeight });

	function rotate(item: Picked) {
		item.rotation = (item.rotation + 90) % 360;
		// The crop is in the picture's own frame, so turning it starts the crop over.
		item.crop = { ...FULL };
	}

	/** Drag a box over the preview; the corners are fractions of the image. */
	function startCrop(item: Picked, event: PointerEvent) {
		const box = (event.currentTarget as HTMLElement).getBoundingClientRect();
		const at = (e: PointerEvent) => ({
			x: (e.clientX - box.left) / box.width,
			y: (e.clientY - box.top) / box.height
		});
		const from = at(event);
		const move = (e: PointerEvent) => (item.crop = cropFromCorners(from, at(e)));
		const up = () => {
			window.removeEventListener('pointermove', move);
			window.removeEventListener('pointerup', up);
			if (item.crop.width < 0.06 || item.crop.height < 0.06) item.crop = { ...FULL };
		};
		window.addEventListener('pointermove', move);
		window.addEventListener('pointerup', up);
		item.crop = clampCrop({ ...from, width: 0.05, height: 0.05 });
	}

	async function start() {
		if (!picked.length || !destination) return;
		busy = true;
		error = null;
		const form = new FormData();
		form.set('category_id', destination);
		if (importer) form.set('importer', importer);
		if (instructions.trim()) form.set('instructions', instructions.trim());
		if (pdfs) form.set('pdf_mode', pdfMode);
		if (firstPage) form.set('first_page', String(firstPage));
		if (target) form.set('target_data_file_id', target);
		for (const p of picked) {
			const file = p.url ? await transform(p.file, p.rotation, p.crop) : p.file;
			form.append('files', file, file.name);
		}
		try {
			const job = await api.startImport(form);
			await goto(`/imports/${job.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			busy = false;
		}
	}
</script>

<svelte:head><title>Add pages · CRAM</title></svelte:head>

<section class="stack">
	<a class="back" href="/">← Collection</a>
	<h1>Add pages{#if category}&nbsp;<span class="muted">to {labelText(category.label, category.path)}</span>{/if}</h1>
	<label class="stack tight destination">
		<span class="muted small">Category these pages go into</span>
		<CategoryPicker bind:value={destination} bind:categories onpick={pickCategory} />
	</label>
	<p class="muted">
		You check every row before anything is saved.
		<Help label="What can be added, and how">
			One or more photos or PDFs of the same lesson become one data file, or join one you already have. Turn a
			sideways photo with ↻, or drag across one to keep part of it. A PDF is read a few pages at a time. A CSV, a
			list of pairs, a JSON export or an Anki deck is read straight off, with no model involved.
		</Help>
	</p>

	{#if !llmConfigured && needsLLM}
		<p class="error" role="alert">
			No LLM provider is configured on the server, so pages can't be read yet. Set <code>MEMO_LLM_API_KEY</code> in
			<code>backend/.env</code> and restart.
		</p>
	{/if}

	<div class="row pickers">
		<label class="button primary">
			Take a photo
			<input class="sr-only" type="file" accept="image/*" capture="environment" onchange={add} />
		</label>
		<label class="button">
			Choose photos
			<input class="sr-only" type="file" accept="image/*" multiple onchange={add} />
		</label>
		<label class="button">
			Choose data files
			<input class="sr-only" type="file" accept=".json,.csv,.tsv,.txt,.md,.apkg,.colpkg,.pdf" multiple onchange={add} />
		</label>
	</div>

	{#if picked.length}
		<ol class="pages">
			{#each picked as p, i (p.key)}
				<li class="card">
					{#if p.url}
						<div
							class="frame"
							style="aspect-ratio: {frameRatio(p)}"
							onpointerdown={(e) => startCrop(p, e)}
							role="application"
							aria-label="Drag to crop page {i + 1}"
						>
							<img
								src={p.url}
								alt="Page {i + 1}"
								style="rotate: {p.rotation}deg"
								class:turned={p.rotation % 180 !== 0}
								onload={(e) => measure(p, e.currentTarget as HTMLImageElement)}
							/>
							{#if !isFullCrop(p.crop)}
								<div
									class="cropbox"
									style="left: {p.crop.x * 100}%; top: {p.crop.y * 100}%; width: {p.crop.width * 100}%; height: {p.crop.height * 100}%"
								></div>
							{/if}
						</div>
					{:else}
						<div class="datafile" aria-hidden="true">{p.file.name.split('.').pop()?.toUpperCase()}</div>
					{/if}
					<div class="spread">
						<span class="muted" title={p.file.name}>
							{p.url ? `Page ${firstPage ? firstPage + i : i + 1}` : p.file.name}
						</span>
						<span class="row">
							{#if p.url}
								<button class="small" onclick={() => rotate(p)} aria-label="Rotate page {i + 1}">↻</button>
								{#if !isFullCrop(p.crop)}
									<button class="small" onclick={() => (p.crop = { ...FULL })} aria-label="Undo crop of page {i + 1}">⤺</button>
								{/if}
							{/if}
							<button class="small" onclick={() => move(i, -1)} disabled={i === 0} aria-label="Move earlier">↑</button>
							<button class="small" onclick={() => move(i, 1)} disabled={i === picked.length - 1} aria-label="Move later">↓</button>
							<button class="small" onclick={() => remove(i)} aria-label="Remove">✕</button>
						</span>
					</div>
				</li>
			{/each}
		</ol>

		<div class="card stack options">
			{#if needsLLM && readers.length > 1}
			<label class="stack tight">
				<span>How to read these pages</span>
				<select bind:value={importer}>
					<option value="">Let the app choose from the first page</option>
					{#each readers as imp (imp.name)}
						<option value={imp.name}>{imp.name} — {imp.description}</option>
					{/each}
				</select>
			</label>
			{/if}
			{#if pdfs}
				<label class="stack tight">
					<span>How to read the PDF</span>
					<select bind:value={pdfMode}>
						<option value="text">Its text — cheaper, any model</option>
						<option value="images">Its pages as pictures — keeps tables and layout</option>
					</select>
				</label>
			{/if}
			{#if needsLLM}
				<label class="stack tight">
					<span>Anything the reader should know <span class="muted">(optional)</span></span>
					<textarea rows="2" bind:value={instructions} placeholder="e.g. only the verbs; ask the questions in German"></textarea>
				</label>
			{/if}
			{#if files.length}
				<label class="stack tight">
					<span>Where these notes go</span>
					<select bind:value={target}>
						<option value="">A new data file</option>
						{#each files as file (file.id)}
							<option value={file.id}>Add to {file.title || 'Untitled file'} ({file.notes} notes)</option>
						{/each}
					</select>
				</label>
			{/if}
			{#if needsLLM}
				<label class="stack tight">
					<span>Printed number of the first page <span class="muted">(optional)</span></span>
					<input type="number" min="1" bind:value={firstPage} placeholder="e.g. 6" />
				</label>
			{/if}
		</div>

		{#if error}<p class="error">{error}</p>{/if}
		{#if mixed}
			<p class="error">Photos and PDFs are read differently from data files — import them one kind at a time.</p>
		{/if}
		<button class="primary wide" onclick={start} disabled={busy || mixed || (needsLLM && !llmConfigured)}>
			{#if busy}Uploading…{:else if pdfs}Read {picked.length} file{picked.length === 1 ? '' : 's'}{:else if needsLLM}Read {picked.length} page{picked.length === 1 ? '' : 's'}{:else}
				Import {picked.length} file{picked.length === 1 ? '' : 's'}{/if}
		</button>
	{:else if error}
		<p class="error">{error}</p>
	{/if}
</section>

<style>
	.destination {
		max-width: 32rem;
	}

	.pickers label {
		cursor: pointer;
	}

	.pages {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.pages li {
		padding: var(--space-2);
	}

	.frame {
		position: relative;
		container-type: size;
		margin-bottom: var(--space-2);
		touch-action: none;
		cursor: crosshair;
		overflow: hidden;
		border-radius: var(--space-2);
		background: var(--sunken);
	}

	.pages img {
		position: absolute;
		top: 50%;
		left: 50%;
		translate: -50% -50%;
		width: 100cqw;
		height: 100cqh;
		object-fit: fill;
		display: block;
	}

	/* Turned: the photo is sized to the frame's other side, then rotated into it. */
	.pages img.turned {
		width: 100cqh;
		height: 100cqw;
	}

	.cropbox {
		position: absolute;
		border: var(--border-strong) solid var(--accent);
		background: color-mix(in srgb, var(--accent) 15%, transparent);
		pointer-events: none;
	}

	.datafile {
		width: 100%;
		aspect-ratio: 3 / 4;
		border-radius: var(--space-2);
		background: var(--sunken);
		color: var(--muted);
		display: grid;
		place-items: center;
		font-weight: var(--weight-semibold);
		letter-spacing: 0.05em;
		margin-bottom: var(--space-2);
	}
</style>
