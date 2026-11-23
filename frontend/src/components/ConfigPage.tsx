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
  /* manual version-matching inputs for the search mode: when the source's
     timeline and the uploaded audio disagree in length, the user types the
     cut point (m:ss) for whichever side is longer */
  // crop start entered as separate 分/秒 fields; joined into "m:ss" on build
  const [lyricMin, setLyricMin] = useState("");
  const [lyricSec, setLyricSec] = useState("");
  const [audioMin, setAudioMin] = useState("");
  const [audioSec, setAudioSec] = useState("");
  /* custom-lyrics: ask for the offline zh translation during the build job */
  const [wantTranslate, setWantTranslate] = useState(false);

  /* ---- step 3: build ---- */
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  /* ---- whisper model for the custom-lyrics mode ---- */
  const [modelInstalled, setModelInstalled] = useState<boolean | null>(null);
  const [modelJob, setModelJob] = useState<Job | null>(null);
  const [modelBusy, setModelBusy] = useState(false);

  // probe once so the custom panel can show "装好了" without a round-trip
  useEffect(() => {
    api.modelStatus().then((s) => setModelInstalled(s.installed)).catch(() => setModelInstalled(null));
  }, []);

  const installModel = useCallback(async () => {
    setModelBusy(true);
    setNotice(null);
    setModelJob(null);
    try {
      const { job_id } = await api.installModel();
      if (!job_id) {
        setModelInstalled(true);
        return;
      }
      const done = await waitForJob(job_id, setModelJob, 800);
      if (done.status === "error") {
        setNotice(`扩展安装失败：${done.error ?? "未知错误"}`);
      } else {
        setModelInstalled(true);
        setNotice("语音识别扩展已装好，可以离线自定义歌词了");
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setModelBusy(false);
    }
  }, []);

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
    // one of the two lengths disagrees only when the source's timeline and the
    // file differ past a small tolerance; the matching input then says where
    // the shorter side's clock starts inside the longer one's
    const srcDur = picked.duration || 0;
    const audDur = upload.duration || 0;
    const payload: Record<string, unknown> = {
      upload_id: upload.id,
      title: title || picked.title,
      artist: artist || picked.artist,
    };
    const mmss = (m: string, s: string) =>
      `${m.trim() || "0"}:${(s.trim() || "0").padStart(2, "0")}`;
    if (srcDur > audDur + 2 && (lyricMin.trim() || lyricSec.trim())) {
      payload.lyric_start = mmss(lyricMin, lyricSec);
    } else if (audDur > srcDur + 2 && (audioMin.trim() || audioSec.trim())) {
      payload.audio_start = mmss(audioMin, audioSec);
    }
    void track(() =>
      api.buildFromSource(picked, payload),
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
        translate: wantTranslate,
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
  // the crop inputs only matter (and only show) when the two durations really
  // disagree — an exact-ish match never asks for one
  const srcDur = picked?.duration ?? 0;
  const audDur = upload?.duration ?? 0;
  const needsCrop = srcDur > 0 && audDur > 0 && Math.abs(srcDur - audDur) > 2;
  const sourceLonger = srcDur > audDur + 2;
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

              {needsCrop && (
                <div className="crop-box">
                  {sourceLonger ? (
                    <label className="crop-field">
                      歌词轴（{fmtDur(srcDur)}）比音频（{fmtDur(audDur)}）长。
                      请输入歌词轴播放的起点时刻：
                      <span className="crop-input">
                        <input
                          className="crop-num"
                          value={lyricMin}
                          onChange={(e) => setLyricMin(e.target.value)}
                          placeholder="0"
                          inputMode="numeric"
                        />
                        <span className="crop-unit">分</span>
                        <input
                          className="crop-num"
                          value={lyricSec}
                          onChange={(e) => setLyricSec(e.target.value)}
                          placeholder="00"
                          inputMode="numeric"
                        />
                        <span className="crop-unit">秒</span>
                      </span>
                    </label>
                  ) : (
                    <label className="crop-field">
                      音频（{fmtDur(audDur)}）比歌词轴（{fmtDur(srcDur)}）长。
                      请输入音频播放的起点时刻：
                      <span className="crop-input">
                        <input
                          className="crop-num"
                          value={audioMin}
                          onChange={(e) => setAudioMin(e.target.value)}
                          placeholder="0"
                          inputMode="numeric"
                        />
                        <span className="crop-unit">分</span>
                        <input
                          className="crop-num"
                          value={audioSec}
                          onChange={(e) => setAudioSec(e.target.value)}
                          placeholder="00"
                          inputMode="numeric"
                        />
                        <span className="crop-unit">秒</span>
                      </span>
                    </label>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              {/* the speech model is a separate download, not part of lite —
                  surface its state right where it is needed so a missing pack
                  is a one-click fix instead of a failed build */}
              <div className={`model-banner${modelInstalled ? " ok" : ""}`}>
                {modelInstalled ? (
                  <span className="model-ok">✓ 语音识别扩展已就绪，可离线对齐歌词</span>
                ) : (
                  <>
                    <div className="model-banner-text">
                      <strong>自定义歌词需要语音识别扩展</strong>
                      <span>一次性下载约 426MB，装好即可离线使用（不随版本更新）</span>
                    </div>
                    <div className="model-banner-actions">
                      <button
                        className="btn primary"
                        onClick={() => void installModel()}
                        disabled={modelBusy}
                      >
                        {modelBusy ? "下载安装中…" : "下载并安装扩展"}
                      </button>
                      <details className="model-manual">
                        <summary>手动安装</summary>
                        <p>
                          到
                          <a
                            href="https://github.com/HaneWari/uta-learn-next/releases/latest"
                            target="_blank"
                            rel="noreferrer"
                          >
                            发行版页面
                          </a>
                          下载 <code>UtaLearnNext-whisper-small.zip</code>，
                          解压到应用目录得到 <code>models/whisper-small/model.bin</code>，
                          重启程序即可。
                        </p>
                      </details>
                    </div>
                  </>
                )}
                {modelJob && modelBusy && (
                  <div className="model-progress">
                    <div className="job-bar">
                      <div
                        className="job-fill"
                        style={{ width: `${Math.round(modelJob.progress * 100)}%` }}
                      />
                    </div>
                    <span className="job-msg">
                      {modelJob.message} · {Math.round(modelJob.progress * 100)}%
                    </span>
                  </div>
                )}
              </div>

              <label className="lyric-field">
                歌词（每行一句，不需要时间轴）
                <textarea
                  value={lyrics}
                  onChange={(e) => setLyrics(e.target.value)}
                  placeholder={"つかめ描いた夢を\nまもれ大事な友を\nたくましい自分になれるさ"}
                  spellCheck={false}
                />
                <span className="lyric-reading-hint">
                  想改掉某个汉字/词组的读音？写作 <code>[汉字](读音)</code>，例如{" "}
                  <code>[明日](あす)</code> 或 <code>[運命](さだめ)</code>；
                  假名 / 片假名 / 罗马音都行，方括号圆括号用中文全角也认。
                </span>
              </label>
              <div className="panel-foot">
                <span className="picked-note">
                  会用 whisper 在这段音频上自动对齐每一句
                </span>
                <label className="tswitch" title="用本地翻译模型为每句歌词生成中文翻译">
                  <input
                    type="checkbox"
                    className="tswitch-input"
                    checked={wantTranslate}
                    onChange={(e) => setWantTranslate(e.target.checked)}
                  />
                  <span className="tswitch-track" aria-hidden="true">
                    <span className="tswitch-thumb" />
                  </span>
                  <span className="tswitch-label">开启中文翻译</span>
                </label>
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
