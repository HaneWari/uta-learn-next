import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettings } from "../types";

/**
 * Settings, loaded once per page and shared through a tiny subscriber list.
 *
 * A React context would be the usual answer, but the stage is also mounted in
 * the bare `?render=1` export page where providers are out of scope — a module
 * level cache works in both, and every component that needs a setting gets the
 * same object.
 */

export const DEFAULT_SETTINGS: AppSettings = {
  update_check: true,
  telemetry: true,
  confirm_close: true,
  particle_reading: "pron",
  long_vowel: "ou",
  theme: "system",
  reduce_motion: false,
  ui_font: "m",
  page_zoom: 1,
  play_style: "default",
  karaoke_color: "red",
  karaoke_custom_colors: false,
  karaoke_before_color: "#FFFFFF",
  karaoke_after_color: "#FF2020",
  karaoke_before_stroke_color: "#000000",
  karaoke_after_stroke_color: "#FFFFFF",
  karaoke_stroke_width: 2,
  karaoke_glow: true,
  karaoke_scanline_enabled: true,
  karaoke_scanline_color: "#FFFFFF",
  karaoke_scanline_width: 16,
  karaoke_font: "gothic",
  default_layers: {
    furigana: true,
    romaji: true,
    translation: true,
    next_line: true,
    cards: true,
  },
  jlpt_max: 0,
  proxy_mode: "auto",
  proxy_url: "",
  export_preset: "landscape",
  export_pages: 3,
  install_id: "",
  telemetry_last_day: "",
};

let cached: AppSettings = DEFAULT_SETTINGS;
let loading: Promise<AppSettings> | null = null;
const subscribers = new Set<(s: AppSettings) => void>();

function publish(next: AppSettings) {
  cached = next;
  subscribers.forEach((fn) => fn(next));
}

export function currentSettings(): AppSettings {
  return cached;
}

export function loadSettings(): Promise<AppSettings> {
  if (loading) return loading;
  loading = api
    .settings()
    .then((s) => {
      publish({ ...DEFAULT_SETTINGS, ...s });
      return cached;
    })
    .catch(() => cached)
    .finally(() => {
      loading = null;
    });
  return loading;
}

export async function updateSettings(patch: Partial<AppSettings>) {
  // optimistic: the switch must move on click, not after a round trip
  publish({ ...cached, ...patch });
  try {
    const saved = await api.saveSettings(patch);
    publish({ ...DEFAULT_SETTINGS, ...saved });
  } catch {
    /* keep the optimistic value; the next load re-syncs from disk */
  }
}

export function useSettings(): [AppSettings, (p: Partial<AppSettings>) => void] {
  const [settings, setSettings] = useState<AppSettings>(cached);

  useEffect(() => {
    subscribers.add(setSettings);
    void loadSettings();
    return () => {
      subscribers.delete(setSettings);
    };
  }, []);

  const update = useCallback((patch: Partial<AppSettings>) => {
    void updateSettings(patch);
  }, []);

  return [settings, update];
}
