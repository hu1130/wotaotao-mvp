# Imported UI project voice state sync

## Background

The imported frontdesk UI had a polished center orb, but its communication feedback was still a local demo loop. That made the page look alive even when the avatar was not actually listening, understanding, or speaking.

## Root cause

The avatar page only exposed coarse control-panel state such as `isListening` and `voiceChatText`. The imported UI did not have a stable phase signal to drive its visual core, so it could not reflect the real voice interaction lifecycle.

## Changes

- Added `voicePhase`, `voicePhaseText`, and `voiceActivityLevel` to the avatar state sync payload.
- Updated the voice pipeline to emit phases for listening, understanding, speaking, ready, and error recovery.
- Rebuilt the imported UI so its center orb listens to the project's WebSocket `STATE_SYNC` messages instead of running a timed demo carousel.
- Kept the imported UI's visual structure intact; the change only wires the orb status and motion inputs to project state.

## Validation

- `next build` completed for the imported UI static export.
- `git diff --check` passed.
- `node --check server_deploy/avatar/avatar.js` and `node --check server_deploy/avatar/server.js` passed.
- `npm test` passed in `server_deploy/avatar`.
- Browser screenshot QA confirmed `/imported-ui/` renders and shows the waiting state when no avatar signal is available.
