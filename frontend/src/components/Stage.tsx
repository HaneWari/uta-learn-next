import { useRef, useEffect, useCallback, useState } from "react";
import type { Segment, SongData, StageBackground } from "../types";
import { useSyncEngine } from "../hooks/useSyncEngine";
import { usePlayback } from "../hooks/usePlayback";
import { resolveShortcut } from "../lib/shortcuts";
import type { ShortcutAction } from "../lib/shortcuts";
import { ShortcutHelp } from "./ShortcutHelp";
import { WordPopover } from "./WordPopover";
import type { WordHit } from "./WordPopover";
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
  /** persist any other display layer (disabled in render mode) */
  onPatchView?: (view: Record<string, boolean>) => void;
}

export function Stage({ songData, song, render = false, hasAudio, background, onPatchSegment, onPatchTrans, onPatchView }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  /* Song-wide view state. It lives in `meta.view` on the server rather than in
     localStorage: a second browser, the pywebview window, or a copied dataset
     would otherwise disagree, and the export would silently use another
     layer set than the stage. The export page still accepts URL overrides
     because its recorder profile has no access to the dataset's own state. */
  const view = songData.meta.view ?? {};
  const [viewChoice, setViewChoice] = useState<Record<string, boolean>>({});
  const url = new URLSearchParams(window.location.search);
  const urlFlag = (name: string) => {
    const q = url.get(name);
    return q === null ? undefined : q === "1";
  };
  const layerHidden = (key: string, urlName: string): boolean => {
    // priority: this session's click → URL (recorder) → dataset → visible
    if (key in viewChoice) return viewChoice[key];
    const fromUrl = urlFlag(urlName);
    if (fromUrl !== undefined) return fromUrl;
    return view[key] === false;
  };

  const cardsHidden = layerHidden("cards", "hidecards");
  const transHidden =
    layerHidden("translation", "hidetrans") || !!songData.meta.trans_hidden;

  // the refs keep the handlers stable while still reading the current
  // visibility — otherwise the keyboard listener is rebuilt every render.
  // Assigning inside an effect (not during render) keeps the hooks lint happy.
  const cardsHiddenRef = useRef(cardsHidden);
  const transHiddenRef = useRef(transHidden);
  useEffect(() => {
    cardsHiddenRef.current = cardsHidden;
    transHiddenRef.current = transHidden;
  }, [cardsHidden, transHidden]);

  const toggleCards = useCallback(() => {
    const next = !cardsHiddenRef.current;
    setViewChoice((prev) => ({ ...prev, cards: next }));
    onPatchView?.({ cards: !next });
  }, [onPatchView]);

  const toggleTrans = useCallback(() => {
    const next = !transHiddenRef.current;
    setViewChoice((prev) => ({ ...prev, translation: next }));
    onPatchTrans?.(next);
  }, [onPatchTrans]);
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

  const playback = usePlayback(audioRef, visibleSegments);
  const [helpOpen, setHelpOpen] = useState(false);
  const [wordHit, setWordHit] = useState<WordHit | null>(null);

  const handleAction = useCallback(
    (action: ShortcutAction) => {
      const audio = audioRef.current;
      const at = visibleSegments[syncState.displayIndex];
      switch (action) {
        case "toggle-play":
          if (!audio) return;
          if (audio.paused) void audio.play();
          else audio.pause();
          return;
        case "seek-back":
          if (audio) audio.currentTime = Math.max(0, audio.currentTime - SEEK_STEP);
          return;
        case "seek-forward":
          if (audio) {
            audio.currentTime = Math.min(
              audio.duration || 0,
              audio.currentTime + SEEK_STEP,
            );
          }
          return;
        case "prev-line":
        case "next-line": {
          if (!audio) return;
          const dir = action === "prev-line" ? -1 : 1;
          const index = Math.min(
            visibleSegments.length - 1,
            Math.max(0, syncState.displayIndex + dir),
          );
          audio.currentTime = visibleSegments[index]?.start ?? 0;
          return;
        }
        case "rate-down":
          playback.stepRate(-1);
          return;
        case "rate-up":
          playback.stepRate(1);
          return;
        case "loop-line":
          playback.toggleLoop(at ?? null);
          return;
        case "shadow":
          playback.toggleShadow();
          return;
        case "toggle-trans":
          toggleTrans();
          return;
        case "toggle-cards":
          toggleCards();
          return;
        case "help":
          setHelpOpen(true);
          return;
        case "close":
          setHelpOpen(false);
          return;
        case "undo":
          window.dispatchEvent(new CustomEvent("uta:undo"));
          return;
      }
    },
    [audioRef, playback, syncState.displayIndex, toggleCards, toggleTrans, visibleSegments],
  );

  useEffect(() => {
    if (render) return;
    const onKey = (e: KeyboardEvent) => {
      const action = resolveShortcut(e);
      if (!action) return;
      // Space would otherwise scroll, arrows would scroll, "?" types nothing
      if (action !== "undo") e.preventDefault();
      handleAction(action);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleAction, render]);

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
        rate={playback.rate}
        onRate={playback.setRate}
        looping={!!playback.loopSegment}
        shadow={playback.shadow}
        onToggleLoop={() => playback.toggleLoop(visibleSegments[syncState.displayIndex] ?? null)}
        onToggleShadow={playback.toggleShadow}
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
          onWordClick={render ? undefined : setWordHit}
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

      {helpOpen && <ShortcutHelp onClose={() => setHelpOpen(false)} />}
      {wordHit && (
        <WordPopover
          hit={wordHit}
          song={song}
          songTitle={songData.meta.title}
          onClose={() => setWordHit(null)}
          onSeek={() => {
            const a = audioRef.current;
            if (a) {
              a.currentTime = Math.max(0, wordHit.segment.start - 0.05);
              void a.play();
            }
            setWordHit(null);
          }}
        />
      )}
    </div>
  );
}
