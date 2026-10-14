import { expect, test } from 'vitest';
import { next } from './roving';

test('an arrow moves one step and wraps round', () => {
	expect(next(0, 1, 4)).toBe(1);
	expect(next(3, 1, 4)).toBe(0);
	expect(next(0, -1, 4)).toBe(3);
});

test('the first arrow press lands on the near end', () => {
	expect(next(-1, 1, 4)).toBe(0);
	expect(next(-1, -1, 4)).toBe(3);
});

test('an answered tile is stepped over, not focused and found dead', () => {
	const paired = (i: number) => i === 1 || i === 2;
	expect(next(0, 1, 4, paired)).toBe(3);
	expect(next(3, 1, 4, paired)).toBe(0);
	expect(next(0, -1, 4, paired)).toBe(3);
});

test('staying put follows a row that got shorter', () => {
	// A piece was placed and the pool re-rendered: focus the one that slid in.
	expect(next(2, 0, 3)).toBe(2);
	expect(next(3, 0, 3)).toBe(2);
	expect(next(0, 0, 3)).toBe(0);
});

test('nowhere to go is staying where you are', () => {
	expect(next(2, 1, 4, () => true)).toBe(2);
	expect(next(0, 1, 1)).toBe(0);
	expect(next(0, 1, 0)).toBe(-1);
});
