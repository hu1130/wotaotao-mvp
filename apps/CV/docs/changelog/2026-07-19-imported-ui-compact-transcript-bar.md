# 2026-07-19 Imported UI Compact Transcript Bar

## Background
- The previous imported vortex UI transcript change used two large bottom cards.
- The user wanted the original glass bottom-bar feeling back, with visitor recognition text and digital-human speech/status displayed together instead of split left and right.

## Changes
- Reworked the imported UI bottom transcript into a single rounded glass control bar.
- Kept `Mute` on the left to preserve the original control-bar rhythm.
- Combined `访客识别` and `数字人` into one central two-line transcript well.
- Kept the right side as a small voice-state pill instead of restoring `End Call`, `00:15 / Live`, or the center microphone.
- Rebuilt and copied the exported imported UI into `server_deploy/avatar/imported-ui`.

## Validation
- Next.js imported UI build succeeded.
- `git diff --check`
- Local preview `http://127.0.0.1:8787/imported-ui/` includes the compact transcript bar and does not include `End Call`, `00:15`, or the center microphone label.
- Synced to `myserver:/opt/server_deploy/avatar/imported-ui`, rebuilt `avatar`, restarted `nginx`, and verified `/health`, `/healthz`, `/imported-ui/`, plus a full imported-ui old-marker scan.
