import { describe, expect, it } from 'vitest';
import { clampCrop, cropFromCorners, FULL, isFullCrop, needsWork, rotatedSize } from './image';

describe('preparing a photo', () => {
	it('a quarter turn swaps the sides', () => {
		expect(rotatedSize(400, 300, 90)).toEqual([300, 400]);
		expect(rotatedSize(400, 300, 270)).toEqual([300, 400]);
		expect(rotatedSize(400, 300, 180)).toEqual([400, 300]);
		expect(rotatedSize(400, 300, -90)).toEqual([300, 400]);
	});

	it('a crop is built from corners in any order', () => {
		const crop = cropFromCorners({ x: 0.6, y: 0.8 }, { x: 0.2, y: 0.3 });
		expect(crop.x).toBeCloseTo(0.2);
		expect(crop.y).toBeCloseTo(0.3);
		expect(crop.width).toBeCloseTo(0.4);
		expect(crop.height).toBeCloseTo(0.5);
	});

	it('a crop never leaves the picture or collapses', () => {
		const crop = clampCrop({ x: -0.5, y: 0.9, width: 2, height: 0.01 });
		expect(crop).toEqual({ x: 0, y: 0.9, width: 1, height: 0.05 });
		expect(crop.y + crop.height).toBeLessThanOrEqual(1);
	});

	it('an untouched photo is left alone', () => {
		expect(isFullCrop(FULL)).toBe(true);
		expect(needsWork(0, FULL)).toBe(false);
		expect(needsWork(360, FULL)).toBe(false);
		expect(needsWork(90, FULL)).toBe(true);
		expect(needsWork(0, { x: 0, y: 0, width: 0.5, height: 1 })).toBe(true);
	});
});
