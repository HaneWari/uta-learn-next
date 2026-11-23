import { useState, useEffect } from "react";
import { useCallback } from "react";
import type { Segment, SongData } from "../types";
import { api } from "../api";

/** Load one dataset by name; `null` clears it. */
export function useSongData(song: string | null) {
  const [songData, setSongData] = useState<SongData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!song) {
      setSongData(null);
      setError(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    setSongData(null);

    fetch(`/api/songs/${encodeURIComponent(song)}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (alive) setSongData(data);
      })
      .catch((err) => {
        if (alive) setError(err.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [song]);

  /** Persist card edits for one segment; applies optimistically. */
  const patch = useCallback(
    (segId: number, body: Partial<Segment>): Segment | undefined => {
      if (!song) return;
      let updated: Segment | undefined;
      setSongData((prev) => {
        if (!prev) return prev;
        const next = {
          ...prev,
          segments: prev.segments.map((s) =>
            s.id === segId ? ((updated = { ...s, ...body }), updated) : s,
          ),
        };
        return next;
      });
      api
        .patchSong(song, { id: segId, ...body })
        .then((server) => {
          // The server can *enrich* a patch — a lyric edit re-tokenises the
          // text into `lyric_override.words`/`grammar` — so the authoritative
          // segment replaces the optimistic one, not the other way round.
          setSongData((prev) =>
            prev
              ? {
                  ...prev,
                  segments: prev.segments.map((s) =>
                    s.id === segId ? ({ ...s, ...server } as Segment) : s,
                  ),
                }
              : prev,
          );
        })
        .catch(() => {
          /* keep the optimistic state; next full reload re-reads the file */
        });
      return updated;
    },
    [song],
  );

  return { songData, error, loading, patch };
}
