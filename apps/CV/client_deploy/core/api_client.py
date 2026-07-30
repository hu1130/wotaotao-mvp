"""Signed HTTP client used by device-side API-only mode."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from api.auth import sign_request
from config import API_BASE_URL, API_KEY, API_SECRET
from core.device_identity import get_enrolled_device_identity

logger = logging.getLogger(__name__)


class ApiClientError(RuntimeError):
    pass


class SignedApiClient:
    def __init__(
        self,
        base_url: str = API_BASE_URL,
        api_key: str | None = None,
        api_secret: str | None = None,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        explicit_hmac = api_key is not None or api_secret is not None
        self.api_key = API_KEY if api_key is None else api_key
        self.api_secret = API_SECRET if api_secret is None else api_secret
        self.timeout = timeout
        self.device_identity = (
            None if explicit_hmac else get_enrolled_device_identity(self.base_url)
        )

    def get(self, path: str, timeout: float | None = None) -> dict:
        return self.request("GET", path, None, timeout=timeout)

    def post(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        return self.request("POST", path, payload, timeout=timeout)

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None,
        timeout: float | None = None,
    ) -> dict:
        body = (
            b""
            if payload is None
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        parsed_path = urlsplit(path)
        signing_path = parsed_path.path or path
        device_signing_target = signing_path
        if parsed_path.query:
            device_signing_target += f"?{parsed_path.query}"
        if self.device_identity is not None:
            headers = self.device_identity.signed_headers(
                method, device_signing_target, body
            )
        else:
            if not self.api_key or not self.api_secret:
                raise ApiClientError("no enrolled device identity or HMAC credential")
            timestamp = str(int(time.time()))
            headers = {
                "X-Api-Key": self.api_key,
                "X-Timestamp": timestamp,
                "X-Signature": sign_request(
                    self.api_secret,
                    method,
                    signing_path,
                    timestamp,
                    body,
                ),
            }
        if body:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body if body else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                text = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="ignore")
            raise ApiClientError(f"HTTP {exc.code}: {text}") from exc
        except Exception as exc:
            raise ApiClientError(str(exc)) from exc
        try:
            data = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise ApiClientError(text or str(exc)) from exc
        if data.get("ok") is False:
            raise ApiClientError(str(data.get("detail") or data.get("error") or data))
        return data
