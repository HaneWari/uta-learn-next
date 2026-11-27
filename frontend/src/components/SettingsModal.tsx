import { useCallback, useEffect, useState } from "react";
import { api, waitForJob } from "../api";
import { useSettings } from "../lib/settings";
import type { AboutInfo, AppSettings, PackStatus } from "../types";
import { ShortcutGroups } from "./ShortcutHelp";
import { ConfirmDialog } from "./ConfirmDialog";

type Group =
  | "general"
  | "display"
  | "shortcuts"
  | "lyrics"
  | "network"
  | "export"
  | "packs"
  | "data"
  | "about";

const GROUPS: { id: Group; label: string }[] = [
  { id: "general", label: "常规" },
  { id: "display", label: "显示" },
  { id: "shortcuts", label: "快捷键" },
  { id: "lyrics", label: "歌词" },
  { id: "network", label: "网络" },
  { id: "export", label: "导出" },
  { id: "packs", label: "扩展包" },
  { id: "data", label: "数据" },
  { id: "about", label: "关于" },
];

/** "1.2 GB" / "237 MB" — the settings page never shows raw bytes. */
function humanSize(bytes: number): string {
  if (!bytes || bytes <= 0) return "—";
  const mb = bytes / 1048576;
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${Math.round(mb)} MB`;
}

const PACK_META = {
  custom_lyrics: {
    title: "自定义歌词扩展包",
    hint: "含 whisper 语音识别与日中翻译模型；自定义歌词和中文翻译都需要它",
  },
  chromium: {
    title: "Chromium 扩展包",
    hint: "系统浏览器无法用于导出时使用;装好后导出不再依赖已安装的 Chrome",
  },
} as const;

/** A labelled switch. Only the switch itself changes the value.

 * Clicking the row (or its label text) must do nothing: the settings page is
 * a list of rows, and a stray click while scrolling used to flip a switch the
 * user never aimed at.
 */
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
    <div className="setrow">
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
    </div>
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

/** 页面缩放以百分比输入；输入过程中不立刻夹取，失焦或回车时才提交。 */
function ZoomField({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  const current = Math.round(value * 100);
  const [draft, setDraft] = useState(String(current));

  useEffect(() => {
    setDraft(String(current));
  }, [current]);

  const commit = () => {
    const n = Number(draft);
    if (!Number.isFinite(n)) {
      setDraft(String(current));
      return;
    }
    const clamped = Math.min(150, Math.max(80, Math.round(n / 5) * 5));
    setDraft(String(clamped));
    if (clamped / 100 !== value) onChange(clamped / 100);
  };

  return (
    <div className="zoom-field">
      <input
        className="setinput zoom-input"
        type="number"
        min={80}
        max={150}
        step={5}
        inputMode="numeric"
        value={draft}
        aria-label="页面缩放百分比"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
            (e.currentTarget as HTMLInputElement).blur();
          }
        }}
      />
      <span className="zoom-unit">%</span>
      <button
        type="button"
        className="btn small"
        onClick={() => {
          setDraft("100");
          onChange(1);
        }}
        disabled={value === 1}
      >
        重置
      </button>
    </div>
  );
}

/** 颜色设置:浏览器取色器 + 十六进制文本,两边保持同步。 */
function ColorRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  // 颜色输入必须用本地草稿:直接受控到已保存值会让用户无法删掉一个字符
  // 重新输入(#FFFFFF → #F 时校验失败、值被弹回)。
  const [draft, setDraft] = useState(value);
  const [seen, setSeen] = useState(value);
  // 外部(取色器/另一处设置)改了值时同步草稿。渲染期调整状态是 React
  // 官方推荐的“props 变化时重置 state”写法,不会像 effect 那样多跑一轮。
  if (value !== seen) {
    setSeen(value);
    setDraft(value);
  }

  const commit = () => {
    const v = draft.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) {
      onChange(v.toUpperCase());
    } else {
      setDraft(value);
    }
  };

  return (
    <div className="setrow">
      <span className="setlabel">{label}</span>
      <span className="color-field">
        <input
          type="color"
          className="setcolor"
          value={value}
          aria-label={label}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
        />
        <input
          className="setinput color-hex"
          value={draft}
          spellCheck={false}
          aria-label={`${label}十六进制值`}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
              e.currentTarget.blur();
            }
          }}
        />
      </span>
    </div>
  );
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, update] = useSettings();
  const [group, setGroup] = useState<Group>("general");
  const [about, setAbout] = useState<AboutInfo | null>(null);
  /* 扩展包:真实体积 + 安装/删除动作 */
  const [packs, setPacks] = useState<PackStatus[]>([]);
  const [packBusy, setPackBusy] = useState<string | null>(null);
  const [packNote, setPackNote] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<PackStatus["key"] | null>(null);
  const [proxyNote, setProxyNote] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  /* legacy data import (§5.5.3) */
  const [legacy, setLegacy] = useState<{
    scanning: boolean;
    items: Awaited<ReturnType<typeof api.scanLegacy>>["candidates"];
    note: string | null;
  }>({ scanning: false, items: [], note: null });
  /* update state: check · download · restart */
  const [upd, setUpd] = useState<{
    checking: boolean;
    available: boolean;
    latest?: string;
    kind?: "patch" | "full";
    runtimeChanged?: boolean;
    notes?: string;
    note?: string;
    error?: string;
    applying: boolean;
    pct: number;
    ready?: string;
  }>({ checking: false, available: false, applying: false, pct: 0 });

  useEffect(() => {
    if (group !== "about" && group !== "packs") return;
    api.about().then(setAbout).catch(() => setAbout(null));
  }, [group]);

  const refreshPacks = useCallback(() => {
    api
      .packStatus()
      .then((r) => setPacks(r.packs))
      .catch(() => setPacks([]));
  }, []);

  useEffect(() => {
    if (group === "packs") refreshPacks();
  }, [group, refreshPacks]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 删除确认框自己处理 Esc；否则会连设置页一起关掉。
      if (e.key === "Escape" && !confirmRemove) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, confirmRemove]);

  /** Download (or re-download) one pack, then re-read the real size. */
  async function installPack(key: PackStatus["key"]) {
    setPackBusy(key);
    setPackNote(null);
    try {
      const r =
        key === "custom_lyrics"
          ? await api.installModel()
          : await api.installChromium();
      if (r.job_id) {
        const done = await waitForJob(r.job_id, () => undefined);
        // the download can fail (offline, rate-limited, antivirus lock); the
        // old code ignored `status` and claimed success every time
        if (done.status !== "done") {
          throw new Error(done.error || "安装失败");
        }
      }
      setPackNote(
        key === "custom_lyrics"
          ? "自定义歌词扩展包已安装"
          : "Chromium 扩展包已安装,重启应用后生效",
      );
      refreshPacks();
    } catch (e) {
      setPackNote(e instanceof Error ? e.message : String(e));
    } finally {
      setPackBusy(null);
    }
  }

  async function removePack(key: PackStatus["key"]) {
    const meta = PACK_META[key];
    setPackBusy(key);
    setPackNote(null);
    try {
      await api.removePack(key);
      setPackNote(`已删除「${meta.title}」`);
      refreshPacks();
    } catch (e) {
      setPackNote(e instanceof Error ? e.message : String(e));
    } finally {
      setPackBusy(null);
    }
  }

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

  async function checkUpdate(force = true) {
    setUpd((u) => ({ ...u, checking: true, error: undefined }));
    try {
      const r = await api.updateCheck(force);
      setUpd({
        checking: false,
        available: !!r.available,
        latest: r.latest,
        kind: r.kind,
        runtimeChanged: r.runtime_changed,
        notes: r.notes,
        note: r.note,
        error: r.error,
        applying: false,
        pct: 0,
      });
    } catch (e) {
      setUpd((u) => ({
        ...u,
        checking: false,
        error: e instanceof Error ? e.message : String(e),
      }));
    }
  }

  async function applyUpdate() {
    setUpd((u) => ({ ...u, applying: true, pct: 0 }));
    try {
      const { job_id } = await api.updateApply();
      const done = await waitForJob(job_id, (j) =>
        setUpd((u) => ({ ...u, pct: Math.round(j.progress * 100) })),
      );
      if (done.status === "error") {
        setUpd((u) => ({
          ...u,
          applying: false,
          error: done.error ?? "更新失败",
        }));
        return;
      }
      setUpd((u) => ({
        ...u,
        applying: false,
        available: false,
        ready: "更新已准备好，重启后生效",
      }));
    } catch (e) {
      setUpd((u) => ({
        ...u,
        applying: false,
        error: e instanceof Error ? e.message : String(e),
      }));
    }
  }

  return (
    <>
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
                  label="主题"
                  value={settings.theme}
                  options={[
                    { value: "system", label: "跟随系统" },
                    { value: "light", label: "浅色" },
                    { value: "dark", label: "深色" },
                  ]}
                  onChange={(v) => update({ theme: v })}
                />
                <div className="setrow">
                  <span className="setlabel">
                    界面字号
                    <span className="sethint">只放大界面文字,歌词仍按窗口宽度自适应</span>
                  </span>
                  <div className="segmented" role="radiogroup" aria-label="界面字号">
                    {(
                      [
                        ["s", "小"],
                        ["m", "标准"],
                        ["l", "大"],
                      ] as const
                    ).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        role="radio"
                        aria-checked={settings.ui_font === value}
                        className={settings.ui_font === value ? "on" : ""}
                        onClick={() => update({ ui_font: value })}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="setrow">
                  <span className="setlabel">
                    页面缩放
                    <span className="sethint">
                      整个界面的比例,「100%」为默认;{Math.round(settings.page_zoom * 100)}%
                    </span>
                  </span>
                  <ZoomField
                    value={settings.page_zoom}
                    onChange={(v) => update({ page_zoom: v })}
                  />
                </div>
                <Toggle
                  label="减少动效"
                  hint="关闭卡片入场、背景渐入等动画"
                  on={settings.reduce_motion}
                  onChange={(v) => update({ reduce_motion: v })}
                />
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

                {/* 以下设置只属于某一种播放样式,所以放在样式选择之后 */}
                <Radio
                  label="播放样式"
                  hint="默认样式偏学习;卡拉OK样式只保留字幕、注音与罗马音"
                  value={settings.play_style}
                  options={[
                    { value: "default", label: "默认样式" },
                    { value: "karaoke", label: "卡拉OK样式" },
                  ]}
                  onChange={(v) => update({ play_style: v })}
                />

                {settings.play_style === "default" ? (
                  <>
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
                          update({
                            default_layers: { ...settings.default_layers, [key]: v },
                          })
                        }
                      />
                    ))}
                  </>
                ) : (
                  <>
                    <Radio
                      label="卡拉OK主题色"
                      hint="字幕里已唱部分的颜色;注音与罗马音保持白色系"
                      value={settings.karaoke_color}
                      options={[
                        { value: "red", label: "经典红" },
                        { value: "coral", label: "珊瑚色" },
                        { value: "blue", label: "深蓝色" },
                        { value: "green", label: "绿色" },
                      ]}
                      onChange={(v) => update({ karaoke_color: v })}
                    />
                    <Toggle
                      label="自定义走字配色"
                      hint="分别设置走字前、走字后的文字色与描边色"
                      on={settings.karaoke_custom_colors}
                      onChange={(v) => update({ karaoke_custom_colors: v })}
                    />
                    {settings.karaoke_custom_colors && (
                      <>
                        <ColorRow
                          label="走字前文字"
                          value={settings.karaoke_before_color}
                          onChange={(v) => update({ karaoke_before_color: v })}
                        />
                        <ColorRow
                          label="走字后文字"
                          value={settings.karaoke_after_color}
                          onChange={(v) => update({ karaoke_after_color: v })}
                        />
                        <ColorRow
                          label="走字前描边"
                          value={settings.karaoke_before_stroke_color}
                          onChange={(v) =>
                            update({ karaoke_before_stroke_color: v })
                          }
                        />
                        <ColorRow
                          label="走字后描边"
                          value={settings.karaoke_after_stroke_color}
                          onChange={(v) =>
                            update({ karaoke_after_stroke_color: v })
                          }
                        />
                      </>
                    )}
                    <Radio
                      label="字幕字体"
                      value={settings.karaoke_font}
                      options={[
                        { value: "gothic", label: "黑体" },
                        { value: "mincho", label: "明朝" },
                        { value: "rounded", label: "圆体" },
                      ]}
                      onChange={(v) => update({ karaoke_font: v })}
                    />
                    <div className="setrow">
                      <span className="setlabel">
                        描边宽度
                        <span className="sethint">
                          以 1080p 为基准,导出 4K 会自动放大
                        </span>
                      </span>
                      <input
                        className="setinput karaoke-number"
                        type="number"
                        min={0}
                        max={8}
                        step={0.5}
                        value={settings.karaoke_stroke_width}
                        onChange={(e) =>
                          update({ karaoke_stroke_width: Number(e.target.value) })
                        }
                      />
                    </div>
                    <Toggle
                      label="扫字高光带"
                      hint="锋面处的一条提亮带;关掉后只剩连续的颜色扫过"
                      on={settings.karaoke_scanline_enabled}
                      onChange={(v) => update({ karaoke_scanline_enabled: v })}
                    />
                    {settings.karaoke_scanline_enabled && (
                      <>
                        <ColorRow
                          label="高光带颜色"
                          value={settings.karaoke_scanline_color}
                          onChange={(v) => update({ karaoke_scanline_color: v })}
                        />
                        <div className="setrow">
                          <span className="setlabel">高光带宽度</span>
                          <input
                            className="setinput karaoke-number"
                            type="number"
                            min={4}
                            max={48}
                            step={2}
                            value={settings.karaoke_scanline_width}
                            onChange={(e) =>
                              update({
                                karaoke_scanline_width: Number(e.target.value),
                              })
                            }
                          />
                        </div>
                      </>
                    )}
                    <Toggle
                      label="走字后发光"
                      hint="已唱的字带一层同色外发光"
                      on={settings.karaoke_glow}
                      onChange={(v) => update({ karaoke_glow: v })}
                    />
                    <p className="sethint karaoke-note">
                      卡拉OK样式是点歌机画面:顶部左为当前句翻译、右为下一句翻译,
                      中间画面叠当前句歌词,底部黑边预告下一句;不显示词条卡片。
                      右键字幕可切换注音、罗马音与翻译;导出时不会出现控制栏、
                      进度条和右侧歌词列表。
                    </p>
                  </>
                )}
              </>
            )}

            {group === "shortcuts" && (
              <>
                <p className="sethint">
                  在播放页按下按键即可生效；正在输入文字时，单键快捷键会自动
                  让位给输入框。按 <kbd className="inline-kbd">?</kbd> 也能
                  随时打开这张表。
                </p>
                <ShortcutGroups />
              </>
            )}

            {group === "lyrics" && (
              <>
                <p className="sethint">
                  搜索结果固定按「逐字且时长接近」优先,其余按时长从小到大,
                  不再提供排序开关。
                </p>
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
              </>
            )}

            {group === "packs" && (
              <>
                <p className="sethint">
                  两个扩展包都与版本无关:装一次,之后升级应用不用重装。
                  这里显示的是磁盘上的真实占用。
                </p>
                {packs.length === 0 && <p className="sethint">读取中...</p>}
                {packs.map((pack) => {
                  const meta = PACK_META[pack.key];
                  const busy = packBusy === pack.key;
                  return (
                    <div className="packrow" key={pack.key}>
                      <div className="packrow-main">
                        <span className="setlabel">
                          {meta.title}
                          <span className="sethint">{meta.hint}</span>
                        </span>
                        <span className="sethint packrow-meta">
                          {pack.installed ? `已安装 · ${humanSize(pack.size)}` : "未安装"} ·{" "}
                          <code className="setpath">{pack.path}</code>
                        </span>
                      </div>
                      <div className="packrow-actions">
                        <button
                          type="button"
                          className={`btn small${pack.installed ? "" : " primary"}`}
                          onClick={() => void installPack(pack.key)}
                          disabled={busy}
                        >
                          {busy ? "处理中..." : pack.installed ? "重新安装" : "安装"}
                        </button>
                        <button
                          type="button"
                          className="btn small"
                          onClick={() => setConfirmRemove(pack.key)}
                          disabled={busy || !pack.installed}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  );
                })}
                {packNote && <p className="setnote">{packNote}</p>}
              </>
            )}

            {group === "data" && (
              <>
                <p className="sethint">
                  发现同级目录里的旧版本时，可以把歌曲、扩展包和设置一次搬过来。
                  歌曲会在第一次打开时自动迁移到当前格式（迁移前先备份）。
                </p>
                <div className="setrow">
                  <span className="setlabel">
                    扫描旧版本
                    <span className="sethint">
                      {legacy.scanning
                        ? "扫描中…"
                        : legacy.items.length
                          ? `找到 ${legacy.items.length} 个旧安装`
                          : "在同级目录里找 v1.x 的数据"}
                    </span>
                  </span>
                  <button
                    className="btn"
                    onClick={() => {
                      setLegacy((s) => ({ ...s, scanning: true, note: null }));
                      void api
                        .scanLegacy()
                        .then((r) =>
                          setLegacy({ scanning: false, items: r.candidates, note: null }),
                        )
                        .catch((e: unknown) =>
                          setLegacy({
                            scanning: false,
                            items: [],
                            note: e instanceof Error ? e.message : String(e),
                          }),
                        );
                    }}
                    disabled={legacy.scanning}
                  >
                    扫描
                  </button>
                </div>
                {legacy.note && <p className="setnote">{legacy.note}</p>}
                {legacy.items.map((item) => (
                  <div className="legacy-card" key={item.path}>
                    <header>
                      <strong>{item.label}</strong>
                      {item.version && <span className="legacy-ver">v{item.version}</span>}
                    </header>
                    <span className="sethint">
                      {item.songs} 首歌
                      {Object.keys(item.packs).length
                        ? ` · 扩展包 ${Object.keys(item.packs).join(" / ")}`
                        : ""}
                    </span>
                    <span className="sethint legacy-names">
                      {item.song_names.slice(0, 4).join("、")}
                      {item.songs > 4 ? " …" : ""}
                    </span>
                    <div className="legacy-actions">
                      <button
                        className="btn primary"
                        onClick={() => {
                          void api
                            .importLegacy(item.path, false)
                            .then((r) =>
                              setLegacy((s) => ({
                                ...s,
                                note: `已复制 ${r.copied} 首，跳过 ${r.skipped} 首`,
                              })),
                            )
                            .catch((e: unknown) =>
                              setLegacy((s) => ({
                                ...s,
                                note: e instanceof Error ? e.message : String(e),
                              })),
                            );
                        }}
                      >
                        复制导入
                      </button>
                      <button
                        className="btn"
                        onClick={() => {
                          void api
                            .importLegacy(item.path, true)
                            .then((r) =>
                              setLegacy((s) => ({
                                ...s,
                                note: `已移动 ${r.copied} 首，跳过 ${r.skipped} 首`,
                              })),
                            )
                            .catch((e: unknown) =>
                              setLegacy((s) => ({
                                ...s,
                                note: e instanceof Error ? e.message : String(e),
                              })),
                            );
                        }}
                      >
                        移动导入
                      </button>
                    </div>
                  </div>
                ))}
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
                <div className="setrow">
                  <span className="setlabel">
                    版本更新
                    <span className="sethint">
                      {upd.ready
                        ? upd.ready
                        : upd.checking
                          ? "检查中..."
                          : upd.available
                            ? upd.kind === "patch"
                              ? `新版本 ${upd.latest}（补丁，约 1MB）`
                              : `新版本 ${upd.latest}（运行时变化，需完整包）`
                            : upd.note
                              ? upd.note
                              : upd.error
                                ? `检查失败:${upd.error}`
                              : upd.latest
                                ? "已是最新版本"
                                : "启动时会静默检查一次"}
                    </span>
                  </span>
                  <div className="update-actions">
                    {upd.available && upd.kind === "patch" && (
                      <button
                        className="btn primary"
                        onClick={() => void applyUpdate()}
                        disabled={upd.applying}
                      >
                        {upd.applying ? `下载中 ${upd.pct}%` : "下载并更新"}
                      </button>
                    )}
                    {upd.available && upd.kind === "full" && (
                      <a
                        className="btn primary"
                        href="https://github.com/HaneWari/uta-learn-next/releases/latest"
                        target="_blank"
                        rel="noreferrer"
                      >
                        下载完整包
                      </a>
                    )}
                    <button
                      className="btn"
                      onClick={() => void checkUpdate(true)}
                      disabled={upd.checking}
                    >
                      检查更新
                    </button>
                  </div>
                </div>
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
      {confirmRemove && (
        <ConfirmDialog
          title="删除扩展包"
          message={`确定删除「${PACK_META[confirmRemove].title}」吗？需要时可以再装回来。`}
          confirmLabel="删除"
          danger
          onCancel={() => setConfirmRemove(null)}
          onConfirm={() => {
            const key = confirmRemove;
            setConfirmRemove(null);
            void removePack(key);
          }}
        />
      )}
    </>
  );
}

export type { AppSettings };
