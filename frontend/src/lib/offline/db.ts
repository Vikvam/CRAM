/**
 * The little bit of this device's disk the app is allowed to keep.
 *
 * Three stores. `outbox` holds answers the server has not acknowledged yet, and
 * is the reason a session on a phone with no signal is not thrown away; `batch`
 * holds the last queue that was fetched, so there is something to practise when
 * nothing can be fetched; `kept` holds the last collection this device was shown,
 * because a batch you cannot reach is no use — the screens that lead to a session
 * are built out of the category tree, and without it the app opens on an empty
 * collection with nothing to tap (found on a real phone, 2026-10-10).
 *
 * localStorage would not do: an answer carries the text that was typed and a
 * batch carries a few hundred cards. IndexedDB can still be absent — a private
 * window, a browser with site data blocked — so every call here can come back
 * empty instead of throwing, and every caller is written to carry on when it does.
 */

const NAME = 'memo';
//: 2 added `kept`. Bumping is safe — `onupgradeneeded` only creates what is
//: missing, so a phone already holding answers keeps them.
const VERSION = 2;
export const OUTBOX = 'outbox';
export const BATCH = 'batch';
export const KEPT = 'kept';

let opening: Promise<IDBDatabase | null> | null = null;

function open(): Promise<IDBDatabase | null> {
	if (opening) return opening;
	opening = new Promise((resolve) => {
		if (typeof indexedDB === 'undefined') return resolve(null);
		let request: IDBOpenDBRequest;
		try {
			request = indexedDB.open(NAME, VERSION);
		} catch {
			return resolve(null);
		}
		request.onupgradeneeded = () => {
			const db = request.result;
			// `client_id` is this device's id for an answer, `scope` is what a queue
			// was asked for. Each is what the thing *is*, so each is its own key.
			if (!db.objectStoreNames.contains(OUTBOX)) db.createObjectStore(OUTBOX, { keyPath: 'client_id' });
			if (!db.objectStoreNames.contains(BATCH)) db.createObjectStore(BATCH, { keyPath: 'scope' });
			if (!db.objectStoreNames.contains(KEPT)) db.createObjectStore(KEPT, { keyPath: 'name' });
		};
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => resolve(null);
		request.onblocked = () => resolve(null);
	});
	return opening;
}

function run<T>(store: string, mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest) {
	return open().then(
		(db) =>
			new Promise<T | null>((resolve) => {
				if (!db) return resolve(null);
				try {
					const transaction = db.transaction(store, mode);
					const request = work(transaction.objectStore(store));
					request.onsuccess = () => resolve(request.result as T);
					request.onerror = () => resolve(null);
					transaction.onabort = () => resolve(null);
				} catch {
					resolve(null);
				}
			})
	);
}

export const put = <T>(store: string, value: T) => run<IDBValidKey>(store, 'readwrite', (s) => s.put(value));
export const get = <T>(store: string, key: string) => run<T>(store, 'readonly', (s) => s.get(key));
export const all = <T>(store: string) =>
	run<T[]>(store, 'readonly', (s) => s.getAll()).then((rows) => rows ?? []);

/** Several keys in one transaction, so a half-finished flush cannot lose rows. */
export function remove(store: string, keys: readonly string[]): Promise<void> {
	if (!keys.length) return Promise.resolve();
	return open().then(
		(db) =>
			new Promise((resolve) => {
				if (!db) return resolve();
				try {
					const transaction = db.transaction(store, 'readwrite');
					const target = transaction.objectStore(store);
					for (const key of keys) target.delete(key);
					transaction.oncomplete = () => resolve();
					transaction.onerror = () => resolve();
					transaction.onabort = () => resolve();
				} catch {
					resolve();
				}
			})
	);
}
