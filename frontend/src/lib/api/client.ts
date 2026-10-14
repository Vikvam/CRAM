/**
 * Typed access to the backend. Types come from its OpenAPI document
 * (`npm run types`), so a renamed field fails the type check, not the user.
 */
import type { components } from "./schema";

type S = components["schemas"];
export type AuthStatus = S["AuthStatus"];
export type Category = S["CategoryOut"];
export type CategoryPatch = S["CategoryPatch"];
export type DataFileSummary = S["DataFileSummary"];
export type Importer = S["ImporterOut"];
export type ImportJob = S["ImportJobOut"];
export type QueueCard = S["QueueCardOut"];
export type Queue = S["QueueOut"];
export type AnswerBody = S["AnswerBody"];
export type AnswerOut = S["AnswerOut"];
export type AnswerRow = S["AnswerRowIn"];
export type AnswersReport = S["AnswersOut"];
export type Settings = S["SettingsOut"];
export type Note = S["NoteOut"];
export type NotePatch = S["NoteIn"];
export type Notes = S["NotesOut"];
export type NotesCreated = S["NotesCreatedOut"];
export type Group = S["GroupOut"];
export type Duplicate = S["DuplicateOut"];
export type DuplicateRow = S["DuplicateRow"];
export type FilePatch = S["DataFilePatch"];
export type ImportJobPatch = S["ImportJobPatch"];
export type ExportReport = S["ExportOut"];
export type Progress = S["ProgressOut"];
export type Mastery = S["MasteryOut"];
export type FileMastery = S["FileMasteryOut"];
export type GroupMastery = S["GroupMasteryOut"];
export type FileProgress = S["FileProgressOut"];
export type WeakCard = S["WeakCardOut"];
export type Day = S["DayOut"];
export type Word = S["WordOut"];
export type Words = S["WordsOut"];
export type Audit = S["AuditOut"];
export type AuditFinding = S["AuditFindingOut"];
export type AuditNote = S["AuditNoteOut"];
export type NoteHit = S["NoteHitOut"];
export type SearchResult = S["SearchOut"];
export type WordList = S["ListOut"];
export type WordListWords = S["ListWordsOut"];
export type Related = S["RelatedOut"];

