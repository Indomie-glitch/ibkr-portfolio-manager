"""Settings and file locations, shared by the dev server and the Mac app.

Imported before anything that reads settings: in development it loads the repo's .env; the Mac
app passes settings as environment variables instead and sets PORTFOLIO_DATA_DIR to its
Application Support folder.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Saved summaries and caches: data/ in the repo for development, Application Support in the Mac app
DATA_DIR = Path(os.getenv("PORTFOLIO_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
IN_APP = bool(os.getenv("PORTFOLIO_DATA_DIR"))

# Set by app_main.py in the Mac app (read from stdin, never from a file or the command line)
API_TOKEN = None

# Secrets the Mac app sends over stdin from the macOS Keychain, held only in memory
SECRETS = {}

# Settings the Mac app sends over stdin from its Settings screen (development uses .env)
SETTINGS = {}


def ib_port():
    """IB Gateway's API port: the Settings screen in the Mac app, IB_PORT in .env in development."""
    return int(SETTINGS.get("ib_port") or os.getenv("IB_PORT", "4002"))


def anthropic_api_key():
    """The Anthropic key: from the Keychain in the Mac app, from .env in development."""
    if IN_APP:
        return SECRETS.get("anthropic_api_key")
    return os.getenv("ANTHROPIC_API_KEY")


# What to tell the user when there's no key
MISSING_KEY_MESSAGE = ("Add your Anthropic API key in Settings to turn on AI summaries." if IN_APP else
                       "Add ANTHROPIC_API_KEY to .env and restart the backend to turn on AI summaries.")
