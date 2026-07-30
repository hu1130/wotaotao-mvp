"""Factory for browser-facing voice dialogue backends."""

from __future__ import annotations

import logging

from config import VOICE_PIPELINE_BACKEND
from core.speech_streaming.pipeline import Sender, VoicePipelineSession


logger = logging.getLogger(__name__)

SUPPORTED_BACKENDS = {"cascade", "omni"}


def create_voice_pipeline_session(send_json: Sender) -> VoicePipelineSession:
    backend = (VOICE_PIPELINE_BACKEND or "cascade").strip().lower()
    if backend == "omni":
        from core.speech_streaming.omni import OmniVoicePipelineSession

        logger.info("创建浏览器语音会话: backend=omni")
        return OmniVoicePipelineSession(send_json)
    if backend != "cascade":
        raise ValueError(
            f"unsupported VOICE_PIPELINE_BACKEND={backend!r}; "
            f"expected one of {sorted(SUPPORTED_BACKENDS)}"
        )
    logger.info("创建浏览器语音会话: backend=cascade")
    return VoicePipelineSession(send_json)
