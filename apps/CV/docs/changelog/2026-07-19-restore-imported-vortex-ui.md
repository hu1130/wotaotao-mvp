# Restore imported vortex UI

## 问题

The mainline was rolled back to the version without the imported vortex frontdesk UI, but the user decided to restore the saved vortex version.

## 原因

The vortex UI version had already been preserved at branch `codex/personal-vortex-ui-20260719` and tag `personal-vortex-ui-20260719`. Restoring it should bring the page and runtime integration back without rewriting git history.

## 修改方案

- Reverted the previous rollback commits for the imported UI series.
- Restored `/imported-ui/` static assets.
- Restored `vortex-runtime.html`.
- Restored the runtime bridge and same-window frontdesk surface switcher.
- Kept the saved branch and tag as a stable reference to the preferred vortex UI version.

## 影响

The mainline and server deployment should again expose the imported vortex frontdesk UI and allow switching between the normal avatar and vortex frontdesk surfaces from the control console.

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/control.js`
- `npm test` in `server_deploy/avatar` passed 17/17 tests.
- `python scripts/check-runtime-boundaries.py`
- `git diff --check`
- Confirmed `server_deploy/avatar/imported-ui/index.html` is restored.
- Confirmed `server_deploy/avatar/vortex-runtime.html` is restored.
- Confirmed `/imported-ui/` contains the hidden `/vortex-runtime.html` runtime iframe.
- Confirmed active runtime/control files contain `frontdesk-surface-switcher`, `SWITCH_FRONTDESK_SURFACE`, and `frontdeskSurface` markers.
