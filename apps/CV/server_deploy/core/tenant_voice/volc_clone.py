"""Volcengine clone-2.0 training adapter with secret-safe diagnostics."""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from config import (
    VOLC_VOICE_CLONE_ACCESS_TOKEN,
    VOLC_VOICE_CLONE_APP_ID,
    VOLC_VOICE_CLONE_MODEL_TYPE,
    VOLC_VOICE_CLONE_STATUS_RESOURCE_ID,
    VOLC_VOICE_CLONE_STATUS_URL,
    VOLC_VOICE_CLONE_TRAIN_RESOURCE_ID,
    VOLC_VOICE_CLONE_UPLOAD_URL,
)

from .service import mask_speaker_id


logger = logging.getLogger(__name__)
HttpPost = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


class VolcCloneError(RuntimeError):
    pass


class VolcCloneClient:
    def __init__(
        self,
        app_id: str = VOLC_VOICE_CLONE_APP_ID,
        access_token: str = VOLC_VOICE_CLONE_ACCESS_TOKEN,
        *,
        upload_url: str = VOLC_VOICE_CLONE_UPLOAD_URL,
        status_url: str = VOLC_VOICE_CLONE_STATUS_URL,
        resource_id: str = VOLC_VOICE_CLONE_TRAIN_RESOURCE_ID,
        status_resource_id: str = VOLC_VOICE_CLONE_STATUS_RESOURCE_ID,
        model_type: int = VOLC_VOICE_CLONE_MODEL_TYPE,
        http_post: HttpPost | None = None,
    ) -> None:
        self.app_id = str(app_id or "").strip()
        self.access_token = str(access_token or "").strip()
        self.upload_url = upload_url
        self.status_url = status_url
        self.resource_id = resource_id
        self.status_resource_id = status_resource_id
        self.model_type = int(model_type)
        self.http_post = http_post or _post_json

    @property
    def ready(self) -> bool:
        return bool(self.app_id and self.access_token)

    def upload(self, speaker_id: str, audio_path: str | Path, transcript: str) -> dict:
        self._validate_contract(speaker_id)
        path = Path(audio_path).expanduser().resolve()
        if path.suffix.lower() != ".wav" or not path.is_file():
            raise ValueError("clone training input must be an existing WAV file")
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("clone training input exceeds the 10MB provider limit")
        transcript = (transcript or "").strip()
        if not transcript:
            raise ValueError("a transcript matching the training audio is required")
        body = {
            "speaker_id": speaker_id,
            "appid": self.app_id,
            "audios": [
                {
                    "audio_bytes": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "text": transcript,
                    "audio_format": "wav",
                }
            ],
            "model_type": self.model_type,
            "source": 2,
        }
        logger.info(
            "提交 O2.0 音色训练: speaker=%s wav_bytes=%s transcript_chars=%s",
            mask_speaker_id(speaker_id),
            path.stat().st_size,
            len(transcript),
        )
        return self.http_post(
            self.upload_url,
            self._headers(self.resource_id),
            body,
            60.0,
        )

    def status(self, speaker_id: str) -> dict:
        self._validate_contract(speaker_id)
        payload = self.http_post(
            self.status_url,
            self._headers(self.status_resource_id),
            {"appid": self.app_id, "speaker_id": speaker_id},
            30.0,
        )
        return {"state": normalize_provider_state(payload), "provider": payload}

    def _headers(self, resource_id: str) -> dict[str, str]:
        if not self.ready:
            raise VolcCloneError("VOLC_VOICE_CLONE_APP_ID/ACCESS_TOKEN are not configured")
        if self.resource_id != "seed-icl-2.0" or self.model_type != 4:
            raise VolcCloneError("O2.0 clone training requires seed-icl-2.0/model_type=4")
        if not resource_id:
            raise VolcCloneError("clone provider resource id is empty")
        return {
            "Authorization": f"Bearer; {self.access_token}",
            "Resource-Id": resource_id,
            "Content-Type": "application/json",
        }

    def _validate_contract(self, speaker_id: str) -> None:
        if not str(speaker_id or "").startswith("S_"):
            raise ValueError("speaker_id must start with S_")
        self._headers(self.resource_id)


def _post_json(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise VolcCloneError(
            f"clone provider HTTP {exc.code}: {_redact_text(detail)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise VolcCloneError(f"clone provider request failed: {exc.reason}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VolcCloneError("clone provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise VolcCloneError("clone provider returned a non-object response")
    code = _find_status_code(payload)
    if code not in {None, 0, "0", 200, "200"}:
        raise VolcCloneError(
            f"clone provider rejected request: code={code} response={_safe_summary(payload)}"
        )
    return payload


def normalize_provider_state(payload: dict[str, Any]) -> str:
    numeric_status = payload.get("status")
    if numeric_status is not None:
        try:
            return {
                0: "unknown",
                1: "training",
                2: "success",
                3: "failed",
                4: "active",
            }.get(int(numeric_status), "unknown")
        except (TypeError, ValueError):
            pass
    result = payload.get("Result") or payload.get("result")
    if isinstance(result, dict):
        statuses = result.get("Statuses") or result.get("statuses") or []
        if statuses and isinstance(statuses[0], dict):
            explicit_state = str(
                statuses[0].get("State") or statuses[0].get("state") or ""
            ).strip().casefold()
            if explicit_state in {
                "unknown",
                "training",
                "success",
                "active",
                "expired",
                "reclaimed",
                "failed",
            }:
                return explicit_state
    text = json.dumps(payload, ensure_ascii=False).casefold()
    for state, markers in (
        ("reclaimed", ("reclaimed", "reclaim")),
        ("expired", ("expired", "expire")),
        ("active", ("active", "activated")),
        ("success", ("success", "succeeded")),
        ("failed", ("failed", "error")),
        ("training", ("training", "processing", "pending")),
    ):
        if any(marker in text for marker in markers):
            return state
    return "unknown"


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lowered = str(key).casefold()
            if "audio" in lowered or "token" in lowered or "authorization" in lowered:
                result[key] = "***"
            elif "speaker" in lowered and isinstance(item, str):
                result[key] = mask_speaker_id(item)
            else:
                result[key] = redact_payload(item)
        return result
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def _find_status_code(payload: dict[str, Any]):
    for key in ("code", "status_code", "StatusCode"):
        if key in payload:
            return payload[key]
    base = payload.get("BaseResp") or payload.get("base_resp")
    if isinstance(base, dict):
        return _find_status_code(base)
    return None


def _safe_summary(payload: dict[str, Any]) -> str:
    return json.dumps(redact_payload(payload), ensure_ascii=False)[:1000]


def _redact_text(text: str) -> str:
    return text.replace(VOLC_VOICE_CLONE_ACCESS_TOKEN, "***") if VOLC_VOICE_CLONE_ACCESS_TOKEN else text
