import { useCallback, useEffect, useMemo, useState } from "react";
import { api, waitForJob } from "./api";
import { useSongData } from "./hooks/useSongData";
import { useTheme } from "./lib/theme";
import { useSettings } from "./lib/settings";
import { onSaveFailure } from "./lib/saveQueue";
import type { SaveFailure } from "./lib/saveQueue";
import { BackgroundModal } from "./components/BackgroundModal";
import { ConfigPage } from "./components/ConfigPage";
import { ExportEnvModal } from "./components/ExportEnvModal";
import { OffsetModal } from "./components/OffsetModal";
import { SettingsModal } from "./components/SettingsModal";
import { VocabBook } from "./components/VocabBook";
import { ExportDialog } from "./components/ExportDialog";
import { ExportList } from "./components/ExportList";
import type { ExportChoice } from "./components/ExportDialog";
import { Stage } from "./components/Stage";
import type { SongSummary, StageBackground } from "./types";
import "./App.css";

type Tab = "config" | "stage";

const DEFAULT_BG: StageBackground = { mode: "default", url: null };

export default function App() {
  useTheme();
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const renderMode = params.get("render") === "1";
  const initialSong = params.get("song");

  const [tab, setTab] = useState<Tab>(initialSong ? "stage" : "config");
  const [song, setSong] = useState<string | null>(initialSong);
  const [songs, setSongs] = useState<SongSummary[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportPct, setExportPct] = useState(0);
  const [exportNote, setExportNote] = useState<string | null>(null);
  const [envOpen, setEnvOpen] = useState(false);
  const [envChecking, setEnvChecking] = useState(false);
  const [background, setBackground] = useState<StageBackground>(DEFAULT_BG);
  const [bgOpen, setBgOpen] = useState(false);
  const [offsetOpen, setOffsetOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings] = useSettings();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const [bookOpen, setBookOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportListOpen, setExportListOpen] = useState(false);
  /* 单行重新对齐 needs the whisper pack; the button says so when it is absent */
  const [whisperReady, setWhisperReady] = useState(false);
  const {
    songData,
    error,
    loading,
    patch: patchSegment,
    setTimeOffset,
    setTransHidden,
    patchView,
  } = useSongData(song);

  const refresh = useCallback(() => {
    api.songs().then(setSongs).catch(() => setSongs([]));
  }, []);

  // a failed dataset save must never look saved: the toast offers the retry
  useEffect(() => {
    onSaveFailure(setSaveFailure);
    return () => onSaveFailure(null);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // the background lives server-side so the export sees the same one
  useEffect(() => {
    api.background().then(setBackground).catch(() => setBackground(DEFAULT_BG));
  }, []);

  useEffect(() => {
    api
      .modelStatus()
      .then((s) => setWhisperReady(!!s.installed))
      .catch(() => setWhisperReady(false));
  }, []);

  // first visit: open the reference song, or whatever is available
  useEffect(() => {
    if (song || !songs.length) return;
    const prefer =
      songs.find((s) => s.name === "braveheart") ??
      songs.find((s) => s.has_audio) ??
      songs[0];
    setSong(prefer.name);
  }, [songs, song]);

  const play = useCallback((name: string) => {
    setSong(name);
    setTab("stage");
    const url = new URL(window.location.href);
    url.searchParams.set("song", name);
    window.history.replaceState(null, "", url.toString());
  }, []);

  /** Shared by the button and the env modal: start a background export. */
  const startExportJob = useCallback(
    async (choice: ExportChoice) => {
      if (!song) return;
      setExporting(true);
      setExportPct(0);
      try {
        // the recorder's fresh browser profile can't read our local view state,
        // so only the legacy hide-cards hint is sent; the server prefers
        // `meta.view` anyway
        const hideCards = localStorage.getItem(`hideCards:${song}`) === "1";
        const { job_id } = await api.startExport(song, hideCards, {
          preset: choice.preset,
          clipStart: choice.clipStart > 0 ? choice.clipStart : undefined,
          clipEnd: choice.clipEnd,
        });
        // the job runs server-side: closing this dialog does not stop it, and
        // the toast below reports the result whenever it lands
        const job = await waitForJob(
          job_id,
          (j) => setExportPct(Math.round(j.progress * 100)),
          1200,
        );
        if (job.status === "error") {
          setExportNote(job.error ?? "导出失败");
        } else if (job.status === "canceled") {
          setExportNote("已取消导出");
        } else {
          const result = job.result as { dir?: string; file?: string } | null;
          setExportNote(
            result?.dir
              ? `已导出至 ${result.dir}\n${result.file ?? ""}`
              : "导出完成",
          );
        }
      } catch (e) {
        setExportNote(e instanceof Error ? e.message : String(e));
      } finally {
        setExporting(false);
      }
    },
    [song],
  );

  const runExport = useCallback(async () => {
    if (!song || exporting) return;
    // Check the export environment first: a green probe falls straight through
    // to the export; anything wrong opens the env modal with a fix instead of
    // a bare failure toast. The button shows a brief "checking" state so the
    // click doesn't feel dead while the probe runs.
    setEnvChecking(true);
    setExportNote(null);
    try {
      const env = await api.exportEnv();
      if (!env.ok) {
        setEnvOpen(true);
        return;
      }
    } catch {
      // probe itself failed — still offer the modal so the user can retry/fix
      setEnvOpen(true);
      return;
    } finally {
      setEnvChecking(false);
    }
    // environment is fine: ask what to render rather than guessing
    setExportOpen(true);
  }, [song, exporting]);

  const handleDeleted = useCallback(
    (name: string) => {
      if (song !== name) return;
      // the dataset backing the stage is gone; fall back to the config tab
      setSong(null);
      setTab("config");
      const url = new URL(window.location.href);
      url.searchParams.delete("song");
      window.history.replaceState(null, "", url.toString());
    },
    [song],
  );

  // A dataset can disappear while its name is still in the URL: the user deleted
  // it, or generated the same song twice (the second one gets a "-2" suffix) and
  // removed the first. Rather than a dead "载入失败 HTTP 404" screen, fall back
  // to whatever is still available and say so.
  //
  // These hooks stay above the render-mode early return: the export page mounts
  // the same component with a different prop, and a conditional hook order would
  // crash when that prop flips.
  const [recovered, setRecovered] = useState<string | null>(null);
  useEffect(() => {
    if (!error || !songs.length) return;
    if (!/40[34]/.test(error)) return;
    const fallback = songs.find((s) => s.has_audio) ?? songs[0];
    if (!fallback || fallback.name === song) return;
    setRecovered(`「${song ?? ""}」已不存在，已切到「${fallback.title}」`);
    setSong(fallback.name);
    const url = new URL(window.location.href);
    url.searchParams.set("song", fallback.name);
    window.history.replaceState(null, "", url.toString());
  }, [error, songs, song]);

  useEffect(() => {
    if (!recovered) return;
    const t = setTimeout(() => setRecovered(null), 8000);
    return () => clearTimeout(t);
  }, [recovered]);

  /* ---- video export: bare stage, no chrome ---- */
  if (renderMode) {
    if (error) return <p className="status">载入失败：{error}</p>;
    if (!songData || !song) return <p className="status">正在载入…</p>;
    const meta = songs.find((x) => x.name === song);
    return (
      <Stage
        songData={songData}
        song={song}
        render
        hasAudio={meta?.has_audio}
        background={background}
      />
    );
  }

  const current = songs.find((s) => s.name === song);
  const timeOffset = songData?.meta.time_offset ?? 0;

  return (
    <div className="shell">
      <nav className="tabbar">
        <span className="tabbar-brand">
          <span className="brand-mark">唄</span>
          <span className="brand-word">UTA LEARN NEXT</span>
        </span>

        <div className="tabs">
          <button
            className={`tab${tab === "config" ? " on" : ""}`}
            onClick={() => setTab("config")}
          >
            配置
          </button>
          <button
            className={`tab${tab === "stage" ? " on" : ""}`}
            onClick={() => setTab("stage")}
            disabled={!song}
          >
            播放
          </button>
        </div>

        {/* the gear shows on both tabs — settings are not stage-only */}
        <button
          className="exportbtn bgbtn gearbtn"
          onClick={() => setSettingsOpen(true)}
          title="设置"
          aria-label="设置"
        >
          ⚙
        </button>

        {/* stage-only controls: meaningless (and confusing) on the config tab,
            so they only exist once a song is actually loaded for playback */}
        {tab === "stage" && (
          <>
            <button
              className="exportbtn bgbtn"
              onClick={() => {
                // tuning is done by ear against the stage, so bring it up
                setTab("stage");
                setOffsetOpen(true);
              }}
              disabled={!songData}
              title="调整当前这首的高亮、切句与歌声之间的时间差"
            >
              {timeOffset
                ? `时间偏移 ${timeOffset > 0 ? "+" : ""}${timeOffset.toFixed(1)}s`
                : "时间偏移"}
            </button>

            <button
              className="exportbtn bgbtn"
              onClick={() => setBgOpen(true)}
              title="更换播放页的背景图"
            >
              设置背景
            </button>

            <button
              className="exportbtn bgbtn"
              onClick={() => setBookOpen(true)}
              title="查看已收藏的单词"
            >
              生词本
            </button>

            <button
              className="exportbtn bgbtn"
              onClick={() => setExportListOpen(true)}
              title="已导出的视频"
            >
              导出记录
            </button>

            <button
              className={`exportbtn${exporting || envChecking ? " busy" : ""}`}
              onClick={() => void runExport()}
              disabled={!song || exporting || envChecking}
              title="把当前这首渲染成 1920×1080 / 60fps 的 MP4"
            >
              {envChecking
                ? "检查环境…"
                : exporting
                  ? `导出中 ${exportPct}%`
                  : "导出视频"}
            </button>
          </>
        )}
      </nav>

      {envOpen && (
        <ExportEnvModal
          onClose={() => setEnvOpen(false)}
          onReady={() => {
            setEnvOpen(false);
            // environment just turned green — ask what to render. Bypass the
            // probe this time so a borderline check doesn't loop.
            setExportOpen(true);
          }}
        />
      )}

      {bgOpen && (
        <BackgroundModal
          current={background}
          onClose={() => setBgOpen(false)}
          onApplied={setBackground}
        />
      )}

      {offsetOpen && songData && (
        <OffsetModal
          current={timeOffset}
          songTitle={songData.meta.title || song || ""}
          onPreview={(v) => void setTimeOffset(v, false)}
          onSave={(v) => setTimeOffset(v, true)}
          onClose={() => setOffsetOpen(false)}
        />
      )}

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      {exportListOpen && (
        <ExportList onClose={() => setExportListOpen(false)} />
      )}
      {exportOpen && songData && (
        <ExportDialog
          // the export runs to the *audio* length, not the lyric timeline:
          // a trimmed intro or a different edit makes them differ by tens of
          // seconds, and the dialog must show what will actually be rendered
          duration={
            (current?.duration && current.duration > 0
              ? current.duration
              : songData.meta.duration_seconds) ||
            (songData.segments[songData.segments.length - 1]?.end ?? 0)
          }
          settings={settings}
          onClose={() => setExportOpen(false)}
          onStart={(choice) => {
            setExportOpen(false);
            void startExportJob(choice);
          }}
        />
      )}

      {bookOpen && (
        <VocabBook
          onClose={() => setBookOpen(false)}
          onPlaySong={(name, at) => {
            play(name);
            // let the stage mount before seeking into it
            window.setTimeout(() => {
              const audio = document.querySelector("audio");
              if (audio) {
                audio.currentTime = Math.max(0, at);
                void audio.play();
              }
            }, 350);
          }}
        />
      )}

      {recovered && (
        <div className="export-toast" role="status">
          <span>{recovered}</span>
          <button onClick={() => setRecovered(null)} aria-label="关闭">×</button>
        </div>
      )}

      {exportNote && (
        <div className="export-toast" role="status">
          <span>{exportNote}</span>
          <button onClick={() => setExportNote(null)} aria-label="关闭">
            ×
          </button>
        </div>
      )}

      {saveFailure && (
        <div className="export-toast error" role="alert">
          <span>保存失败:{saveFailure.message}</span>
          <button
            className="toast-retry"
            onClick={() => {
              saveFailure.retry();
              setSaveFailure(null);
            }}
          >
            重试
          </button>
          <button onClick={() => setSaveFailure(null)} aria-label="关闭">
            ×
          </button>
        </div>
      )}

      <div className="tab-body">
        {tab === "config" ? (
          <ConfigPage
            songs={songs}
            onRefresh={refresh}
            onPlay={play}
            onDeleted={handleDeleted}
          />
        ) : error && !songs.length ? (
          <p className="status">载入失败：{error}</p>
        ) : error ? (
          <p className="status">正在切换到可用曲目…</p>
        ) : loading || !songData || !song ? (
          <p className="status">正在载入…</p>
        ) : (
          <Stage
            songData={songData}
            song={song}
            hasAudio={current?.has_audio}
            background={background}
            onPatchSegment={patchSegment}
            onPatchTrans={(hidden) => void setTransHidden(hidden, true)}
            onPatchView={(view) => void patchView(view)}
            onUndo={(label) => setExportNote(`已撤销:${label}`)}
            onNudgeLine={(segmentId, delta) => {
              const seg = songData?.segments.find((s) => s.id === segmentId);
              if (!seg) return;
              const next = Math.max(
                -2,
                Math.min(2, Math.round(((seg.line_offset ?? 0) + delta) * 10) / 10),
              );
              void patchSegment(segmentId, { line_offset: next });
            }}
            onRealignLine={(segmentId) => {
              if (!song) return;
              void api
                .realignLine(song, segmentId)
                .then(() => setExportNote("正在重新对齐这一行…"))
                .catch((e: unknown) =>
                  setExportNote(e instanceof Error ? e.message : String(e)),
                );
            }}
            canRealign={whisperReady}
          />
        )}
      </div>
    </div>
  );
}
