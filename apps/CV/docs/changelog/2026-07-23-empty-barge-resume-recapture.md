# 2026-07-23 空打断续播二次捕获

## 问题

用户第一次空打断实时语音回答后，数字人会显示“你说，我听着~”，随后继续说“刚才我接着说……”。如果用户在这段继续回答里再次空打断，状态栏不显示监听提示，随后只显示“没有识别到内容”，也不会继续回答。

## 原因

第一次空打断后，前端会把被打断的回答保存为 `pendingEmptyBargeResume`，空 ASR 后用 `playRawTTS` 本地续播。但旧逻辑在续播期间再次打断时直接跳过 `captureEmptyBargeResume()`，日志表现为 `empty barge resume skipped during resume playback`。因此第二次空 ASR 结束后没有 pending resume 可恢复，只能显示“没有识别到内容”。

同时，本地续播时 WebSocket 可能已被后端回收，旧状态文案分支只在可复用 WebSocket 的 barge-in 中显示“你说，我听着~”，导致二次空打断的监听提示缺失。

## 修改方案

- 为 `local_dialog` 的本地 TTS 续播记录当前播放文本和估算播放时长。
- 续播被再次打断时，不再跳过捕获，而是按当前播放进度保存当前句及后续文本为新的 `pendingEmptyBargeResume`。
- 本地对话续播音频被打断时，也显示与实时流式回答一致的监听提示。
- reset、播放结束、异常路径都会清理本地播放文本，避免旧回答残留。

## 影响

只影响 avatar 端实时对话空打断后的续播恢复。用户空打断续播时会继续保持“你说，我听着~”提示；如果用户说了有效内容，ASR partial/final 仍会清掉 pending resume，不会强行续播旧回答。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
