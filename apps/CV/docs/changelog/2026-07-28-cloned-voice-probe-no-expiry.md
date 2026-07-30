# 2026-07-28 克隆音色探针不过期

## 问题

`platform-shared` 克隆音色已启用且状态为 `ready`，但最近一次探针时间超过 7 天后，实时沟通和固定语音会自动切回官方兜底音色。现场表现为数字人还能说话，但听感不再是克隆音色。

## 根因

原策略使用 `VOICE_PROFILE_PROBE_TTL_SECONDS=604800` 作为探针新鲜度安全阀。只要 `last_probe_at` 超过 7 天，即使 profile 仍是 `enabled + ready`，解析结果也会 `cloneEnabled=false`，从而使用 `fallback_speaker_id`。

## 修改

- `VOICE_PROFILE_PROBE_TTL_SECONDS <= 0` 现在表示探针不过期。
- 默认值和 `.env.server.example` 改为 `0`，即 ready 的克隆音色不会再因为时间到期自动兜底。
- 仍保留 `enabled`、`status=ready` 和 `last_probe_at` 存在性检查，避免未验证或未启用的 profile 被直接使用。

## 影响

影响租户克隆音色解析链路，以及复用该链路的 Omni 实时沟通和固定语音。若供应商侧 speaker/resource 后续失效，系统不会仅因时间自动兜底，需要通过实际语音错误日志或人工探针发现并处理。

## 验证

- `python -m unittest -v tests.test_tenant_voice`
- `python -m py_compile config/voice.py core/tenant_voice/models.py core/tenant_voice/service.py`
