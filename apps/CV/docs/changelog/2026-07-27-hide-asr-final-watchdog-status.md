# ASR 最终识别兜底不显示到状态栏

## 问题

当 avatar 前端已经停止收音并等待最终 `asr_final`，但 9 秒内没有收到当前轮次有效识别结果时，会显示“没有收到识别结果，已恢复监听”。这条文案属于内部兜底恢复，不适合作为数字人状态栏内容展示给用户。

## 原因

ASR final watchdog 复用了 `finalizeStreamingDialogTurn(statusText)`，该函数默认会把 `statusText` 同时写入语音沟通文字和状态栏。超时兜底需要保留日志和语音层复位，但不需要用户可见提示。

## 修改方案

- `finalizeStreamingDialogTurn()` 增加 `suppressUserStatus` 选项。
- ASR final watchdog 触发时继续执行语音层复位，但不再写入状态栏或用户可见语音文字。
- 其它错误恢复文案不变，仍可正常提示真实连接异常。

## 影响

影响 avatar 前端 ASR 兜底超时展示。触发时当前语音 WebSocket 会被重置，麦克风监听仍保持，下一次用户说话会重新创建语音轮次。

## 验证

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
