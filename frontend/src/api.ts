import type {
  AboutInfo,
  AppSettings,
  ExportEnv,
  Job,
  SearchHit,
  SongSummary,
  StageBackground,
  UploadInfo,
} from "./types";

// relative paths: the vite dev server proxies /api and /poc to :8000
const BASE = "";

/**
 * Per-launch token injected into index.html by the backend. The server rejects
 * cross-site writes, and a foreign page cannot read this tag, so attaching it
 * proves the request came from our own page. In dev (Vite serves index.html)
 * the tag is absent and the server skips the check.
 */
function writeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="uta-token"]');
  return meta?.content ? { ...extra, "X-Uta-Token": meta.content } : extra;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: writeHeaders({ "content-type": "application/json" }),
    body: JSON.stringify(body),
  }).then((r) => json<T>(r));
}

export const api = {
  /* settings live server-side so the export recorder sees the same choices */
  settings: () => fetch(`${BASE}/api/settings`).then((r) => json<AppSettings>(r)),

  saveSettings: (patch: Partial<AppSettings>) =>
    fetch(`${BASE}/api/settings`, {
      method: "PATCH",
      headers: writeHeaders({ "content-type": "application/json" }),
      body: JSON.stringify(patch),
    }).then((r) => json<AppSettings>(r)),

  testProxy: (proxyUrl?: string) =>
    post<{ ok: boolean; proxy: string | null; status?: number; error?: string }>(
      "/api/settings/test-proxy",
      { proxy_url: proxyUrl ?? "" },
    ),

  about: () => fetch(`${BASE}/api/about`).then((r) => json<AboutInfo>(r)),

  diagnosticsUrl: () => `${BASE}/api/diagnostics`,

  /* jobs v2: cancel + the SSE stream (polling stays as the fallback) */
  cancelJob: (id: string) =>
    fetch(`${BASE}/api/jobs/${id}/cancel`, {
      method: "POST",
      headers: writeHeaders(),
    }).then((r) => json<{ canceled: boolean }>(r)),

  jobs: (activeOnly = false) =>
    fetch(`${BASE}/api/jobs${activeOnly ? "?active=true" : ""}`).then((r) =>
      json<Job[]>(r),
    ),

  sources: () =>
    fetch(`${BASE}/api/sources`).then((r) =>
      json<{ name: string; label: string }[]>(r),
    ),

  search: (
    query: string,
    opts: { sources?: string[]; duration?: number; sort?: string } = {},
  ) =>
    post<{
      results: SearchHit[];
      errors: { source: string; error: string }[];
      statuses: Record<string, "ok" | "empty" | "error">;
      sort: string;
    }>(
      "/api/search",
      { query, ...opts },
    ),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/api/uploads`, {
      method: "POST",
      headers: writeHeaders(),
      body: form,
    }).then((r) => json<UploadInfo>(r));
  },

  buildFromSource: (
    song: SearchHit,
    opts: {
      upload_id?: string;
      title?: string;
      artist?: string;
      lyric_start?: string;
      audio_start?: string;
    },
  ) => post<{ job_id: string; name: string }>("/api/build", { song, ...opts }),

  buildFromText: (payload: {
    upload_id: string;
    lyrics: string;
    title?: string;
    artist?: string;
    translate?: boolean;
  }) => post<{ job_id: string; name: string }>("/api/build-text", payload),

  job: (id: string) => fetch(`${BASE}/api/jobs/${id}`).then((r) => json<Job>(r)),

  /* whisper model extension pack for the custom-lyrics mode */
  modelStatus: () =>
    fetch(`${BASE}/api/models/status`).then((r) =>
      json<{ installed: boolean; path: string; asset: string }>(r),
    ),
  installModel: () =>
    fetch(`${BASE}/api/models/install`, {
      method: "POST",
      headers: writeHeaders(),
    }).then((r) => json<{ job_id: string | null; installed?: boolean }>(r)),

  songs: () => fetch(`${BASE}/api/songs`).then((r) => json<SongSummary[]>(r)),

  /* deep export-environment probe, run fresh on every 导出视频 click */
  exportEnv: () =>
    fetch(`${BASE}/api/export/env`).then((r) => json<ExportEnv>(r)),

  fixExport: () =>
    post<{ job_id: string }>("/api/export/fix", {}),

  installChromium: () =>
    post<{ job_id: string | null; installed?: boolean }>(
      "/api/export/install-chromium",
      {},
    ),

  exports: () =>
    fetch(`${BASE}/api/exports`).then((r) =>
      json<{ file: string; size: number; created: number; url: string }[]>(r),
    ),

  // `hideCards` rides along so the headless recorder page (a fresh browser
  // profile that can't see this window's localStorage) hides the vocab row
  // exactly like the stage the user is looking at.
  startExport: (song: string, hideCards = false) =>
    post<{ job_id: string; file: string }>("/api/export", {
      song,
      hide_cards: hideCards,
    }),

  remove: (name: string) =>
    fetch(`${BASE}/api/songs/${encodeURIComponent(name)}`, {
      method: "DELETE",
      headers: writeHeaders(),
    }).then((r) => json<{ deleted: string }>(r)),

  /* persist card edits for one segment of a dataset */
  patchSong: (name: string, patch: { id: number } & Record<string, unknown>) =>
    fetch(`${BASE}/api/songs/${encodeURIComponent(name)}`, {
      method: "PATCH",
      headers: writeHeaders({ "content-type": "application/json" }),
      body: JSON.stringify(patch),
    }).then((r) => json<Record<string, unknown>>(r)),

  /* song-wide lyric/audio offset, kept in the dataset's meta (export reads it) */
  setTimeOffset: (name: string, timeOffset: number) =>
    fetch(`${BASE}/api/songs/${encodeURIComponent(name)}`, {
      method: "PATCH",
      headers: writeHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({ time_offset: timeOffset }),
    }).then((r) => json<{ time_offset: number }>(r)),

  /* translation visibility, same meta channel — the export page reads it too */
  setTransHidden: (name: string, hidden: boolean) =>
    fetch(`${BASE}/api/songs/${encodeURIComponent(name)}`, {
      method: "PATCH",
      headers: writeHeaders({ "content-type": "application/json" }),
      body: JSON.stringify({ trans_hidden: hidden }),
    }).then((r) => json<{ trans_hidden: boolean }>(r)),

  /* stage background: stored server-side so the export sees it too */
  background: () =>
    fetch(`${BASE}/api/ui/background`).then((r) => json<StageBackground>(r)),

  setBackground: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/api/ui/background`, {
      method: "POST",
      headers: writeHeaders(),
      body: form,
    }).then((r) => json<StageBackground>(r));
  },

  resetBackground: () =>
    fetch(`${BASE}/api/ui/background`, {
      method: "DELETE",
      headers: writeHeaders(),
    }).then((r) => json<StageBackground>(r)),
};

export const audioUrl = (name: string) =>
  `${BASE}/api/audio/${encodeURIComponent(name)}`;

export const songUrl = (name: string) =>
  `${BASE}/api/songs/${encodeURIComponent(name)}`;

/** Poll a job until it settles. */
export async function waitForJob(
  id: string,
  onTick?: (job: Job) => void,
  interval = 600,
): Promise<Job> {
  for (;;) {
    const job = await api.job(id);
    onTick?.(job);
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((res) => setTimeout(res, interval));
  }
}
