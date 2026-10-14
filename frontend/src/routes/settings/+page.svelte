<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type Settings } from '$lib/api/client';
	import { auth } from '$lib/auth.svelte';
	import { appearance, SCALES, SKINS, THEMES, type Scale, type Skin, type Theme } from '$lib/theme.svelte';
	import { sync } from '$lib/offline/sync.svelte';
	import { onDevice, pack } from '$lib/offline/pack';
	import Help from '$lib/components/Help.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';

	const THEME_LABELS: Record<Theme, string> = { system: 'Auto', light: 'Light', dark: 'Dark' };
	const SKIN_LABELS: Record<Skin, string> = { paper: 'Paper', ink: 'Ink' };
	/** What is on this device to practise with nothing to reach. */
	let cards = $state<{ cards: number; at: string } | null>(null);
	let packing = $state(false);

	async function countCards() {
		cards = await onDevice();
	}

	async function takeMore() {
		packing = true;
		try {
			// `force`: the point of a button is to ask again even when what is here
			// would have done.
			await pack(undefined, {}, undefined, true);
			await countCards();
		} finally {
			packing = false;
		}
	}

	/** How long ago, in words. */
	function ago(iso: string) {
		const hours = (Date.now() - new Date(iso).getTime()) / 3_600_000;
		if (hours < 1) return 'just now';
		if (hours < 24) return `${Math.round(hours)}h ago`;
		return `${Math.round(hours / 24)}d ago`;
	}

	const SCALE_LABELS: Record<Scale, string> = {
		compact: 'Compact',
		default: 'Default',
		large: 'Large',
		larger: 'Larger'
	};

	let settings = $state<Settings | null>(null);
	let error = $state<string | null>(null);
	let saved = $state(false);

	onMount(async () => {
		void countCards();
		try {
			settings = await api.settings();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	});

	/**
	 * Hand the waiting answers over as a file.
	 *
	 * The way out when the two devices will not meet on a network at all: the
	 * file goes to this device's downloads, and `memo import-answers` takes it in
	 * on the laptop. The rows are not deleted — the upload may still manage it
	 * later, and being imported twice is already harmless (each row carries its
	 * own id).
	 */
	async function download() {
		const text = await sync.file();
		const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
		const link = document.createElement('a');
		link.href = url;
		link.download = `cram-answers-${new Date().toISOString().slice(0, 10)}.json`;
		link.click();
		URL.revokeObjectURL(url);
	}

	async function choose(scheduler: string) {
		saved = false;
		try {
			settings = await api.saveSettings({ scheduler });
			saved = true;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<svelte:head><title>Settings · CRAM</title></svelte:head>

<section class="stack">
	<h1>Settings</h1>
	<!-- Offline, the banner above has already said so; saying it again in red is noise. -->
	{#if error && sync.online}<p class="error" role="alert">{error}</p>{/if}

	<div class="card stack">
		<h2>
			Look
			<Help label="Why this is per device">
				Kept in this browser, not on the server: the laptop and the phone are read in different light, at
				different distances and at different sizes, so each keeps its own answer. Size moves the whole
				interface, not just the words, and whatever text size the device itself is set to still counts.
			</Help>
		</h2>

		<div class="segmented" role="group" aria-label="Skin">
			{#each SKINS as option (option)}
				<label class="segment">
					<input
						type="radio"
						name="skin"
						class="sr-only"
						checked={appearance.skin === option}
						onchange={() => appearance.setSkin(option)}
					/>
					<span>{SKIN_LABELS[option]}</span>
				</label>
			{/each}
		</div>

		<div class="segmented" role="group" aria-label="Light or dark">
			{#each THEMES as option (option)}
				<label class="segment">
					<input
						type="radio"
						name="theme"
						class="sr-only"
						checked={appearance.theme === option}
						onchange={() => appearance.set(option)}
					/>
					<span>{THEME_LABELS[option]}</span>
				</label>
			{/each}
		</div>

		<div class="segmented" role="group" aria-label="Size">
			{#each SCALES as option (option)}
				<label class="segment">
					<input
						type="radio"
						name="scale"
						class="sr-only"
						checked={appearance.scale === option}
						onchange={() => appearance.setScale(option)}
					/>
					<span>{SCALE_LABELS[option]}</span>
				</label>
			{/each}
		</div>
	</div>

	<div class="card stack">
		<h2>
			Cards on this device
			<Help label="Why cards are kept here">
				A session can only use cards this device already has. They are fetched whenever the app is open
				and the laptop is reachable, so there is usually nothing to do — this is here to check before
				you leave, and to ask for more now.
			</Help>
		</h2>
		{#if cards === null}
			<p class="muted">Nothing here yet{sync.online ? '' : ', and no way to fetch any'}.</p>
		{:else}
			<p class="plain">{cards.cards} {cards.cards === 1 ? 'card' : 'cards'}, fetched {ago(cards.at)}.</p>
		{/if}
		<div class="row">
			<button onclick={takeMore} disabled={packing || !sync.online}>
				{packing ? 'Fetching…' : 'Take more now'}
			</button>
		</div>
	</div>

	<div class="card stack">
		<h2>
			Answers on this device
			<Help label="Why answers wait here">
				Every answer is written down here first and handed to the laptop afterwards, so a session with no
				signal is a session. The laptop still does all the scheduling, which is why they have to get back.
			</Help>
		</h2>
		{#if sync.waiting === 0}
			<p class="muted">Nothing waiting — the laptop has everything.</p>
		{:else}
			<p class="plain">
				{sync.waiting}
				{sync.waiting === 1 ? 'answer' : 'answers'} waiting{sync.online ? '' : ', and no way to reach the laptop'}.
			</p>
			<div class="row">
				<button onclick={() => sync.flush()} disabled={sync.sending || !sync.online}>
					{sync.sending ? 'Sending…' : 'Send now'}
				</button>
				<button onclick={download}>Save to a file</button>
			</div>
			<p class="muted small">
				A saved file goes in with <code>memo import-answers &lt;file&gt;</code> on the laptop. Doing both is
				safe: each answer carries its own id, so it lands once.
			</p>
		{/if}
		{#if sync.stuck && sync.online}<p class="muted small">Last try: {sync.stuck}</p>{/if}
	</div>

	{#if settings}
		<div class="card stack">
			<h2>
				Scheduler
				<Help label="What switching does">
					Each scheduler keeps its own schedule from the same review history, so you can switch back and forth
					without losing anything. It only changes when cards come back.
				</Help>
			</h2>
			<div class="segmented" role="group" aria-label="Scheduler">
				{#each settings.schedulers as name (name)}
					<label class="segment">
						<input
							type="radio"
							name="scheduler"
							class="sr-only"
							checked={settings.scheduler === name}
							onchange={() => choose(name)}
						/>
						<span>{name.toUpperCase()}</span>
					</label>
				{/each}
			</div>
			{#if saved}<p class="muted small" role="status">Saved.</p>{/if}
		</div>

		<div class="card stack">
			<h2>
				Reading pages
				<Help label="About the model key">
					The key stays on the server and is never sent to this page.
				</Help>
			</h2>
			{#if settings.llm_configured}
				<p class="plain">
					<code>{settings.llm_model}</code>{#if settings.structured_output}&nbsp;·&nbsp;<code>{settings.structured_output}</code>{/if}
				</p>
			{:else}
				<p class="error">No provider. Set <code>MEMO_LLM_API_KEY</code> in <code>backend/.env</code>.</p>
			{/if}
		</div>

		<div class="card spread">
			<span><span class="label">Profile</span> <span class="plain">{settings.profile}</span></span>
			{#if auth.status && !auth.status.gate_open}
				<button onclick={() => auth.logout()}>Sign out</button>
			{/if}
		</div>
	{:else if !error}
		<div class="card"><Skeleton lines={3} height="var(--tap)" label="Loading settings" /></div>
	{/if}
</section>

<style>
	h2 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.segmented {
		max-width: 28rem;
	}

	.plain {
		font-family: var(--font-ui);
		font-size: var(--text-sm);
	}

	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
</style>
