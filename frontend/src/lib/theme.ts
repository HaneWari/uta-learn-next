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
export function useTheme() {
  const [settings] = useSettings();
  const { theme, reduce_motion } = settings;

  useEffect(() => {
    const root = document.documentElement;
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
  }, [theme]);

  useEffect(() => {
    const root = document.documentElement;
    if (reduce_motion) root.dataset.motion = "reduce";
    else delete root.dataset.motion;
  }, [reduce_motion]);
}

export type ThemeSettings = Pick<AppSettings, "theme" | "reduce_motion">;
