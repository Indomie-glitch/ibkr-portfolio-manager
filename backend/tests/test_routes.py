"""Every endpoint the API serves, so moving code between routers can't lose or rename one."""
import unittest

import main

ENDPOINTS = [
    "GET /account",
    "GET /competitors/{con_id}",
    "GET /health",
    "GET /history/{con_id}",
    "GET /indices",
    "GET /indices/{con_id}",
    "GET /indices/{index_id}/members",
    "GET /lots/status",
    "GET /lots/{con_id}",
    "GET /news/{con_id}",
    "GET /orders",
    "GET /orders/stream",
    "GET /performance/{con_id}",
    "GET /portfolio-summary",
    "GET /portfolio-summary/compare",
    "GET /portfolio-summary/facts",
    "GET /portfolio-summary/history",
    "GET /portfolio-summary/history/{summary_id}",
    "GET /positions",
    "GET /prices",
    "GET /profile/{con_id}",
    "GET /quotes",
    "GET /risk",
    "GET /risk/bankruptcy",
    "GET /search",
    "GET /stats/{con_id}",
    "GET /summary/{con_id}",
    "GET /summary/{con_id}/compare",
    "GET /summary/{con_id}/facts",
    "GET /summary/{con_id}/history",
    "GET /summary/{con_id}/history/{summary_id}",
    "GET /trading/borrowing",
    "GET /trading/status",
    "GET /usage",
    "POST /orders",
    "POST /orders/preview",
    "POST /orders/{order_id}/cancel",
    "POST /orders/{order_id}/modify",
    "POST /portfolio-summary",
    "POST /summary/{con_id}",
    "POST /trading/borrowing",
]


class RoutesTest(unittest.TestCase):
    def test_all_endpoints_are_served(self):
        served = sorted(f"{method.upper()} {path}" for path, methods in main.app.openapi()["paths"].items() for method in methods)
        self.assertEqual(served, ENDPOINTS)


if __name__ == "__main__":
    unittest.main()
