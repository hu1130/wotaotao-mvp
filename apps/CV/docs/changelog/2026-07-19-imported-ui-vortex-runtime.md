# Imported UI vortex runtime

## 问题

`/imported-ui/` only rendered the new visual shell and subscribed to status updates. It did not run the avatar client itself, so it could not receive avatar events, fixed greetings, realtime voice, RAG, memory, or playback lifecycle callbacks.

## 原因

The server routes business events to the active WebSocket client registered as `avatar`. The imported UI was registered as a passive `control` observer and therefore had no device-scoped avatar session, no voice ticket access, and no event queue ownership.

## 修改方案

- Added `vortex-runtime.html`, a hidden device-protected avatar runtime used by `/imported-ui/`.
- The hidden runtime keeps the existing avatar pipeline: device session, WebSocket avatar registration, fixed speech, realtime voice, memory/RAG, audio locks, and playback completion.
- Added a same-origin `postMessage` bridge so the runtime can push `STATE_SYNC` directly to the visible vortex UI without requiring a control-console session.
- Wired the visible `Mute`, microphone, and `End Call` controls to runtime commands.
- Extended avatar state sync so fixed speech and external realtime speech also drive the vortex `speaking/ready/error` states.
- Protected `vortex-runtime.html` with the same avatar device session check as the normal avatar page.

## 影响

The visible `/imported-ui/` page becomes a vortex-style frontdesk surface while preserving the existing backend voice and memory behavior. It still requires a valid avatar device session to run the full interaction stack; a control-console session alone cannot impersonate a frontdesk device.

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/server.js`
- `npm test` in `server_deploy/avatar` passed 17/17 tests.
- `python scripts/check-runtime-boundaries.py`
- `git diff --check`
- Local `/imported-ui/` returned 200 and the built HTML contains the hidden `/vortex-runtime.html` runtime iframe.
- Built imported UI chunks contain the runtime bridge and `VOICE_MUTE_SET`, `VOICE_CHAT_TOGGLE`, and `VOICE_END_CALL` command wiring.
