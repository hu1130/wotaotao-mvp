# Remove avatar page switcher

## 问题

The avatar frontdesk page showed quick links for `数字人`, `语音展示`, and `外部UI`. These controls affected the frontdesk presentation, while switching is now handled from the control console.

## 原因

The links were an older page-level navigation helper. After adding console-based frontdesk surface switching, keeping the helper on the visible avatar page became redundant and visually distracting.

## 修改方案

- Removed the `#page-switcher` navigation from `server_deploy/avatar/index.html`.
- Removed the unused `#page-switcher` CSS rules from `server_deploy/avatar/styles.css`.

## 影响

The avatar frontdesk page no longer displays those top quick links. Existing console-based switching between avatar and imported vortex UI is unchanged.

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/control.js`
- `npm test` in `server_deploy/avatar` passed 17/17 tests.
- `python scripts/check-runtime-boundaries.py`
- `git diff --check`
- Confirmed `server_deploy/avatar/index.html` and `server_deploy/avatar/styles.css` no longer contain `page-switcher` or the removed quick-link labels.
