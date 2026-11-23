import { useCallback, useEffect, useState } from "react";
import { api, waitForJob } from "../api";
import type { ExportEnv, Job } from "../types";

interface Props {
  /** start the real export once the environment checks out */
  onReady: () => void;
  onClose: () => void;
}

type Phase = "probing" | "ready" | "fixing" | "installing" | "needs_restart";

/**
 * Pre-flight check for video export. The user only sees it when something is
 * actually wrong — a green probe closes itself and starts the export.
 *
 * The ladder of fixes, cheapest first:
 *   1. playwright missing/broken → repair it (pip + `playwright install`)
 *   2. browser won't launch     → download the bundled-Chromium extension pack
 * Anything that drops a browser on disk asks for a restart so the resolver
 * picks it up cleanly.
 */
export function ExportEnvModal({ onReady, onClose }: Props) {
  const [env, setEnv] = useState<ExportEnv | null>(null);
  const [phase, setPhase] = useState<Phase>("probing");
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const probe = useCallback(async () => {
    setPhase("probing");
    setErr(null);
    try {
      const e = await api.exportEnv();
      setEnv(e);
      if (e.ok) {
        onReady();
      } else {
        setPhase("ready");
      }
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
      setPhase("ready");
    }
  }, [onReady]);

  useEffect(() => {
    void probe();
  }, [probe]);

  const runJob = useCallback(
    async (start: () => Promise<{ job_id: string | null }>) => {
      setErr(null);
      setJob(null);
      try {
        const { job_id } = await start();
        if (!job_id) {
          // already satisfied — reprobe; a green result auto-continues
          await probe();
          return true;
        }
        const done = await waitForJob(job_id, setJob, 900);
        if (done.status === "error") {
          setErr(done.error ?? "操作失败");
          return false;
        }
        return true;
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
        return false;
      }
    },
    [probe],
  );

  const fixPlaywright = useCallback(async () => {
    setPhase("fixing");
    const ok = await runJob(() => api.fixPlaywright());
    if (ok) {
      // a repaired runtime may still need a fresh import context — safest is a
      // restart, but if the probe is already green we can continue right away
      await probe();
      setPhase((p) => (p === "fixing" ? "ready" : p));
    } else {
      setPhase("ready");
    }
  }, [runJob, probe]);

  const installChromium = useCallback(async () => {
    setPhase("installing");
    const ok = await runJob(() => api.installChromium());
    if (ok) {
      // the resolver caches nothing, but the launcher's env only sets
      // PLAYWRIGHT_BROWSERS_PATH at startup — ask for a restart to be safe
      setPhase("needs_restart");
    } else {
      setPhase("ready");
    }
  }, [runJob]);

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
          <p className="bghint">正在检查导出所需环境…</p>
        )}

        {phase === "needs_restart" && (
          <>
            <p className="bghint">
              ✅ Chromium 扩展包已装好。请<b>重启 Uta Learn Next</b>
              后再点「导出视频」，新浏览器才会生效。
            </p>
            <div className="env-actions">
              <button className="btn primary" onClick={onClose}>我知道了</button>
            </div>
          </>
        )}

        {phase !== "probing" && phase !== "needs_restart" && env && (
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
              <li className={c?.ffmpeg ? "ok" : "bad"}>
                ffmpeg{c?.ffmpeg ? "" : "（缺失，无法合成视频）"}
              </li>
            </ul>

            {(env.state === "no_playwright" || env.state === "no_browser") && (
              <p className="bghint">
                {env.state === "no_playwright"
                  ? "缺少 Playwright 运行库。可以先让程序自动安装修复；修复不了再装 Chromium 扩展包。"
                  : c?.bundled_chromium
                    ? "已解压 Chromium 扩展包，但浏览器仍启动失败——可先尝试修复 Playwright 运行库，或重新安装扩展包。"
                    : "没找到能启动的 Chromium 内核浏览器（Chrome / Edge / Brave / 360 / QQ 等均可）。可以先让程序自动修复，或安装内置 Chromium 扩展包。"}
              </p>
            )}
            {env.state === "no_ffmpeg" && (
              <p className="bghint">
                浏览器正常，但缺少 <b>ffmpeg</b>。请把 ffmpeg 放到应用目录的{" "}
                <code>bin/</code> 下或加入系统 PATH 后重启。
              </p>
            )}

            {err && <p className="env-fail">⚠ {err}</p>}

            {busy ? (
              <div className="job">
                <div className="job-bar">
                  <div className="job-fill" style={{ width: `${pct}%` }} />
                </div>
                <span className="job-msg">
                  {job?.message ?? "处理中…"}
                  {job ? ` · ${pct}%` : ""}
                </span>
              </div>
            ) : (
              <div className="env-actions">
                {(env.state === "no_playwright" || env.state === "no_browser") && (
                  <button className="btn primary" onClick={() => void fixPlaywright()}>
                    自动安装修复
                  </button>
                )}
                {(env.state === "no_browser" || env.state === "no_playwright") && (
                  <button
                    className="btn"
                    onClick={() => void installChromium()}
                  >
                    {c?.bundled_chromium ? "重新下载 Chromium 扩展包" : "下载安装 Chromium 扩展包"}
                  </button>
                )}
                <button className="btn" onClick={() => void probe()}>
                  重新检测
                </button>
                <button className="btn" onClick={onClose}>
                  取消
                </button>
              </div>
            )}
          </>
        )}

        {phase !== "probing" && phase !== "needs_restart" && !env && (
          <>
            <p className="bghint">环境检查失败{err ? `：${err}` : ""}</p>
            <div className="env-actions">
              <button className="btn" onClick={() => void probe()}>
                重新检测
              </button>
              <button className="btn" onClick={onClose}>
                取消
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
