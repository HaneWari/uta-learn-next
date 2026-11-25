import { useEffect, useState } from "react";
import { api } from "../api";

interface ExportFile {
  file: string;
  size: number;
  created: number;
  url: string;
}

function sizeLabel(bytes: number) {
  if (bytes > 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
}

function when(sec: number) {
  const d = new Date(sec * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Exported files, newest first. Served straight from the export folder, so a
 * video rendered in a previous session is still here — the old UI only ever
 * showed the toast from the run that had just finished.
 */
export function ExportList({ onClose }: { onClose: () => void }) {
  const [files, setFiles] = useState<ExportFile[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      setFiles(await api.exports());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="bgmask" role="dialog" aria-modal="true" aria-label="导出记录">
      <div className="bgmodal exportlist">
        <header className="bghead">
          <h2>导出记录</h2>
          <button className="bgclose" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="book-tools">
          <button className="btn" type="button" onClick={() => void api.revealExport()}>
            打开导出文件夹
          </button>
          <button className="btn" type="button" onClick={() => void load()}>
            刷新
          </button>
        </div>

        {err && <p className="setnote">{err}</p>}
        {loading && <p className="sethint">载入中…</p>}
        {!loading && !files.length && (
          <p className="sethint">还没有导出过视频。播放页点「导出视频」即可。</p>
        )}

        <div className="exportrows">
          {files.map((f) => (
            <div className="exportrow" key={f.file}>
              <span className="exportrow-name" title={f.file}>
                {f.file}
              </span>
              <span className="exportrow-meta">
                {sizeLabel(f.size)} · {when(f.created)}
              </span>
              <div className="exportrow-actions">
                <button
                  className="btn"
                  type="button"
                  onClick={() => void api.revealExport(f.file)}
                >
                  打开位置
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={async () => {
                    try {
                      await api.deleteExport(f.file);
                      setFiles((prev) => prev.filter((x) => x.file !== f.file));
                    } catch (e) {
                      setErr(e instanceof Error ? e.message : String(e));
                    }
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
