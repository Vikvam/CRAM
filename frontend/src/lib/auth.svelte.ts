import { api, type AuthStatus } from './api/client';

/**
 * Shared sign-in state. The API fires `memo:signed-out` on any 401.
 *
 * `/auth/status` answers 200 whether or not you are signed in, so a *thrown*
 * error from it means the server could not be reached at all — a phone out of
 * range, a laptop asleep. That is not being signed out, and it must not look
 * like it: the last answer is remembered here so a session can go on offline.
 * Only a real 401 forgets it.
 */
const REMEMBERED = 'memo.signed-in';

function remember(status: AuthStatus | null) {
	try {
		if (status?.signed_in) localStorage.setItem(REMEMBERED, JSON.stringify(status));
		else localStorage.removeItem(REMEMBERED);
	} catch {
		/* a private window: the app simply asks again next time */
	}
}

function remembered(): AuthStatus | null {
	try {
		const raw = localStorage.getItem(REMEMBERED);
		return raw ? (JSON.parse(raw) as AuthStatus) : null;
	} catch {
		return null;
	}
}

class Auth {
	status = $state<AuthStatus | null>(null);
	error = $state<string | null>(null);
	/** Signed in as far as this device knows, but the server has not been reached. */
	stale = $state(false);

	async refresh() {
		// What this device knew last, before asking — the whole app is gated on
		// `status` being something (`+layout.svelte`), so waiting for an answer
		// that may never come is the difference between opening and appearing
		// broken. A laptop that is asleep swallows the request rather than
		// refusing it, so "may never come" is the normal case, not the odd one.
		if (this.status === null) {
			const last = remembered();
			if (last) {
				this.status = last;
				this.stale = true;
			}
		}
		try {
			this.status = await api.status();
			this.stale = false;
			this.error = null;
			remember(this.status);
		} catch (e) {
			this.error = e instanceof Error ? e.message : String(e);
			// Carry on with what was true last time, rather than locking the app.
			// Usually already done above; this covers a refresh of a session that
			// began with an answer and has since lost the server.
			const last = remembered();
			if (last) {
				this.status = last;
				this.stale = true;
			}
		}
	}

	async login(password: string) {
		this.status = await api.login(password);
		this.stale = false;
		this.error = null;
		remember(this.status);
	}

	async logout() {
		await api.logout();
		remember(null);
		await this.refresh();
	}

	/** A 401 is the one answer that means the remembered state was wrong. */
	forget() {
		remember(null);
		this.stale = false;
	}
}

export const auth = new Auth();
