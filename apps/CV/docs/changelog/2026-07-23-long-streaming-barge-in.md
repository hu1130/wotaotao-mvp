# 修复长回答分段间隙无法抢话

- 根因：实时数字人长回答按多个 TTS 音频块播放，前端只在 `streamingAudioPlaying`、队列非空或 `audio` 存在时认为回答可被抢话。
- 影响：第一、二句播放时可打断；后续句子在两个音频块之间等待下一段 TTS 时，会落到更严格的 pending-response VAD 分支，容易表现为“用户说话被吞”。
- 修复：新增 `streamingPlaybackStarted` 状态。本轮回答一旦已经开始播放，在后端 `done` 且所有音频播放完成前，分段间隙也保持 realtime barge-in 窗口。
- 保护：还没开始播放的 pending response 仍走原来的更强 VAD 证据要求；固定语录的保护规则不变。
