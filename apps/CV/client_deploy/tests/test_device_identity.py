from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from core.device_auth_protocol import encode_base64url
from core.device_identity import DeviceIdentityStore


class DeviceIdentityStoreTests(unittest.TestCase):
    def test_identity_round_trip_and_private_key_protection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "identity.json"
            store = DeviceIdentityStore(path)
            identity = store.load_or_create_pending("test-device")
            raw_private = identity.private_key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            loaded = store.load()
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(loaded.public_key_bytes, identity.public_key_bytes)
            self.assertNotIn(
                encode_base64url(raw_private), path.read_text(encoding="utf-8")
            )
            expected = "windows-dpapi-user" if os.name == "nt" else "file-0600"
            self.assertEqual(payload["privateKeyProtection"], expected)


if __name__ == "__main__":
    unittest.main()
