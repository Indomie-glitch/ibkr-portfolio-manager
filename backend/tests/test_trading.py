import unittest

from trading import account_kind, status


class AccountKindTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(account_kind(["DU1234567"]), "paper")
        self.assertEqual(account_kind(["DF100", "DU200"]), "paper")
        self.assertEqual(account_kind(["U1234567"]), "live")
        self.assertEqual(account_kind(["U1", "DU2"]), "unknown")
        self.assertEqual(account_kind([]), "unknown")
        self.assertEqual(account_kind(None), "unknown")


class StatusTest(unittest.TestCase):
    def check(self, accounts, mode, read_only=False, live_confirmed=False):
        return status(accounts, read_only, mode=mode, live_confirmed=live_confirmed)

    def test_off_by_default_is_read_only(self):
        result = self.check(["DU1"], "off")
        self.assertFalse(result["can_trade"])
        self.assertIn("read only", result["reason"])
        self.assertEqual(result["account_label"], "Paper account")

    def test_paper_mode_on_paper_account(self):
        self.assertTrue(self.check(["DU1"], "paper")["can_trade"])

    def test_paper_mode_refuses_live_account(self):
        result = self.check(["U1"], "paper")
        self.assertFalse(result["can_trade"])
        self.assertIn("live account", result["reason"])

    def test_unknown_account_refused(self):
        self.assertFalse(self.check([], "paper")["can_trade"])

    def test_live_needs_confirmation(self):
        self.assertFalse(self.check(["U1"], "live")["can_trade"])
        self.assertTrue(self.check(["U1"], "live", live_confirmed=True)["can_trade"])

    def test_read_only_connection_refused(self):
        result = self.check(["DU1"], "paper", read_only=True)
        self.assertFalse(result["can_trade"])
        self.assertIn("Restart", result["reason"])


if __name__ == "__main__":
    unittest.main()
