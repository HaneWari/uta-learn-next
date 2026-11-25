import { useCallback, useEffect, useRef, useState } from "react";
import { api, waitForJob } from "../api";
import type { ExportEnv, Job } from "../types";

interface Props {
  /** start the real export once the environment checks out */
  onReady: () => void;
  onClose: () => void;
}

type Phase = "probing" | "ready" | "fixing" | "installing" | "done_ok" | "done_fail";

/**
 * Pre-flight check for video export. The user only sees it when something is
 * actually wrong — a green probe closes itself and starts the export.
 *
 * The ladder of fixes, cheapest first, driven by one 自动修复 button:
 *   missing ffmpeg    → drop the slim build into bin/
 *   playwright broken  → pip install + pull its chromium
 *   nothing launches   → promote the bundled-Chromium extension pack
 * Fixing always re-probes on its own (no separate 重新检测 button); a green
 * result means the user just needs to restart.
 */
export function ExportEnvModal({ onReady, onClose }: Props) {
  const [env, setEnv] = useState<ExportEnv | null>(null);
  const [phase, setPhase] = useState<Phase>("probing");
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fixedOk, setFixedOk] = useState(false);
  const mounted = useRef(true);

  useEffect(() => () => {
    mounted.current = false;
  }, []);

  const applyEnv = useCallback(
    (e: ExportEnv) => {
      if (!mounted.current) return;
      setEnv(e);
      if (e.ok) {
        onReady();
      } else {
        setPhase("ready");
      }
    },
    [onReady],
  );
  const applyFailure = useCallback((e2: unknown) => {
    if (!mounted.current) return;
    setErr(e2 instanceof Error ? e2.message : String(e2));
    setPhase("ready");
  }, []);

  // `showSpinner` is only for the explicit re-check button: on mount the
  // initial phase already *is* "probing", and setting state synchronously
  // inside the mount effect would cascade an extra render.
  const probe = useCallback(async (showSpinner = false) => {
    if (showSpinner) {
      setPhase("probing");
      setErr(null);
    }
    try {
      applyEnv(await api.exportEnv());
    } catch (e2) {
      applyFailure(e2);
    }
  }, [applyEnv, applyFailure]);

  // The mount probe goes through a promise chain rather than `probe()` so no
  // state is written synchronously from the effect body.
  useEffect(() => {
    let alive = true;
    api
      .exportEnv()
      .then((e) => {
        if (alive) applyEnv(e);
      })
      .catch((e2) => {
        if (alive) applyFailure(e2);
      });
    return () => {
      alive = false;
    };
  }, [applyEnv, applyFailure]);

  // One-button auto-repair: run the unified fix job, then re-probe. The job
  // itself drops ffmpeg/playwright/chromium as needed; a still-broken browser
  // afterwards is the signal to promote the extension pack.
  const fix = useCallback(async () => {
    setPhase("fixing");
    setErr(null);
    setJob(null);
    try {
      const { job_id } = await api.fixExport();
      const done = await waitForJob(job_id, setJob, 900);
      if (!mounted.current) return;
      if (done.status === "error") {
        setErr(done.error ?? "修复失败");
        setPhase("done_fail");
        return;
      }
      const e = await api.exportEnv();
      if (!mounted.current) return;
      setEnv(e);
      setFixedOk(e.ok);
      setPhase(e.ok ? "done_ok" : "done_fail");
      if (!e.ok) setErr(null);
    } catch (e2) {
      if (!mounted.current) return;
      setErr(e2 instanceof Error ? e2.message : String(e2));
      setPhase("done_fail");
    }
  }, []);

  const installChromium = useCallback(async () => {
    setPhase("installing");
    setErr(null);
    setJob(null);
    try {
      const { job_id } = await api.installChromium();
      if (!job_id) {
        await probe();
        return;
      }
      const done = await waitForJob(job_id, setJob, 900);
      if (!mounted.current) return;
      if (done.status === "error") {
        setErr(done.error ?? "安装失败");
        setPhase("done_fail");
        return;
      }
      // a browser binary dropped on disk needs a restart before the resolver
      // picks it up — that IS the success path here
      setFixedOk(true);
      setPhase("done_ok");
    } catch (e2) {
      if (!mounted.current) return;
      setErr(e2 instanceof Error ? e2.message : String(e2));
      setPhase("done_fail");
    }
  }, [probe]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const c = env?.checks;
  const busy = phase === "fixing" || phase === "installing" || phase === "probing";
  const pct = job ? Math.round(job.progress * 100) : 0;
  const fixFailed = phase === "done_fail" && !fixedOk;

  return (
    <div className="bgmask" role="dialog" aria-modal="true" aria-label="导出环境检查">
      <div className="bgmodal envmodal">
        <header className="bghead">
          <h2>导出环境检查</h2>
          <button className="bgclose" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        {phase === "probing" && (
          <p className="bghint env-busy">
            <span className="spin" aria-hidden="true" />
            正在检查导出所需环境…
          </p>
        )}

        {phase === "done_ok" && (
          <>
            <p className="bghint">
              ✅ {fixedOk ? "修复完成，环境已就绪。" : "环境已就绪。"}
              请<b>重启 Uta Learn Next</b> 后再点「导出视频」。
            </p>
          </>
        )}

        {phase === "done_fail" && (
          <p className="env-fail">
            ⚠ 自动修复未成功{err ? `：${err}` : "。请安装 Chromium 扩展包。"}
          </p>
        )}

        {phase !== "probing" && env && phase !== "done_ok" && (
          <>
            <ul className="env-checks">
              <li className={c?.playwright ? "ok" : "bad"}>
                Playwright 运行库{c?.playwright ? "" : "（缺失）"}
              </li>
              <li className={c?.browser_launch ? "ok" : "bad"}>
                Chromium 内核浏览器
                {c?.browser_path ? (
                  <span className="env-path" title={c.browser_path}>
                    {c.browser_path}
                  </span>
                ) : (
                  ""
                )}
                {!c?.browser_launch && c?.launch_error ? (
                  <span className="env-err">{c.launch_error}</span>
                ) : (
                  ""
                )}
              </li>
              {c?.browser_launch === true && c?.record_video === false && (
                <li className="dim">
                  兼容模式录制组件（不影响正常导出）
                  <span className="env-err">{c.record_error}</span>
                </li>
              )}
              <li className={c?.ffmpeg ? "ok" : "bad"}>
                ffmpeg{c?.ffmpeg ? "" : "（缺失，无法合成视频）"}
              </li>
            </ul>

            {phase === "ready" && env.state !== "ok" && (
              <p className="bghint">
                {env.state === "no_ffmpeg"
                  ? "缺少 ffmpeg，点「自动修复」即可自动下载安装。"
                  : "点「自动修复」让程序装好缺失的组件；修复不了再装内置 Chromium 扩展包。"}
              </p>
            )}

            {busy && (
              <div className="job">
                <div className="job-bar">
                  <div className="job-fill" style={{ width: `${pct}%` }} />
                </div>
                <span className="job-msg env-busy">
                  <span className="spin" aria-hidden="true" />
                  {phase === "fixing" ? "自动修复中" : "安装中"}
                  {job?.message ? ` · ${job.message}` : ""}
                  {job ? ` ${pct}%` : ""}
                </span>
              </div>
            )}

            {!busy && (
              <div className="env-actions">
                {(env.state === "no_playwright" ||
                  env.state === "no_browser" ||
                  env.state === "no_ffmpeg") && (
                  <button
                    className={`btn${fixFailed ? "" : " primary"}`}
                    onClick={() => void fix()}
                  >
                    自动修复
                  </button>
                )}
                <button
                  className={`btn${fixFailed ? " primary" : ""}`}
                  onClick={() => void installChromium()}
                >
                  {c?.bundled_chromium ? "重装 Chromium 扩展包" : "安装 Chromium 扩展包"}
                </button>
              </div>
            )}
          </>
        )}

        {phase !== "probing" && phase !== "done_ok" && !env && (
          <>
            <p className="bghint">环境检查失败{err ? `：${err}` : ""}</p>
            <div className="env-actions">
              <button className="btn primary" onClick={() => void fix()}>
                自动修复
              </button>
          <button className="btn" onClick={() => void probe(true)}>
                重新检测
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
