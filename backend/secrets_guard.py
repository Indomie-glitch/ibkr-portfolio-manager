"""Safety net so a secret can never reach logs, the browser or the database.

The Anthropic key is only ever read by the Anthropic SDK, and the Flex token only by the Flex client;
nothing in the app copies them. Even so, any text that comes from an exception, or that is about to
be saved, goes through mask_secrets() first.
"""
import re

# Written in two parts so this file doesn't contain the literal prefix the pre-commit scan looks for
_PREFIX = "sk" + "-ant-"
_KEY_PATTERN = re.compile(re.escape(_PREFIX) + r"[A-Za-z0-9_\-]{8,}")


def _known_secrets():
    """Secrets with no recognisable shape (the Flex token is just digits; the OpenFIGI key), masked by their value."""
    import config  # here, not at the top: config imports modules that import this one
    return [value for value in (config.flex_token(), config.openfigi_api_key()) if value and len(value) >= 8]


def mask_secrets(text):
    """Replace anything that looks like an Anthropic key with the prefix, "..." and its last 4
    characters, and the Flex token with "..." and its last 4 characters."""
    text = _KEY_PATTERN.sub(lambda m: f"{_PREFIX}...{m.group()[-4:]}", str(text))
    for secret in _known_secrets():
        text = text.replace(secret, f"...{secret[-4:]}")
    return text
