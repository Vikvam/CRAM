import { describe, expect, it } from 'vitest';
import { blankRow, changes, isBlank, pair, toRow, type Row } from './rows';
import type { Note } from '$lib/api/client';

const note = (over: Partial<Note> = {}): Note => ({
	id: 'n_1',
	data_file_id: 'df_1',
	position: 0,
	type: null,
	front: '나라',
	back: 'country',
	front_lang: null,
	back_lang: null,
	fields: null,
	accept: null,
	modes: null,
	note: null,
	group: null,
	tags: null,
	status: null,
	confidence: null,
	suspended: null,
	priority: null,
	page: null,
	cards: 2,
	reviewed: 0,
	archived: false,
	progress: 'new',
	...over
});

describe('grid rows', () => {
	it('a fresh row is blank until something is typed', () => {
		const row = blankRow();
		expect(isBlank(row)).toBe(true);
		row.back = 'country';
		expect(isBlank(row)).toBe(false);
	});

	it('an unchanged row asks for no patch', () => {
		expect(changes(toRow(note()))).toEqual({});
	});

	it('a patch carries only what changed', () => {
		const row = toRow(note());
		row.back = 'nation';
		expect(changes(row)).toEqual({ back: 'nation' });
	});

	it('clearing a group sends null, not an empty string', () => {
		const row = toRow(note({ group: '나라' }));
		row.group = '  ';
		expect(changes(row)).toEqual({ group: null });
	});

	it('a new row patches every field it has', () => {
		const row: Row = { ...blankRow(), front: '한국', back: 'Korea', group: '나라' };
		expect(changes(row)).toEqual({ front: '한국', back: 'Korea', group: '나라' });
		expect(pair(row)).toEqual(['한국', 'Korea']);
	});

	it('a half-typed row still reports its one side', () => {
		const row = { ...blankRow(), front: '나라' };
		expect(pair(row)).toEqual(['나라', null]);
	});
});
