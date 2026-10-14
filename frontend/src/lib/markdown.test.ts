import { expect, test } from 'vitest';
import { plain } from './markdown';

test('markup is not read out', () => {
	expect(plain('**굵게**')).toBe('굵게');
	expect(plain('_기울임_')).toBe('기울임');
	expect(plain('`code`')).toBe('code');
	expect(plain('[Russia](https://example.com)')).toBe('Russia');
});

test('a formula is left unsaid rather than spelled out', () => {
	expect(plain('$x^2$')).toBe('');
	expect(plain('the sum $x^2$ here')).toBe('the sum here');
});

test('entities are said as the character', () => {
	expect(plain('salt &amp; pepper')).toBe('salt & pepper');
});

test('a line break is a pause, not a word', () => {
	expect(plain('하나\n둘')).toBe('하나 둘');
	expect(plain('  하나   둘  ')).toBe('하나 둘');
});

test('nothing to say', () => {
	expect(plain(null)).toBe('');
	expect(plain(undefined)).toBe('');
	expect(plain('')).toBe('');
});

test('plain text comes back as it was', () => {
	expect(plain('러시아')).toBe('러시아');
});
