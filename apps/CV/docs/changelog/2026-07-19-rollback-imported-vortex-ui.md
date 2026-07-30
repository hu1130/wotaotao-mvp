# Roll back imported vortex UI from mainline

## 问题

The imported vortex frontdesk UI should be kept as a personal version, but the current mainline should continue as the version without that added page.

## 原因

The imported UI work added a separate `/imported-ui/` surface, visual iteration assets, a hidden runtime bridge, and console switching controls. The user wants to preserve that implementation without keeping it active in the main working version.

## 修改方案

- Saved the full imported vortex UI version at commit `8c95e61`.
- Created branch `codex/personal-vortex-ui-20260719`.
- Created tag `personal-vortex-ui-20260719`.
- Reverted the imported UI commit series from `f16a6b5` through `8c95e61` on `master`.

## 影响

The mainline no longer contains the imported vortex page, `/imported-ui/` assets, `vortex-runtime.html`, or the same-window frontdesk surface switcher. The saved branch/tag can be checked out later to restore or continue the vortex UI version.

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/control.js`
- `npm test` in `server_deploy/avatar` passed 17/17 tests.
- `python scripts/check-runtime-boundaries.py`
- `git diff --check`
- Confirmed `server_deploy/avatar/imported-ui` is removed.
- Confirmed `server_deploy/avatar/vortex-runtime.html` is removed.
- Confirmed active runtime/control files no longer contain `imported-ui`, `vortex-runtime`, `SWITCH_FRONTDESK_SURFACE`, or `frontdesk-surface-switcher` markers.
