/**
 * How the app looks on this device: the skin, and light or dark.
 *
 * Both live in this browser rather than on the server — the laptop and the
 * phone are read in different light and at different distances, so one of them
 * being dark, or being set to the heavier skin, is not an instruction about the
 * other. `app.html` applies both before the first paint; this module keeps
 * them in step afterwards.
 */

export type Theme = 'system' | 'light' | 'dark';
export const THEMES: Theme[] = ['system', 'light', 'dark'];

/** `paper` reads like a book; `ink` reads like a sign. */
export type Skin = 'paper' | 'ink';
export const SKINS: Skin[] = ['paper', 'ink'];

/**
 * How big everything is, as a percentage on the root element.
 *
 * Not a text-only setting: every space, gap and tap target in the app is in
 * rem, and rem is the root font size, so this carries the whole interface with
 * it. A percentage rather than a pixel size, so whatever the device's own
 * accessibility text size is doing still multiplies in instead of being
 * overridden — the phone wants this smaller and the big screen wants it
 * larger, which is why it lives here and not on the server.
 */
export type Scale = 'compact' | 'default' | 'large' | 'larger';
export const SCALES: Scale[] = ['compact', 'default', 'large', 'larger'];
export const PERCENT: Record<Scale, number> = { compact: 90, default: 100, large: 115, larger: 130 };

const THEME_KEY = 'memo.theme';
const SKIN_KEY = 'memo.skin';
const SCALE_KEY = 'memo.scale';

/** The browser's own chrome, told what the page decided. Mirrors `app.html`. */
const BAR: Record<Skin, Record<'light' | 'dark', string>> = {
	paper: { light: '#faf8f2', dark: '#14130f' },
	ink: { light: '#edece7', dark: '#0b0b0c' }
};

function read(key: string, fallback: string): string {
	try {
		return localStorage.getItem(key) ?? fallback;
	} catch {
		return fallback;
	}
}

function write(key: string, value: string) {
	try {
		localStorage.setItem(key, value);
	} catch {
		/* private mode — the choice just isn't remembered */
	}
}

const prefersDark = () =>
	typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;

class Appearance {
	theme = $state<Theme>('system');
	skin = $state<Skin>('paper');
	scale = $state<Scale>('default');

	/** Called once the page is up: adopt what `app.html` already applied. */
	start() {
		this.theme = (read(THEME_KEY, 'system') as Theme) ?? 'system';
		this.skin = (read(SKIN_KEY, 'paper') as Skin) ?? 'paper';
		const scale = read(SCALE_KEY, 'default') as Scale;
		this.scale = SCALES.includes(scale) ? scale : 'default';
		this.apply();
		// "System" is a live answer, not a snapshot: follow the phone if it turns.
		const media = window.matchMedia('(prefers-color-scheme: dark)');
		const listener = () => this.theme === 'system' && this.apply();
		media.addEventListener('change', listener);
		return () => media.removeEventListener('change', listener);
	}

	set(theme: Theme) {
		this.theme = theme;
		write(THEME_KEY, theme);
		this.apply();
	}

	setSkin(skin: Skin) {
		this.skin = skin;
		write(SKIN_KEY, skin);
		this.apply();
	}

	setScale(scale: Scale) {
		this.scale = scale;
		write(SCALE_KEY, scale);
		this.apply();
	}

	private apply() {
		const scheme = this.theme === 'dark' || (this.theme === 'system' && prefersDark()) ? 'dark' : 'light';
		const root = document.documentElement;
		root.dataset.theme = scheme;
		root.dataset.skin = this.skin;
		root.style.fontSize = `${PERCENT[this.scale]}%`;
		document.getElementById('theme-color')?.setAttribute('content', BAR[this.skin][scheme]);
	}
}

export const appearance = new Appearance();
