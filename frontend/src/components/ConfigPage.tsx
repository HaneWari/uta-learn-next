import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, waitForJob } from "../api";
import type { Job, SearchHit, SongSummary, UploadInfo } from "../types";

interface Props {
  songs: SongSummary[];
  onRefresh: () => void;
  onPlay: (name: string) => void;
  onDeleted: (name: string) => void;
}

const SOURCE_LABEL: Record<string, string> = {
  qq: "QQ 音乐",
  kugou: "酷狗",
  lrclib: "Lrclib",
};

const SOURCE_NOTE: Record<string, string> = {
  qq: "逐字",
  kugou: "逐字",
  lrclib: "逐行",
};

type LyricMode = "search" | "custom";

function fmtDur(s: number) {
  if (!s) return "--:--";
  // round the whole length once, then split -- rounding the seconds remainder on
  // its own turns 59.7s into "1:60"
  const total = Math.round(s);
  const m = Math.floor(total / 60);
  const r = total % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

/**
 * Three steps, in the order a new song actually arrives: bring the audio, then
 * decide where the lyrics come from, then generate. The audio is required
 * because a dataset without it cannot be sung along to.
 */
export function ConfigPage({ songs, onRefresh, onPlay, onDeleted }: Props) {
  const [step, setStep] = useState(1);

  /* ---- step 1: audio ---- */
  const [upload, setUpload] = useState<UploadInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  /* ---- step 2: lyrics ---- */
  const [mode, setMode] = useState<LyricMode>("search");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [picked, setPicked] = useState<SearchHit | null>(null);
  const [lyrics, setLyrics] = useState("");

  /* ---- step 3: build ---- */
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  const doUpload = useCallback(async (file: File) => {
    setUploading(true);
    setNotice(null);
    try {
      const info = await api.upload(file);
      setUpload(info);
      setTitle((t) => t || file.name.replace(/\.[^.]+$/, ""));
      setStep(2);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }, []);

  const runSearch = useCallback(async () => {
    const q = query.trim();
    if (q.length < 2) {
      setSearchErr("请输入至少 2 个字符");
      return;
    }
    setSearching(true);
    setSearchErr(null);
    setHits([]);
    setPicked(null);
    try {
      const { results, errors } = await api.search(q);
      results.sort((a, b) => {
        const rank = (k: string) => (k === "char" ? 0 : 1);
        return rank(a.kind) - rank(b.kind) || a.duration - b.duration;
      });
      setHits(results);
      if (!results.length) setSearchErr("三个来源都没有找到，试试别的关键词");
      if (errors.length) {
        setSearchErr(
          `部分来源不可用：${errors
            .map((e) => SOURCE_LABEL[e.source] ?? e.source)
            .join("、")}`,
        );
      }
    } catch (e) {
      setSearchErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  }, [query]);

  const track = useCallback(
    async (start: () => Promise<{ job_id: string }>) => {
      setBusy(true);
      setNotice(null);
      setJob(null);
      try {
        const { job_id } = await start();
        const done = await waitForJob(job_id, setJob);
        if (done.status === "error") {
          setNotice(done.error ?? "生成失败");
        } else {
          onRefresh();
          const name = done.result?.name;
          setNotice(`已生成「${done.result?.title ?? name}」`);
          if (name) onPlay(name);
        }
      } catch (e) {
        setNotice(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [onRefresh, onPlay],
  );

  const buildFromSource = () => {
    if (!upload || !picked) return;
    void track(() =>
      api.buildFromSource(picked, {
        upload_id: upload.id,
        title: title || picked.title,
        artist: artist || picked.artist,
      }),
    );
  };

  const buildFromText = () => {
    if (!upload) return;
    if (lyrics.trim().split("\n").filter((l) => l.trim()).length < 2) {
      setNotice("请粘贴歌词，每行一句（至少 2 行）");
      return;
    }
    void track(() =>
      api.buildFromText({
        upload_id: upload.id,
        lyrics,
        title: title || upload.filename,
        artist,
      }),
    );
  };

  const doDelete = async (name: string) => {
    setConfirmDel(null);
    try {
      await api.remove(name);
      onDeleted(name);
      onRefresh();
      setNotice(`已删除「${name}」`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    }
  };

  const pct = job ? Math.round(job.progress * 100) : 0;
  const hasAudio = !!upload;
  const canSearch = hasAudio && !!picked && !busy;
  const canCustom =
    hasAudio && lyrics.trim().split("\n").filter((l) => l.trim()).length >= 2 && !busy;
  const grouped = useMemo(() => hits.slice(0, 40), [hits]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  const stepState = (n: number) =>
    n < step ? " done" : n === step ? " active" : "";

  return (
    <div className="cfg">
      <ol className="steps" aria-label="步骤">
        <li className={`step-item${stepState(1)}`}>
          <button onClick={() => setStep(1)}>
            <span className="step-no">1</span>
            <span className="step-label">上传音频</span>
          </button>
        </li>
        <li className={`step-item${stepState(2)}`}>
          <button onClick={() => hasAudio && setStep(2)} disabled={!hasAudio}>
            <span className="step-no">2</span>
            <span className="step-label">选择歌词</span>
          </button>
        </li>
        <li className={`step-item${stepState(3)}`}>
          <button onClick={() => setStep(3)}>
            <span className="step-no">3</span>
            <span className="step-label">已生成</span>
          </button>
        </li>
      </ol>

      {/* ---------------- step 1 ---------------- */}
      {step === 1 && (
        <section className="panel">
          <header className="panel-head">
            <h2>先放入这首歌的音频</h2>
            <span className="panel-sub">mp3 / wav / m4a / flac，最大 200MB</span>
          </header>

          <div className={`drop big${upload ? " has" : ""}`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files?.[0];
              if (f) void doUpload(f);
            }}
          >
            <input
              ref={fileRef}
              className="drop-input"
              type="file"
              accept="audio/*,video/mp4"
              aria-label="选择音频文件"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void doUpload(f);
              }}
            />
            {uploading ? (
              <span>上传中…</span>
            ) : upload ? (
              <>
                <strong>{upload.filename}</strong>
                <span className="drop-meta">
                  {fmtDur(upload.duration)} · {(upload.size / 1048576).toFixed(1)} MB
                </span>
                <span className="drop-hint">点击可换一个文件</span>
              </>
            ) : (
              <>
                <strong>点击或拖入音频文件</strong>
                <span className="drop-meta">
                  跟唱必须有音频；上传后下一步再决定歌词从哪来
                </span>
              </>
            )}
          </div>

          <div className="field-row">
            <label>
              歌名
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="可选，用于命名数据集" />
            </label>
            <label>
              歌手
              <input value={artist} onChange={(e) => setArtist(e.target.value)} placeholder="可选" />
            </label>
          </div>

          <div className="panel-foot">
            <span className="picked-note">
              {upload ? "音频已就绪，去第 2 步选择歌词" : "还没有音频，先选一个文件"}
            </span>
            <button className="btn primary" onClick={() => setStep(2)} disabled={!hasAudio}>
              下一步：选择歌词
            </button>
          </div>
        </section>
      )}

      {/* ---------------- step 2 ---------------- */}
      {step === 2 && (
        <section className="panel">
          <header className="panel-head">
            <h2>歌词从哪来</h2>
            <span className="panel-sub">
              {upload ? `${upload.filename} · ${fmtDur(upload.duration)}` : "请先上传音频"}
            </span>
          </header>

          <div className="mode-switch" role="tablist">
            <button
              role="tab"
              aria-selected={mode === "search"}
              className={mode === "search" ? "on" : ""}
              onClick={() => setMode("search")}
            >
              搜索歌词
              <em>自动找逐字时间轴</em>
            </button>
            <button
              role="tab"
              aria-selected={mode === "custom"}
              className={mode === "custom" ? "on" : ""}
              onClick={() => setMode("custom")}
            >
              自定义歌词
              <em>粘贴文本，用音频对齐</em>
            </button>
          </div>

          {mode === "search" ? (
            <>
              <div className="search-row">
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void runSearch()}
                  placeholder="歌名 / 歌手，例如：夜に駆ける YOASOBI"
                  spellCheck={false}
                />
                <button className="btn" onClick={() => void runSearch()} disabled={searching}>
                  {searching ? "搜索中…" : "搜索"}
                </button>
              </div>

              {searchErr && <p className="hint-warn">{searchErr}</p>}

              <div className="hits">
                {!grouped.length && !searching && (
                  <div className="hits-empty">
                    <span className="hits-empty-mark">♪</span>
                    <p>一次查 QQ 音乐、酷狗、Lrclib</p>
                    <p className="hits-empty-sub">
                      带「逐字」的结果有每个字的时间戳，高亮最准
                    </p>
                  </div>
                )}
                {grouped.map((h) => {
                  const active = picked?.source === h.source && picked?.id === h.id;
                  return (
                    <button
                      key={`${h.source}-${h.id}-${h.title}`}
                      className={`hit${active ? " on" : ""}`}
                      onClick={() => setPicked(h)}
                    >
                      <span className={`src s-${h.source}`}>
                        {SOURCE_LABEL[h.source] ?? h.source}
                      </span>
                      <span className="hit-main">
                        <span className="hit-title">{h.title}</span>
                        <span className="hit-artist">{h.artist}</span>
                      </span>
                      <span className={`kind${h.kind === "char" ? " char" : ""}`}>
                        {SOURCE_NOTE[h.source] ?? h.kind}
                      </span>
                      <span className="hit-dur">{fmtDur(h.duration)}</span>
                    </button>
                  );
                })}
              </div>

              <div className="panel-foot">
                <span className="picked-note">
                  {picked ? `已选：${picked.title}` : "点选一条结果"}
                </span>
                <button className="btn primary" onClick={buildFromSource} disabled={!canSearch}>
                  生成
                </button>
              </div>
            </>
          ) : (
            <>
              <label className="lyric-field">
                歌词（每行一句，不需要时间轴）
                <textarea
                  value={lyrics}
                  onChange={(e) => setLyrics(e.target.value)}
                  placeholder={"つかめ描いた夢を\nまもれ大事な友を\nたくましい自分になれるさ"}
                  spellCheck={false}
                />
              </label>
              <div className="panel-foot">
                <span className="picked-note">
                  会用 whisper 在这段音频上自动对齐每一句
                </span>
                <button className="btn primary" onClick={buildFromText} disabled={!canCustom}>
                  生成
                </button>
              </div>
            </>
          )}

          {(busy || job) && (
            <div className="job">
              <div className="job-bar">
                <div className="job-fill" style={{ width: `${pct}%` }} />
              </div>
              <span className="job-msg">
                {job?.message ?? "准备中…"}
                {job ? ` · ${pct}%` : ""}
              </span>
            </div>
          )}
        </section>
      )}

      {/* ---------------- step 3 ---------------- */}
      {step === 3 && (
        <section className="panel">
          <header className="panel-head">
            <h2>已生成</h2>
            <span className="panel-sub">{songs.length} 首</span>
          </header>
          <div className="songlist">
            {songs.map((s) => (
              <div className="songrow" key={s.name}>
                <span className="song-title">{s.title}</span>
                <span className="song-artist">{s.artist}</span>
                <span className={`song-audio${s.has_audio ? " ok" : ""}`}>
                  {s.has_audio ? "有音频" : "缺音频"}
                </span>
                <span className="song-dur">{fmtDur(s.duration)}</span>
                <button className="btn small" onClick={() => onPlay(s.name)}>
                  播放
                </button>
                {confirmDel === s.name ? (
                  <>
                    <button className="btn small danger" onClick={() => void doDelete(s.name)}>
                      确认删除
                    </button>
                    <button className="btn small" onClick={() => setConfirmDel(null)}>
                      取消
                    </button>
                  </>
                ) : (
                  <button
                    className="btn small ghost"
                    onClick={() => setConfirmDel(s.name)}
                    title="删除这个数据集"
                  >
                    删除
                  </button>
                )}
              </div>
            ))}
            {!songs.length && <p className="hint-dim">还没有生成任何歌曲</p>}
          </div>
        </section>
      )}

      {notice && <div className="toast">{notice}</div>}
    </div>
  );
}
