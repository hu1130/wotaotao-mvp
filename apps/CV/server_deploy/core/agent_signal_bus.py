"""Internal signal bus for agent-to-agent coordination."""

from __future__ import annotations

import json
import logging

from config import (
    AGENT_SIGNAL_REDIS_STREAM,
    AGENT_SIGNAL_STREAM_ENABLED,
    AGENT_SIGNAL_STREAM_MAXLEN,
)
from core.redis_health import RedisHealthMonitor
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)


class AgentSignalBus:
    """Publishes hidden agent signals to Redis Stream with log fallback."""

    def __init__(self) -> None:
        self._health = RedisHealthMonitor(name="Agent 信号总线")
        if AGENT_SIGNAL_STREAM_ENABLED:
            self._health.initialize()

    def publish(self, signal: dict) -> None:
        if not signal:
            return
        if not AGENT_SIGNAL_STREAM_ENABLED:
            logger.debug("Agent 信号总线未启用: signal=%s", signal.get("intent") or signal.get("type"))
            return

        if not self._health.ensure_connected():
            logger.info("AGENT_SIGNAL | %s", json.dumps(signal, ensure_ascii=False))
            return

        try:
            tenant_id = normalize_tenant_id(
                str(signal.get("tenant_id") or DEFAULT_TENANT_ID)
            )
            stream_name = f"{AGENT_SIGNAL_REDIS_STREAM}:{tenant_id}"
            self._health.client.xadd(
                stream_name,
                {"payload": json.dumps(signal, ensure_ascii=False)},
                maxlen=AGENT_SIGNAL_STREAM_MAXLEN,
                approximate=True,
            )
            logger.info(
                "Agent 信号已发布: stream=%s intent=%s source=%s targets=%s",
                stream_name,
                signal.get("intent") or signal.get("event"),
                signal.get("source"),
                signal.get("target_agents"),
            )
        except Exception as exc:
            logger.warning("Agent 信号发布失败, 降级为日志模式: %s", exc)
            self._health.mark_unhealthy()
            logger.info("AGENT_SIGNAL | %s", json.dumps(signal, ensure_ascii=False))
