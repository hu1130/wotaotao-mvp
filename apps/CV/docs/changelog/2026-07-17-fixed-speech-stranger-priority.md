# 2026-07-17

## 问题

`stranger`、`returning_stranger` 仍按低优先级固定事件处理，噪音先触发“我在听呢”空监听时，陌生人欢迎语可能被丢弃或挡住。

`stranger_stare`、`checked_in_stare` 属于轻提醒，但播放时也走固定语音防噪保护，用户开口说话不容易打断。

## 原因

avatar 前端只按 `legacy_tts` owner 判断固定语音，没有区分欢迎类固定语录和凝视类提醒。低优先级事件过滤、空监听抢占和 VAD 自发声保护都缺少事件级语义。

## 修改方案

将 `stranger`、`returning_stranger` 加入受保护固定语录组，和 `check_in`、`check_out`、`first_time`、`returning`、`repeat` 一样，可以打断噪音造成的空 listening 状态后直接播放。

为当前固定语音记录事件类型。`stranger_stare`、`checked_in_stare` 播放时不启用固定语音防噪保护，并通过抢话阈值判断用户说话，允许真实说话打断这两类轻提醒。

同时补充每日 TTS 生成提示，要求 check_in/check_out 句子不仅带姓名，也要明确提到签到/签退，避免生成泛欢迎句。

## 影响

陌生人欢迎和回访欢迎不再被空监听吞掉。凝视提醒仍保持低优先级，不抢实时沟通，也不抢签到签退，但用户开口说话可以打断。

## 验证

已验证：

- `node --check server_deploy/avatar/avatar.js`
- `node --test server_deploy/avatar/tests/voice_turn_policy.test.js`
- `python -m py_compile server_deploy/tools/generate_daily_tts_texts.py`
- 服务器已同步 `avatar.js`、`voice_turn_policy.test.js`、`generate_daily_tts_texts.py`
- 服务器 `docker compose --env-file .env.server -f docker-compose.deploy.yml build avatar`
- 服务器 `docker compose --env-file .env.server -f docker-compose.deploy.yml up -d avatar`
- 服务器重启 nginx 后，`/health` 和 `/healthz` 均返回 ok
- 服务器 avatar 容器内 `node --check avatar.js` 和 `node --test tests/voice_turn_policy.test.js` 均通过
- 服务器 `python3 -m py_compile tools/generate_daily_tts_texts.py` 通过
