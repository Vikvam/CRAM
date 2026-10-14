import { expect, test } from 'vitest';
import { foreign, pickVoice } from './speech.svelte';

/** A voice list is the browser's, never ours — but only these two fields matter. */
const voice = (lang: string, localService = true) => ({ lang, localService });

test('an exact region beats a bare language', () => {
	const bare = voice('ko');
	const exact = voice('ko-KR');
	expect(pickVoice([bare, exact], 'ko-KR')).toBe(exact);
	expect(pickVoice([exact, bare], 'ko-KR')).toBe(exact);
});

test('a bare language still answers a request for a region', () => {
	const bare = voice('ko');
	expect(pickVoice([bare], 'ko-KR')).toBe(bare);
});

test('a region is offered when none was asked for', () => {
	const korean = voice('ko-KR');
	expect(pickVoice([korean], 'ko')).toBe(korean);
});

test('underscores and case are the same tag', () => {
	const korean = voice('ko_KR');
	expect(pickVoice([korean], 'ko-KR')).toBe(korean);
	expect(pickVoice([voice('ko-KR')], 'KO_kr')).not.toBeNull();
});

test('a voice on the device beats one that needs the network', () => {
	const remote = voice('ko-KR', false);
	const local = voice('ko-KR', true);
	expect(pickVoice([remote, local], 'ko-KR')).toBe(local);
	expect(pickVoice([local, remote], 'ko-KR')).toBe(local);
});

test('the right language beats being on the device', () => {
	const near = voice('ko', true);
	const exact = voice('ko-KR', false);
	expect(pickVoice([near, exact], 'ko-KR')).toBe(exact);
});

test('another language is not a voice for this one', () => {
	expect(pickVoice([voice('ko-KR'), voice('en-US')], 'ja')).toBeNull();
});

test('nothing to choose from, nothing chosen', () => {
	expect(pickVoice([], 'ko')).toBeNull();
	expect(pickVoice([voice('ko-KR')], null)).toBeNull();
	expect(pickVoice([voice('ko-KR')], '')).toBeNull();
});

test('equally good voices keep the order the browser gave', () => {
	const first = voice('ko-KR');
	const second = voice('ko-KR');
	expect(pickVoice([first, second], 'ko-KR')).toBe(first);
});

test('only a language memo is not written in is worth saying aloud', () => {
	expect(foreign('ko')).toBe(true);
	expect(foreign('ko-KR')).toBe(true);
	expect(foreign('en')).toBe(false);
	expect(foreign('en-GB')).toBe(false);
	expect(foreign(null)).toBe(false);
	expect(foreign('')).toBe(false);
});
