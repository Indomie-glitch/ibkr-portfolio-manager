"""Entry point of the backend bundled inside the Mac app (built with PyInstaller, started by Tauri).

The app writes a per-launch access token as the first line of stdin, then keeps stdin open.
When stdin closes (the app quit or crashed), the backend stops too, so it never keeps running on
its own.
"""
import argparse
import json
import os
import sys
import threading

import uvicorn


def watch_parent():
    """Messages from the app, one JSON object per line, until stdin closes:
    {"set_secret": name, "value": ...} or {"clear_secret": name} (secrets from the Keychain)."""
    import config
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue  # never echo the line: it may hold a secret
        if "set_secret" in message:
            config.SECRETS[message["set_secret"]] = message.get("value")
        elif "clear_secret" in message:
            config.SECRETS.pop(message["clear_secret"], None)
    os._exit(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token-stdin", action="store_true", help="read the API access token from stdin")
    args = parser.parse_args()

    import config
    if args.token_stdin:
        config.API_TOKEN = sys.stdin.readline().strip() or None
        if not config.API_TOKEN:
            sys.exit("No access token on stdin")

    import main as backend  # after argument parsing, so --help works without importing everything

    threading.Thread(target=watch_parent, daemon=True).start()
    uvicorn.run(backend.app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
