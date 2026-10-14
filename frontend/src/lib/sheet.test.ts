import { describe, expect, test } from 'vitest';
import { sections, tally } from './sheet';
import type { Group, Note } from '$lib/api/client';

const note = (front: string, group: string | null, progress = 'new') =>
	({ id: front, front, back: front.toUpperCase(), group, progress }) as unknown as Note;
const group = (key: string, label: Record<string, string> | null = null) =>
	({ key, label, note: null }) as Group;

describe('a data file read as a sheet (PLAN 6, phase 4)', () => {
	test('rows are grouped under the heading they carry', () => {
		const out = sections(
			[note('나라', 'countries'), note('한국', 'countries'), note('의사', 'jobs')],
			[group('countries', { en: 'Countries' }), group('jobs')]
		);
		expect(out.map((s) => [s.group?.key, s.notes.length])).toEqual([
			['countries', 2],
			['jobs', 1]
		]);
		expect(out[0].group?.label).toEqual({ en: 'Countries' });
	});

	test('notes under no heading make a section of their own', () => {
		const out = sections([note('책', null), note('나라', 'countries')], [group('countries')]);
		expect(out.map((s) => s.group)).toEqual([null, group('countries')]);
	});

	test('a heading taken up again is gathered into its first section', () => {
		const out = sections([note('a', 'x'), note('b', 'y'), note('c', 'x')], [group('x'), group('y')]);
		expect(out.map((s) => [s.group?.key, s.notes.map((n) => n.id)])).toEqual([
			['x', ['a', 'c']],
			['y', ['b']]
		]);
	});

	test('a word moved to another heading in the editor joins it on the sheet', () => {
		// 2-1 after 이집트 was given Countries while sitting among Additional.
		const out = sections(
			[
				note('러시아', 'countries'),
				note('간호사', 'jobs'),
				note('나라', 'additional'),
				note('이집트', 'countries'),
				note('사람', 'additional')
			],
			[group('countries'), group('jobs'), group('additional')]
		);
		expect(out.map((s) => [s.group?.key, s.notes.map((n) => n.id)])).toEqual([
			['countries', ['러시아', '이집트']],
			['jobs', ['간호사']],
			['additional', ['나라', '사람']]
		]);
	});

	test('notes under no heading are one section wherever they sit', () => {
		const out = sections([note('a', null), note('b', 'x'), note('c', null)], [group('x')]);
		expect(out.map((s) => [s.group?.key ?? null, s.notes.length])).toEqual([
			[null, 2],
			['x', 1]
		]);
	});

	test('a heading the file never declared is still shown by its key', () => {
		const out = sections([note('a', 'ghost')], []);
		expect(out[0].group).toEqual({ key: 'ghost', label: null, note: null });
	});

	test('an empty file is an empty sheet', () => {
		expect(sections([], [group('x')])).toEqual([]);
	});

	test('the sheet can count what it is showing', () => {
		const rows = [
			note('a', null, 'mastered'),
			note('b', null, 'known'),
			note('c', null, 'learning'),
			note('d', null)
		];
		expect(tally(rows)).toEqual({ new: 1, learning: 1, known: 1, mastered: 1 });
	});

	test('a known low word counts as mastered until nothing else is left', () => {
		const low = { ...note('a', null, 'known'), priority: 'low' } as Note;
		expect(tally([low, note('b', null, 'known')])).toEqual({ new: 0, learning: 0, known: 1, mastered: 1 });
		expect(tally([low, note('b', null, 'mastered')])).toEqual({ new: 0, learning: 0, known: 1, mastered: 1 });
		expect(tally([low, note('b', null, 'learning')]).mastered).toBe(1);
		expect(tally([low, note('b', null, 'mastered')]).known).toBe(1);
	});
});
