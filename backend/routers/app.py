"""App: health of the connection to IB Gateway."""

from fastapi import APIRouter

import config
from ib_core import connection, ib

router = APIRouter()

@router.get("/health")
def health():
    """Whether IB Gateway is connected; if not, why (see ib_connection.py) and on which port.
    Connected but IBKR not answering (e.g. the account logged in elsewhere) adds problem
    "not_answering"."""
    if ib.isConnected():
        stalled = connection.not_answering()
        return {"connected": True, "port": config.ib_port(), **stalled} if stalled else {"connected": True}
    return {"connected": False, "port": config.ib_port(), **connection.as_dict()}
