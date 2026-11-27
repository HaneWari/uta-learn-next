import { useRef, useEffect, useMemo, useState } from "react";
import type { Segment, SongData, StageBackground } from "../types";
import { useSyncEngine } from "../hooks/useSyncEngine";
import { usePlayback } from "../hooks/usePlayback";
import { resolveShortcut } from "../lib/shortcuts";
import type { ShortcutAction } from "../lib/shortcuts";
import { popUndo } from "../lib/saveQueue";
import { ShortcutHelp } from "./ShortcutHelp";
import { WordPopover } from "./WordPopover";
import type { WordHit } from "./WordPopover";
import { LyricsRail } from "./LyricsRail";
import { useViewStore } from "../store/viewStore";
import type { LayerKey } from "../store/viewStore";
import { Player } from "./Player";
import { LyricsDisplay } from "./LyricsDisplay";
import { VocabCards } from "./VocabCards";
import { KaraokeStage } from "./KaraokeStage";
import { useSettings } from "../lib/settings";

const SEEK_STEP = 3;

/** URL flag names the export recorder uses for each layer. */
const LAYER_URL: Record<"furigana" | "romaji" | "next_line", string> = {
  furigana: "hidefurigana",
  romaji: "hideromaji",
  next_line: "hidenext",
};

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
  /** called after Ctrl+Z restores something, so the shell can toast it */
  onUndo?: (label: string) => void;
  /** 5.3.3 逐行微调: move the current line ±0.1 s */
  onNudgeLine?: (segmentId: number, delta: number) => void;
  /** 5.3.3 单行重新对齐 */
  onRealignLine?: (segmentId: number) => void;
  /** whether the whisper pack is installed (greys the realign button) */
  canRealign?: boolean;
}

