import asyncio
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import config  # first: loads .env before other modules read settings
import constituents
import directors
from supply_chain import worker as pipeline
import lots
from ib_core import NOT_CONNECTED, ib, keep_connected
from routers import app as app_routes, directors as directors_routes, flex, indices, pipeline as pipeline_routes, positions, risk, summaries, trading
from web import ALLOWED_ORIGINS, end_streams_on_stop

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Live streams end when the server is told to stop, so a reload or quit doesn't hang on them
    end_streams_on_stop()
    task = asyncio.create_task(keep_connected())
    # Purchase dates from IBKR's Flex report, refreshed daily when Flex is set up (docs/flex-query.md)
    lots_task = asyncio.create_task(lots.keep_refreshed())
    # Members of six stock indexes, refreshed weekly (constituents.py)
    indices_task = asyncio.create_task(constituents.keep_refreshed())
    # Boards of directors: the bundled US seed is merged in; newer documents are looked for weekly
    try:
        directors.merge_seed()
    except Exception as exc:  # a damaged seed: boards are read on demand instead
        print(f"Directors: couldn't load the seed: {exc.__class__.__name__}")
    directors_task = asyncio.create_task(directors.keep_checked())
    # The supply chain pipeline's workers: only while PIPELINE=1 (they download filings and spend AI budget)
    pipeline_task = asyncio.create_task(pipeline.keep_running())
    yield
    task.cancel()
    lots_task.cancel()
    indices_task.cancel()
    directors_task.cancel()
    pipeline_task.cancel()
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

class PathCORS:
    """Two CORS policies chosen by path: GET-only everywhere, GET + POST for the summaries."""

    def __init__(self, app):
        self.get_only = CORSMiddleware(app, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET"],
                                       allow_headers=["X-App-Token"])
        self.get_post = CORSMiddleware(app, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                                       allow_headers=["X-App-Token"])

    async def __call__(self, scope, receive, send):
        summary_path = scope["type"] == "http" and (scope["path"].startswith(("/summary/", "/orders/", "/directors/", "/pipeline/"))
                                                    or scope["path"] in ("/portfolio-summary", "/orders", "/trading/borrowing"))
        await (self.get_post if summary_path else self.get_only)(scope, receive, send)

# In the Mac app, every request must carry the token the app created at launch, so other programs
# on the computer can't use this API. Added before PathCORS so PathCORS wraps it and a 401 still
# carries CORS headers the page can read. Development (no token) is unchanged.
@app.middleware("http")
async def require_app_token(request: Request, call_next):
    if config.API_TOKEN and request.method != "OPTIONS":
        if not secrets.compare_digest(request.headers.get("x-app-token", ""), config.API_TOKEN):
            return JSONResponse({"detail": "Missing or wrong app token"}, status_code=401)
    return await call_next(request)

app.add_middleware(PathCORS)

# If Gateway drops in the middle of a request, ib_async raises ConnectionError
@app.exception_handler(ConnectionError)
async def connection_error(request: Request, exc: ConnectionError):
    return JSONResponse(status_code=503, content={"detail": NOT_CONNECTED})

for routes in (app_routes, positions, flex, summaries, trading, risk, indices, directors_routes, pipeline_routes):
    app.include_router(routes.router)
