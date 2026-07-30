# 2026-07-23 二次打断后监听状态恢复

## 问题

数字人回答被用户打断一次后，会正常显示“你说，我听着~”并准备重新回答；如果这段继续回答再次被打断，状态栏不再显示监听提示。

## 原因

第一次打断命中实时语音流式回答的 barge-in 状态，前端会保护并显示监听文案。空打断后继续回答时，前端使用 `playRawTTS` 播放上一轮回答续句，此时 `activeSpeechOwner` 是 `local_dialog` 且浏览器存在本地音频，但 `isDialogBusy` 已在空 ASR 结束时重置为 `false`。旧策略要求 `isDialogBusy=true` 才把回答判定为实时对话回答，导致第二次打断不走受保护的监听状态分支。

## 修改方案

- 扩展 avatar 语音策略：`activeSpeechOwner=local_dialog` 且存在本地音频时，也视为实时对话回答活跃。
- 保持其他固定语音 owner 不可被误判为实时对话回答。
- 增加策略单测覆盖二次打断前的本地继续回答播放状态。

## 影响

只影响 avatar 端 VAD 打断状态判断。实时对话继续回答、本地续播回答在被用户打断时都会显示一致的监听提示；签到、签退、repeat 等受保护固定语音仍按原规则不可被用户打断。

## 验证

- `node --check server_deploy/avatar/voice_turn_policy.js`
- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
