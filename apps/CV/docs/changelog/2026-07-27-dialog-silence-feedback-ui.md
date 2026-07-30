# 2026-07-27 数字人业务静音反馈 UI 修复

## 问题

数字人收到“静音/开启静音”后，业务静音状态会立即显示“静音中”，导致本轮静音反馈语音的状态栏文字被遮挡；如果浏览器端 `done` 事件早于音频播放完成到达，前端会提前结束反馈保护。

## 修复

- 静音控制反馈期间保持 `voiceDialogSilenceFeedbackActive`，直到浏览器流式音频队列真正播放结束后，再恢复“静音中，喊{名字}唤醒我”。
- 新增固定语录 UI 播放标记，签到、签退、陌生人等固定语录播放时不受业务静音状态栏保护影响，播完后再恢复静音提示。
- 静音状态仍只关闭实时沟通；喊数字人名字解除静音的服务端逻辑保持不变。

## 验证

- `node --check server_deploy\avatar\avatar.js`
- `npm test -- --runInBand` in `server_deploy\avatar`
- `python -m unittest -v tests.test_dialog_silence tests.test_dialog_actions` in `server_deploy`
- `git diff --check`
