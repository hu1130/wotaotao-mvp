# 动态实时沟通场景话术

## 问题

实时沟通链路中，唤名、寒暄、静音、人物上下文、个人记忆命令、音量调节、人脸录入命令和空打断续播等场景会直接播固定话术，或把固定前缀与实时回答拼接。用户频繁触发同一场景时，数字人会反复输出相同句式，真实感和智能感下降。

## 原因

业务路由和话术表达耦合在一起：确定性代码既判断动作是否执行，也直接给出最终口播文本。部分前端恢复链路还在浏览器内拼接“刚才我继续说”类固定前缀，绕过了后端人设、上下文和模型表达能力。

## 修改方案

- `DialogChatService` 新增 `scene_reply()`，把业务场景、角色人设、用户话语、当前上下文、用户信息、必须保留的业务事实和约束组织为 Prompt，由模型生成最终口播。
- 本地 quick reply 从“直接返回固定句”改为“识别固定场景后交给模型改写”，保留 `match_local_quick_reply()` 兼容旧测试和调用。
- Cascade 与 Omni 语音链路中，唤名、静音、人物上下文、个人记忆命令和语音动作执行结果改为动态场景话术；动作执行仍由确定性代码完成，模型只负责表达。
- 新增 `/api/v1/dialog/scene-reply` 和 avatar 网关 `/dialog/scene-reply`，前端空打断续播/重生成不再拼接固定前缀，而是请求场景话术。
- 新增 `DIALOG_SCENE_REPLY_TEMPERATURE` 和 `DIALOG_SCENE_REPLY_MAX_TOKENS`，让场景话术更自然但保持短句约束。

## 影响

影响浏览器实时语音 `/api/v1/dialog/voice-stream` 的 Cascade 和 Omni 后端，以及 avatar 前端空打断恢复链路。人脸识别触发的签到、签退、陌生人等固定语录播放机制未在本次改动中替换。企业知识 RAG、人物记忆归属、动作执行权限和播放完成后提交记忆的规则不变。

## 验证

- `python -m py_compile server_deploy/core/dialog_chat.py server_deploy/core/speech_streaming/pipeline.py server_deploy/core/speech_streaming/omni.py server_deploy/api/main.py server_deploy/api/schemas.py server_deploy/config/voice.py`
- `node --check server_deploy/avatar/server.js; node --check server_deploy/avatar/avatar.js`
- `python scripts/check-runtime-boundaries.py`
- `npm test -- --runInBand` in `server_deploy/avatar`
- `python -m unittest -v tests.test_dialog_wake_name tests.test_dialog_silence tests.test_dialog_actions` in `server_deploy`
- `tests.test_omni_voice` 已按场景分段执行覆盖全部用例；本机 Redis 未启动，整文件一次性执行会被 Redis 降级等待拖慢到超时，分段执行均通过。
