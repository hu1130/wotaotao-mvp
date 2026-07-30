# 2026-07-23

## 问题

数字人播放较长回答时，用户插话可以打断音频，但底部状态栏有时仍显示被打断前的回答分句，而不是“你说，我听着~”。短回答路径表现正常。

## 原因

长回答会走流式播放路径，并通过播放进度计时器持续把当前回答分句写入状态栏。打断逻辑虽然会停止播放并显示监听提示，但状态栏和语音文本写入口没有统一保护“打断后监听提示”的优先级，导致旧流式播放进度或清理流程在保护窗口内仍可能覆盖提示文案。

## 修改方案

- 在 `voice_turn_policy.js` 增加 `shouldProtectInterruptedListeningStatus` 策略函数，明确打断后监听提示优先于旧回答文本。
- 在 `avatar.js` 的 `showStatus`、`updateVoiceChatText` 和 `clearVoiceChatText` 写入口使用该策略，阻止旧播放分句或清空动作覆盖“你说，我听着~”。
- 增加 Node 单元测试覆盖打断监听提示对旧回答文本的保护规则。

## 影响

影响 avatar 浏览器端语音打断后的 UI 状态展示。不会改变 VAD 阈值、ASR、LLM、TTS 或音频打断逻辑。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
