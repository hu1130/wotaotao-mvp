# Omni 语音停顿卡死与自动恢复修复说明

## 1. 问题现象

浏览器检测到用户长时间停顿后显示“正在回答”，但部分复用的 Omni 长连接没有返回最终 ASR 或服务端 VAD 结束事件。旧实现随后直接进入覆盖 ASR、RAG 和 TTS 的统一等待，最坏约 88 秒后才失败。

这段时间内前端状态为 `isListening=false`、`isDialogBusy=true`。麦克风监控节点仍在运行，但新的声音不会上传，因此用户感受到的是“数字人没有回答，而且继续说话也无法识别”。

## 2. 根因

问题由三个状态共同造成：

1. 客户端 VAD 发出 `stop` 后立即停止本轮音频上传。
2. Omni 复用连接偶发没有返回事件 459，服务端无法进入最终 ASR、意图路由和回答生成。
3. `finish_audio()` 在 ASR 尚未完成时使用了完整 RAG 等待预算；前端同时用 120 秒总轮次看门狗，恢复过慢。

旧前端还把“WebSocket 仍然存在”等同于“数字人正在发声”，导致等待回答期间的 VAD 被完全屏蔽。

## 3. 修复设计

### 3.1 分阶段超时

停止录音后的等待拆为两个阶段：

- ASR 最终识别阶段：从收到客户端 `stop` 开始计时，总时限由 `REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS` 控制，默认 6 秒，其中包含为了触发服务端 VAD 而发送的静音补帧时间。
- 回答阶段：只有收到最终 ASR 后，才进入原有的意图路由、RAG 和 TTS 分级超时。

ASR 超时后，服务端执行以下原子恢复流程：

1. 将当前输入标记为结束，拒绝迟到 ASR。
2. 向上游发送 interrupt。
3. 立即关闭并淘汰当前 Omni 物理连接。
4. 向浏览器发送带 `code=asr_final_timeout` 的可恢复错误和 `done`。
5. 下一轮开始前建立新的 Omni 连接。

回答阶段总超时也会淘汰连接，防止迟到的旧音频污染下一轮。

### 3.2 浏览器本地恢复

浏览器新增 9 秒 ASR 最终结果看门狗。服务端错误、网络中断或消息丢失导致浏览器始终收不到最终 ASR 时，浏览器会主动关闭旧 WebSocket、清空 busy/音频队列并恢复 VAD，不再等待 120 秒总轮次看门狗。

页面资源版本已更新为 `20260714-voice-recovery`，避免浏览器继续使用缓存的旧状态机。

### 3.3 等待回答期间允许用户打断

当本轮已经停止收音、尚未开始播放数字人语音，而且没有待播放音频时，持续麦克风监控会继续检测用户人声。检测到有效语音后：

1. 旧轮次立刻失效，旧 WebSocket 被关闭。
2. 未完整完成的问答不会写入浏览器会话历史。
3. 使用 VAD 预录缓冲创建新 WebSocket 和新轮次，避免吞掉新一句话的开头。
4. 旧轮次的回调携带旧 `turnId`，无法更新新轮次 UI 或播放旧音频。

数字人实际播放音频时仍保持自回声抑制，避免扬声器声音被误判为用户打断。

## 4. 配置

```env
# 客户端停止说话后等待 Omni 最终识别/服务端判停的总时限（含静音补帧）
REALTIME_DIALOG_ASR_FINAL_TIMEOUT_SECONDS=6

# Omni 模式下客户端兜底判停静音时长，默认 8 秒，优先让服务端 VAD 判停
VOICE_PIPELINE_CLIENT_VAD_FALLBACK_MS=8000
```

该配置已加入 `.env.server` 和 `.env.server.example`。不建议把它调到低于 4 秒，否则高网络抖动环境中可能提前淘汰本可恢复的连接；也不建议高于 10 秒，否则前台交互会重新出现明显停顿。

## 5. 日志与定位

正常轮次应依次出现：

```text
Omni 收到客户端结束兜底
Omni 服务端判停
Omni 语音轮次完成
```

异常恢复会记录：

```text
Omni 客户端停顿后未收到最终识别，立即回收连接
Omni 上游通道已标记回收
Omni 上游物理连接已回收
```

浏览器本地看门狗触发时，服务端 avatar 日志会出现：

```text
voice asr final watchdog fired
```

用户在等待回答时重新开口，会出现：

```text
vad speech start ... interruptsPendingResponse=true
voice turn cancelled
voice turn start
```

## 6. 回归验证

自动化覆盖以下场景：

- Omni 不返回最终 ASR 时，在独立短超时内发送可恢复错误并淘汰连接。
- ASR 已结束时继续等待正常回答，不误触发短超时。
- 超时后的下一轮会先重建 Omni 物理连接。
- 等待回答且尚未播放音频时允许新语音打断。
- 正在监听、正在播放或音频已排队时不重复开启轮次。
- 超时状态文本明确告知用户已经恢复监听。

本地验证命令：

```powershell
node --test server_deploy/avatar/tests/voice_turn_policy.test.js
node --check server_deploy/avatar/avatar.js
cd server_deploy
python -m unittest tests.test_omni_voice
```

## 7. 部署与回滚

同步 `.env.server`、Python API、avatar 页面及策略文件后，同时重建 `api` 和 `avatar`。等待两者健康后重启 Nginx，使其重新解析容器地址。

如需回滚，恢复本次提交前的源码和 `.env.server`，重新构建 `api/avatar`。本次修改不包含数据库迁移，也不会修改人物记忆、员工、人脸、知识库或租户数据。
