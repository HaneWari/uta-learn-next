# AGENTS.md

Guidance for AI coding agents working on **Uta Learn Next** — a karaoke-style Japanese
learning app (FastAPI backend + React/Vite frontend, packaged as a no-install portable).

---

## Project at a glance

- **Backend** — `backend/`, Python >= 3.12, FastAPI + uvicorn. `main.py` only assembles
  middleware and routers; the routes live in `app/api/` (config, songs, export, packs,
  settings, update, stage). Optional extras: `speech` (whisper + fugashi),
  `export` (playwright), `gpu` (torch), `desktop` (pywebview), `dev` (ruff/pytest).
- **Desktop** — `desktop.py` at the repo root runs the server in-process, picks a free
  port, waits for the API and opens a pywebview window (system browser if WebView2 is
  missing). The portable build ships `UtaLearn Next.exe` (the double-click entry,
  compiled from `tools/launcher/Launcher.cs`) plus a console-only `.cmd` for
  debugging. `desktop.py` sets the extension-pack environment itself, so every
  entry point shares one code path and no `.cmd` wrapper has to duplicate it.
- **Frontend** — `frontend/`, React 19 + TypeScript + Vite 7. Strict TS (`strict`,
  `noUnusedLocals`, `noUnusedParameters`, `erasableSyntaxOnly`). Pure logic lives in
  `src/lib/` so vitest can cover it without mounting React.
- **Data** — `localdata/<song>/song_data.json` is the unit of truth for a dataset
  (segments, word timings, vocab overrides, `meta.view`). Schema v2: every file carries
  `schema_version` and `revision`; all writes go through `app/repo.py`.
  `localdata/` and `exports/` are gitignored.
- **Build** — `tools/build_portable.py` emits the portable zip and `update.json` (the
  update manifest the app reads — never a human download; the name is fixed because
  the updater fetches `releases/latest/download/update.json`). A patch is only built
  when `--patch-from <version>` says an older build can install it: the release that
  first ships the updater has nothing to patch *from*, so it must not carry a patch
  asset. Whenever one is built it is named `auto-update-patch.zip` — no version
  prefix, same URL shape for every release. The build prunes
  pip/setuptools/onnxruntime, ships
  **only** `ffmpeg.exe` (duration comes from `binaries.probe_duration`, no ffprobe),
  re-quantises the whisper pack to int8 (~461 → 237 MB) and drops Playwright's
  `chrome-headless-shell` from the Chromium pack (~333 → 209 MB).

## How to run

```bash
# Backend (hot reload) — needs ffmpeg on PATH or the /api/songs probe returns 500
cd backend && python -m uvicorn main:app --reload --port 8000

# Frontend (vite dev server, proxies API to :8000)
cd frontend && npm run dev

# Desktop shell (server in-process + pywebview window)
python desktop.py --port 8000

# Quality gates — the same set CI runs
cd backend && python -m ruff check . && python -m pytest
cd frontend && npx eslint src && npx tsc --noEmit && npm test && npm run build
```

`dev.cmd` / `dev.sh` are the one-shot launchers for source checkouts.

## Conventions

- **Language** — the UI, README, code comments and commit messages are in Chinese
  (Simplified). Keep it that way; don't translate user-facing strings.
- **Comments** — explain *why*, not *what*. Short paragraph-style comments above a
  block are the house style; no inline trailing comments unless truly needed, and
  never license headers.
- **Naming** — snake_case in Python, camelCase/PascalCase in TS/React. Don't rename
  existing identifiers just for style.
- **Errors** — backend raises `HTTPException` with a Chinese `detail`; frontend shows
  them raw. Don't wrap in extra error envelopes.
- **State** — the karaoke stage derives everything from `song_data.json` + the
  `segments` list. Any edit path (card override, lyric override, hidden flag,
  `meta.view`) must round-trip through `PATCH /api/songs/{name}`, never a side channel.
  Display layers used to be split between localStorage and `meta.trans_hidden`;
  `meta.view` is now the single copy — don't reintroduce a browser-local one.
- **Reading marks** — users annotate a custom reading inline as `[汉字](よみ)`
  (full-width `【】()` also accepted, romaji readings like `[明日](asu)` work).
  `dicts.parse_reading_marks` strips the mark-up *before* tokenisation and
  `apply_reading_marks` re-writes the token `kana`/`romaji` after, so the tagger
  never sees the brackets and the per-glyph wipe survives.
- **Karaoke sweep** — the karaoke style paints one continuous front, never a
  per-glyph fill. `lib/karaokeSweep.buildLine` maps words to `rubyGroups` and a
  flat glyph list; `KaraokeStage` stacks three identical layers (before / after /
  scanline) and moves a single `clip-path` x, interpolating across gaps between
  glyphs. The scanline mask must stay inside glyph shapes — a plain vertical
  bar across the row reads as a bug, not as karaoke. Colours and sizes come from
  `lib/karaokeStyle.ts` (`KaraokeColorState`-style before/after text + stroke),
  scaled off a 1080p baseline so 4K exports keep the same weight.
- **Romaji has two readings** — `enrich` stores `kana`/`kana_literal` and
  `romaji`/`romaji_literal`; particles differ (は → `ha` literal, `wa` sung). The
  browser picks one per setting (`lib/romaji.ts`). Never bake a single form in.

## Things that bite

- **ffmpeg on PATH** — dev backend 500s on `/api/songs` without `ffprobe`; the
  portable build puts it in `bin/`. Set `PATH=D:\uta-build\ffmpeg-slim;...` when
  debugging locally.
