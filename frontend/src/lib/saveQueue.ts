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
