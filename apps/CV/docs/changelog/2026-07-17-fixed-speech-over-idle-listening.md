# 2026-07-17

## 问题

人物未出现或刚触发识别前，环境噪音可能先触发浏览器自动 VAD，前端进入“我在听呢”监听状态。随后签到、签退或 repeat 固定语录到达时，会被本地实时语音轮次占用的优先级和音频锁挡住，导致语录排队、过期或没有播放。

## 原因

空监听状态会设置 `activeSpeechOwner=local_dialog` 和较高的本地对话优先级。固定语录优先级低于本地实时对话，repeat 还会在语音忙碌时直接丢弃。系统没有区分“噪音触发的空监听”和“已经识别/思考/播放中的真实实时沟通”。

## 修改方案

在 avatar 前端语音仲裁层新增空监听让路逻辑：当本地轮次仍处于 listening、没有识别文本、没有回答文本、没有音频队列和播放时，允许 `check_in`、`check_out`、`first_time`、`returning`、`repeat` 固定语音打断该空监听。播放前取消空监听轮次，释放本地语音锁和优先级，再按原固定语音链路播放。

repeat 的过期丢弃策略也加入同样的空监听例外，避免噪音造成的 websocket/listening 状态提前吞掉 repeat。

## 影响

签到、签退和 repeat 在“我在听呢”的空监听状态下可以直接播放。已经进入 ASR 文本、LLM 思考、实时回答播放或音频播放的真实沟通仍保持原有保护，不会被固定语录抢断。

## 验证

已验证：

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- 服务器 `docker compose --env-file .env.server -f docker-compose.deploy.yml build avatar`
- 服务器 `docker compose --env-file .env.server -f docker-compose.deploy.yml up -d avatar`
- 服务器重启 nginx 后，`/health` 和 `/healthz` 均返回 ok
- 服务器 avatar 容器内 `node --check avatar.js` 和 `node --test tests/voice_turn_policy.test.js` 均通过
