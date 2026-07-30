"""Signed HTTP client used by device-side API-only mode."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from api.auth import sign_request
from config import API_BASE_URL, API_KEY, API_SECRET

logger = logging.getLogger(__name__)


class ApiClientError(RuntimeError):
    pass


class SignedApiClient:
    def __init__(
        self,
        base_url: str = API_BASE_URL,
        api_key: str = API_KEY,
        api_secret: str = API_SECRET,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout

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
        body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        timestamp = str(int(time.time()))
        headers = {
            "X-Api-Key": self.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": sign_request(
                self.api_secret,
                method,
                path,
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
