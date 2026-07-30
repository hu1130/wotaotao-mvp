# Control frontdesk link

## 问题

The imported frontdesk UI was available from the avatar page switcher, but the enterprise control console did not provide a direct way to open it.

## 原因

The previous integration only touched the frontdesk display entry points. `control.html` still only exposed tenant operations, connection status, and model information.

## 修改方案

- Added a `前台展示` link in the control console header.
- Styled the link as a compact console action and allowed the header info group to wrap on narrow screens.
- The link opens `/imported-ui/` in a new tab so operators do not lose their current console state.

## 影响

Only the avatar control console UI is affected. No API, WebSocket command, tenant data, or voice pipeline behavior changed.

## 验证

- `git diff --check` passed.
- `GET /control.html` returned 200 locally.
- Browser screenshot QA confirmed the `前台展示` button renders in the console header without overlapping status text.
