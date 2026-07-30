# Frontdesk surface switch

## 问题

The control console exposed `/imported-ui/` as a normal link with `target="_blank"`. Clicking it opened a separate browser page, while the user expects it to switch the already running frontdesk window the same way avatar model switching works.

## 原因

The imported UI entry was not wired into the avatar WebSocket command channel. The active frontdesk page had no command for changing its visible surface, so the console could only open another page instead of instructing the device-owned avatar session to navigate.

## 修改方案

- Replaced the header link with a command button.
- Added a frontdesk surface switcher with `数字人` and `旋涡前台` options.
- Added `SWITCH_FRONTDESK_SURFACE` to the avatar runtime command handler.
- The active avatar runtime now reports `frontdeskSurface` in `STATE_SYNC`.
- Switching to vortex navigates the current frontdesk window to `/imported-ui/`; switching back navigates the same window to `/?model=...`.

## 影响

The console no longer opens a new browser tab for the imported UI. It controls the currently connected frontdesk/avatar session, preserving the trusted device-session boundary.

## 验证

- `node --check server_deploy/avatar/control.js`
- `node --check server_deploy/avatar/avatar.js`
- `npm test` in `server_deploy/avatar` passed 17/17 tests.
- `python scripts/check-runtime-boundaries.py`
- `git diff --check`
- Confirmed `control.html` no longer exposes the imported UI as a `target="_blank"` frontdesk link.
- Confirmed the control/runtime command path contains `SWITCH_FRONTDESK_SURFACE`, `frontdeskSurface`, and same-window `location.assign`.
