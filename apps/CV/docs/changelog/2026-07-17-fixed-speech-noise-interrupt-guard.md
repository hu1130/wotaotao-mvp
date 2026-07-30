# 2026-07-17 固定语音防噪音打断

## 问题

签到、签退或 repeat 固定语音播放时，脚步声、关门声等环境噪音容易被前端 VAD 当作新语音，进而启动新语音轮次并取消当前语录，导致状态栏和播报不显示完整语录。

## 原因

固定语音使用 `legacy_tts` 语音槽。前端 `isSelfSpeechActive()` 对固定语音 owner 返回 `false`，因此固定语音加载或播放期间，只要固定语音噪声 guard 没覆盖住，自动 VAD 仍可能把环境噪音识别为新一轮用户输入并打断当前语音。

## 修改方案

固定语音 owner 活跃时，将其视为自发声保护状态。自动 VAD 在该状态下只更新噪声底线并重置候选，不启动新语音轮次。

## 影响

- 签到、签退、repeat 播报期间不再被脚步、关门等短促噪音打断。
- 实时对话回答播放时的真人抢话逻辑不变。
- 手动按钮仍可主动发起语音交互。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
