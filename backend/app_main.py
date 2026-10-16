"""Entry point of the backend bundled inside the Mac app (built with PyInstaller, started by Tauri).

The app keeps this process's stdin open. When stdin closes (the app quit or crashed), the backend
stops too, so it never keeps running on its own.
"""
import argparse
import os
import sys
import threading

import uvicorn


def watch_parent():
    for _line in sys.stdin:
        pass  # later steps send messages here
    os._exit(0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import main as backend  # after argument parsing, so --help works without importing everything

    threading.Thread(target=watch_parent, daemon=True).start()
    uvicorn.run(backend.app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
