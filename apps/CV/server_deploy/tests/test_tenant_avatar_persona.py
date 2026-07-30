from __future__ import annotations

import unittest
import json
import tempfile
from dataclasses import asdict
from datetime import date

from core import daily_tts_texts
from core.dialog_chat import match_local_quick_reply
from core.tenant_avatar.models import TenantAvatarPersona
from core.tenant_avatar.service import TenantAvatarPersonaService


class FakePersonaRepository:
    def __init__(self, persona: TenantAvatarPersona | None = None) -> None:
        self.persona = persona

    def get(self, tenant_id: str) -> TenantAvatarPersona | None:
        if self.persona is None or self.persona.tenant_id != tenant_id:
            return None
        return self.persona

    def upsert(self, persona: TenantAvatarPersona) -> TenantAvatarPersona:
        version = (self.persona.version if self.persona else 0) + 1
        self.persona = TenantAvatarPersona(**{**asdict(persona), "version": version})
        return self.persona


class FakeCache:
    def get(self, key: str):
        return None

    def setex(self, key: str, ttl: int, value: str) -> None:
        return None

    def delete(self, key: str) -> None:
        return None


class TenantAvatarPersonaServiceTests(unittest.TestCase):
    def test_missing_persona_uses_default_settings(self) -> None:
        service = TenantAvatarPersonaService(
            repository=FakePersonaRepository(),
            cache=FakeCache(),
        )

        settings = service.resolve("default")

        self.assertFalse(settings.customized)
        self.assertEqual(settings.version, 0)
        self.assertIn("叮当", settings.wake_aliases)

    def test_custom_name_updates_prompt_and_wake_aliases(self) -> None:
        service = TenantAvatarPersonaService(
            repository=FakePersonaRepository(),
            cache=FakeCache(),
        )

        service.save(
            tenant_id="default",
            assistant_name="小鹿",
            personality="专业、温柔",
            speaking_tone="短句，语气稳定",
            extra_instructions="不要自称叮当",
            wake_aliases=["鹿鹿"],
        )
        settings = service.resolve("default")

        self.assertTrue(settings.customized)
        self.assertEqual(settings.assistant_name, "小鹿")
        self.assertIn("小鹿", settings.wake_aliases)
        self.assertNotIn("小小鹿", settings.wake_aliases)
        self.assertIn("鹿鹿", settings.wake_aliases)
        self.assertNotIn("叮当", settings.wake_aliases)
        self.assertNotIn("小叮当", settings.wake_aliases)
        self.assertEqual(settings.custom_wake_aliases, ("鹿鹿",))
        self.assertIn("名字叫小鹿", settings.system_role)
        self.assertIn("正式名字只有小鹿", settings.chat_system_prompt)
        self.assertIn("我叫小鹿", settings.system_role)
        self.assertIn("我是小鹿", settings.chat_system_prompt)
        self.assertNotIn("只回答你叫小鹿", settings.system_role)
        self.assertNotIn("只回答你叫小鹿", settings.chat_system_prompt)
        self.assertIn("专业、温柔", settings.chat_system_prompt)
        self.assertIn("短句，语气稳定", settings.speaking_style)
        self.assertEqual(match_local_quick_reply("你叫啥？", persona=settings), "")
        self.assertEqual(match_local_quick_reply("你的名字是什么？", persona=settings), "")

    def test_custom_speaking_style_does_not_inherit_default_tone(self) -> None:
        service = TenantAvatarPersonaService(
            repository=FakePersonaRepository(
                TenantAvatarPersona(
                    tenant_id="default",
                    assistant_name="小丑",
                    personality="说话爱说人机，脾气暴躁，阴阳怪气",
                    speaking_tone="愤怒",
                    version=9,
                )
            ),
            cache=FakeCache(),
        )

        settings = service.resolve("default")

        self.assertIn("脾气暴躁", settings.speaking_style)
        self.assertIn("愤怒", settings.speaking_style)
        self.assertIn("严格优先服从", settings.speaking_style)
        self.assertNotIn("温柔活泼", settings.speaking_style)
        self.assertNotIn("亲切", settings.speaking_style)

    def test_identity_question_takes_priority_over_wake_alias(self) -> None:
        class AmbiguousPersona:
            assistant_name = "小鹿"
            wake_aliases = ("你", "小鹿")

        self.assertEqual(
            match_local_quick_reply("你叫啥？", persona=AmbiguousPersona()),
            "",
        )

    def test_empty_saved_persona_is_treated_as_default(self) -> None:
        service = TenantAvatarPersonaService(
            repository=FakePersonaRepository(
                TenantAvatarPersona(tenant_id="default", version=4)
            ),
            cache=FakeCache(),
        )

        settings = service.resolve("default")

        self.assertFalse(settings.customized)
        self.assertEqual(settings.version, 4)

    def test_custom_name_ignores_default_aliases_from_older_saved_values(self) -> None:
        service = TenantAvatarPersonaService(
            repository=FakePersonaRepository(
                TenantAvatarPersona(
                    tenant_id="default",
                    assistant_name="兜兜",
                    wake_aliases=("兜兜", "小兜兜", "叮当", "小叮当"),
                    personality="直接",
                    speaking_tone="短句",
                    version=8,
                )
            ),
            cache=FakeCache(),
        )

        settings = service.resolve("default")

        self.assertEqual(settings.assistant_name, "兜兜")
        self.assertEqual(settings.wake_aliases, ("兜兜", "小兜兜"))
        self.assertEqual(settings.custom_wake_aliases, ("兜兜", "小兜兜"))
        self.assertNotIn("叮当", settings.chat_system_prompt)

    def test_tenant_daily_texts_override_default_pool(self) -> None:
        default_texts = {"epsilon": {"check_in": ["{}，默认签到。"]}}
        original_dir = daily_tts_texts.TENANT_DAILY_TTS_TEXTS_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                daily_tts_texts.TENANT_DAILY_TTS_TEXTS_DIR = tmp_dir
                daily_tts_texts.invalidate_tenant_daily_texts()
                path = daily_tts_texts.tenant_daily_texts_path("tenant-a")
                path.write_text(
                    json.dumps(
                        {
                            "date": date.today().isoformat(),
                            "tenant_id": "tenant-a",
                            "texts": {"epsilon": {"check_in": ["{}，专属签到。"]}},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                self.assertEqual(
                    daily_tts_texts.choose_text(
                        default_texts,
                        "check_in",
                        require_placeholder=True,
                        tenant_id="tenant-a",
                    ),
                    "{}，专属签到。",
                )

                daily_tts_texts.delete_tenant_daily_texts("tenant-a")
                self.assertEqual(
                    daily_tts_texts.choose_text(
                        default_texts,
                        "check_in",
                        require_placeholder=True,
                        tenant_id="tenant-a",
                    ),
                    "{}，默认签到。",
                )
        finally:
            daily_tts_texts.TENANT_DAILY_TTS_TEXTS_DIR = original_dir
            daily_tts_texts.invalidate_tenant_daily_texts()


if __name__ == "__main__":
    unittest.main()