- **Vocab row layout** — cards are `flex: 0 0 calc((100% - 3*gap)/4)` on purpose
  (fixed 4-up width). Don't add `flex:1`/`wrap` — it regressed to two rows before.
- **Right-click zone** — `.vocab` has `overflow-y:auto`, so a `::before` bleed for a
  wider context-menu hit area gets clipped. The wide zone lives in a document-level
  `contextmenu` listener in `VocabCards.tsx`, not CSS.
- **Lyric edits & highlight** — only write `lyric_override.text` when the text
  actually changed; a translation-only edit must not kill the per-glyph wipe.
  When `text` *did* change the PATCH route re-tokenises it (`builder.retime_words`)
  into `lyric_override.words` + `grammar`, so an edited line still shows furigana,
  romaji and a re-estimated wipe. Render and highlight must both read
  `lib/words.effectiveWords(seg)` — reading `seg.words` on one side and the override
  on the other desyncs the wipe.
- **Export port** — `api_export` derives the recorder URL from the incoming request.
  Never hardcode 8000: the launcher picks the first free port in 8000–8010, and a
  hardcoded default made every export on :8011 record a dead page.
- **Export output must have video** — ffmpeg happily writes an audio-only MP4 when the
  filter chain produced zero frames (happened when the progress-bar calibration read the
  card row's orange accent in portrait). `_has_video()` guards both muxes; keep that
  check when touching the calibration path.
- **`no_recorder` is not a failure** — the frame renderer needs no Playwright video
  component, so `env_check` returns `ok` with `compat_ready: false` on such a machine.
  Only `no_playwright` / `no_browser` / `no_ffmpeg` block an export.
- **whisper is an extension pack** — `fallback._transcribe_chunked` loads a bundled
  `models/whisper-small/` straight off disk. The model is *never* pulled from
  HuggingFace — a missing pack is a hard, actionable error, and the config page can
  one-click-install it (`POST /api/models/install`, `GET /api/models/status`).
  Build the pack with `tools/build_portable.py --custom-pack`; it is
  version-independent (`UtaLearnNext-custom-lyrics.zip`, whisper + ja-zh translation).
- **fallback alignment is chunked + kana-global** — `build_from_audio` runs
  `_transcribe_chunked` (30 s windows, keeps only each window's trusted middle), then
  `_kana_match` does a single Needleman–Wunsch over all lyric kana vs all transcript
  kana (kanji on either side is read through `analyze`), and `_anchor_rows`/`_line_times`
  turn matched kana into per-char times. Lines with no anchors are interpolated; a
  leading run of unmatched lines is clipped (`found[0] > 2`) as is a trailing run past
  `song_end` (the last transcript word's end, not the file duration).
- **Jobs are per-resource** — `jobs.create(kind, resource)` then `jobs.run(jid, fn)`.
  `cpu` / `export` run one at a time, `net` two. Long loops must call `progress()`:
  that is where cancellation is checked.
- **Export is frame-by-frame** — `render=1` installs `window.__utaSeek.seek(t)` and
  `__utaReady`; `app/render_frames.py` screenshots each 60 fps frame through CDP and
  pipes it into one x264 pass. The old recorder survives only behind
  `settings.export_compat`. Never reintroduce a wall-clock/realtime path as the default.
- **Cards: one rule** — `app/vocab_rules.content_flag` decides whether a token earns a
  card, for both build pipelines. Don't call `dicts.is_content` directly in a pipeline.
- **View state** — `store/viewStore.ts` (zustand) holds the session's layer overrides;
  `meta.view` is the persisted truth. Both must agree, and the export reads the URL
  flags derived from them.
- **Generated types** — `frontend/src/api-types.ts` comes from
  `python tools/gen_api_types.py`; CI runs it with `--check`.
- **`.git` is read-only in the sandbox** — commits and pushes require escalation.

## Git

- **Branch model** — `dev` is the working branch; `main` only receives merges that
  are ready to ship. Develop, test and commit on `dev`; merge into `main` when a
  version is verified. `main` currently sits at the v1.3.0 release (`95c3e73`) and
  intentionally does *not* contain the v2 work.
- **Remotes** — only `origin` -> `HaneWari/uta-learn-next`. The upstream project
  (`rafaelanobre/utalearn`) is no longer tracked; don't re-add it.
- **Commits** — Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, etc.),
  English subject, optional scope (`cards`, `export`, `sources`, `ui`). Body explains
  the *why* when it isn't obvious.
- **Pushing** — push `dev` for work in progress. Push `main` only as part of a
  deliberate release merge. Push only when the task calls for it or the user asks.
- **Don't rewrite** published history — except the one deliberate reset that moved
  `main` back to the v1.3.0 release.

## Testing

- `npx tsc --noEmit` must pass before touching anything else in the frontend.
- `ruff check backend/` for backend style (line length 100, py312).
- `python -m pytest` in `backend/` — 300 tests, fully offline (lyric sources are faked).
  `npm test` in `frontend/` — vitest, 84 cases.
- `tools/check_export_sync.py` is the regression harness for audio-video timing — run
  it when touching `export.py`.
- `python tools/smoke_portable.py <folder>` boots a built portable and checks
  `/api/version`, `/api/songs` and the SPA; `--ci` builds without zip/chromium for it.
- Playwright E2E lives in ad-hoc scripts, not a suite; write one to `*.py` when
  verifying a UI change end-to-end and delete it after.

## Don't touch

- `localdata/`, `exports/`, `_update/`, `app.prev/` — user data and update state.
- `backend/app/data/` dictionaries unless regenerating them on purpose.
- `backend/app/version.py` is the single source of the version number; the API and the
  build script both read it. Don't hardcode a version anywhere else.
- Release tags and published assets on GitHub.
