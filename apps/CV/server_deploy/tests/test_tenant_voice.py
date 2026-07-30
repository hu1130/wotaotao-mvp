from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from core.tenant_voice.models import TenantVoiceProfile
from core.tenant_voice.service import TenantVoiceProfileService


class FakeProfileRepository:
    def __init__(self, profiles: list[TenantVoiceProfile] | None = None) -> None:
        self.profiles = {item.tenant_id: item for item in profiles or []}

    def get(self, tenant_id: str) -> TenantVoiceProfile | None:
        return self.profiles.get(tenant_id)

    def register(self, profile: TenantVoiceProfile) -> TenantVoiceProfile:
        current = self.profiles.get(profile.tenant_id)
        version = (current.version if current else 0) + 1
        saved = replace(profile, version=version)
        self.profiles[profile.tenant_id] = saved
        return saved

    def set_enabled(self, tenant_id: str, enabled: bool) -> TenantVoiceProfile | None:
        current = self.profiles.get(tenant_id)
        if current is None:
            return None
        saved = replace(current, enabled=enabled, version=current.version + 1)
        self.profiles[tenant_id] = saved
        return saved


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.values.pop(key, None)


def ready_profile(
    tenant_id: str,
    speaker_id: str,
    *,
    enabled: bool = True,
    status: str = "ready",
    version: int = 1,
    last_probe_at: datetime | None = None,
) -> TenantVoiceProfile:
    return TenantVoiceProfile(
        tenant_id=tenant_id,
        provider="volcengine",
        enabled=enabled,
        status=status,
        speaker_id=speaker_id,
        fallback_speaker_id="zh_female_vv_jupiter_bigtts",
        omni_model="1.2.1.1",
        realtime_resource_id="volc.speech.dialog",
        training_resource_id="seed-icl-2.0",
        tts_2_0_model="expressive",
        speech_persona={"speaking_style": "自然、简短，偶尔使用嗯、呀等语气词。"},
        sample_sha256="a" * 64,
        consent_reference="company-approval-20260714",
        version=version,
        last_probe_at=last_probe_at or datetime.now() - timedelta(minutes=5),
    )


class TenantVoiceProfileServiceTests(unittest.TestCase):
    def test_profiles_are_resolved_by_trusted_tenant_only(self) -> None:
        repo = FakeProfileRepository(
            [
                ready_profile("tenant-a", "S_voice_a"),
                ready_profile("tenant-b", "S_voice_b"),
            ]
        )
        service = TenantVoiceProfileService(
            repository=repo,
            cache=FakeCache(),
            platform_enabled=True,
        )

        self.assertEqual(service.resolve("tenant-a").speaker_id, "S_voice_a")
        self.assertEqual(service.resolve("tenant-b").speaker_id, "S_voice_b")

    def test_shared_profile_is_used_for_existing_and_future_tenants(self) -> None:
        shared = ready_profile("platform-shared", "S_shared")
        service = TenantVoiceProfileService(
            repository=FakeProfileRepository([shared]),
            cache=FakeCache(),
            platform_enabled=True,
            shared_profile_tenant_id="platform-shared",
        )

        settings = service.resolve("future-tenant")

        self.assertEqual(settings.tenant_id, "future-tenant")
        self.assertEqual(settings.speaker_id, "S_shared")
        self.assertTrue(settings.clone_enabled)

    def test_tenant_profile_overrides_shared_profile(self) -> None:
        repo = FakeProfileRepository(
            [
                ready_profile("platform-shared", "S_shared"),
                ready_profile("tenant-a", "S_private"),
            ]
        )
        service = TenantVoiceProfileService(
            repository=repo,
            cache=FakeCache(),
            platform_enabled=True,
            shared_profile_tenant_id="platform-shared",
        )

        self.assertEqual(service.resolve("tenant-a").speaker_id, "S_private")

    def test_only_ready_profile_can_be_enabled(self) -> None:
        profile = ready_profile("tenant-a", "S_voice_a", enabled=False, status="draft")
        service = TenantVoiceProfileService(
            repository=FakeProfileRepository([profile]),
            cache=FakeCache(),
            platform_enabled=True,
        )

        with self.assertRaisesRegex(ValueError, "ready"):
            service.set_enabled("tenant-a", True)

    def test_platform_switch_forces_fallback_without_losing_profile_version(self) -> None:
        profile = ready_profile("tenant-a", "S_voice_a", version=9)
        service = TenantVoiceProfileService(
            repository=FakeProfileRepository([profile]),
            cache=FakeCache(),
            platform_enabled=False,
        )

        settings = service.resolve("tenant-a")

        self.assertFalse(settings.clone_enabled)
        self.assertEqual(settings.speaker_id, profile.fallback_speaker_id)
        self.assertEqual(settings.profile_version, 9)

    def test_expired_probe_uses_fallback_by_default(self) -> None:
        profile = ready_profile(
            "tenant-a",
            "S_voice_a",
            last_probe_at=datetime.now() - timedelta(days=8),
        )
        service = TenantVoiceProfileService(
            repository=FakeProfileRepository([profile]),
            cache=FakeCache(),
            platform_enabled=True,
            probe_ttl_seconds=7 * 24 * 60 * 60,
        )

        settings = service.resolve("tenant-a")

        self.assertFalse(settings.clone_enabled)
        self.assertEqual(settings.speaker_id, profile.fallback_speaker_id)

    def test_non_positive_probe_ttl_never_expires_ready_profile(self) -> None:
        profile = ready_profile(
            "tenant-a",
            "S_voice_a",
            last_probe_at=datetime.now() - timedelta(days=365),
        )
        service = TenantVoiceProfileService(
            repository=FakeProfileRepository([profile]),
            cache=FakeCache(),
            platform_enabled=True,
            probe_ttl_seconds=0,
        )

        settings = service.resolve("tenant-a")

        self.assertTrue(settings.clone_enabled)
        self.assertEqual(settings.speaker_id, "S_voice_a")

    def test_cache_round_trip_keeps_datetime_and_persona(self) -> None:
        profile = ready_profile("tenant-a", "S_voice_a")
        cache = FakeCache()
        repo = FakeProfileRepository([profile])
        service = TenantVoiceProfileService(repo, cache, platform_enabled=True)

        first = service.get_profile("tenant-a")
        repo.profiles.clear()
        second = service.get_profile("tenant-a")

        self.assertEqual(first, second)
        self.assertEqual(
            json.loads(next(iter(cache.values.values())))["speaker_id"],
            "S_voice_a",
        )

    def test_registration_validates_exact_o2_contract(self) -> None:
        service = TenantVoiceProfileService(
            FakeProfileRepository(),
            FakeCache(),
            platform_enabled=True,
        )
        invalid = ready_profile("tenant-a", "S_voice_a", enabled=False)

        with self.assertRaisesRegex(ValueError, "training resource"):
            service.register(
                replace(invalid, training_resource_id="volc.speech.dialog")
            )
        with self.assertRaisesRegex(ValueError, "expressive"):
            service.register(replace(invalid, tts_2_0_model="standard"))

    def test_enable_increments_version_and_invalidates_cache(self) -> None:
        profile = ready_profile("tenant-a", "S_voice_a", enabled=False, version=3)
        cache = FakeCache()
        service = TenantVoiceProfileService(
            FakeProfileRepository([profile]),
            cache,
            platform_enabled=True,
        )
        service.get_profile("tenant-a")

        changed = service.set_enabled("tenant-a", True)

        self.assertTrue(changed.enabled)
        self.assertEqual(changed.version, 4)
        self.assertEqual(cache.deleted, ["voice-profile:tenant-a:v1"])
