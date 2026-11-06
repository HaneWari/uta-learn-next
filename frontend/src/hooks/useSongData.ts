import { useState, useEffect } from "react";
import type { SongData } from "../types";

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

  return { songData, error, loading };
}
