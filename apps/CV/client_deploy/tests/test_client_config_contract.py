from __future__ import annotations

import importlib
import unittest


class ClientConfigContractTests(unittest.TestCase):
    def test_realtime_dialog_app_key_is_exported(self):
        config = importlib.import_module("config")

        self.assertTrue(hasattr(config, "REALTIME_DIALOG_APP_KEY"))

    def test_shared_fixed_tts_imports_with_client_config(self):
        fixed_tts = importlib.import_module("core.fixed_tts")

        self.assertTrue(hasattr(fixed_tts, "FixedTtsClient"))


if __name__ == "__main__":
    unittest.main()
