/**
 * Saying a card out loud, in whatever voice the device already has.
 *
 * Nothing is downloaded and nothing is generated on a server: this is the
 * browser's own synthesiser, which on an Android phone is a good neural Korean
 * voice and on a laptop is whatever speech-dispatcher was given, if anything. A
 * device with no voice for the language is the ordinary case, not a failure —
 * `can()` says so and the button is never drawn.
 *
 * Nothing here ever speaks on its own: every utterance is a tap, or a sitting
 * started with *Read questions aloud*, which says each question as it appears.
 */

const normalise = (tag: string) => tag.replace(/_/g, '-').toLowerCase();
const primary = (tag: string) => normalise(tag).split('-')[0];

/**
 * The best voice for a language tag, or null when the device has none.
 *
 * Pure, and the only interesting logic in here, so it is tested directly: the
 * voice list cannot be faked in a unit test but a list of plain objects can.
 * An exact `ko-KR` beats a bare `ko`, a bare `ko` answers a request for
 * `ko-KR`, and a voice that lives on the device beats one that needs the
 * network. Ties keep the order the browser gave, so the answer is stable.
 */
export function pickVoice<V extends { lang: string; localService?: boolean }>(
	voices: readonly V[],
	lang: string | null | undefined
): V | null {
	const want = normalise(lang ?? '');
	if (!want) return null;
	let best: V | null = null;
	let score = 0;
	for (const voice of voices) {
		const has = normalise(voice.lang);
		if (primary(has) !== primary(want)) continue;
		const point = 1 + (has === want ? 2 : 0) + (voice.localService === false ? 0 : 1);
		if (point > score) {
			best = voice;
			score = point;
		}
	}
	return best;
}

/** Worth offering aloud: a language that is not the one memo itself is written in. */
export function foreign(lang: string | null | undefined): boolean {
	const want = primary(lang ?? '');
	if (!want) return false;
	const ours = typeof document === 'undefined' ? 'en' : primary(document.documentElement.lang || 'en');
	return want !== ours;
}

/** Chrome keeps no reference of its own: a collected utterance goes silent. */
let held: SpeechSynthesisUtterance | null = null;
let pending: ReturnType<typeof setTimeout> | null = null;

/** The voice list is empty on the first call and fills late — twice, on Android. */
const POLLS = [0, 250, 1000];

class Speech {
	/** A browser either has the API or does not; this never changes. */
	readonly supported = typeof window !== 'undefined' && 'speechSynthesis' in window;

	/** Reactive, because it arrives after the first paint. */
	voices = $state<SpeechSynthesisVoice[]>([]);

	/** What is being said, so a second tap can stop it. `speaking` is unreliable. */
	saying = $state<string | null>(null);

	/** Called once, by the layout. Returns its own teardown, like `appearance`. */
	start() {
		if (!this.supported) return () => {};
		const synth = window.speechSynthesis;
		const read = () => (this.voices = synth.getVoices());
		const timers = POLLS.map((after) => setTimeout(read, after));
		synth.addEventListener('voiceschanged', read);
		// onDestroy does not run on a reload, a closed tab, or a phone putting the
		// browser in the background — and Chrome carries on talking to an empty room.
		const quieten = () => this.stop();
		const hidden = () => document.visibilityState === 'hidden' && this.stop();
		document.addEventListener('visibilitychange', hidden);
		window.addEventListener('pagehide', quieten);
		return () => {
			timers.forEach(clearTimeout);
			synth.removeEventListener('voiceschanged', read);
			document.removeEventListener('visibilitychange', hidden);
			window.removeEventListener('pagehide', quieten);
			this.stop();
		};
	}

	/** Whether this language can be spoken here at all. */
	can(lang: string | null | undefined): boolean {
		return pickVoice(this.voices, lang) !== null;
	}

	/** Say it, or stop if it is already being said. */
	speak(text: string, lang: string | null | undefined) {
		const words = text.trim();
		const voice = pickVoice(this.voices, lang);
		const again = this.saying === words;
		this.stop();
		if (!words || !voice || again) return;
		this.saying = words;
		const utterance = new SpeechSynthesisUtterance(words);
		utterance.voice = voice;
		// `lang` on its own is only a hint, and Android falls back to its UI locale.
		utterance.lang = voice.lang;
		const done = () => {
			if (this.saying === words) this.saying = null;
		};
		// Nothing to report: the only errors reachable here are the ones `stop()` causes.
		utterance.onend = done;
		utterance.onerror = done;
		held = utterance;
		// Speaking in the same tick as cancel() loses the utterance, so let it land first.
		pending = setTimeout(() => window.speechSynthesis.speak(utterance), 60);
	}

	stop() {
		this.saying = null;
		if (pending !== null) {
			clearTimeout(pending);
			pending = null;
		}
		held = null;
		if (this.supported) window.speechSynthesis.cancel();
	}
}

export const speech = new Speech();
