import { useRef, useEffect, useCallback } from "react";
import type { SongData, StageBackground } from "../types";
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
}

export function Stage({ songData, song, render = false, hasAudio, background }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const { syncState, clockRef } = useSyncEngine(songData, audioRef);
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
          segments={songData.segments}
          syncState={syncState}
          audioRef={audioRef}
          clockRef={clockRef}
        />
        <VocabCards segment={songData.segments[syncState.displayIndex] ?? null} />
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
