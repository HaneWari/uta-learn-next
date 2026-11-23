import { useRef, useEffect, useCallback, useState } from "react";
import type { Segment, SongData, StageBackground } from "../types";
import { useSyncEngine } from "../hooks/useSyncEngine";
import { Player } from "./Player";
import { LyricsDisplay } from "./LyricsDisplay";
import { VocabCards } from "./VocabCards";

const SEEK_STEP = 5;

interface Props {
  songData: SongData;
  song: string;
  /** video export: no chrome, no interaction affordances */
  render?: boolean;
  /** whether this dataset actually has an audio file */
  hasAudio?: boolean;
  /** paper theme, or the user's own image behind the stage */
  background?: StageBackground;
  /** persist card edits (disabled in render mode) */
  onPatchSegment?: (
    segId: number,
    body: Partial<Segment>,
  ) => Segment | undefined;
  /** persist the translation visibility flag (disabled in render mode) */
  onPatchTrans?: (hidden: boolean) => void;
}

export function Stage({ songData, song, render = false, hasAudio, background, onPatchSegment, onPatchTrans }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  // song-wide card visibility, remembered per dataset so a listener who only
  // wants the lyrics can switch the vocab row off (and the export matches)
  const [cardsHidden, setCardsHidden] = useState(
    () => {
      // the video-export page carries the flag in its URL because the headless
      // recorder runs a fresh browser profile with no localStorage of ours
      const q = new URLSearchParams(window.location.search).get("hidecards");
      if (q !== null) return q === "1";
      return localStorage.getItem(`hideCards:${song}`) === "1";
    },
  );
  const toggleCards = useCallback(() => {
    setCardsHidden((h) => {
      const next = !h;
      localStorage.setItem(`hideCards:${song}`, next ? "1" : "0");
      return next;
    });
  }, [song]);

  /* same idea for the translation: a dataset meta flag the export also
     reads, so the video shows exactly the gloss state the listener left */
  const [transHidden, setTransHidden] = useState(() => {
    const q = new URLSearchParams(window.location.search).get("hidetrans");
    if (q !== null) return q === "1";
    return !!songData.meta.trans_hidden;
  });
  // the dataset is the source of truth once it loads — a stale local guess
  // shouldn't stick around
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("hidetrans");
    if (q === null) setTransHidden(!!songData.meta.trans_hidden);
  }, [songData.meta.trans_hidden]);
  const toggleTrans = useCallback(() => {
    setTransHidden((h) => {
      const next = !h;
      onPatchTrans?.(next);
      return next;
    });
  }, []);
  // hidden lines are left in the dataset but skipped everywhere the timeline
  // is consumed — the sync engine, the lyric display and the vocab row all
  // see the same filtered segment list, so a removed line just never plays.
  const visibleSegments = songData.segments.filter((s) => !s.hidden);
  const visibleData: SongData = { ...songData, segments: visibleSegments };
  const { syncState, clockRef } = useSyncEngine(visibleData, audioRef);
  const audioSrc = `/api/audio/${encodeURIComponent(song)}`;
  const custom = background?.mode === "custom" && !!background.url;
  // The dataset's own flag wins; otherwise use the list endpoint's answer, and
  // only fall back to the timeline length for datasets built before the flag
  // existed. duration_seconds alone proves nothing about an audio file.
  const withAudio =
    hasAudio ?? songData.meta.has_audio ?? songData.meta.duration_seconds > 0;

  const handleKey = useCallback((e: KeyboardEvent) => {
    const audio = audioRef.current;
    if (!audio) return;
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;

    switch (e.code) {
      case "Space":
        e.preventDefault();
        if (audio.paused) audio.play();
        else audio.pause();
        break;
      case "ArrowLeft":
        e.preventDefault();
        audio.currentTime = Math.max(0, audio.currentTime - SEEK_STEP);
        break;
      case "ArrowRight":
        e.preventDefault();
        audio.currentTime = Math.min(
          audio.duration || 0,
          audio.currentTime + SEEK_STEP,
        );
        break;
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <div
      className={`app${render ? " render-mode" : ""}${syncState.outro ? " outro" : ""}`}
      data-bg={custom ? "custom" : "default"}
    >
      {custom && (
        <div
          className="bg-photo"
          style={{ backgroundImage: `url("${background.url}")` }}
          aria-hidden
        />
      )}
      <div className="grain" />

      <div className="stage-title">
        <span className="stage-title-main">{songData.meta.title}</span>
        {songData.meta.artist && (
          <span className="stage-title-artist">{songData.meta.artist}</span>
        )}
      </div>

      <Player
        audioRef={audioRef}
        audioSrc={audioSrc}
        hasAudio={withAudio}
      />

      <main className="main">
        <LyricsDisplay
          segments={visibleSegments}
          syncState={syncState}
          audioRef={audioRef}
          clockRef={clockRef}
          offset={songData.meta.time_offset ?? 0}
          transHidden={transHidden}
          onPatch={render ? undefined : onPatchSegment}
        />
        {/* the export recorder must never carry the collapsed bar, so the
            whole row is unmounted in render mode when cards are hidden */}
        {!(render && cardsHidden) && (
          <VocabCards
            segment={visibleSegments[syncState.displayIndex] ?? null}
            hidden={cardsHidden}
            onToggleHidden={toggleCards}
            transHidden={transHidden}
            onToggleTrans={render ? undefined : toggleTrans}
            onPatch={
              render || !onPatchSegment
                ? undefined
                : (patch) =>
                    onPatchSegment(
                      visibleSegments[syncState.displayIndex].id,
                      patch,
                    )
            }
          />
        )}
      </main>

      <div className="curtain" aria-hidden={!syncState.outro}>
        <span className="curtain-mark">唄</span>
        <span className="curtain-title">{songData.meta.title}</span>
        <span className="curtain-sub">{songData.meta.artist}</span>
        <span className="curtain-tail">UTA LEARN NEXT</span>
      </div>
    </div>
  );
}
