import { useEffect, useState } from "react";
import { api } from "../api";
import { useSettings } from "../lib/settings";
import type { AboutInfo, AppSettings } from "../types";

type Group = "general" | "display" | "lyrics" | "network" | "export" | "packs" | "about";

const GROUPS: { id: Group; label: string }[] = [
  { id: "general", label: "常规" },
  { id: "display", label: "显示" },
  { id: "lyrics", label: "歌词" },
  { id: "network", label: "网络" },
  { id: "export", label: "导出" },
  { id: "packs", label: "扩展包" },
  { id: "about", label: "关于" },
];

/** A labelled switch: the click target is the whole row, not a 12px knob. */
function Toggle({
  label,
  hint,
  on,
  onChange,
}: {
  label: string;
  hint?: string;
  on: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="setrow">
      <span className="setlabel">
        {label}
        {hint && <span className="sethint">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        className={`switch${on ? " on" : ""}`}
        onClick={() => onChange(!on)}
      >
        <span className="switch-knob" />
      </button>
    </label>
  );
}

function Radio<T extends string>({
  label,
  hint,
  value,
  options,
  onChange,
}: {
  label: string;
  hint?: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="setrow">
      <span className="setlabel">
        {label}
        {hint && <span className="sethint">{hint}</span>}
      </span>
      <div className="segmented" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            className={value === o.value ? "on" : ""}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, update] = useSettings();
  const [group, setGroup] = useState<Group>("general");
  const [about, setAbout] = useState<AboutInfo | null>(null);
  const [proxyNote, setProxyNote] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    if (group !== "about" && group !== "packs") return;
    api.about().then(setAbout).catch(() => setAbout(null));
  }, [group]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function testProxy() {
    setTesting(true);
    setProxyNote(null);
    try {
      const r = await api.testProxy(
        settings.proxy_mode === "manual" ? settings.proxy_url : undefined,
      );
      setProxyNote(
        r.ok
          ? `连接成功（${r.proxy ?? "直连"}）`
          : `连接失败${r.proxy ? `（${r.proxy}）` : ""}：${r.error ?? `HTTP ${r.status}`}`,
      );
    } catch (e) {
      setProxyNote(e instanceof Error ? e.message : String(e));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="bgmask" role="dialog" aria-modal="true" aria-label="设置">
      <div className="bgmodal setmodal">
        <header className="bghead">
          <h2>设置</h2>
          <button className="bgclose" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="setbody">
          <nav className="setnav" aria-label="设置分组">
            {GROUPS.map((g) => (
              <button
                key={g.id}
                className={group === g.id ? "on" : ""}
                onClick={() => setGroup(g.id)}
              >
                {g.label}
              </button>
            ))}
          </nav>

          <div className="setpane">
            {group === "general" && (
              <>
                <Toggle
                  label="自动检查更新"
                  hint="启动后静默检查一次是否有新版本"
                  on={settings.update_check}
                  onChange={(v) => update({ update_check: v })}
                />
                <Toggle
                  label="匿名使用统计"
                  hint="每天最多一次，只含随机安装 ID、版本号、系统版本；不含歌曲、歌词、路径或个人信息"
                  on={settings.telemetry}
                  onChange={(v) => update({ telemetry: v })}
                />
                <Toggle
                  label="关闭窗口时确认"
                  on={settings.confirm_close}
                  onChange={(v) => update({ confirm_close: v })}
                />
              </>
            )}

            {group === "display" && (
              <>
                <Radio
                  label="助词读法"
                  hint="「東京へ行こう」→ toukyou e ikou / toukyou he ikou"
                  value={settings.particle_reading}
                  options={[
                    { value: "pron", label: "按发音" },
                    { value: "literal", label: "按字面" },
                  ]}
                  onChange={(v) => update({ particle_reading: v })}
                />
                <Radio
                  label="长音写法"
                  hint="「東京」→ toukyou / tōkyō / tookyoo"
                  value={settings.long_vowel}
                  options={[
                    { value: "ou", label: "ou" },
                    { value: "macron", label: "ō" },
                    { value: "oo", label: "oo" },
                  ]}
                  onChange={(v) => update({ long_vowel: v })}
                />
                <Radio
                  label="主题"
                  value={settings.theme}
                  options={[
                    { value: "system", label: "跟随系统" },
                    { value: "light", label: "浅色" },
                    { value: "dark", label: "深色" },
                  ]}
                  onChange={(v) => update({ theme: v })}
                />
                <Toggle
                  label="减少动效"
                  hint="关闭卡片入场、背景渐入等动画"
                  on={settings.reduce_motion}
                  onChange={(v) => update({ reduce_motion: v })}
                />
                <div className="setrow">
                  <span className="setlabel">
                    新歌默认显示
                    <span className="sethint">只影响之后新生成的歌曲</span>
                  </span>
                </div>
                {(
                  [
                    ["furigana", "注音"],
                    ["romaji", "罗马音"],
                    ["translation", "翻译"],
                    ["next_line", "下一句"],
                    ["cards", "词条卡片"],
                  ] as const
                ).map(([key, label]) => (
                  <Toggle
                    key={key}
                    label={label}
                    on={settings.default_layers[key]}
                    onChange={(v) =>
                      update({ default_layers: { ...settings.default_layers, [key]: v } })
                    }
                  />
                ))}
              </>
            )}

            {group === "lyrics" && (
              <>
                <Radio
                  label="默认搜索排序"
                  hint="上传音频后「时长匹配」才有效，否则自动按逐字优先"
                  value={settings.search_sort}
                  options={[
                    { value: "duration", label: "时长匹配" },
                    { value: "char", label: "逐字优先" },
                    { value: "source", label: "按来源" },
                  ]}
                  onChange={(v) => update({ search_sort: v })}
                />
                <div className="setrow">
                  <span className="setlabel">
                    卡片 JLPT 过滤
                    <span className="sethint">只出该等级及更难的词；0 表示不过滤</span>
                  </span>
                  <select
                    className="setselect"
                    value={settings.jlpt_max}
                    onChange={(e) => update({ jlpt_max: Number(e.target.value) })}
                  >
                    <option value={0}>不过滤</option>
                    <option value={5}>N5 及以上</option>
                    <option value={4}>N4 及以上</option>
                    <option value={3}>N3 及以上</option>
                    <option value={2}>N2 及以上</option>
                    <option value={1}>只要 N1</option>
                  </select>
                </div>
              </>
            )}

            {group === "network" && (
              <>
                <Radio
                  label="代理"
                  hint="自动只认系统代理与常见本地端口（Clash / V2Ray 等）"
                  value={settings.proxy_mode}
                  options={[
                    { value: "auto", label: "自动" },
                    { value: "system", label: "系统" },
                    { value: "manual", label: "手动" },
                    { value: "off", label: "关闭" },
                  ]}
                  onChange={(v) => update({ proxy_mode: v })}
                />
                {settings.proxy_mode === "manual" && (
                  <div className="setrow">
                    <span className="setlabel">代理地址</span>
                    <input
                      className="setinput"
                      placeholder="http://127.0.0.1:7890"
                      value={settings.proxy_url}
                      onChange={(e) => update({ proxy_url: e.target.value })}
                    />
                  </div>
                )}
                <div className="setrow">
                  <span className="setlabel">测试连接</span>
                  <button className="btn" onClick={() => void testProxy()} disabled={testing}>
                    {testing ? "测试中…" : "测试"}
                  </button>
                </div>
                {proxyNote && <p className="setnote">{proxyNote}</p>}
              </>
            )}

            {group === "export" && (
              <>
                <Radio
                  label="默认导出预设"
                  value={settings.export_preset}
                  options={[
                    { value: "landscape", label: "横屏 1080p" },
                    { value: "portrait", label: "竖屏 1080p" },
                    { value: "4k", label: "4K 横屏" },
                  ]}
                  onChange={(v) => update({ export_preset: v })}
                />
                <div className="setrow">
                  <span className="setlabel">并行渲染页数</span>
                  <select
                    className="setselect"
                    value={settings.export_pages}
                    onChange={(e) => update({ export_pages: Number(e.target.value) })}
                  >
                    {[1, 2, 3, 4].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
                <Toggle
                  label="兼容模式（旧录屏器）"
                  hint="只在导出画面异常时打开"
                  on={settings.export_compat}
                  onChange={(v) => update({ export_compat: v })}
                />
              </>
            )}

            {group === "packs" && (
              <>
                <p className="sethint">
                  两个扩展包都与版本无关：装一次，之后升级应用不用重装。
                </p>
                <div className="setrow">
                  <span className="setlabel">
                    自定义歌词扩展包
                    <span className="sethint">whisper + 日中翻译模型，约 500MB</span>
                  </span>
                  <span className={`packstate${about?.packs.custom_lyrics ? " ok" : ""}`}>
                    {about?.packs.custom_lyrics ? "已安装" : "未安装"}
                  </span>
                </div>
                <div className="setrow">
                  <span className="setlabel">
                    Chromium 扩展包
                    <span className="sethint">系统浏览器无法用于导出时使用，约 316MB</span>
                  </span>
                  <span className={`packstate${about?.packs.chromium ? " ok" : ""}`}>
                    {about?.packs.chromium ? "已安装" : "未安装"}
                  </span>
                </div>
              </>
            )}

            {group === "about" && (
              <>
                <div className="setrow">
                  <span className="setlabel">
                    Uta Learn Next
                    <span className="sethint">
                      {about ? `v${about.version} · Python ${about.python}` : "载入中…"}
                    </span>
                  </span>
                </div>
                {about && (
                  <>
                    <div className="setrow">
                      <span className="setlabel">应用目录</span>
                      <code className="setpath">{about.paths.app}</code>
                    </div>
                    <div className="setrow">
                      <span className="setlabel">数据目录</span>
                      <code className="setpath">{about.paths.data}</code>
                    </div>
                    <div className="setrow">
                      <span className="setlabel">
                        诊断信息
                        <span className="sethint">
                          含版本、环境与最近日志；不含音频、歌词与个人信息
                        </span>
                      </span>
                      <a className="btn" href={api.diagnosticsUrl()} download>
                        导出诊断包
                      </a>
                    </div>
                  </>
                )}
                <p className="sethint">
                  第三方组件：ffmpeg（GPL）、faster-whisper（MIT）、
                  opus-mt-ja-zh（CC-BY-4.0）。完整许可见发行版内 LICENSES/。
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export type { AppSettings };
