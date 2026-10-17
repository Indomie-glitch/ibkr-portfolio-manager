import unittest

from trading import account_kind, status


class AccountKindTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(account_kind(["DU1234567"]), "paper")
        self.assertEqual(account_kind(["DF100", "DU200"]), "paper")
        self.assertEqual(account_kind(["U1234567"]), "live")
        self.assertEqual(account_kind(["U1", "DU2"]), "live")  # any live account: treat as live
        self.assertEqual(account_kind([]), "unknown")
        self.assertEqual(account_kind(None), "unknown")


class StatusTest(unittest.TestCase):
    def test_paper_and_live_accounts_can_trade(self):
        for accounts, label in ((["DU1"], "Paper account"), (["U1"], "Live account")):
            result = status(accounts)
            self.assertTrue(result["can_trade"])
            self.assertIsNone(result["reason"])
            self.assertEqual(result["account_label"], label)

    def test_not_connected(self):
        result = status([])
        self.assertFalse(result["can_trade"])
        self.assertIn("connected", result["reason"])

    def test_reports_the_order_limit(self):
        self.assertGreater(status(["DU1"])["max_order_value"], 0)


if __name__ == "__main__":
    unittest.main()
