"""Settings and file locations, shared by the dev server and the Mac app.

Imported before anything that reads settings: in development it loads the repo's .env; the Mac
app passes settings as environment variables instead and sets PORTFOLIO_DATA_DIR to its
Application Support folder.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Saved summaries and caches: data/ in the repo for development, Application Support in the Mac app
DATA_DIR = Path(os.getenv("PORTFOLIO_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
IN_APP = bool(os.getenv("PORTFOLIO_DATA_DIR"))

# Set by app_main.py in the Mac app (read from stdin, never from a file or the command line)
API_TOKEN = None

# Secrets the Mac app sends over stdin (the Anthropic key entered in Settings), held only in
# memory: nothing secret is ever stored
SECRETS = {}

# Settings the Mac app sends over stdin from its Settings screen (development uses .env)
SETTINGS = {}


def ib_client_id():
    """The first client ID to use: 17 in the Mac app, IB_CLIENT_ID (default 1) in development, so a
    dev backend and the app can both be connected at the same time."""
    return 17 if IN_APP else int(os.getenv("IB_CLIENT_ID", "1"))


def index_loader_enabled():
    """Whether the background task loads index members and their Yahoo data (about 20 minutes of
    Yahoo calls). Off by default until there is a UI that uses them (#114): INDEX_LOADER=1 in .env
    in development, "load_index_members" in the app's settings.json."""
    if IN_APP:
        return bool(SETTINGS.get("index_loader"))
    return os.getenv("INDEX_LOADER", "").strip().lower() in ("1", "true", "yes", "on")


def ib_port():
    """IB Gateway's API port: the Settings screen in the Mac app, IB_PORT in .env in development."""
    return int(SETTINGS.get("ib_port") or os.getenv("IB_PORT", "4002"))


def anthropic_api_key():
    """The Anthropic key: entered in Settings in the Mac app (memory only), from .env in development."""
    if IN_APP:
        return SECRETS.get("anthropic_api_key")
    return os.getenv("ANTHROPIC_API_KEY")


# Settings bundled with the Mac app's backend at build time (write_app_config.py), not in the repo
APP_CONFIG_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "app_config.json"


def bundled_setting(name):
    try:
        return json.loads(APP_CONFIG_PATH.read_text()).get(name)
    except (OSError, ValueError, AttributeError):
        return None


def sec_contact_email():
    """The contact address SEC requires in every EDGAR request (its fair-access rule; without one
    EDGAR answers 403): SEC_CONTACT_EMAIL in .env in development; in the Mac app, the address bundled
    at build time (app_config.json). Never written in the code (#113)."""
    if IN_APP:
        return SETTINGS.get("sec_contact_email") or bundled_setting("sec_contact_email") or None
    return os.getenv("SEC_CONTACT_EMAIL") or None


# Board extraction (#113) always uses the cheapest current model, whatever the summaries use: it
# fills a fixed answer shape from a document, and the seed covers hundreds of companies
DIRECTORS_MODEL = "claude-haiku-5-5"


def flex_token():
    """The IBKR Flex Web Service token (a secret: memory only in the Mac app, IB_FLEX_TOKEN in .env in
    development). See docs/flex-query.md."""
    if IN_APP:
        return SECRETS.get("flex_token")
    return os.getenv("IB_FLEX_TOKEN") or None


def flex_query_id():
    """The ID of the Activity Flex Query that lists open lots and trades (not a secret)."""
    if IN_APP:
        return SETTINGS.get("flex_query_id")
    return os.getenv("IB_FLEX_QUERY_ID") or None


def flex_configured():
    return bool(flex_token() and flex_query_id())


# Models the Settings screen offers (structured outputs + streaming work on all of them)
AI_MODELS = {
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
}


def ai_model():
    """The model for AI summaries: the Settings screen in the Mac app, AI_MODEL in .env in development
    (default claude-haiku-4-5, the single place to change it)."""
    chosen = SETTINGS.get("ai_model")
    return chosen if chosen in AI_MODELS else os.getenv("AI_MODEL", "claude-haiku-4-5")


# What to tell the user when there's no key
MISSING_KEY_MESSAGE = ("Add your Anthropic API key in Settings to turn on AI summaries. It isn't saved, "
                       "so enter it again after restarting." if IN_APP else
                       "Add ANTHROPIC_API_KEY to .env and restart the backend to turn on AI summaries.")


# ---------- trading (Milestone 6) ----------

def max_order_value():
    """The largest order allowed, in the account's base currency (MAX_ORDER_VALUE, default 10,000)."""
    try:
        value = float(os.getenv("MAX_ORDER_VALUE", "10000"))
    except ValueError:
        return 10000.0
    return value if value > 0 else 10000.0


# ---------- risk analysis (Milestone 8) ----------

def risk_free_rate():
    """What cash earns in a year, for the Sharpe ratio and the example mixes: RISK_FREE_RATE in .env,
    default 0.046 (the RBA cash rate target, 4.60% since 29 Sep 2026)."""
    try:
        return float(os.getenv("RISK_FREE_RATE", "0.046"))
    except ValueError:
        return 0.046
