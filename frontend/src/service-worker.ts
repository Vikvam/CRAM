/// <reference types="@sveltejs/kit" />
/// <reference lib="webworker" />

/**
 * What makes the app open at all when there is nothing to reach.
 *
 * Without this, a phone out of range has no HTML and no JavaScript the moment
 * the tab is closed, so a batch of cards sitting on its disk is unreachable —
 * which is the whole reason this file exists (PLAN 5). It caches the app itself
 * and nothing else: `/api/` is never cached, because a stale queue or a stale
 * progress bar pretending to be current is worse than an honest failure, and
 * `sync.svelte.ts` is already built to carry on through one.
 *
 * It only runs over https, or on localhost — a service worker is not allowed in
 * an insecure context, which is why the phone reaches the laptop through
 * Tailscale rather than over plain http on the wifi.
 */

import { base, build, files, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;

/** One cache per build, so a new version never reads the old one's chunks. */
const CACHE = `memo-${version}`;
/** `${base}/` is the whole app: the server answers every route with that one page. */
const SHELL = [...build, `${base}/`];
/** Icons and the manifest: wanted, but not what the app needs in order to run. */
const EXTRAS = files;

/**
 * `addAll` is all-or-nothing, and `build` carries every bundled KaTeX font, so
 * one request failing on a phone with two bars used to mean no service worker
 * at all — the one thing that has to survive a bad connection. So the shell is
 * required and everything else is best effort.
 */
async function precache(cache: Cache) {
	await cache.addAll(SHELL);
	await Promise.allSettled(EXTRAS.map((path) => cache.add(path)));
}

sw.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(CACHE)
			.then(precache)
			.then(() => sw.skipWaiting())
	);
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
			.then(() => sw.clients.claim())
	);
});

/** Hashed and never rewritten, so what is cached is by definition still right. */
const immutable = new Set(build);

/**
 * How long the network gets before the cache answers instead.
 *
 * The reason this exists: a laptop that is asleep does not *refuse* a
 * connection, it swallows the packets, so `fetch` sits there until the
 * operating system gives up — well over a minute. Network-first with no limit
 * therefore means the app fails to open in precisely the situation the cache is
 * for, and the phone looks broken rather than offline (reported 2026-10-10:
 * "it just takes a lot of time to load"). Being switched off entirely fails in
 * milliseconds, which is why this never showed up in testing.
 *
 * It stays online-first: a server on the same desk answers in a few
 * milliseconds, so this only ever bites when something is actually wrong.
 */
const PATIENCE = 1500;

const after = (ms: number) => new Promise<null>((resolve) => setTimeout(() => resolve(null), ms));

/**
 * Ask the network, but hand over the cache if it does not come back in time.
 *
 * A failure resolves to `null` rather than throwing, so the race ends the
 * moment the network is known to be unreachable instead of waiting out the
 * clock. With nothing cached there is nothing to fall back to, so the network
 * is awaited after all — a slow answer beats a broken page.
 */
async function soonest(request: Request, fallback: Request | string, keep = false): Promise<Response> {
	const network = fetch(request).then(
		(response) => {
			if (keep && response.ok) {
				const copy = response.clone();
				void caches.open(CACHE).then((cache) => cache.put(request, copy));
			}
			return response;
		},
		() => null
	);
	const first = await Promise.race([network, after(PATIENCE)]);
	if (first) return first;
	const hit = await caches.match(fallback);
	if (hit) return hit;
	return (await network) ?? Response.error();
}

sw.addEventListener('fetch', (event) => {
	const request = event.request;
	const url = new URL(request.url);
	const ours = url.origin === location.origin;
	if (request.method !== 'GET' || !ours || url.pathname.startsWith('/api/')) return;

	if (immutable.has(url.pathname)) {
		event.respondWith(
			caches.match(request).then((hit) => hit ?? fetch(request))
		);
		return;
	}

	// A page: ask first, because a new build should be picked up as soon as it
	// exists, and fall back to the one page the app is when the asking fails or
	// takes too long.
	if (request.mode === 'navigate') {
		event.respondWith(soonest(request, `${base}/`));
		return;
	}

	event.respondWith(soonest(request, request, true));
});
