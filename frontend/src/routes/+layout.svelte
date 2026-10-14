<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { auth } from '$lib/auth.svelte';
	import { immersion } from '$lib/chrome.svelte';
	import { appearance } from '$lib/theme.svelte';
	import { speech } from '$lib/speech.svelte';
	import { sync } from '$lib/offline/sync.svelte';
	import { collecting } from '$lib/collecting.svelte';
	import { pack } from '$lib/offline/pack';
	import Offline from '$lib/components/Offline.svelte';
	import Confirm from '$lib/components/Confirm.svelte';
	import Login from '$lib/components/Login.svelte';

	let { children } = $props();

	/** The three places there are, in the one bar at the top. It was at the
	 *  bottom on a phone, for the thumb — but a fixed strip there is the strip
	 *  the browser's own chrome wants, and it lost. */
	const PLACES = [
		{ href: '/', label: 'Collection' },
		{ href: '/progress', label: 'Progress' },
		{ href: '/settings', label: 'Settings' }
	];

	let main = $state<HTMLElement | null>(null);

	onMount(() => {
		const stop = appearance.start();
		// Which list is being filled, if one is: read once the page exists, so
		// nothing reaches for storage during rendering.
		collecting.start();
		// One owner for the voice list, and for stopping a voice that is still
		// talking when the tab is hidden or closed.
		const hush = speech.start();
		// One owner for the outbox, so the count in the header and the flush after
		// an answer cannot disagree.
		const settle = sync.start();
		auth.refresh();
		// Take cards along on the way in, so the phone is ready for a journey
		// nobody announced. It is one GET, and only when there is something to
		// reach and what is kept is missing, too small to last, or yesterday's.
		if (sync.online) void pack();
		const signedOut = () => {
			auth.forget();
			auth.refresh();
		};
		window.addEventListener('memo:signed-out', signedOut);
		return () => {
			window.removeEventListener('memo:signed-out', signedOut);
			settle();
			hush();
			stop();
		};
	});

	// Following a link should move the keyboard and the screen reader to what the
	// link led to, not leave them in the navigation of the page that is gone.
	// `from` is null on the first load, which is nobody following anything.
	afterNavigate(({ from }) => {
		if (from) main?.focus();
	});

	/** The narrow column a session reads in — the whole of /practice. */
	const practice = $derived(page.url.pathname.startsWith('/practice/'));
	/** Nothing but the card: set by the session itself, while it is running. */
	const immersive = $derived(immersion.on);
	const here = (href: string) =>
		(href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href)) ? 'page' : undefined;
</script>

{#if auth.status === null}
	<main class="center">
		{#if auth.error}
			<p class="error">Can't reach the server: {auth.error}</p>
			<p class="muted">Nothing has been practised on this device yet, so there is nothing to go on with.</p>
			<button onclick={() => auth.refresh()}>Try again</button>
		{:else}
			<p class="muted" role="status">Loading…</p>
		{/if}
	</main>
{:else if !auth.status.signed_in}
	<Login />
{:else}
	{#if !immersive}
		<a class="skip no-print" href="#main">Skip to the page</a>
		<header class="no-print">
			<div class="row">
				<a class="brand" href="/">CRAM</a>
				<nav aria-label="Main">
					{#each PLACES as place (place.href)}
						<a href={place.href} aria-current={here(place.href)}>{place.label}</a>
					{/each}
				</nav>
			</div>
		</header>
	{/if}

	<main id="main" bind:this={main} tabindex="-1" class:practice class:immersive>
		<Offline />
		{@render children()}
	</main>

	<Confirm />
{/if}

<style>
	.skip {
		position: fixed;
		top: var(--space-2);
		left: var(--space-2);
		z-index: var(--z-overlay);
		padding: var(--space-2) var(--space-3);
		border: var(--border) solid var(--line);
		border-radius: var(--radius-sm);
		background: var(--bg);
		translate: 0 -200%;
	}

	.skip:focus-visible {
		translate: 0 0;
	}

	/* A running head: the name of the thing, then where you are in it.
	   Sticky, so it is one tap away wherever you have scrolled to — which is
	   what it has to be now that it is the only navigation there is. The strip
	   is full width and opaque so nothing shows through it in the margins; the
	   row inside keeps the reading column's width. */
	header {
		position: sticky;
		top: 0;
		z-index: var(--z-nav);
		background: var(--bg);
		border-bottom: var(--border) solid var(--line);
	}

	.row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-5);
		max-width: var(--page-max);
		margin: 0 auto;
		padding: var(--space-4) var(--space-5) var(--space-3);
	}

	.brand {
		font-family: var(--font-read);
		font-size: var(--text-md);
		font-weight: var(--heading-weight);
		text-transform: var(--heading-case);
		letter-spacing: var(--heading-tracking);
		color: var(--text);
		text-decoration: none;
	}

	header nav {
		display: flex;
		gap: var(--space-5);
	}

	header nav a {
		font-family: var(--font-ui);
		font-size: var(--text-xs);
		font-weight: var(--label-weight);
		letter-spacing: var(--label-tracking);
		text-transform: uppercase;
		color: var(--muted);
		text-decoration: none;
		transition: color var(--dur-fast) var(--ease);
	}

	header nav a {
		padding-bottom: var(--space-1);
		margin-bottom: calc(-1 * var(--space-3) - var(--border));
		border-bottom: var(--border-strong) solid transparent;
	}

	header nav a:hover {
		color: var(--text);
	}

	header nav a[aria-current='page'] {
		color: var(--text);
		border-bottom-color: var(--text);
	}

	main {
		max-width: var(--page-max);
		margin: 0 auto;
		padding: var(--space-6) var(--space-5) var(--space-8);
	}

	main:focus {
		outline: none;
	}

	main.practice {
		max-width: var(--reading-max);
	}

	main.immersive {
		min-height: 100dvh;
		padding: var(--space-5) var(--space-5) var(--space-6);
	}

	.center {
		display: grid;
		place-items: center;
		min-height: 60vh;
		gap: var(--space-4);
	}

	@media (max-width: 640px) {
		/* The header *is* the tab bar here, so it is built like one: the brand
		   goes (the three places are the whole point of it on a phone), they
		   spread across the width, and each is a thumb's worth tall. */
		.row {
			padding: 0 var(--space-2);
		}

		.brand {
			display: none;
		}

		header nav {
			flex: 1 1 auto;
			gap: 0;
		}

		header nav a {
			flex: 1 1 0;
			display: flex;
			align-items: center;
			justify-content: center;
			min-height: var(--tap);
			padding: 0 var(--space-1);
			margin-bottom: 0;
			border-bottom-width: var(--border-strong);
			text-align: center;
		}

		main {
			padding: var(--space-5) var(--space-4) var(--space-8);
		}

		main.immersive {
			padding-top: var(--space-4);
			padding-bottom: var(--space-5);
		}
	}
</style>
