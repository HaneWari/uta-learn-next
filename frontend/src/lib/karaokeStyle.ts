import type { AppSettings } from "../types";

/**
 * 卡拉OK字幕的配色与尺寸只在这里换算一次。
 *
 * 参考 Lin-K Lyrics 的 `KaraokeColorState` / `PaintFill`:
 * 「走字前」和「走字后」各自有文字色与描边色,而不是只把文字换成主题色。
 * 预设主题仍然保留,自定义配色则让用户直接控制这四只颜色。
 */

export type KaraokeFont = "gothic" | "mincho" | "rounded";

export interface KaraokePreset {
  after: string;
  glow: string;
}

export const KARAOKE_PRESETS: Record<
  AppSettings["karaoke_color"],
  KaraokePreset
> = {
  red: { after: "#FF2020", glow: "rgba(255, 32, 32, 0.55)" },
  coral: { after: "#FF8A3D", glow: "rgba(255, 138, 61, 0.55)" },
  blue: { after: "#3FA9FF", glow: "rgba(63, 169, 255, 0.55)" },
  green: { after: "#45D98A", glow: "rgba(69, 217, 138, 0.5)" },
};

export interface KaraokePalette {
  before: string;
  after: string;
  beforeStroke: string;
  afterStroke: string;
  strokeWidth: number;
  glow: string;
  scanline: boolean;
  scanlineColor: string;
  scanlineWidth: number;
  font: KaraokeFont;
}

const FALLBACK: KaraokePalette = {
  before: "#FFFFFF",
  after: "#FF2020",
  beforeStroke: "#000000",
  afterStroke: "#FFFFFF",
  strokeWidth: 2,
  glow: "rgba(255, 32, 32, 0.55)",
  scanline: true,
  scanlineColor: "#FFFFFF",
  scanlineWidth: 16,
  font: "gothic",
};

/**
 * `scale` 让 4K 导出和窗口缩放得到同一套视觉比例:设置值以 1080p 为基准。
 */
export function karaokePalette(
  settings: AppSettings,
  scale = 1,
): KaraokePalette {
  const preset = KARAOKE_PRESETS[settings.karaoke_color] ?? KARAOKE_PRESETS.red;
  const custom = settings.karaoke_custom_colors === true;
  const after = custom
    ? settings.karaoke_after_color || preset.after
    : preset.after;
  const before = custom
    ? settings.karaoke_before_color || FALLBACK.before
    : FALLBACK.before;
  const glow = settings.karaoke_glow === false
    ? "transparent"
    : custom
      ? after
      : preset.glow;

  return {
    before,
    after,
    beforeStroke: custom
      ? settings.karaoke_before_stroke_color || FALLBACK.beforeStroke
      : FALLBACK.beforeStroke,
    afterStroke: custom
      ? settings.karaoke_after_stroke_color || FALLBACK.afterStroke
      : FALLBACK.afterStroke,
    strokeWidth: Math.max(
      0,
      Number(settings.karaoke_stroke_width ?? FALLBACK.strokeWidth),
    ) * scale,
    glow,
    scanline: settings.karaoke_scanline_enabled !== false,
    scanlineColor:
      settings.karaoke_scanline_color || FALLBACK.scanlineColor,
    scanlineWidth: Math.max(
      4,
      Number(settings.karaoke_scanline_width ?? FALLBACK.scanlineWidth),
    ) * scale,
    font: settings.karaoke_font ?? FALLBACK.font,
  };
}
