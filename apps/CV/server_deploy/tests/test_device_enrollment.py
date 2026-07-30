from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from api.auth import TenantContext, context_allows_request
from core.device_auth_protocol import (
    build_device_signature_payload,
    build_enrollment_proof_payload,
    encode_base64url,
)
from core.device_identity.models import (
    DeviceEnrollmentError,
    DeviceRecord,
    EnrollmentResult,
)
from core.device_identity.service import DeviceAuthenticationService
from core.device_identity.sessions import DeviceSessionStore


class FakeRepository:
    def __init__(self, record: DeviceRecord):
        self.record = record
        self.touches = 0

    def get_device(self, device_id: str):
        return self.record if device_id == self.record.device_id else None

    def touch_device(self, device_id: str, minimum_interval_seconds: int):
        self.touches += 1

    def claim_activation_code(self, **kwargs):
        if kwargs["installation_id"] != self.record.installation_id:
            raise AssertionError("installation mismatch")
        if kwargs["public_key"] != self.record.public_key:
            raise AssertionError("public key mismatch")
        return EnrollmentResult(self.record, False)


class FakeReplayGuard:
    def __init__(self):
        self.values = set()

    def accept(self, device_id: str, nonce: str) -> bool:
        key = (device_id, nonce)
        if key in self.values:
            return False
        self.values.add(key)
        return True


class FakeRedis:
    def __init__(self):
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)

    def eval(self, script, key_count, key):
        return self.values.pop(key, None)


class FakeHealth:
    def __init__(self):
        self.client = FakeRedis()

    def ensure_connected(self):
        return True

    def mark_unhealthy(self):
        raise AssertionError("fake redis should stay healthy")


class FakeDeviceAuth:
    def __init__(self, record: DeviceRecord):
        self.record = record

    def get_active_device(self, device_id: str):
        if device_id == self.record.device_id and self.record.active:
            return self.record
        return None


class DeviceEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self.record = DeviceRecord(
            device_id="dev_test-device-001",
            tenant_id="tenant-a",
            installation_id="00000000-0000-0000-0000-000000000001",
            public_key=self.private_key.public_key().public_bytes_raw(),
            display_name="test",
            status="active",
            auth_version=1,
            created_at=datetime.now(UTC),
        )

    def test_device_signature_is_verified_and_replay_is_rejected(self):
        repository = FakeRepository(self.record)
        service = DeviceAuthenticationService(repository, FakeReplayGuard())
        body = b'{"frame":1}'
        timestamp = str(int(time.time()))
        nonce = "nonce_1234567890abcdef"
        payload = build_device_signature_payload(
            "POST", "/api/v1/recognition/frame", timestamp, nonce, body
        )
        signature = encode_base64url(self.private_key.sign(payload))

        authenticated = service.authenticate(
            method="POST",
            path="/api/v1/recognition/frame",
            timestamp=timestamp,
            nonce=nonce,
            device_id=self.record.device_id,
            signature=signature,
            body=body,
            tolerance_seconds=60,
        )
        replay = service.authenticate(
            method="POST",
            path="/api/v1/recognition/frame",
            timestamp=timestamp,
            nonce=nonce,
            device_id=self.record.device_id,
            signature=signature,
            body=body,
            tolerance_seconds=60,
        )

        self.assertEqual(authenticated, self.record)
        self.assertIsNone(replay)
        self.assertEqual(repository.touches, 1)

        second_nonce = "nonce_abcdef1234567890"
        second_payload = build_device_signature_payload(
            "POST",
            "/api/v1/recognition/frame",
            timestamp,
            second_nonce,
            body,
        )
        second = service.authenticate(
            method="POST",
            path="/api/v1/recognition/frame",
            timestamp=timestamp,
            nonce=second_nonce,
            device_id=self.record.device_id,
            signature=encode_base64url(self.private_key.sign(second_payload)),
            body=body,
            tolerance_seconds=60,
        )
        self.assertEqual(second, self.record)
        self.assertEqual(repository.touches, 1)

    def test_enrollment_requires_private_key_possession_proof(self):
        service = DeviceAuthenticationService(
            FakeRepository(self.record), FakeReplayGuard()
        )
        activation_code = "act_abcdefghijklmnopqrstuvwxyz123456"
        public_key = encode_base64url(self.record.public_key)
        proof = self.private_key.sign(
            build_enrollment_proof_payload(
                activation_code,
                self.record.installation_id,
                public_key,
            )
        )

        result = service.enroll(
            activation_code=activation_code,
            installation_id=self.record.installation_id,
            public_key_b64=public_key,
            proof_signature_b64=encode_base64url(proof),
            display_name="test",
            platform_info={},
        )

        self.assertEqual(result.device, self.record)
        with self.assertRaises(DeviceEnrollmentError):
            service.enroll(
                activation_code=activation_code,
                installation_id=self.record.installation_id,
                public_key_b64=public_key,
                proof_signature_b64=encode_base64url(b"x" * 64),
                display_name="test",
                platform_info={},
            )

    def test_device_and_avatar_principals_are_least_privileged(self):
        device = TenantContext(
            "tenant-a", auth_method="device", device_id=self.record.device_id
        )
        avatar = TenantContext(
            "tenant-a", auth_method="avatar-session", device_id=self.record.device_id
        )

        self.assertTrue(
            context_allows_request(device, "POST", "/api/v1/recognition/frame")
        )
        self.assertTrue(
            context_allows_request(
                device,
                "POST",
                "/api/v1/device-sessions/avatar-state-session",
            )
        )
        self.assertFalse(
            context_allows_request(device, "DELETE", "/api/v1/employees/a")
        )
        self.assertTrue(
            context_allows_request(avatar, "POST", "/api/v1/dialog/voice-ticket")
        )
        self.assertFalse(context_allows_request(avatar, "GET", "/api/v1/employees"))

    def test_avatar_bootstrap_is_one_time_and_session_is_tenant_bound(self):
        health = FakeHealth()
        store = DeviceSessionStore(health, FakeDeviceAuth(self.record))
        bootstrap, _ = store.issue_bootstrap("tenant-a", self.record.device_id)

        consumed = store.consume_bootstrap(bootstrap)
        replay = store.consume_bootstrap(bootstrap)

        self.assertIsNotNone(consumed)
        self.assertIsNone(replay)
        session_token, binding = consumed
        authenticated = store.authenticate_session(session_token)
        self.assertEqual(binding.tenant_id, "tenant-a")
        self.assertEqual(authenticated.device_id, self.record.device_id)

    def test_active_device_can_issue_direct_avatar_state_session(self):
        store = DeviceSessionStore(FakeHealth(), FakeDeviceAuth(self.record))

        session_token, binding = store.issue_session(
            "tenant-a", self.record.device_id
        )

        self.assertEqual(binding.tenant_id, "tenant-a")
        self.assertEqual(binding.device_id, self.record.device_id)
        self.assertEqual(
            store.authenticate_session(session_token).tenant_id,
            "tenant-a",
        )
        with self.assertRaises(ValueError):
            store.issue_session("tenant-b", self.record.device_id)


if __name__ == "__main__":
    unittest.main()
