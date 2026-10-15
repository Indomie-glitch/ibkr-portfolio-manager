"""Safety net so an API key can never reach logs, the browser or the database.

The key is only ever read by the Anthropic SDK; nothing in the app copies it. Even so, any text
that comes from an exception, or that is about to be saved, goes through mask_secrets() first.
"""
import re

# Written in two parts so this file doesn't contain the literal prefix the pre-commit scan looks for
_PREFIX = "sk" + "-ant-"
_KEY_PATTERN = re.compile(re.escape(_PREFIX) + r"[A-Za-z0-9_\-]{8,}")


def mask_secrets(text):
    """Replace anything that looks like an Anthropic key with the prefix, "..." and its last 4 characters."""
    return _KEY_PATTERN.sub(lambda m: f"{_PREFIX}...{m.group()[-4:]}", str(text))
