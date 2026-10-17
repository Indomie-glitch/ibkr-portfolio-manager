"""HTTP helpers shared by the routers: the allowed origins, the Origin check for POSTs and
Server-Sent Events."""
import json

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

def sse(event, data):
    """One Server-Sent Event: a named event with a JSON payload (masked, as a safety net)."""
    return f"event: {event}\ndata: {mask_secrets(json.dumps(data, ensure_ascii=False))}\n\n"