/** The interchange format (PLAN 3) — kept loose here, exactly like the backend model. */
export interface DraftNote {
  id?: string;
  type?: "bidirectional" | "directional";
  front?: string | null;
  back?: string | null;
  accept?: { front?: string[] | null; back?: string[] | null } | null;
  note?: string | null;
  group?: string | null;
  status?: string | null;
  confidence?: number | null;
  page?: number | null;
  [key: string]: unknown;
}
export interface DraftGroup {
  id?: string;
  label?: Record<string, string> | null;
  [key: string]: unknown;
}
export interface DataFile {
  format: "memo.datafile";
  version: number;
  id?: string;
  title?: string | null;
  front_lang?: string | null;
  back_lang?: string | null;
  groups: DraftGroup[];
  notes: DraftNote[];
  extra?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/**
 * How long to wait for a reply before deciding there is nobody there.
 *
 * A laptop that is asleep swallows the packets rather than refusing them, so a
 * `fetch` with no limit waits for the operating system to give up — minutes,
 * during which every screen sits empty (reported 2026-10-10: "it just takes a
 * lot of time to load"). The server is normally on the same desk and answers in
 * single-digit milliseconds, so this is nowhere near a real request.
 */
const PATIENCE = 2500;

/**
 * Once one request has found nothing there, the next one does not wait again.
 *
 * Opening a screen with four requests on it otherwise costs four timeouts, one
 * after another. Any success clears it, and so does the browser coming back
 * online, so this can only ever delay the discovery that the laptop is back by
 * one request.
 */
let unreachableSince = 0;
const BREAKER = 10_000;

if (typeof window !== "undefined") {
  window.addEventListener("online", () => {
    unreachableSince = 0;
  });
}

/** Long jobs — an import, a commit — are allowed to take as long as they take. */
const patient = (method: string, path: string) =>
  method !== "GET" || path.startsWith("/imports") || path.startsWith("/export");

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] =
      "application/json";
  }
  const wait = patient(method, path) ? 0 : PATIENCE;
  if (wait && unreachableSince && Date.now() - unreachableSince < BREAKER) {
    throw new ApiError(0, "Can't reach the laptop.");
  }
  if (wait) init.signal = AbortSignal.timeout(wait);
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    // fetch only throws when the request never happened: offline, asleep, or
    // out of range — or, now, when it took so long that waiting was worse
    // than saying so. "Failed to fetch" is the browser's phrase, not a
    // sentence to show anybody, and nothing above here can tell the
    // difference anyway.
    if (wait) unreachableSince = Date.now();
    throw new ApiError(0, "Can't reach the laptop.");
  }
  unreachableSince = 0;
  if (!response.ok) {
    let message = response.statusText;
    try {
      const detail = (await response.json()).detail;
      message = typeof detail === "string" ? detail : JSON.stringify(detail);
    } catch {
      /* not JSON — keep the status text */
    }
    if (response.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new CustomEvent("memo:signed-out"));
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== "",
  );
  return entries.length
    ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}`
    : "";
};

export const api = {
  status: () => request<AuthStatus>("GET", "/auth/status"),
  login: (password: string) =>
    request<AuthStatus>("POST", "/auth/login", { password }),
  logout: () => request<void>("POST", "/auth/logout"),

  categories: () => request<Category[]>("GET", "/categories"),
  createCategory: (path: string, label?: Record<string, string>) =>
    request<Category>("POST", "/categories", { path, label }),
  patchCategory: (id: string, body: CategoryPatch) =>
    request<Category>("PATCH", `/categories/${id}`, body),
  deleteCategory: (id: string) => request<void>("DELETE", `/categories/${id}`),
  files: (categoryId: string) =>
    request<DataFileSummary[]>("GET", `/categories/${categoryId}/files`),
  file: (fileId: string) => request<DataFile>("GET", `/files/${fileId}`),

  createFile: (categoryId: string, body: FilePatch) =>
    request<DataFileSummary>("POST", `/categories/${categoryId}/files`, body),
  patchFile: (fileId: string, body: FilePatch) =>
    request<DataFileSummary>("PATCH", `/files/${fileId}`, body),
  archiveFile: (fileId: string, restore = false) =>
    request<DataFileSummary>(
      "POST",
      `/files/${fileId}/archive${q({ restore: restore ? "true" : undefined })}`,
    ),
  notes: (fileId: string, archived = false) =>
    request<Notes>(
      "GET",
      `/files/${fileId}/notes${q({ archived: archived ? "true" : undefined })}`,
    ),
  addNotes: (fileId: string, notes: NotePatch[]) =>
    request<NotesCreated>("POST", `/files/${fileId}/notes`, { notes }),
  patchNote: (noteId: string, body: NotePatch) =>
    request<Note>("PATCH", `/notes/${noteId}`, body),
  archiveNote: (noteId: string, restore = false) =>
    request<Note>(
      "POST",
      `/notes/${noteId}/archive${q({ restore: restore ? "true" : undefined })}`,
    ),
  reorderNotes: (fileId: string, noteIds: string[]) =>
    request<Notes>("POST", `/files/${fileId}/reorder`, { note_ids: noteIds }),
  checkDuplicates: (
    pairs: [string | null, string | null][],
    options: { categoryId?: string; excludeNoteIds?: string[] } = {},
  ) =>
    request<{ rows: DuplicateRow[] }>("POST", "/notes/duplicates", {
      pairs,
      category_id: options.categoryId,
      exclude_note_ids: options.excludeNoteIds ?? [],
    }),

  exportTree: (categoryId?: string) =>
    request<ExportReport>("POST", "/export", {
      category_id: categoryId ?? null,
    }),

  importers: () => request<Importer[]>("GET", "/importers"),
  startImport: (form: FormData) => request<ImportJob>("POST", "/imports", form),
  imports: (categoryId?: string) =>
    request<ImportJob[]>("GET", `/imports${q({ category_id: categoryId })}`),
  importJob: (id: string) => request<ImportJob>("GET", `/imports/${id}`),
  saveDraft: (id: string, draft: DataFile) =>
    request<ImportJob>("PUT", `/imports/${id}/draft`, draft),
  patchImport: (id: string, body: ImportJobPatch) =>
    request<ImportJob>("PATCH", `/imports/${id}`, body),
  discardImport: (id: string) => request<void>("DELETE", `/imports/${id}`),
  retryImport: (id: string) =>
    request<ImportJob>("POST", `/imports/${id}/retry`),
  commitImport: (id: string) =>
    request<ImportJob>("POST", `/imports/${id}/commit`),
  rawUrl: (path: string) =>
    `/api/raw/${path.split("/").map(encodeURIComponent).join("/")}`,

  /**
   * A category, or — started from a sheet — one data file or one of its headings.
   *
   * `limit` is the whole sitting, due cards included; `newLimit` is a ceiling on
   * the share of it spent on words not met yet. One options object rather than
   * five positional parameters, which is what it had grown into.
   */
  queue: (
    options: {
      categoryId?: string;
      newLimit?: number;
      limit?: number;
      distractorScope?: string;
      within?: { fileId?: string; group?: string };
      /** Drill one list: every word on it, due or not. */
      listId?: string;
      /** Drill: everything in scope, due or not, still capped by `limit`. */
      drill?: boolean;
      /** Ask a two-sided note one way round only: its front, or its back. */
      direction?: "fwd" | "rev";
    } = {},
  ) =>
    request<Queue>(
      "GET",
      `/practice/queue${q({
        category_id: options.categoryId,
        file_id: options.within?.fileId,
        group: options.within?.group,
        list_id: options.listId,
        drill: options.drill ? 'true' : undefined,
        direction: options.direction,
        new_limit: options.newLimit,
        limit: options.limit,
        distractor_scope: options.distractorScope,
        // The estimate of how long a sitting takes counts answers per day,
        // so the server has to know which day this device is having.
        tz_offset: -new Date().getTimezoneOffset(),
      })}`,
    ),
  answer: (body: AnswerBody) =>
    request<AnswerOut>("POST", "/practice/answer", body),
  /** Answers earned with no server to tell. Safe to send twice (PLAN 5). */
  uploadAnswers: (rows: readonly AnswerRow[]) =>
    request<AnswersReport>("POST", "/practice/answers", { rows }),
  accept: (noteId: string, side: "front" | "back", value: string) =>
    request<{ accepted: string[] }>("POST", `/notes/${noteId}/accept`, {
      side,
      value,
    }),

  /** The overview page. Days come back in the client's own timezone. */
  progress: (
    options: { scheduler?: string; days?: number; limit?: number } = {},
  ) =>
    request<Progress>(
      "GET",
      `/progress${q({
        scheduler: options.scheduler,
        days: options.days,
        limit: options.limit,
        tz_offset: -new Date().getTimezoneOffset(),
      })}`,
    ),

  /** The whole of one of the lists Progress shows a glimpse of — or of one
   *  lesson's (`file`) or one category's and everything under it (`category`). */
  words: (
    bucket: string,
    options: { limit?: number; offset?: number; file?: string; category?: string } = {},
  ) =>
    request<Words>(
      "GET",
      `/progress/words${q({
        bucket,
        limit: options.limit,
        offset: options.offset,
        file: options.file,
        category: options.category,
      })}`,
    ),

  /** One lesson in full: its counts, each heading's, and its words by bucket. */
  fileProgress: (fileId: string) =>
    request<FileProgress>("GET", `/progress/files/${encodeURIComponent(fileId)}`),

  /**
   * Find a word by any of the words it is written with.
   *
   * Both printed sides, the spellings it also accepts, its note, its heading and
   * its lesson's title — and suspended words too, which is the point: a word set
   * aside is the one you cannot otherwise get back to.
   */
  search: (
    q_: string,
    options: {
      categoryId?: string;
      mark?: string;
      standing?: string;
      aside?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ) =>
    request<SearchResult>(
      "GET",
      `/notes/search${q({
        q: q_,
        category_id: options.categoryId,
        mark: options.mark,
        standing: options.standing,
        aside: options.aside === undefined ? undefined : String(options.aside),
        limit: options.limit,
        offset: options.offset,
      })}`,
    ),

  /** Other words in the collection with something to do with this one. */
  related: (noteId: string) =>
    request<{ note_id: string; related: Related[] }>(
      "GET",
      `/notes/${noteId}/related`,
    ),

  lists: () => request<{ lists: WordList[] }>("GET", "/lists"),
  list: (id: string) => request<WordListWords>("GET", `/lists/${id}`),
  createList: (body: {
    name: string;
    note?: string | null;
    focus_until?: string | null;
  }) => request<WordList>("POST", "/lists", body),
  /**
   * A field left out is left alone; a field sent as null is cleared, which is how
   * a focus is ended rather than merely forgotten.
   */
  patchList: (
    id: string,
    body: { name?: string; note?: string | null; focus_until?: string | null },
  ) => request<WordList>("PATCH", `/lists/${id}`, body),
  deleteList: (id: string) => request<void>("DELETE", `/lists/${id}`),
  /** Words by id, or a whole lesson, or one heading of one. */
  addToList: (
    id: string,
    body: { note_ids?: string[]; file_id?: string; group?: string },
  ) => request<WordListWords>("POST", `/lists/${id}/notes`, body),
  removeFromList: (id: string, noteId: string) =>
    request<WordList>("DELETE", `/lists/${id}/notes/${noteId}`),

  /** What is wrong with the collection as practice would meet it (read-only). */
  audit: (categoryId?: string) =>
    request<Audit>("GET", `/collection/audit${q({ category_id: categoryId })}`),

  settings: () => request<Settings>("GET", "/settings"),
  saveSettings: (body: { scheduler?: string }) =>
    request<Settings>("PUT", "/settings", body),
};
