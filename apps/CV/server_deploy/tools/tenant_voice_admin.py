"""Server-only tenant cloned-voice profile management."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tenant_voice.models import TenantVoiceProfile
from core.tenant_voice.service import (
    get_tenant_voice_profile_service,
    mask_speaker_id,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="租户 Omni 克隆音色管理（仅服务器命令）")
    commands = parser.add_subparsers(dest="command", required=True)

    show = commands.add_parser("show", help="查看租户音色配置")
    show.add_argument("--tenant-id", required=True)

    resolve = commands.add_parser("resolve", help="查看租户最终生效的音色配置")
    resolve.add_argument("--tenant-id", required=True)

    for name, help_text in (
        ("enable", "下一轮起启用已通过探针的克隆音色"),
        ("disable", "下一轮起切回租户默认音色"),
    ):
        item = commands.add_parser(name, help=help_text)
        item.add_argument("--tenant-id", required=True)

    register = commands.add_parser("register", help="登记已通过协议探针的 O2.0 克隆音色")
    register.add_argument("--tenant-id", required=True)
    register.add_argument("--speaker-id", required=True)
    register.add_argument("--omni-model", default="1.2.1.1")
    register.add_argument("--realtime-resource-id", default="volc.speech.dialog")
    register.add_argument("--training-resource-id", default="seed-icl-2.0")
    register.add_argument("--tts-2-0-model", default="expressive")
    register.add_argument(
        "--fallback-speaker-id",
        default="zh_female_vv_jupiter_bigtts",
    )
    register.add_argument("--persona-file", required=True)
    register.add_argument("--sample-sha256", required=True)
    register.add_argument("--consent-reference", required=True)
    register.add_argument(
        "--probe-passed-at",
        required=True,
        help="voice_clone_admin probe 成功输出的 ISO 时间",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    service = get_tenant_voice_profile_service()
    if args.command == "show":
        profile = service.get_profile(args.tenant_id)
        _print({"ok": profile is not None, "profile": _profile_payload(profile)})
        return 0 if profile is not None else 1
    if args.command == "resolve":
        settings = service.resolve(args.tenant_id)
        source_tenant_id = settings.tenant_id
        if service.get_profile(args.tenant_id) is None:
            source_tenant_id = (
                service.shared_profile_tenant_id
                if service.get_profile(service.shared_profile_tenant_id) is not None
                else "global-default"
            )
        _print(
            {
                "ok": True,
                "effective": {
                    "tenantId": settings.tenant_id,
                    "sourceTenantId": source_tenant_id,
                    "cloneEnabled": settings.clone_enabled,
                    "speakerIdMasked": mask_speaker_id(settings.speaker_id),
                    "fallbackSpeakerId": settings.fallback_speaker_id,
                    "omniModel": settings.model,
                    "tts2Model": settings.tts_2_0_model,
                    "profileVersion": settings.profile_version,
                },
            }
        )
        return 0
    if args.command in {"enable", "disable"}:
        profile = service.set_enabled(args.tenant_id, args.command == "enable")
        _print({"ok": True, "profile": _profile_payload(profile)})
        return 0

    persona_path = Path(args.persona_file).expanduser().resolve()
    if not persona_path.is_file():
        raise SystemExit(f"说话风格文件不存在: {persona_path}")
    try:
        persona = json.loads(persona_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"说话风格文件读取失败: {exc}") from exc
    try:
        probe_passed_at = datetime.fromisoformat(args.probe_passed_at)
    except ValueError as exc:
        raise SystemExit("--probe-passed-at 必须是 ISO 时间") from exc
    profile = service.register(
        TenantVoiceProfile(
            tenant_id=args.tenant_id,
            provider="volcengine",
            enabled=False,
            status="ready",
            speaker_id=args.speaker_id,
            fallback_speaker_id=args.fallback_speaker_id,
            omni_model=args.omni_model,
            realtime_resource_id=args.realtime_resource_id,
            training_resource_id=args.training_resource_id,
            tts_2_0_model=args.tts_2_0_model,
            speech_persona=persona,
            sample_sha256=args.sample_sha256.lower(),
            consent_reference=args.consent_reference,
            last_probe_at=probe_passed_at,
        )
    )
    _print(
        {
            "ok": True,
            "profile": _profile_payload(profile),
            "notice": "音色已登记但尚未启用；确认试听后执行 enable",
        }
    )
    return 0


def _profile_payload(profile: TenantVoiceProfile | None) -> dict | None:
    if profile is None:
        return None
    return {
        "tenantId": profile.tenant_id,
        "provider": profile.provider,
        "enabled": profile.enabled,
        "status": profile.status,
        "speakerIdMasked": mask_speaker_id(profile.speaker_id),
        "fallbackSpeakerId": profile.fallback_speaker_id,
        "omniModel": profile.omni_model,
        "realtimeResourceId": profile.realtime_resource_id,
        "trainingResourceId": profile.training_resource_id,
        "tts2Model": profile.tts_2_0_model,
        "sampleSha256": profile.sample_sha256,
        "consentReference": profile.consent_reference,
        "version": profile.version,
        "lastProbeAt": profile.last_probe_at,
        "createdAt": profile.created_at,
        "updatedAt": profile.updated_at,
    }


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    raise SystemExit(main())
