import { useEffect, useRef, useState } from "react";
import { useCallback } from "react";
import type { Segment, SongData } from "../types";
import { api } from "../api";
import { clearFailure, enqueue, reportFailure } from "../lib/saveQueue";

/**
 * Load one dataset by name; `null` clears it.
 *
 * The fetched payload is keyed by the song it belongs to, so switching songs
 * never shows the previous dataset while the new request is in flight, and the
 * hook never has to "reset" state from inside an effect (which would cascade a
 * second render on every navigation).
 */
export function useSongData(song: string | null) {
  const [result, setResult] = useState<{
    song: string;
    data?: SongData;
    error?: string;
  } | null>(null);
  // the retry callbacks have to call the *current* function without capturing
  // themselves in their own dependency array (which the hooks lint rejects as
  // "accessed before declared"); a ref is the standard escape hatch
  const patchRef = useRef<(id: number, body: Partial<Segment>) => void>(() => {});
  const timeOffsetRef = useRef<(v: number, p: boolean) => void>(() => {});
  const transHiddenRef = useRef<(h: boolean, p: boolean) => void>(() => {});

  useEffect(() => {
    if (!song) return;
    let alive = true;

    fetch(`/api/songs/${encodeURIComponent(song)}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (alive) setResult({ song, data });
      })
      .catch((err) => {
        if (alive) setResult({ song, error: err.message });
      });

    return () => {
      alive = false;
    };
  }, [song]);

  const current = result && result.song === song ? result : null;
  const songData = current?.data ?? null;
  const error = current?.error ?? null;
  const loading = !!song && !current;

  const updateData = useCallback(
    (fn: (prev: SongData) => SongData) => {
      if (!song) return;
      setResult((prev) =>
        prev && prev.song === song && prev.data
          ? { ...prev, data: fn(prev.data) }
          : prev,
      );
    },
    [song],
  );

  /**
   * Persist card edits for one segment; applies optimistically.
   *
   * A failure rolls the segment back to the last server copy and surfaces a
   * retry, instead of leaving the UI showing an edit that never reached disk —
   * which used to look saved until the next reload.
   */
  const patch = useCallback(
    (segId: number, body: Partial<Segment>): Segment | undefined => {
      if (!song) return;
      const before = current?.data?.segments.find((s) => s.id === segId);
      let updated: Segment | undefined;
      updateData((prev) => ({
        ...prev,
        segments: prev.segments.map((s) =>
          s.id === segId ? ((updated = { ...s, ...body }), updated) : s,
        ),
      }));
      enqueue(`${song}:patch`, () => api.patchSong(song, { id: segId, ...body }))
        .then((server) => {
          // The server can *enrich* a patch — a lyric edit re-tokenises the
          // text into `lyric_override.words`/`grammar` — so the authoritative
          // segment replaces the optimistic one, not the other way round.
          clearFailure();
          updateData((prev) => ({
            ...prev,
            segments: prev.segments.map((s) =>
              s.id === segId ? ({ ...s, ...server } as Segment) : s,
            ),
          }));
        })
        .catch((err: unknown) => {
          // roll back to what the server still has, then offer a retry
          if (before) {
            updateData((prev) => ({
              ...prev,
              segments: prev.segments.map((s) =>
                s.id === segId ? before : s,
              ),
            }));
          }
          reportFailure(
            err instanceof Error ? err.message : String(err),
            () => patchRef.current(segId, body),
          );
        });
      return updated;
    },
    [song, updateData, current],
  );

  /** Apply a time offset to the stage at once; `persist` also saves it. */
  const setTimeOffset = useCallback(
    (value: number, persist: boolean): Promise<void> => {
      const before = current?.data?.meta.time_offset ?? 0;
      updateData((prev) => ({ ...prev, meta: { ...prev.meta, time_offset: value } }));
      if (!persist || !song) return Promise.resolve();
      return enqueue(`${song}:meta`, () => api.setTimeOffset(song, value))
        .then(() => {
          clearFailure();
        })
        .catch((err: unknown) => {
          updateData((prev) => ({
            ...prev,
            meta: { ...prev.meta, time_offset: before },
          }));
          reportFailure(
            err instanceof Error ? err.message : String(err),
            () => timeOffsetRef.current(value, true),
          );
        });
    },
    [song, updateData, current],
  );

  /** Toggle the song-wide translation visibility; `persist` saves it to meta. */
  const setTransHidden = useCallback(
    (hidden: boolean, persist: boolean): Promise<void> => {
      const before = !!current?.data?.meta.trans_hidden;
      updateData((prev) => ({
        ...prev,
        meta: { ...prev.meta, trans_hidden: hidden || undefined },
      }));
      if (!persist || !song) return Promise.resolve();
      return enqueue(`${song}:meta`, () => api.setTransHidden(song, hidden))
        .then(() => {
          clearFailure();
        })
        .catch((err: unknown) => {
          updateData((prev) => ({
            ...prev,
            meta: { ...prev.meta, trans_hidden: before || undefined },
          }));
          reportFailure(
            err instanceof Error ? err.message : String(err),
            () => transHiddenRef.current(hidden, true),
          );
        });
    },
    [song, updateData, current],
  );

  useEffect(() => {
    patchRef.current = patch;
    timeOffsetRef.current = setTimeOffset;
    transHiddenRef.current = setTransHidden;
  }, [patch, setTimeOffset, setTransHidden]);

  return { songData, error, loading, patch, setTimeOffset, setTransHidden };
}
