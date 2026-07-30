# 2026-07-21

## 问题

数字人页面和漩涡页面中，用户在数字人思考或准备回答阶段打断后，后续提问可能一直显示“思考中”或“我正在听呢”，数字人不再自动恢复回答。

## 原因

服务端日志显示，RAG 已选中外部回答但首段音频等待超时，且普通回答缓冲为空：`pending_default=0`。此时 `_release_default_response()` 仍返回已释放，调用方不会继续发送本轮 `done` 事件，浏览器端因此保持忙碌/思考状态。

同时，前端把播放中的低延迟抢话阈值复用于“尚未开始播放的思考期打断”。刚说完问题后的尾音或短噪声容易被当作新的抢话，导致还没输出任何字的回答被取消。

## 修改方案

- 修正 Omni 普通回答释放语义：没有待释放句子且普通回答尚未结束时返回未释放，让外层按 RAG 超时原因主动完成轮次并发送 `done`。
- 为思考期打断设置独立且更严格的 VAD 门槛，不影响播放中固定语录和实时回答的抢话敏感度。
- 前端识别 RAG、路由和 TTS 超时完成原因，提示“回答等待超时，我在听，请再说一次”，避免误显示普通完成。
- 增加服务端 RAG 首音频超时且无默认回答的回归测试。

## 影响

影响数字人页面和漩涡页面共用的实时语音链路。播放中的固定语录、实时回答仍可被抢话；思考期只有在检测到更持续、更明确的新语音时才会取消当前待回答轮次。

## 验证

- 本地执行 `python -m py_compile server_deploy/core/speech_streaming/omni.py` 通过。
- 本地执行 `node --check server_deploy/avatar/avatar.js`、`node --check server_deploy/avatar/voice_turn_policy.js` 通过。
- 本地执行 `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`，15 个用例通过。
- 已同步服务器并重建 API/avatar，重启 Nginx。
- 服务器 API 容器执行 RAG 超时与默认回答释放目标用例，4 个用例通过。
- 服务器 `http://127.0.0.1:8000/health` 和 `http://127.0.0.1/healthz` 均返回正常。
