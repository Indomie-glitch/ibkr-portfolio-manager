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
    """Whether the background task keeps index members and their Yahoo data up to date. On by
    default since the Connections section uses them (#114); the bundled seed means it only tops up.
    Off with INDEX_LOADER=0 in .env in development, or "load_index_members": false in the app's
    settings.json."""
    if IN_APP:
        return SETTINGS.get("index_loader") is not False
    return os.getenv("INDEX_LOADER", "").strip().lower() not in ("0", "false", "no", "off")


def person_data_enabled():
    """Whether the weekly check for new people's Wikipedia and Wikidata facts runs (#280). On by default;
    PERSON_DATA=0 in .env (or "person_data": false from the app) turns it off."""
    if IN_APP:
        return SETTINGS.get("person_data") is not False
    return os.getenv("PERSON_DATA", "").strip().lower() not in ("0", "false", "no", "off")


def pipeline_enabled():
    """Whether the supply chain pipeline's workers run in the background (#116). Off by default: they spend AI budget
    and download filings. PIPELINE=1 in .env (or "pipeline": true from the app) turns them on."""
    if IN_APP:
        return SETTINGS.get("pipeline") is True
    return os.getenv("PIPELINE", "").strip().lower() in ("1", "true", "yes", "on")


def pipeline_workers():
    """How many workers run side by side (PIPELINE_WORKERS, default 2)."""
    try:
        return max(1, min(8, int(os.getenv("PIPELINE_WORKERS", "2"))))
    except ValueError:
        return 2


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

# The supply chain Reader (#124) reads filings chunk by chunk with the cheapest current model, whatever the summaries
# use: a fixed answer shape from a passage, for every filing of every watched company. The Verifier checks its claims.
READER_MODEL = "claude-haiku-5-5"

# The Verifier (#125) checks each Reader claim against its paragraph: fewer calls, and a wrong link costs more than a
# missed one, so a stronger model than the Reader's. A refusal can be answered by Anthropic's fallback model instead
# (verifier.py records which model answered).
VERIFIER_MODEL = "claude-sonnet-5-5"


def flex_token():
    """The IBKR Flex Web Service token (a secret: memory only in the Mac app, IB_FLEX_TOKEN in .env in
    development). See docs/flex-query.md."""
    if IN_APP:
        return SECRETS.get("flex_token")
    return os.getenv("IB_FLEX_TOKEN") or None


def openfigi_api_key():
    """Optional OpenFIGI key (OPENFIGI_API_KEY in .env; in the Mac app, memory only): without one OpenFIGI allows 25
    searches a minute, with one 250. A secret, so never logged (secrets_guard)."""
    if IN_APP:
        return SECRETS.get("openfigi_api_key")
    return os.getenv("OPENFIGI_API_KEY") or None


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
