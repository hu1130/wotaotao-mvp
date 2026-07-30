# 2026-07-21 动态问答临时关闭缓存

## 问题

用户连续问相同问题时，数字人的回答内容高度一致，现场感受像命中了缓存。

## 原因

当前浏览器语音走 Omni 后端。代码中没有跨轮复用答案文本的本地缓存，但 Omni 会话会保持上游会话和短期对话上下文；RAG 仲裁也会在本轮内暂存默认回答候选。相同人设、相同上下文和相同问题会让模型稳定生成相近甚至相同的回答。`/tts-raw` 另有原始文本音频缓存，虽然不影响 Omni 实时回答文本，但会让动态补播音频复用旧文件。

## 修改方案

- 新增 `REALTIME_DIALOG_DYNAMIC_NO_CACHE`，默认开启。开启后浏览器动态问答每轮重建 Omni 上游会话，不向上游发送上一轮短期问答上下文，并在系统提示中要求相同或相近问题重新组织表达。
- 新增 `RAW_TTS_CACHE_ENABLED`，默认关闭。`/tts-raw` 使用临时音频文件并在发送后删除；保留显式开启开关，方便后续按性能需要恢复。
- 保留 `/tts` 命名固定话术缓存和预热缓存，不影响签到、签退、repeat、arrival_task 的直播放链路。

## 影响

影响浏览器动态问答和 raw TTS 原始文本补播。固定话术、租户音色、人设保存、签到签退和到场任务播报优先级不变。每轮重建 Omni 会话会增加少量建连开销，但符合当前“暂时不缓存”的要求。

## 验证

- `python -m py_compile server_deploy/config/voice.py server_deploy/core/speech_streaming/omni.py`
- `node --check server_deploy/avatar/server.js`
