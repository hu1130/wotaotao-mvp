"""消息队列事件发布: 签到/签退事件推送到 Redis 和数字人前端"""

import json
import logging
import time
from datetime import datetime

from config import MQ_TOPIC_PREFIX, TENANT_ID
from core.redis_health import RedisHealthMonitor
from core.tenant import normalize_tenant_id

logger = logging.getLogger(__name__)


class EventBus:
    """事件总线: 支持 Redis Pub/Sub + 数字人前端事件."""

    def __init__(self, emotion_module=None, tenant_id: str = TENANT_ID):
        self._health = RedisHealthMonitor(name="事件总线")
        self._health.initialize()
        self._emotion_module = emotion_module
        self.tenant_id = normalize_tenant_id(tenant_id)
        self._last_avatar_event: dict | None = None
        self._last_avatar_time: float = 0.0

    def publish(self, event_type: str, payload: dict) -> None:
        runtime_scope = str(payload.get("runtime_scope") or "")
        scope_tenant = (
            runtime_scope[len("tenant=") :].split("|", 1)[0]
            if runtime_scope.startswith("tenant=")
            else ""
        )
        tenant_id = normalize_tenant_id(
            str(payload.get("tenant_id") or scope_tenant or self.tenant_id)
        )
        payload = {**payload, "tenant_id": tenant_id}
        topic = f"{MQ_TOPIC_PREFIX}.{tenant_id}.{event_type}"
        message = {
            "event": event_type,
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
            "payload": payload,
        }
        if not self._health.ensure_connected():
            logger.info(
                "EVENT | %s | %s", topic, json.dumps(payload, ensure_ascii=False)
            )
            return
        self._do_publish(topic, message, payload)

    def _do_publish(self, topic: str, message: dict, payload: dict) -> None:
        try:
            self._health.client.publish(topic, json.dumps(message, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Redis 事件发布失败, 降级为日志模式: %s", exc)
            self._health.mark_unhealthy()
            logger.info(
                "EVENT | %s | %s", topic, json.dumps(payload, ensure_ascii=False)
            )
        logger.debug("EVENT | %s | %s", topic, payload.get("name", "?"))

    def _avatar_event(self, event_type: str, payload: dict) -> None:
        payload = {
            **payload,
            "tenant_id": normalize_tenant_id(
                str(payload.get("tenant_id") or self.tenant_id)
            ),
        }
        msg = {"type": event_type, **payload}
        self._last_avatar_event = msg
        self._last_avatar_time = time.time()
        if self._emotion_module is not None:
            self._emotion_module.on_avatar_event(event_type, payload)

    def checkin(
        self,
        name: str,
        row_id: int,
        similarity: float,
        is_first: bool = False,
        is_returning: bool = False,
        tenant_id: str | None = None,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id or self.tenant_id)
        self.publish(
            "checkin",
            {
                "name": name,
                "tenant_id": tenant_id,
                "row_id": row_id,
                "similarity": round(similarity, 4),
                "time": time.time(),
            },
        )
        self._avatar_event(
            "check_in",
            {
                "name": name,
                "tenant_id": tenant_id,
                "is_first": is_first,
                "is_returning": is_returning,
            },
        )

    def checkout(
        self,
        name: str,
        row_id: int,
        duration_minutes: int,
        tenant_id: str | None = None,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id or self.tenant_id)
        self.publish(
            "checkout",
            {
                "name": name,
                "tenant_id": tenant_id,
                "row_id": row_id,
                "duration_minutes": duration_minutes,
                "time": time.time(),
            },
        )
        self._avatar_event(
            "check_out",
            {"name": name, "tenant_id": tenant_id},
        )

    def stranger(
        self,
        visitor_label: str | None = None,
        is_returning: bool = False,
        gender: str | None = None,
        salutation: str | None = None,
    ) -> None:
        payload = {
            "time": time.time(),
            "visitor_label": visitor_label or "未知访客",
            "is_returning": is_returning,
            "gender": gender,
            "salutation": salutation,
        }
        self.publish("stranger_detected", payload)
        self._avatar_event("stranger", payload)

    def stranger_stare(self, salutation: str | None = None) -> None:
        payload = {
            "time": time.time(),
            "salutation": salutation,
        }
        self.publish("stranger_stare", payload)
        self._avatar_event("stranger_stare", payload)

    def repeat_checkin(self, name: str) -> None:
        self.publish("repeat_checkin", {"name": name, "time": time.time()})
        self._avatar_event("repeat", {"name": name})

    def checked_in_stare(self, name: str) -> None:
        self.publish("checked_in_stare", {"name": name, "time": time.time()})
        self._avatar_event("checked_in_stare", {"name": name})

    def attention(self) -> None:
        now = time.time()
        if (
            self._last_avatar_event
            and self._last_avatar_event.get("type") == "attention"
        ):
            if now - self._last_avatar_time < 5.0:
                return
        self._avatar_event("attention", {})

    def idle_long(self) -> None:
        self._avatar_event("idle_long", {})

    def crowd(self, count: int) -> None:
        now = time.time()
        if self._last_avatar_event and self._last_avatar_event.get("type") == "crowd":
            if now - self._last_avatar_time < 30.0:
                return
        self._avatar_event("crowd", {"count": count})
