# Agent1 交付：修复实时语音回复后固定语录不播报

## 问题现象

用户反馈新增“叮当”唤名后，数字人实时语音回复结束，后续人脸识别触发的固定语录不再自动播报。

## 根因

服务器 API 正常发送固定语音事件，avatar 也正常收到事件；日志显示前端持续输出 `wait queued avatar event`，阻塞详情中只有 `voiceStreamOpen=true`，其他状态均为空闲：

- `isDialogBusy=false`
- `streamingAudioPlaying=false`
- `streamingAudioQueue=0`
- `hasAudio=false`
- `audioLockedMs=0`

前端旧逻辑在 `canRunScheduledAvatarEvent()` 中要求 `!voiceStreamWs`。Omni 人物会话为了复用上下文，会在回复结束后保留 `keepOpen` 长连接；因此固定语录在“空闲但 WebSocket 常驻”的状态下永远排队，最终过期或被低优先级策略丢弃。

“叮当”提交没有直接修改 avatar 固定语录队列，但唤名后现场更容易进入实时语音长连接复用状态，所以暴露了该旧判断。

## 修复方案

1. 在 `server_deploy/avatar/voice_turn_policy.js` 增加 `canRunFixedSpeechEvent(state)`，集中判断固定语录何时可播放。
2. 将 `server_deploy/avatar/avatar.js` 的队列放行条件改为策略调用。
3. 保留原有语音冲突约束：用户正在说话、数字人正在回复、流式音频播放中、有音频队列、有当前音频、有音频锁时仍不播放固定语录。
4. 仅允许 `voiceStreamOpen=true && voiceStreamKeepOpen=true` 的空闲长连接状态播放固定语录。
5. 阻塞日志增加 `voiceStreamKeepOpen` 字段，后续排查能区分“忙碌连接”和“空闲复用连接”。

## 修改文件

- `server_deploy/avatar/voice_turn_policy.js`
- `server_deploy/avatar/avatar.js`
- `server_deploy/avatar/tests/voice_turn_policy.test.js`

## 验证

本地验证：

```powershell
node --check server_deploy\avatar\avatar.js
node --check server_deploy\avatar\voice_turn_policy.js
node --test server_deploy\avatar\tests\voice_turn_policy.test.js
```

结果：11 条测试全部通过。

服务器验证：

```bash
cd /opt/server_deploy
docker compose --env-file .env.server -f docker-compose.deploy.yml build avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
curl -fsS http://127.0.0.1/health
curl -fsS http://127.0.0.1/healthz
docker compose --env-file .env.server -f docker-compose.deploy.yml exec -T avatar node --test tests/voice_turn_policy.test.js
```

结果：

- API 健康接口通过。
- avatar 健康接口通过。
- nginx healthy。
- avatar 策略测试 11 条全部通过。

## Agent2 复测建议

1. 打开客户端并完成一次实时语音对话，确认数字人回复结束后处于可继续唤醒状态。
2. 保持用户在画面中或短暂离开再回来，触发 `repeat`、`checked_in_stare` 或到场任务播报。
3. 检查 avatar 日志不再持续出现 `wait queued avatar event` 且阻塞详情仅为 `voiceStreamOpen=true`。
4. 确认真正对话中固定语录不会插入用户讲话或数字人回复。
