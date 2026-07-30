# 固定语录噪声打断抑制修复方案

## 背景

用户反馈当前数字人播放固定语录时，容易被环境噪声频繁打断，导致原本的固定语录无法稳定播完。本次不实现“任何用户语音都能打断所有语录”的大改动，只先解决固定语录被噪声误打断的问题。

## 修改方案

1. 在 avatar 端新增固定语录噪声保护状态：
   - `fixedSpeechNoiseGuardEnabled`
   - `fixedSpeechPostGuardMs`
   - `fixedSpeechActive`
   - `fixedSpeechGuardUntil`
2. 将固定语录 owner `legacy_tts` 播放期间视为数字人自发声：
   - VAD 仍可持续更新噪声底线。
   - 但不会因为固定语录播放声、回声或短噪声开启新的用户语音轮次。
3. 固定语录播放结束、失败、过期、Abort 时都释放保护，并保留默认 1200ms 尾部保护，避免尾音/回声立刻触发。
4. 通过 `/dialog-settings` 下发运行时配置：
   - `FIXED_SPEECH_NOISE_GUARD_ENABLED=1`
   - `FIXED_SPEECH_POST_GUARD_MS=1200`
5. 修复 Raw TTS Abort 分支未释放 speech priority 的清理问题，避免取消后的旧优先级影响后续固定语录调度。

## 二次修正

现场反馈“说话没反应”后复查日志，发现固定语录保护在 TTS 请求刚拿到播放权时就开启，保护时长会使用 `DIALOG_AUDIO_LOCK_MAX_MS`，日志中出现 `holdMs: 120000`。当 repeat、到场任务、盯视语录连续触发时，用户真实说话可能在 TTS 生成等待阶段被当成数字人自发声吞掉。

已调整为：

1. 固定语录保护只在音频 `playing` 后开启，按实际音频时长续保护。
2. `legacy_tts` 在等待 TTS 生成时不再被 `isSelfSpeechActive()` 当成自发声，用户此时说话可以正常开启语音轮次。
3. `stopCurrentAudio()` 主动停止当前音频时同步释放固定语录保护状态。

## 影响范围

- 仅影响 avatar 浏览器端固定语录播放与本地 VAD 判定。
- 不改变实时对话 `doubao_realtime` 外部音频链路。
- 不改变普通用户主动语音入口。
- 不修改客户端 EXE，不需要重新打包客户端。

## 回退方式

如现场发现固定语录保护过强，可在服务器 `/opt/server_deploy/.env.server` 设置：

```env
FIXED_SPEECH_NOISE_GUARD_ENABLED=0
```

然后重建并重启 avatar：

```bash
cd /opt/server_deploy
docker compose --env-file .env.server -f docker-compose.deploy.yml build avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml up -d avatar
docker compose --env-file .env.server -f docker-compose.deploy.yml restart nginx
```

如果只是尾部保护偏长，可调整：

```env
FIXED_SPEECH_POST_GUARD_MS=800
```

## Agent2 建议测试

1. 触发欢迎语、repeat、到场任务固定语录，确认固定语录能完整播完。
2. 固定语录播放期间制造轻微环境噪声，确认状态栏不会频繁切到“正在听/识别/思考”并中断语录。
3. 固定语录播完后等待 1-2 秒，再正常说“你好”，确认仍能进入正常语音对话。
4. 检查 avatar 日志中是否能看到：
   - `fixed speech noise guard active`
   - `fixed speech noise guard tail`
5. 确认实时对话回复和外部音频不受本次固定语录保护影响。

## 本地验证

- `node --check server_deploy/avatar/avatar.js`
- `node --check server_deploy/avatar/server.js`
