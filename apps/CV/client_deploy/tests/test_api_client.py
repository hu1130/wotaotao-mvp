from __future__ import annotations

import unittest
from unittest.mock import patch

from api.auth import sign_request
from core.api_client import SignedApiClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"ok":true}'


class RecordingIdentity:
    def __init__(self):
        self.target = ""

    def signed_headers(self, method: str, target: str, body: bytes):
        self.target = target
        return {"X-Device-Id": "dev_test-device-001"}


class SignedApiClientTests(unittest.TestCase):
    def test_legacy_hmac_keeps_query_out_of_existing_signature_protocol(self):
        captured = []

        def urlopen(request, timeout):
            captured.append(request)
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=urlopen):
            client = SignedApiClient(
                "http://server", api_key="legacy-key", api_secret="legacy-secret"
            )
            client.get("/api/v1/client-tasks/next?device_id=frontdesk")

        request = captured[0]
        timestamp = request.get_header("X-timestamp")
        expected = sign_request(
            "legacy-secret",
            "GET",
            "/api/v1/client-tasks/next",
            timestamp,
            b"",
        )
        self.assertEqual(request.get_header("X-signature"), expected)

    def test_device_signature_covers_query_string(self):
        identity = RecordingIdentity()
        with (
            patch(
                "core.api_client.get_enrolled_device_identity", return_value=identity
            ),
            patch("urllib.request.urlopen", return_value=FakeResponse()),
        ):
            client = SignedApiClient("http://server")
            client.get("/api/v1/client-tasks/next?device_id=frontdesk")

        self.assertEqual(
            identity.target,
            "/api/v1/client-tasks/next?device_id=frontdesk",
        )


if __name__ == "__main__":
    unittest.main()
