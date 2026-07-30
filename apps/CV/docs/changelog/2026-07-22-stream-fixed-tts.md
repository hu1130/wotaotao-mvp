# 2026-07-22

## 问题

固定语音已经切到火山 O2 音色后，浏览器仍通过 `/tts-raw` 等完整 wav 文件生成完成再播放。签到、repeat 等固定语音即使已经进入 TTS，也要等待整段音频落盘并下载后才有声音。

## 原因

共享 TTS 层内部已经从 O2 实时会话收到 PCM 音频帧，但旧实现把这些帧全部 append 到内存并组装为 wav 文件。Node 端只提供整文件接口，avatar 前端也只支持 `Audio(blob)` 播放，因此首包音频无法提前播放。

## 修改方案

- `shared_runtime/core/fixed_tts.py` 增加固定语音音频帧异步迭代接口，文件合成和流式输出复用同一条 O2 接收循环。
- `shared_runtime/core/tts_server.py` 增加 `--raw --stream` 模式，输出 `start/audio/done` NDJSON，`audio` 行携带 base64 PCM 块。
- `server_deploy/avatar/server.js` 新增 `/tts-raw-stream`，以 HTTP NDJSON 流转发 Python 输出，不落盘、不缓存。
- `server_deploy/avatar/avatar.js` 对固定语音 owner 使用 WebAudio 调度 PCM 块，首个音频块到达即开始播放、口型和状态更新；普通本地对话仍保留原 `/tts-raw` 整文件路径。

## 影响

影响 avatar 固定语音播放链路，包括签到、repeat、stare、欢迎语等通过固定语音事件播报的文本。实时语音对话、Omni 流式回答和普通本地对话不改协议。流式固定语音仍使用同一次 O2 TTS 请求，理论上不会因为播放方式变化而增加 API 调用费用。

## 验证

- `python -m py_compile shared_runtime/core/fixed_tts.py shared_runtime/core/tts_server.py`
- `node --check server_deploy/avatar/server.js`
- `node --check server_deploy/avatar/avatar.js`
- `npm test`（server_deploy/avatar）
- `python scripts/check-runtime-boundaries.py`
