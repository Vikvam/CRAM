/**
 * Straightening a photo before it is read (PLAN 6, phase 2).
 *
 * A phone photo of a textbook is often sideways, and usually has half the desk
 * in it. Both cost the model accuracy, so they are fixed here — in the browser,
 * before the upload — and the server only ever sees the picture you approved.
 */

/** A crop as fractions of the (already rotated) image: 0–1 from the top left. */
export interface Crop {
	x: number;
	y: number;
	width: number;
	height: number;
}

export const FULL: Crop = { x: 0, y: 0, width: 1, height: 1 };

export const isFullCrop = (crop: Crop) =>
	crop.x <= 0.001 && crop.y <= 0.001 && crop.width >= 0.999 && crop.height >= 0.999;

/** Keep a crop inside the picture and never let it collapse to nothing. */
export function clampCrop(crop: Crop, min = 0.05): Crop {
	const width = Math.min(1, Math.max(min, crop.width));
	const height = Math.min(1, Math.max(min, crop.height));
	return {
		width,
		height,
		x: Math.min(Math.max(0, crop.x), 1 - width),
		y: Math.min(Math.max(0, crop.y), 1 - height)
	};
}

/** A crop from two corners, in any order, as fractions. */
export function cropFromCorners(a: { x: number; y: number }, b: { x: number; y: number }): Crop {
	return clampCrop({
		x: Math.min(a.x, b.x),
		y: Math.min(a.y, b.y),
		width: Math.abs(a.x - b.x),
		height: Math.abs(a.y - b.y)
	});
}

/** The size a picture ends up after a quarter-turn or two. */
export function rotatedSize(width: number, height: number, degrees: number): [number, number] {
	return (((degrees % 360) + 360) % 360) % 180 === 90 ? [height, width] : [width, height];
}

export const needsWork = (rotation: number, crop: Crop) =>
	(((rotation % 360) + 360) % 360) !== 0 || !isFullCrop(crop);

/**
 * Apply the rotation and crop, giving a new JPEG file. The original is returned
 * untouched when there is nothing to do, so a plain upload stays byte for byte
 * what the camera produced.
 */
export async function transform(file: File, rotation: number, crop: Crop): Promise<File> {
	if (!needsWork(rotation, crop)) return file;

	const bitmap = await createImageBitmap(file);
	const [rotatedWidth, rotatedHeight] = rotatedSize(bitmap.width, bitmap.height, rotation);
	const safe = clampCrop(crop);
	const canvas = document.createElement('canvas');
	canvas.width = Math.round(rotatedWidth * safe.width);
	canvas.height = Math.round(rotatedHeight * safe.height);

	const context = canvas.getContext('2d');
	if (!context) return file; // no canvas: upload what we have rather than nothing
	context.translate(-safe.x * rotatedWidth, -safe.y * rotatedHeight);
	context.translate(rotatedWidth / 2, rotatedHeight / 2);
	context.rotate((rotation * Math.PI) / 180);
	context.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
	bitmap.close();

	const blob = await new Promise<Blob | null>((resolve) =>
		canvas.toBlob(resolve, 'image/jpeg', 0.92)
	);
	if (!blob) return file;
	const name = file.name.replace(/\.[^.]+$/, '') + '.jpg';
	return new File([blob], name, { type: 'image/jpeg', lastModified: file.lastModified });
}
