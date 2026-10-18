"""mask_secrets: the last line of defence between a key or token and the logs."""
import unittest
from unittest import mock

import config
from secrets_guard import mask_secrets

# Built in two parts, like secrets_guard.py, so this file doesn't contain the literal prefix
PREFIX = "sk" + "-ant-"
KEY = PREFIX + "api03-AbCdEf_123-456xyzWXYZ"


class MaskSecretsTests(unittest.TestCase):
    def test_an_anthropic_key_keeps_only_its_last_four_characters(self):
        masked = mask_secrets(f"AuthenticationError: invalid x-api-key {KEY} for this request")
        self.assertNotIn(KEY, masked)
        self.assertNotIn("AbCdEf", masked)
        self.assertEqual(masked, f"AuthenticationError: invalid x-api-key {PREFIX}...WXYZ for this request")

    def test_every_key_in_the_text_is_masked(self):
        masked = mask_secrets(f"{KEY} and {KEY[:-4]}abcd")
        self.assertEqual(masked, f"{PREFIX}...WXYZ and {PREFIX}...abcd")

    def test_the_flex_token_is_masked_by_its_value(self):
        with mock.patch.object(config, "flex_token", return_value="123456789012345678"):
            masked = mask_secrets("GetStatement?t=123456789012345678&q=987 failed")
        self.assertEqual(masked, "GetStatement?t=...5678&q=987 failed")

    def test_short_or_missing_tokens_are_not_used_to_mask(self):
        # A token under 8 characters would mask ordinary numbers in error messages
        with mock.patch.object(config, "flex_token", return_value="1234"):
            self.assertEqual(mask_secrets("error 1234 at line 1234"), "error 1234 at line 1234")
        with mock.patch.object(config, "flex_token", return_value=None):
            self.assertEqual(mask_secrets("nothing secret"), "nothing secret")

    def test_not_text_is_turned_into_text_first(self):
        error = ValueError(f"bad key {KEY}")
        self.assertEqual(mask_secrets(error), f"bad key {PREFIX}...WXYZ")

    def test_a_short_prefix_alone_is_left_alone(self):
        # Fewer than 8 characters after the prefix isn't a key
        self.assertEqual(mask_secrets(f"{PREFIX}abc"), f"{PREFIX}abc")


if __name__ == "__main__":
    unittest.main()
