/**
 * Serialised, retryable dataset saves.
 *
 * Two things used to go wrong here: edits fired off in parallel (so two
 * in-flight PATCHes could overwrite each other on disk), and a failed save was
 * swallowed — the UI kept showing the optimistic value while the file still
 * held the old one, and a refresh silently lost the edit.
 *
 * This queue keeps one request in flight per song, remembers the last good
 * server state so a failure can roll the UI back, and offers a retry.
 */

const chains = new Map<string, Promise<unknown>>();

/** Run `task` after every earlier task for `key` has settled. */
export function enqueue<T>(key: string, task: () => Promise<T>): Promise<T> {
  const previous = chains.get(key) ?? Promise.resolve();
  const next = previous.then(task, task);
  // keep the chain alive after a rejection, but don't leak the rejection
  chains.set(
    key,
    next.catch(() => undefined),
  );
  return next;
}

export interface SaveFailure {
  message: string;
  retry: () => void;
}

let failureListener: ((f: SaveFailure | null) => void) | null = null;

/** One place for the app to show "保存失败 · 重试" — the stage never has to. */
export function onSaveFailure(fn: ((f: SaveFailure | null) => void) | null) {
  failureListener = fn;
}

export function reportFailure(message: string, retry: () => void) {
  failureListener?.({ message, retry });
}

export function clearFailure() {
  failureListener?.(null);
}

/* ---------- undo ---------- */

/**
 * A bounded undo stack, one entry per successful edit.
 *
 * The old shortcut only dispatched a `uta:undo` event that nobody listened to,
 * so Ctrl+Z looked supported and did nothing. Both the card row and the lyric
 * editor push a snapshot here before writing, and the stage pops the newest
 * one and replays it through the same PATCH route.
 */
export interface UndoEntry {
  song: string;
  label: string;
  /** the segment fields to restore, exactly as they were before the edit */
  restore: Record<string, unknown>;
  segmentId: number;
}

const HISTORY_LIMIT = 20;
const history: UndoEntry[] = [];

export function pushUndo(entry: UndoEntry) {
  history.push(entry);
  if (history.length > HISTORY_LIMIT) history.shift();
}

/** Pop the newest entry that belongs to `song` (or the newest overall). */
export function popUndo(song?: string): UndoEntry | null {
  for (let i = history.length - 1; i >= 0; i -= 1) {
    if (!song || history[i].song === song) {
      const [entry] = history.splice(i, 1);
      return entry;
    }
  }
  return null;
}

export function undoDepth(song?: string): number {
  return song ? history.filter((e) => e.song === song).length : history.length;
}

export function clearUndo() {
  history.length = 0;
}
