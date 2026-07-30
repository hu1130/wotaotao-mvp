# 2026-07-22

## 问题

固定语音在底部状态栏短暂显示后立即消失且没有语音输出；实时沟通开始后浏览器显示“对话失败，已重置”。

## 原因

固定语音 `/tts`、`/tts-raw` 和浏览器实时沟通 Omni 后端都复用 `VolcRealtimeDialogClient` 建立火山 O2.0 realtime dialog WebSocket。线上探针显示上游网关返回 HTTP 403，且独立 ASR/TTS 资源探针正常，故当前不可用点集中在 `volc.speech.dialog` realtime dialog 资源授权或该资源对应的 `REALTIME_DIALOG_APP_ID / REALTIME_DIALOG_ACCESS_KEY` 组合。前端状态栏一秒后消失是 TTS 生成失败后清理状态的结果，不是根因；实时沟通显示“对话失败，已重置”是前端把后端详细错误覆盖成通用文案。

代码中同时发现 `VolcRealtimeDialogClient` 的 `X-Api-App-Key` 未进入配置体系，虽然当前线上显式值与资源固定值一致，但这是同一链路的配置边界缺口，需要修复，避免后续多环境部署继续依赖硬编码。

按接入文档做最小握手探针后，火山返回体为 `requested resource not granted`，说明当前 AppID 没有 `volc.speech.dialog` 授权。服务器历史备份 `/opt/server_deploy_backup_20260708_110448/.env.server` 中的 realtime AppID/AccessKey 通过同一文档握手探针。切回该授权凭证后，StartSession 进一步暴露共享克隆音色 `S_...` 与该 AppID 的音色资源不匹配，返回 `resource ID is mismatched with speaker related resource`。

## 修改方案

- `server_deploy/config/voice.py` 新增 `REALTIME_DIALOG_APP_KEY` 配置读取，并按火山 realtime dialog 资源契约回退到固定 App-Key。
- `shared_runtime/core/speech_streaming/volc_realtime.py` 的 `VolcRealtimeDialogConfig` 增加 `app_key` 字段，握手头改为使用配置值，并补充脱敏握手诊断日志。
- 固定 TTS、Omni 浏览器语音、旧 realtime dialog wrapper 和音色探针统一传入 `REALTIME_DIALOG_APP_KEY`。
- `server_deploy/avatar/avatar.js` 保留固定语音失败和实时语音上游认证失败状态，不再立刻清空或覆盖成泛化“已重置”。
- 增加单元测试，防止 realtime dialog transport 再次退回硬编码 App-Key。
- 服务器 `.env.server` 的 realtime dialog AppID/AccessKey 切回已验证拥有 `volc.speech.dialog` 授权的历史凭证。
- 关闭 `platform-shared` 共享克隆音色 profile，使租户按既有设计使用同一 realtime AppID 下可用的 O2 官方 fallback 音色 `zh_female_vv_jupiter_bigtts`。

## 影响

影响火山 O2.0 realtime dialog 相关路径：固定语音、原始 TTS、浏览器实时沟通、租户克隆音色探针。未改变前端 VAD、语音轮次锁、人物记忆提交规则。

## 验证

- `python scripts/check-runtime-boundaries.py`
- `python -m py_compile server_deploy/config/voice.py shared_runtime/core/speech_streaming/volc_realtime.py shared_runtime/core/fixed_tts.py shared_runtime/core/realtime_dialog.py server_deploy/core/speech_streaming/omni.py server_deploy/tools/voice_clone_admin.py`
- `PYTHONPATH=server_deploy;shared_runtime python -m unittest server_deploy.tests.test_voice_clone_tools shared_runtime.tests.test_fixed_tts_voice`
- `node --check server_deploy/avatar/server.js`
- `node --check server_deploy/avatar/avatar.js`
- 服务器重建 `api avatar` 并重启 `nginx` 后，容器与 `/health`、`/healthz` 正常。
- 服务器 `tools/volc_speech_check.py --tts-synthesis` 验证独立 ASR/TTS 正常。
- 按文档最小握手探针确认旧 realtime 凭证可连接 `volc.speech.dialog`。
- `python /app/core/tts_server.py --tenant-id default --raw probe /tmp/codex-tts-probe.wav` 成功生成 48036 字节 WAV。
- `python /app/core/tts_server.py --tenant-id computer-mine --raw probe /tmp/codex-tts-probe-computer-mine.wav` 成功生成 48038 字节 WAV。
- 最近 5 分钟 `api/avatar` 日志未再出现 HTTP 403、`requested resource not granted` 或 `resource ID is mismatched`。
