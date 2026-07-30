# 2026-07-22

## 问题

实时沟通中，数字人说话过程被用户打断后，底部状态栏或控制端 assistant 文本会残留被打断前的最后一句。

同次排查中，用户要求把当前数字人的语音切回之前的克隆音色。

## 原因

抢话打断链路 `interruptCurrentVoiceTurnForBargeIn()` 已停止音频、清空播放队列和播放进度，但没有同步清理 `voiceChatText`、`assistantSpeechText` 和状态栏。下一轮 `startVoiceTurn()` 会稍后写入“正在听你说话”，因此中间窗口会残留上一句。

强制重置链路 `forceResetVoiceLayer()` 也只清理了底部 `voiceChatText`，没有使用统一的流式语音显示清理函数。

克隆音色方面，服务器 `platform-shared` profile 中仍保留之前的 `S_...` 克隆 speaker，但当前可用的 Realtime/O2 凭证与该 speaker 资源不匹配。启用后探针在 StartSession 阶段返回 `resource ID is mismatched with speaker related resource`，会导致固定语音和实时语音重新无声。

## 修改方案

- 抢话打断确认后立即调用 `clearStreamingSpeechDisplay()`，同步清空状态栏、底部文本、访客文本和助手文本。
- 抢话打断后立即切到 `listening` 语音阶段，减少 UI 上一轮 speaking 状态停留。
- `forceResetVoiceLayer()` 改为使用同一显示清理函数，避免不同重置路径清理范围不一致。
- `clearVoiceChatText()` 清理时取消旧的 `voiceChatTextTimer`，避免旧计时器影响后续新文本。
- 未强行启用 `platform-shared` 克隆音色；保持 disabled，确保当前官方 fallback 音色可稳定发声。

## 验证

- 服务器临时启用 `platform-shared` 后执行 `/app/core/tts_server.py --tenant-id default --raw 克隆音色探针`，上游返回资源不匹配；已立即 disable 回滚。
- 回滚后执行 `/app/core/tts_server.py --tenant-id default --raw 回滚官方音色探针`，成功生成 WAV。
- 当前环境、切换前备份、2026-07-08 备份、2026-07-20 备份的最小 StartSession 探针：fallback speaker 成功，已登记克隆 speaker 均返回资源不匹配。

