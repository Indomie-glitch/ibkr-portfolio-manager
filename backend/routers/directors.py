"""Boards of directors (#113): read from the company's proxy statement (US) or annual report (ASX)."""
import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import directors
import directors_sources as sources
import yahoo
from ib_core import get_contract_info, require_ib
from names import display_name
from routers.indices import market_of
from routers.positions import yahoo_info
from secrets_guard import mask_secrets
from web import check_origin

router = APIRouter()

NEEDS = {
    "api_key": "Add an Anthropic API key in Settings to read boards.",
    "sec_contact_email": "US boards need a contact email for SEC (SEC_CONTACT_EMAIL).",
    "asx_terms": "ASX boards come from ASX announcements, which ASX allows for personal use only. Accept ASX's terms first.",
    "unsupported_market": "Boards are only available for ASX and US stocks.",
}


async def company(con_id):
    """(market, symbol, full company name). The name is matched against other documents' lists of
    boards, so Yahoo's full name is used where possible: IB cuts names at 28 characters
    ("Commonwealth Bank of Austral")."""
    contract, long_name = await get_contract_info(con_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown stock")
    name = display_name(long_name, contract.symbol)[0] if long_name else contract.symbol
    symbol = yahoo.yahoo_symbol(contract)
    if symbol:
        try:
            info = await yahoo_info(symbol)
            name = info.get("longName") or name
        except Exception:
            pass  # IB's name will do
    return market_of(contract), contract.symbol, name


@router.get("/directors/asx-terms")
def asx_terms():
    """Whether this user has accepted ASX's terms (needed before ASX annual reports are fetched)."""
    return {"accepted_at": directors.asx_terms_accepted()}


class AsxTerms(BaseModel):
    accept: bool


@router.post("/directors/asx-terms")
def change_asx_terms(change: AsxTerms, request: Request):
    """Records the user's own acceptance (or withdrawal) of ASX's terms of use: announcements are for
    private and personal use."""
    check_origin(request)
    return {"accepted_at": directors.accept_asx_terms(change.accept)}


@router.get("/directors/{con_id}", dependencies=[Depends(require_ib)])
async def get_board(con_id: int):
    """The stored board (index members ship with the US seed), or status "not_read" with what is
    needed to read it (POST)."""
    market, symbol, name = await company(con_id)
    stored = directors.board(market, symbol) if market else None
    needs = directors.can_read(market)
    if stored is None:
        return {"status": "not_read", "market": market, "symbol": symbol, "company_name": name,
                "can_read": not needs, "needs": [{"id": n, "message": NEEDS[n]} for n in needs]}
    return {**stored, "market": market, "symbol": symbol, "can_read": not needs,
            "needs": [{"id": n, "message": NEEDS[n]} for n in needs]}


@router.post("/directors/{con_id}", dependencies=[Depends(require_ib)])
async def read_board(con_id: int, request: Request):
    """Reads (or re-reads) the board from the newest document, using the user's Anthropic key: a few
    US cents at most. Takes 10 to 60 seconds."""
    check_origin(request)
    market, symbol, name = await company(con_id)
    needs = directors.can_read(market)
    if needs:
        raise HTTPException(status_code=409, detail=" ".join(NEEDS[n] for n in needs))
    try:
        result = await directors.read_board(market, symbol, name, con_id)
    except sources.SourceUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Claude couldn't read the document ({mask_secrets(exc)}).")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"The board couldn't be read ({exc.__class__.__name__}).")
    return {**result, "market": market, "symbol": symbol, "can_read": True, "needs": []}


@router.get("/people/{person_id}")
def get_person(person_id: str):
    """Every board seat for one person among the boards read so far (by Wikidata ID, or a seat's own
    ID): for "also on BHP's board"."""
    found = directors.person(person_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No board seats for this person")
    return found
