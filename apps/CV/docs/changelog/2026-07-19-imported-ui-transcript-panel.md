# 2026-07-19 Imported UI Transcript Panel

## Background
- The imported vortex frontdesk UI still used call-control affordances such as the center microphone, `End Call`, and `00:15 / Live`.
- The user wants this page to behave like the other digital-human pages: keep the voice runtime, memory, fixed phrases, and speech flow, but replace avatar body feedback with vortex feedback.

## Root Cause
- The imported visual page was carrying presentational controls from the original static design.
- The avatar runtime already had ASR and TTS state, but it did not expose separate visitor-recognition and assistant-speaking text fields for the imported UI to render.

## Changes
- Removed the imported UI bottom call controls and center microphone presentation.
- Added a two-column glass transcript panel:
  - `访客识别语音` for recognized visitor speech.
  - `数字人回复` for digital-human speaking text.
- Added `visitorSpeechText` and `assistantSpeechText` to the avatar runtime broadcast state.
- Wired non-streaming and streaming voice paths so ASR partial/final text and assistant answer text update the imported UI in real time.
- Rebuilt and copied the exported imported UI into `server_deploy/avatar/imported-ui`.

## Validation
- Next.js imported UI build succeeded.
- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/control.js`
- `npm test` in `server_deploy/avatar`
- `python scripts/check-runtime-boundaries.py`
- `git diff --check`
- Local preview `http://127.0.0.1:8787/imported-ui/` returns the new transcript panel and no longer includes `End Call`, `00:15`, or the center microphone label.
- Synced to `myserver:/opt/server_deploy/avatar`, rebuilt `avatar`, restarted `nginx`, and verified `/health`, `/healthz`, `/imported-ui/`, and protected `/vortex-runtime.html`.
