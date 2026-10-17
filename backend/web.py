"""HTTP helpers shared by the routers: the allowed origins, the Origin check for POSTs,
Server-Sent Events, and ending long-lived streams when the server stops."""
import asyncio
import json
import signal
import threading

from fastapi import HTTPException

from secrets_guard import mask_secrets

# Let the Vite dev server and the Mac app's window (Tauri serves the built frontend from
# tauri://localhost) call the API. Everything is GET-only, except POST /summary/{con_id},
# POST /portfolio-summary (generating a summary) and POST /orders/... (trading), which only these
# origins may call.
ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "tauri://localhost"]

def check_origin(request):
    # A cross-site form POST skips the CORS preflight, so check the origin here as well.
    # Requests without an Origin header come from local tools like curl, not other websites.
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin not allowed")

# Set when the server is told to stop (a --reload, Ctrl+C, or the Mac app quitting). uvicorn waits
# for every open connection to finish before it stops, and a live stream never finishes by itself,
# so streams end when this is set. The app's own shutdown can't do it: it runs after that wait.
stopping = asyncio.Event()


def end_streams_on_stop():
    """Called once at startup: set `stopping` on SIGTERM / SIGINT, then let the handler that was
    already there (uvicorn's) do its usual work."""
    if threading.current_thread() is not threading.main_thread():
        return  # signal handlers can only be set from the main thread
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous = signal.getsignal(sig)

        def handler(signum, frame, previous=previous):
            loop.call_soon_threadsafe(stopping.set)
            if callable(previous):
                previous(signum, frame)
            elif previous == signal.SIG_DFL:
                signal.signal(signum, signal.SIG_DFL)
                signal.raise_signal(signum)

        signal.signal(sig, handler)


async def next_or_none(queue, timeout):
    """The next item from queue; None after `timeout` seconds or as soon as the server is stopping."""
    getter = asyncio.ensure_future(queue.get())
    stopper = asyncio.ensure_future(stopping.wait())
    try:
        done, _ = await asyncio.wait({getter, stopper}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (getter, stopper):
            if not task.done():
                task.cancel()
    return getter.result() if getter in done else None


def sse(event, data):
    """One Server-Sent Event: a named event with a JSON payload (masked, as a safety net)."""
    return f"event: {event}\ndata: {mask_secrets(json.dumps(data, ensure_ascii=False))}\n\n"
