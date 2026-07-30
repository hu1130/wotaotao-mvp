"""Business mute controls for realtime avatar dialog."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from core.dialog_wake_name import parse_wake_name
from core.tenant import normalize_tenant_id


ACTION_NONE = "none"
ACTION_MUTE = "mute"
ACTION_WAKE = "wake"
ACTION_SUPPRESS = "suppress"

_COMMANDS = {
    "别说话了",
    "别说话",
    "小嘴巴",
    "别叫了",
    "别叫",
    "静音",
    "请静音",
    "开启静音",
    "开启静音模式",
    "打开静音",
    "打开静音模式",
    "进入静音",
    "进入静音模式",
    "先静音",
    "暂时静音",
    "声音静音",
    "把声音静音",
    "把声音关掉",
    "关掉声音",
    "关闭声音",
    "先别说话",
    "暂时别说话",
    "不要说话",
    "不要说话了",
    "暂停说话",
    "暂停聊天",
    "先安静",
    "安静一下",
}
_COMPACT_RE = re.compile(r"[\s,，.。!！?？:：;；、~～]+")


@dataclass(frozen=True, slots=True)
class DialogSilenceResult:
    action: str
    assistant_name: str
    matched_alias: str = ""
    route_text: str = ""
    response_text: str = ""
    status_text: str = ""


@dataclass(frozen=True, slots=True)
class DialogSilenceState:
    muted: bool = False
    assistant_name: str = ""
    status_text: str = ""


class DialogSilenceStateStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[tuple[str, str], DialogSilenceState] = {}

    def get(self, tenant_id: str, device_id: str) -> DialogSilenceState:
        key = self._key(tenant_id, device_id)
        with self._lock:
            return self._states.get(key, DialogSilenceState())

    def set_muted(
        self,
        *,
        tenant_id: str,
        device_id: str,
        assistant_name: str,
        status_text: str,
    ) -> DialogSilenceState:
        key = self._key(tenant_id, device_id)
        state = DialogSilenceState(
            muted=True,
            assistant_name=(assistant_name or "").strip(),
            status_text=(status_text or "").strip(),
        )
        with self._lock:
            self._states[key] = state
        return state

    def clear(self, tenant_id: str, device_id: str) -> None:
        key = self._key(tenant_id, device_id)
        with self._lock:
            self._states.pop(key, None)

    @staticmethod
    def _key(tenant_id: str, device_id: str) -> tuple[str, str]:
        normalized_tenant = normalize_tenant_id(tenant_id)
        normalized_device = (device_id or "").strip() or "__unknown_device__"
        return normalized_tenant, normalized_device


def resolve_dialog_silence(
    text: str,
    *,
    muted: bool,
    assistant_name: str,
    wake_aliases: tuple[str, ...] | list[str],
) -> DialogSilenceResult:
    original = (text or "").strip()
    assistant_name = (assistant_name or "").strip() or "数字人"
    status_text = build_silence_status_text(assistant_name)
    wake = parse_wake_name(
        original,
        assistant_name=assistant_name,
        wake_aliases=wake_aliases,
    )

    if muted:
        if wake.called:
            return DialogSilenceResult(
                action=ACTION_WAKE,
                assistant_name=wake.assistant_name,
                matched_alias=wake.matched_alias,
                route_text=wake.command_text,
                response_text="" if wake.command_text else build_silence_wake_reply(),
                status_text="已解除静音",
            )
        return DialogSilenceResult(
            action=ACTION_SUPPRESS,
            assistant_name=assistant_name,
            status_text=status_text,
        )

    command_text = wake.command_text if wake.called and wake.command_text else original
    if is_silence_command(command_text):
        result_name = wake.assistant_name if wake.called else assistant_name
        return DialogSilenceResult(
            action=ACTION_MUTE,
            assistant_name=result_name,
            matched_alias=wake.matched_alias,
            response_text=build_silence_enabled_reply(result_name),
            status_text=build_silence_status_text(result_name),
        )

    return DialogSilenceResult(
        action=ACTION_NONE,
        assistant_name=wake.assistant_name if wake.called else assistant_name,
        route_text=original,
    )


def is_silence_command(text: str) -> bool:
    compact = _COMPACT_RE.sub("", (text or "").strip())
    return compact in _COMMANDS


def build_silence_status_text(assistant_name: str) -> str:
    name = (assistant_name or "").strip() or "数字人"
    return f"静音中，喊{name}唤醒我"


def build_silence_enabled_reply(assistant_name: str) -> str:
    name = (assistant_name or "").strip() or "数字人"
    return f"好的，我先开启静音。需要我的时候，喊{name}就能唤醒我。"


def build_silence_wake_reply() -> str:
    return "我在，已解除静音。"


_state_store = DialogSilenceStateStore()


def get_dialog_silence_state_store() -> DialogSilenceStateStore:
    return _state_store