export function Stage({ songData, song, render = false, hasAudio, background, onPatchSegment, onPatchTrans, onPatchView, onUndo, onNudgeLine, onRealignLine, canRealign }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  /* Song-wide view state. It lives in `meta.view` on the server rather than in
     localStorage: a second browser, the pywebview window, or a copied dataset
     would otherwise disagree, and the export would silently use another
     layer set than the stage. The export page still accepts URL overrides
     because its recorder profile has no access to the dataset's own state. */
  const view = songData.meta.view ?? {};
  const url = new URLSearchParams(window.location.search);
  const urlFlag = (name: string) => {
    const q = url.get(name);
    return q === null ? undefined : q === "1";
  };
  // the session state lives in the store now (§5.7); the priority order is
  // unchanged: this session's click → URL (recorder) → dataset → visible
  const storeHidden = useViewStore((s) => s.hidden);
  const toggleLayer = useViewStore((s) => s.toggle);
  const resetForSong = useViewStore((s) => s.resetForSong);
  useEffect(() => {
    resetForSong(song);
  }, [song, resetForSong]);

  const layerHidden = (key: LayerKey, urlName: string): boolean => {
    const fromUrl = urlFlag(urlName);
    if (fromUrl !== undefined) return fromUrl;
    return storeHidden(song, key, view[key] === false);
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

  // plain functions: they read the refs above, so the keyboard listener stays
  // stable without the memoisation the compiler could not preserve
const toggleCards = () => {
  const next = toggleLayer(song, "cards", cardsHiddenRef.current);
  onPatchView?.({ cards: !next });
};

const toggleTrans = () => {
  const next = toggleLayer(song, "translation", transHiddenRef.current);
  onPatchTrans?.(next);
};
  // hidden lines are left in the dataset but skipped everywhere the timeline
  // is consumed — the sync engine, the lyric display and the vocab row all
  // see the same filtered segment list, so a removed line just never plays.
  /* The sync engine keys its clock on `songData`. A fresh object on every
     render re-ran its effect and reset the virtual clock to 0, which made
     `?render=1` screenshot the first line for every frame of an export.
     Both values come straight from the dataset, so memoising on it is exact. */
  const visibleSegments = useMemo(
    () => songData.segments.filter((s) => !s.hidden),
    [songData],
  );
  const visibleData: SongData = useMemo(
    () => ({ ...songData, segments: visibleSegments }),
    [songData, visibleSegments],
  );
  // the export page hands time over to the renderer frame by frame
  const { syncState, clockRef } = useSyncEngine(visibleData, audioRef, render);
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
  const [settings] = useSettings();
  const karaoke = settings.play_style === "karaoke";
  const [karaokeMenu, setKaraokeMenu] = useState<
    { x: number; y: number } | null
  >(null);
  // 右键菜单要在“点空白处”自动收回,和词条卡片的菜单保持同一交互
  useEffect(() => {
    if (!karaokeMenu) return;
    const close = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest(".ctx-menu")) return;
      setKaraokeMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setKaraokeMenu(null);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [karaokeMenu]);
  // the whole-song rail is off by default (the stage stays clean), and the
  // store lets the shortcut and the rail button agree
  const railOpen = useViewStore((s) => s.railOpen);
  const setRailOpen = useViewStore((s) => s.setRail);

  // A plain function, refreshed every render through a ref: the keyboard
  // listener then reads the *current* closure without being rebuilt, and the
  // compiler keeps its ability to optimise the component.
  const handleAction = (action: ShortcutAction) => {
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
        case "undo": {
          // replay the newest snapshot through the same PATCH route the edit
          // went through, so undo can never take a side channel
          const entry = popUndo(song);
          if (!entry || !onPatchSegment) return;
          onPatchSegment(entry.segmentId, entry.restore as Partial<Segment>);
          onUndo?.(entry.label);
          return;
        }
      }
  };

  const actionRef = useRef(handleAction);
  useEffect(() => {
    actionRef.current = handleAction;
  });

  useEffect(() => {
    if (render) return;
    const onKey = (e: KeyboardEvent) => {
      const action = resolveShortcut(e);
      if (!action) return;
      // Space would otherwise scroll, arrows would scroll, "?" types nothing
      if (action !== "undo") e.preventDefault();
      actionRef.current(action);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [render]);

  return (
    <div
      className={`app${render ? " render-mode" : ""}${karaoke ? " karaoke-style" : ""}${syncState.outro ? " outro" : ""}`}
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

      {/* 卡拉OK样式在导出时连底部播放控制栏一起消失 */}
      {!(karaoke && render) && (
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
          abLoop={playback.abLoop}
          onAbLoop={playback.setAbLoop}
        />
      )}

      <main className="main">
        {karaoke ? (
          <KaraokeStage
            segments={visibleSegments}
            syncState={syncState}
            audioRef={audioRef}
            clockRef={clockRef}
            offset={songData.meta.time_offset ?? 0}
            color={settings.karaoke_color}
            showFurigana={!layerHidden("furigana", "hidefurigana")}
            showRomaji={!layerHidden("romaji", "hideromaji")}
            showTranslation={!transHidden}
            song={song}
            onPatch={render ? undefined : onPatchSegment}
            onNudgeLine={render ? undefined : onNudgeLine}
            onRealignLine={render ? undefined : onRealignLine}
            canRealign={canRealign ?? false}
            onWordClick={render ? undefined : setWordHit}
            onContextMenu={
              render
                ? undefined
                : (e) => {
                    // 编辑歌词时保留输入框自己的右键菜单(复制/粘贴)
                    if ((e.target as HTMLElement).closest(".lyr-edit")) return;
                    e.preventDefault();
                    setKaraokeMenu({ x: e.clientX, y: e.clientY });
                  }
            }
          />
        ) : (
        <LyricsDisplay
          segments={visibleSegments}
          syncState={syncState}
          audioRef={audioRef}
          clockRef={clockRef}
          offset={songData.meta.time_offset ?? 0}
          transHidden={transHidden}
          onPatch={render ? undefined : onPatchSegment}
          onWordClick={render ? undefined : setWordHit}
          song={song}
          layers={{
            showFurigana: !layerHidden("furigana", "hidefurigana"),
            showRomaji: !layerHidden("romaji", "hideromaji"),
            showNext: !layerHidden("next_line", "hidenext"),
          }}
          onNudgeLine={render ? undefined : onNudgeLine}
          onRealign={render ? undefined : onRealignLine}
          canRealign={canRealign ?? false}
          onSeekLine={
            render
              ? undefined
              : (seg) => {
                  const a = audioRef.current;
                  if (!a) return;
                  a.currentTime = Math.max(0, seg.start - 0.05);
                  void a.play();
                }
          }
        />
        )}
        {/* the export recorder must never carry the collapsed bar, so the
            whole row is unmounted in render mode when cards are hidden */}
        {!karaoke && !(render && cardsHidden) && (
          <VocabCards
            segment={visibleSegments[syncState.displayIndex] ?? null}
            song={song}
            hidden={cardsHidden}
            onToggleHidden={toggleCards}
            transHidden={transHidden}
            onToggleTrans={render ? undefined : toggleTrans}
            layers={{
              furigana: !layerHidden("furigana", "hidefurigana"),
              romaji: !layerHidden("romaji", "hideromaji"),
              next_line: !layerHidden("next_line", "hidenext"),
            }}
            onToggleLayer={
              render
                ? undefined
                : (key) => {
                    const next = layerHidden(key, LAYER_URL[key]);
                    toggleLayer(song, key as LayerKey, next);
                    onPatchView?.({ [key]: !next });
                  }
            }
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

      {!render && (
        <LyricsRail
          segments={visibleSegments}
          activeId={visibleSegments[syncState.displayIndex]?.id ?? null}
          open={railOpen}
          onOpen={() => setRailOpen(true)}
          onClose={() => setRailOpen(false)}
          onSeek={(seg) => {
            const a = audioRef.current;
            if (a) {
              a.currentTime = Math.max(0, seg.start - 0.05);
              void a.play();
            }
          }}
        />
      )}

      {karaokeMenu && !render && (
        <div
          className="ctx-menu"
          style={{ left: karaokeMenu.x, top: karaokeMenu.y }}
          role="menu"
        >
          <button
            className="ctx-item"
            onClick={() => {
              const next = !layerHidden("furigana", "hidefurigana");
              toggleLayer(song, "furigana", next);
              onPatchView?.({ furigana: !next });
              setKaraokeMenu(null);
            }}
          >
            {layerHidden("furigana", "hidefurigana") ? "显示注音" : "隐藏注音"}
          </button>
          <button
            className="ctx-item"
            onClick={() => {
              const next = !layerHidden("romaji", "hideromaji");
              toggleLayer(song, "romaji", next);
              onPatchView?.({ romaji: !next });
              setKaraokeMenu(null);
            }}
          >
            {layerHidden("romaji", "hideromaji") ? "显示罗马音" : "隐藏罗马音"}
          </button>
          <button
            className="ctx-item"
            onClick={() => {
              setKaraokeMenu(null);
              toggleTrans();
            }}
          >
            {transHidden ? "显示中文翻译" : "隐藏中文翻译"}
          </button>
        </div>
      )}

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
