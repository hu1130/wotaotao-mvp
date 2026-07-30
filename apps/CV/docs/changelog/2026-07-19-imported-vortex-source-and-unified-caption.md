# 2026-07-19 Imported Vortex Source And Unified Caption

## Problem
- The imported vortex UI source was still living in `D:\Download\zip`, outside the repository workspace.
- The bottom bar still rendered visitor recognition and digital-human reply as two separate transcript rows, which did not match the normal digital-human subtitle/status display.

## Cause
- The imported UI was originally copied as a build artifact workflow, so the editable source was not kept with the project.
- The previous compact bar still modeled the transcript as two fields instead of one active caption surface.

## Changes
- Added the imported UI source under `frontend_sources/imported-vortex-frontdesk`.
- Excluded `node_modules/`, `.next/`, and `out/` from the imported source tree.
- Changed the bottom bar center area into one unified caption display:
  - Idle: `语音对话` / `等待访客开口...`
  - Visitor speech: `访客识别` with the recognized text.
  - Digital-human speech: `数字人` with the assistant reply.
  - Voice status: `语音状态` with the runtime status text.
- Rebuilt and copied the static output into `server_deploy/avatar/imported-ui`.

## Validation
- `node .\node_modules\next\dist\bin\next build` in `frontend_sources/imported-vortex-frontdesk`
- `git diff --check`
- Verified the generated static page no longer contains the split `等待数字人回复...` fallback or old call controls.
- Synced to `myserver:/opt/server_deploy/avatar/imported-ui`, rebuilt `avatar`, restarted `nginx`, and verified `/health`, `/healthz`, `/imported-ui/`, plus a full imported-ui old-marker scan.
