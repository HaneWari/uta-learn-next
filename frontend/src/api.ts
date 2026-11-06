import type {
  Job,
  SearchHit,
  SongSummary,
  StageBackground,
  UploadInfo,
} from "./types";

// relative paths: the vite dev server proxies /api and /poc to :8000
const BASE = "";

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
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => json<T>(r));
}

export const api = {
  sources: () =>
    fetch(`${BASE}/api/sources`).then((r) =>
      json<{ name: string; label: string }[]>(r),
    ),

  search: (query: string, sources?: string[]) =>
    post<{ results: SearchHit[]; errors: { source: string; error: string }[] }>(
      "/api/search",
      { query, sources },
    ),

  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/api/uploads`, { method: "POST", body: form }).then(
      (r) => json<UploadInfo>(r),
    );
  },

  buildFromSource: (
    song: SearchHit,
    opts: { upload_id?: string; title?: string; artist?: string },
  ) => post<{ job_id: string; name: string }>("/api/build", { song, ...opts }),

  buildFromText: (payload: {
    upload_id: string;
    lyrics: string;
    title?: string;
    artist?: string;
  }) => post<{ job_id: string; name: string }>("/api/build-text", payload),

  job: (id: string) => fetch(`${BASE}/api/jobs/${id}`).then((r) => json<Job>(r)),

  songs: () => fetch(`${BASE}/api/songs`).then((r) => json<SongSummary[]>(r)),

  exportStatus: () =>
    fetch(`${BASE}/api/export/status`).then((r) =>
      json<{ available: boolean; reason: string }>(r),
    ),

  exports: () =>
    fetch(`${BASE}/api/exports`).then((r) =>
      json<{ file: string; size: number; created: number; url: string }[]>(r),
    ),

  startExport: (song: string) =>
    post<{ job_id: string; file: string }>("/api/export", { song }),

  remove: (name: string) =>
    fetch(`${BASE}/api/songs/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }).then((r) => json<{ deleted: string }>(r)),

  /* stage background: stored server-side so the export sees it too */
  background: () =>
    fetch(`${BASE}/api/ui/background`).then((r) => json<StageBackground>(r)),

  setBackground: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/api/ui/background`, {
      method: "POST",
      body: form,
    }).then((r) => json<StageBackground>(r));
  },

  resetBackground: () =>
    fetch(`${BASE}/api/ui/background`, { method: "DELETE" }).then((r) =>
      json<StageBackground>(r),
    ),
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
