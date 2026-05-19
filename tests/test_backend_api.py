from __future__ import annotations

from tests.helpers.api import ApiTestCase


class BackendApiSmokeTest(ApiTestCase):
    def test_cors_preflight_allows_local_dev_ports(self):
        response = self.client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5174")


if __name__ == "__main__":
    import unittest

    unittest.main()
