# AGENTS.md

Guidance for AI coding agents working on **Uta Learn Next** — a karaoke-style Japanese
learning app (FastAPI backend + React/Vite frontend, packaged as a no-install portable).

---

## Project at a glance

- **Backend** — `backend/`, Python >= 3.12, FastAPI + uvicorn. Single process serves the
  API and, once `frontend/dist` exists, the built SPA. Optional extras: `speech`
  (whisper + fugashi), `export` (playwright), `gpu` (torch), `dev` (ruff).
- **Frontend** — `frontend/`, React 19 + TypeScript + Vite 7. Strict TS (`strict`,
  `noUnusedLocals`, `noUnusedParameters`, `erasableSyntaxOnly`).
- **Data** — `localdata/<song>/song_data.json` is the unit of truth for a dataset
  (segments, word timings, vocab overrides). `localdata/` and `exports/` are gitignored.
- **Build** — `tools/build_portable.py` assembles the portable zip (embeds Python,
  ffmpeg, built frontend, optional Chromium under `browsers/`).

## How to run

```bash
# Backend (hot reload) — needs ffmpeg on PATH or the /api/songs probe returns 500
cd backend && python -m uvicorn main:app --reload --port 8000

# Frontend (vite dev server, proxies API to :8000)
cd frontend && npm run dev

# Type check & build
cd frontend && npx tsc --noEmit && npm run build
```

`dev.cmd` / `dev.sh` are the one-shot launchers for end users.

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
  `segments` list. Any edit path (card override, lyric override, hidden flag) must
  round-trip through the `PATCH /api/songs/{name}` route, never a side channel.
- **Reading marks** — users annotate a custom reading inline as `[汉字](よみ)`
  (full-width `【】（）` also accepted, romaji readings like `[明日](asu)` work).
  `dicts.parse_reading_marks` strips the mark-up *before* tokenisation and
  `apply_reading_marks` re-writes the token `kana`/`romaji` after, so the tagger
  never sees the brackets and the per-glyph wipe survives.

## Things that bite

- **ffmpeg on PATH** — dev backend 500s on `/api/songs` without `ffprobe`; the
  portable build puts it in `bin/`. Set `PATH=D:\uta-build\ffmpeg-slim;...` when
  debugging locally.
- **Vocab row layout** — cards are `flex: 0 0 calc((100% - 3*gap)/4)` on purpose
  (fixed 4-up width). Don't add `flex:1`/`wrap` — it regressed to two rows before.
- **Hidden cards in export** — the headless recorder has no `localStorage`; the
  `hidecards` flag goes in the export URL query, not the profile.
- **Right-click zone** — `.vocab` has `overflow-y:auto`, so a `::before` bleed for a
  wider context-menu hit area gets clipped. The wide zone lives in a document-level
  `contextmenu` listener in `VocabCards.tsx`, not CSS.
- **Lyric edits & highlight** — only write `lyric_override.text` when the text
  actually changed; a translation-only edit must not kill the per-glyph wipe.
  When `text` *did* change the PATCH route re-tokenises it (`builder.retime_words`)
  into `lyric_override.words` + `grammar`, so an edited line still shows furigana,
  romaji and a re-estimated wipe — it is not the verbatim static line it used to be.
- **whisper is an extension pack** — `fallback._transcribe` prefers a bundled
  `models/<name>/` dir (loaded straight off disk, works offline). The model is
  *never* pulled from HuggingFace — a missing pack is a hard, actionable error,
  and the config page can one-click-install it from the repo's latest release
  (`POST /api/models/install`, status via `GET /api/models/status`). Build the
  pack once with `tools/build_portable.py --whisper-pack`; it is version-
  independent and shipped as `UtaLearnNext-whisper-small.zip` on the release.
- **`.git` is read-only in the sandbox** — commits and pushes require escalation.

## Git

- **Commits** — Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, etc.),
  English subject, optional scope (`cards`, `export`, `sources`, `ui`). Body explains
  the *why* when it isn't obvious.
- **Pushing** — remote is `origin` -> `HaneWari/uta-learn-next` (GitHub). Push only
  when the task calls for it or the user asks.
- **Don't rewrite** published history.

## Testing

- `npx tsc --noEmit` must pass before touching anything else in the frontend.
- `ruff check backend/` for backend style (line length 100, py312).
- `tools/check_retime.py` and `tools/check_export_sync.py` are the regression
  harnesses for the audio-lyric timing logic — run them when touching
  `builder.py`/`retime.py`/`export.py`.
- Playwright E2E lives in ad-hoc scripts, not a suite; write one to `*.py` when
  verifying a UI change end-to-end and delete it after.

## Don't touch

- `localdata/`, `exports/` — user data, gitignored for a reason.
- `backend/app/data/` dictionaries unless regenerating them on purpose.
- Release tags and published assets on GitHub.
