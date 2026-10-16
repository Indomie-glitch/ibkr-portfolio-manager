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
