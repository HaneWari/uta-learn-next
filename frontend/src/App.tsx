import { useCallback, useEffect, useMemo, useState } from "react";
import { api, waitForJob } from "./api";
import { useSongData } from "./hooks/useSongData";
import { BackgroundModal } from "./components/BackgroundModal";
import { ConfigPage } from "./components/ConfigPage";
import { Stage } from "./components/Stage";
import type { SongSummary, StageBackground } from "./types";
import "./App.css";

type Tab = "config" | "stage";

const DEFAULT_BG: StageBackground = { mode: "default", url: null };

export default function App() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const renderMode = params.get("render") === "1";
  const initialSong = params.get("song");

  const [tab, setTab] = useState<Tab>(initialSong ? "stage" : "config");
  const [song, setSong] = useState<string | null>(initialSong);
  const [songs, setSongs] = useState<SongSummary[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportPct, setExportPct] = useState(0);
  const [exportNote, setExportNote] = useState<string | null>(null);
  const [background, setBackground] = useState<StageBackground>(DEFAULT_BG);
  const [bgOpen, setBgOpen] = useState(false);
  const { songData, error, loading } = useSongData(song);

  const refresh = useCallback(() => {
    api.songs().then(setSongs).catch(() => setSongs([]));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // the background lives server-side so the export sees the same one
  useEffect(() => {
    api.background().then(setBackground).catch(() => setBackground(DEFAULT_BG));
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

  const runExport = useCallback(async () => {
    if (!song || exporting) return;
    setExporting(true);
    setExportPct(0);
    setExportNote(null);
    try {
      const { job_id } = await api.startExport(song);
      const job = await waitForJob(
        job_id,
        (j) => setExportPct(Math.round(j.progress * 100)),
        1200,
      );
      if (job.status === "error") {
        setExportNote(job.error ?? "导出失败");
      } else {
        const dir = (job.result as { dir?: string } | null)?.dir;
        const file = (job.result as { file?: string } | null)?.file;
        setExportNote(
          dir ? `已导出至 ${dir}\n${file ?? ""}` : "导出完成",
        );
      }
    } catch (e) {
      setExportNote(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
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
            展示
          </button>
        </div>

        <button
          className="exportbtn bgbtn"
          onClick={() => setBgOpen(true)}
          title="更换展示页的背景图"
        >
          设置背景
        </button>

        <button
          className={`exportbtn${exporting ? " busy" : ""}`}
          onClick={() => void runExport()}
          disabled={!song || exporting}
          title="把当前这首渲染成 1920×1080 / 60fps 的 MP4"
        >
          {exporting ? `导出中 ${exportPct}%` : "导出视频"}
        </button>
      </nav>

      {bgOpen && (
        <BackgroundModal
          current={background}
          onClose={() => setBgOpen(false)}
          onApplied={setBackground}
        />
      )}

      {exportNote && (
        <div className="export-toast" role="status">
          <span>{exportNote}</span>
          <button onClick={() => setExportNote(null)} aria-label="关闭">
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
        ) : error ? (
          <p className="status">载入失败：{error}</p>
        ) : loading || !songData || !song ? (
          <p className="status">正在载入…</p>
        ) : (
          <Stage
            songData={songData}
            song={song}
            hasAudio={current?.has_audio}
            background={background}
          />
        )}
      </div>
    </div>
  );
}
