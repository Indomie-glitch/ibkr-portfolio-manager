"""Purchase lots from the IBKR Flex report (Milestone 5.1)."""

from fastapi import APIRouter, Depends, HTTPException

import lots
from ib_core import ib, require_ib

router = APIRouter()

# ---------- Purchase lots (Flex report) ----------

@router.get("/lots/status")
def lots_status():
    """Whether Flex is set up, when the lots were last fetched, the report's date and the last error."""
    return lots.status()

@router.get("/lots/{con_id}", dependencies=[Depends(require_ib)])
def holding_lots(con_id: int):
    """A holding's purchase lots with their 12-month CGT discount dates, matched to the quantity
    held now (lots.lots_for)."""
    held = next((item.position for item in ib.portfolio() if item.contract.conId == con_id), None)
    if held is None:
        raise HTTPException(status_code=404, detail="Not a current holding")
    return lots.lots_for(con_id, held)
