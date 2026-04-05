from __future__ import annotations

import ssl
import unittest
from unittest.mock import patch
from urllib.error import URLError

from mcp_servers.system.core.filesystem.stdio_server import _web_fetch_result


class WebFetchTransportFailureTests(unittest.TestCase):
    def test_web_fetch_classifies_ssl_verification_failure(self) -> None:
        ssl_error = ssl.SSLCertVerificationError("certificate verify failed")
        with patch("mcp_servers.system.core.filesystem.stdio_server.urlopen", side_effect=URLError(ssl_error)):
            result = _web_fetch_result("https://example.com")

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_layer"], "transport")
        self.assertEqual(result["failure_kind"], "ssl_verification_failed")

    def test_web_fetch_keeps_non_ssl_url_errors_as_network_error(self) -> None:
        with patch("mcp_servers.system.core.filesystem.stdio_server.urlopen", side_effect=URLError("temporary failure in name resolution")):
            result = _web_fetch_result("https://example.com")

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_layer"], "transport")
        self.assertEqual(result["failure_kind"], "network_error")


if __name__ == "__main__":
    unittest.main()
