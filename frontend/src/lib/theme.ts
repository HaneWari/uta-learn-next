import { useEffect } from "react";
import type { AppSettings } from "../types";
import { useSettings } from "./settings";

/**
 * Apply the theme + motion settings to `<html>`.
 *
 * Dark mode is a data attribute rather than a pile of media queries: the user
 * can override the OS, and the export page has to render whatever the stage
 * shows (a system-follow mode would otherwise flip per-machine).
 */
export function useTheme(customBackground = false, renderMode = false) {
  const [settings] = useSettings();
  const { theme, reduce_motion, ui_font, page_zoom } = settings;
  const custom = customBackground;

  useEffect(() => {
    const root = document.documentElement;
    // A custom photo is a dark, blurred backdrop. Keeping a light theme on top
    // of it made the lyric text fight the image, so a custom background implies
    // dark unless the user explicitly picked light.
    if (custom && theme === "system") {
      root.dataset.theme = "dark";
      return undefined;
    }
    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const apply = () => {
        root.dataset.theme = mq.matches ? "dark" : "light";
      };
      apply();
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
    root.dataset.theme = theme;
    return undefined;
  }, [theme, custom]);

  useEffect(() => {
    const root = document.documentElement;
    if (reduce_motion) root.dataset.motion = "reduce";
    else delete root.dataset.motion;
  }, [reduce_motion]);

  // UI scale: one root font size + one page zoom. Every size in App.css is in
  // px, so `--ui-scale` multiplies the handful of "chrome" sizes while `zoom`
  // handles the whole page uniformly — the two settings stay independent.
  useEffect(() => {
    const root = document.documentElement;
    // The export renderer screenshots a fixed viewport and then encodes those
    // frames; a user's personal zoom must not resize them. `?render=1` is the
    // recorder page, so it always renders at 100% / default font.
    if (renderMode) {
      root.dataset.font = "m";
      root.style.setProperty("--page-zoom", "1");
      delete root.dataset.zoom;
      return;
    }
    root.dataset.font = ui_font;
    const zoom = Number.isFinite(page_zoom) ? Math.min(1.5, Math.max(0.8, page_zoom)) : 1;
    root.style.setProperty("--page-zoom", String(zoom));
    root.dataset.zoom = zoom === 1 ? "" : "on";
  }, [ui_font, page_zoom, renderMode]);
}

export type ThemeSettings = Pick<AppSettings, "theme" | "reduce_motion">;
