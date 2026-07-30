# 2026-07-27 数字人业务静音路由修复

## 问题

`computer-mine` 现场说“开启静音。”后，服务器没有进入数字人业务静音，而是下发了 `adjust_system_volume` 客户端任务，导致前台电脑系统声音被真实静音。

服务器日志显示：

- `Omni 服务端判停 ... text=开启静音。`
- `语音 Agent 意图命中音量动作 ... params={'direction': 'mute'}`
- `客户端任务已创建 ... action=adjust_system_volume ... payload={'direction': 'mute', ...}`

## 原因

业务静音解析只精确匹配“静音”等少量短句，没有覆盖“开启静音。”；后续音量工具路由只要看到“静音”就返回 `direction=mute`，因此把业务静音误判为系统音量静音。

## 修复

- 扩展业务静音命令，覆盖“开启静音”“请静音”“把声音关掉”“不要说话”等自然表达。
- 语音音量路由不再生成 `direction=mute`，静音只由 `dialog_silence` 业务控制处理。
- 保留调高、调低、音量追问等音量控制能力，不影响已有调音量流程。

## 验证

- `python -m py_compile server_deploy\core\dialog_actions.py server_deploy\core\dialog_silence.py`
- `python -m unittest -v tests.test_dialog_silence tests.test_dialog_actions` in `server_deploy`
- `git diff --check`
