from __future__ import annotations

import unittest

from client_launcher import _browser_security_origin, _redact_browser_url


class ClientLauncherUrlTests(unittest.TestCase):
    def test_bootstrap_token_is_not_copied_into_browser_security_origin(self):
        url = "http://example.test/avatar?display=1&bootstrap=secret-token"

        self.assertEqual(_browser_security_origin(url), "http://example.test")
        self.assertNotIn("secret-token", _redact_browser_url(url))


if __name__ == "__main__":
    unittest.main()
