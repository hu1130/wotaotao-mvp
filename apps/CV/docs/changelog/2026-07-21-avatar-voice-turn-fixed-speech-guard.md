# 2026-07-21

## 问题

线上用户开口后，浏览器麦克风和后端语音 WebSocket 均已收到音频，但 avatar 前端随后收到 `repeat` 等固定话术事件，触发“打断空监听”逻辑并取消当前语音轮次，导致 ASR 尚未返回最终文本时连接关闭，表现为“说话不识别”。

## 原因

固定话术仲裁只判断当前是否处于本地对话监听、是否无播放音频和无已显示文本，没有区分这轮监听是否已经由真实用户语音触发。自动 VAD 已确认用户开始说话并发送音频后，仍可能被入场重复问候当作空监听取消。

## 修改方案

- avatar 前端新增本轮用户语音证据状态，自动 VAD、抢话 VAD、手动监听后的有效人声和 ASR 停止处理都会阻止固定话术打断。
- 固定话术仍可打断真正空的手动监听轮次，保留原有“空监听让位”能力。
- 纯策略层增加防御判断，避免调用方误传 `interruptsIdleListening` 时放行已有用户语音的轮次。
- 数字人页和漩涡页脚本版本更新，确保浏览器加载新的仲裁逻辑。

## 影响

影响 `server_deploy/avatar/` 的实时语音监听和固定话术优先级仲裁。不会改变 ASR、TTS、人物性格或音色配置；固定问候、签到、重复到场等事件在真实用户说话时会排队或按既有规则丢弃，不再取消识别。

## 验证

- 已运行 `node --check server_deploy/avatar/avatar.js`
- 已运行 `node --check server_deploy/avatar/voice_turn_policy.js`
- 已运行 `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- 已同步到服务器并重建 `avatar` 容器，健康接口 `/healthz`、`/health` 均返回正常。
