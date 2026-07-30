# 固定语录克隆音色统一改动说明

## 本次修复方案

固定语录原先由 Edge-TTS 直接生成，和 Omni 实时对话的租户克隆音色链路分离，导致同一个数字人在固定欢迎语、手势播报和实时对话中音色不一致。本次新增统一固定语音 provider，服务端默认使用火山 TTS，并复用 `TenantVoiceProfileService.resolve(tenant_id)` 的租户专属音色、平台共享音色和 fallback speaker 解析规则。

浏览器、query 和客户端请求不再拥有固定语录音色切换权。avatar Node 只从 `req.avatarSession.tenantId` 读取可信租户，并通过 `tts_server.py --tenant-id` 传给 Python 生成入口。

2026-07-15 二次修复：启动客户端后状态栏有文本但无音频，日志显示 `resource ID is mismatched with speaker related resource`。根因是克隆音色 `S_...` 属于 O2.0 端到端实时语音资源，不能送入 standalone `seed-tts-2.0` TTS 通道。本次将服务端 `volc` 固定语音 provider 改为短生命周期 O2.0 realtime session，发送 `ChatTextQuery(501)` 精确复述固定文本，收集 `TTSResponse(352)` 音频并封装成 WAV 文件。

## 主要改动

- `shared_runtime/core/fixed_tts.py`
  - 新增 `FixedTtsClient`，统一固定语音 provider、租户音色解析、缓存身份和音频生成。
  - 服务端 `volc` provider 解析 `tenant_voice_profiles`，未配置克隆时使用同一套 fallback speaker。
  - 服务端 `volc` provider 使用 O2.0 realtime session 合成固定语音，不再调用 standalone TTS。
  - 日志只输出脱敏 speaker。

- `shared_runtime/core/speech_streaming/volc_tts.py`
  - 支持每次合成传入 `speaker_id`。
  - 克隆音色启用时附带 `tts_2.0_model=expressive`。

- `shared_runtime/core/tts_server.py`
  - 固定语录生成不再直连 Edge-TTS，统一走 `FixedTtsClient`。
  - 新增 `--tenant-id` 参数。
  - 修复当前按模型分组语录下 `--print-text` 和 `--print-manifest` 的事件文案解析。
  - 合成文件先写临时文件，成功后再原子替换，失败不会留下 0 字节缓存。

- `shared_runtime/core/voice_system.py`
  - 本地固定播报队列改用 `FixedTtsClient`。
  - 缓存 key 纳入 provider、speaker、profile version 和 clone 状态。
  - 保留原优先级、打断、播放锁和 Live2D 事件行为。

- `server_deploy/avatar/server.js`
  - `/tts`、`/tts-raw` 使用可信 avatar session tenant 生成固定语音。
  - 缓存文件名增加 tenant、provider 和音频格式，避免复用旧 Edge 缓存。
  - 发送缓存前校验文件大小，发现 0 字节缓存会删除后重新生成。
  - 预热任务从多 Edge 音色改为统一固定音色路径。

- `server_deploy/config/voice.py`、`client_deploy/config/voice.py`、`.env.server`
  - 新增 `FIXED_TTS_PROVIDER`、`FIXED_TTS_ALLOW_EDGE_FALLBACK`、`FIXED_TTS_TENANT_ID`。
  - 服务端默认 `volc` 且不自动回退 Edge；客户端默认 `edge` 兼容旧本地运行。

## Agent2 测试重点

1. 已启用平台共享克隆音色时，请求 `/tts?type=check_in&name=访客&variant=0`，日志应出现 `固定语音生成: provider=volc`，speaker 为脱敏 `S_...`，并且 profile version 与 Omni 链路一致。
2. 服务端 `volc` provider 固定语录缓存应生成浏览器可播放的 `.wav`，文件名包含租户和 provider，不应命中旧 Edge `.mp3`。
3. `/tts-raw` 同样应走可信租户音色，不能通过 query 中的 `voice` 或 `model` 改成其他 speaker。
4. `VOICE_CLONE_PLATFORM_ENABLED=0` 时，固定语录应使用同一租户配置的 fallback speaker，而不是 Edge-TTS。
5. 预热任务总量应按事件文案条数统计，不再乘以多个 Edge 模型音色。

## Agent1 已执行检查

- `python -m py_compile shared_runtime/core/fixed_tts.py shared_runtime/core/tts_server.py shared_runtime/core/voice_system.py shared_runtime/core/speech_streaming/volc_tts.py shared_runtime/core/interaction_mode.py server_deploy/config/voice.py client_deploy/config/voice.py`
- `node --check server_deploy/avatar/server.js`
- `python scripts/check-runtime-boundaries.py`
- `python shared_runtime/core/tts_server.py --tenant-id default 访客 check_in --print-text 0`

## 未执行项

- 未执行火山真实 TTS 合成调用。
- 未执行完整业务测试。
- 未执行 exe 打包，按分工交给 Agent2。
