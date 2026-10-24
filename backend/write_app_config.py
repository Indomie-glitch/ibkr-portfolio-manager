"""Writes app_config.json for the Mac app's bundled backend (run by `npm run build:backend`).

It holds settings the app needs that aren't secret but don't belong in the repository either: the
SEC contact email (#113; EDGAR refuses requests without one). Read from the environment or .env, so
the address lives only in your .env and in CI's SEC_CONTACT_EMAIL secret. app_config.json is
gitignored, and anyone who opens the built app can read it.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")
settings = {"sec_contact_email": os.getenv("SEC_CONTACT_EMAIL") or None}
(HERE / "app_config.json").write_text(json.dumps(settings))
if not settings["sec_contact_email"]:
    print("app_config.json: no SEC_CONTACT_EMAIL, so the built app can't read US boards")
