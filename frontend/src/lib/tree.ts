/** The category tree, built from the flat list the API returns. */
import type { Category } from './api/client';

export interface TreeNode {
	category: Category;
	children: TreeNode[];
	/** This node plus everything below it. Inventory only: what is where, not
	 *  what to do about it — nothing here counts down or falls due. */
	totals: { notes: number; cards: number };
	depth: number;
}

export function buildTree(categories: Category[]): TreeNode[] {
	const nodes = new Map<string, TreeNode>();
	for (const category of categories) {
		nodes.set(category.id, {
			category,
			children: [],
			totals: { notes: category.notes ?? 0, cards: category.cards ?? 0 },
			depth: category.path.split('/').length - 1
		});
	}
	const roots: TreeNode[] = [];
	for (const node of nodes.values()) {
		const parent = node.category.parent_id ? nodes.get(node.category.parent_id) : undefined;
		(parent ? parent.children : roots).push(node);
	}
	const sum = (node: TreeNode): TreeNode['totals'] => {
		for (const child of node.children) {
			const t = sum(child);
			node.totals.notes += t.notes;
			node.totals.cards += t.cards;
		}
		node.children.sort((a, b) => a.category.path.localeCompare(b.category.path));
		return node.totals;
	};
	roots.forEach(sum);
	return roots.sort((a, b) => a.category.path.localeCompare(b.category.path));
}

/** A label map → the text to show, preferring English, then anything. */
export function labelText(label: Record<string, string> | null | undefined, fallback = ''): string {
	if (!label) return fallback;
	return label.en ?? Object.values(label)[0] ?? fallback;
}

/** Both sides of a bilingual label, native first: "나라 · Countries". */
export function labelBoth(label: Record<string, string> | null | undefined, fallback = ''): string {
	if (!label) return fallback;
	const values = Object.entries(label)
		.sort(([a], [b]) => (a === 'en' ? 1 : b === 'en' ? -1 : 0))
		.map(([, v]) => v);
	return values.length ? values.join(' · ') : fallback;
}
