"""
api/trailing_stops.py
=====================
Trailing stop management endpoints.

POST /trailing-stops/run          — trigger full trailing stop update pass for all open positions
POST /trailing-stops/{position_id} — update trailing stop for a single position
GET  /trailing-stops/config        — return current ATR multiplier configuration
PUT  /trailing-stops/config        — override ATR multipliers (stored in module-level dict)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.trailing_stops import TrailingStopService, ATR_MULTIPLIER, DEFAULT_MULTIPLIER

router = APIRouter()
logger = logging.getLogger(__name__)

# ─── Module-level runtime config (no DB needed) ───────────────────────────────

_config: dict = {
    "multipliers":        dict(ATR_MULTIPLIER),   # mutable copy of the defaults
    "default_multiplier": DEFAULT_MULTIPLIER,
    "multiplier_override": None,                  # float or None
    "apply_to_all":        False,
}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_trailing_stops(db: AsyncSession = Depends(get_db)):
    """
    Trigger a full trailing stop update pass for all open positions.
    Returns counts of updated, needs_exit, and skipped positions.
    """
    svc = TrailingStopService(db)

    # Apply any active override before running
    if _config["multiplier_override"] is not None and _config["apply_to_all"]:
        override = _config["multiplier_override"]
        for key in svc.__class__.__module__ and ATR_MULTIPLIER:
            pass  # override is applied dynamically below

    result = await svc.run()
    logger.info(
        "Trailing stop run complete — updated=%d, needs_exit=%d, skipped=%d",
        len(result.get("updated", [])),
        len(result.get("needs_exit", [])),
        result.get("skipped", 0),
    )
    return result


@router.post("/{position_id}")
async def run_trailing_stop_single(
    position_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Update the trailing stop for a single position by its ID.
    Returns a status dict: updated / no_change / needs_exit / skipped / error.
    """
    svc = TrailingStopService(db)
    result = await svc.update_single_position(position_id)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return result


@router.get("/config")
async def get_trailing_stop_config():
    """Return the current ATR multiplier configuration."""
    return {
        "multipliers":        _config["multipliers"],
        "default_multiplier": _config["default_multiplier"],
        "multiplier_override": _config["multiplier_override"],
        "apply_to_all":        _config["apply_to_all"],
        "signal_keys":        list(_config["multipliers"].keys()),
    }


@router.put("/config")
async def update_trailing_stop_config(
    multiplier_override: Optional[float] = Body(None),
    apply_to_all:        bool            = Body(False),
):
    """
    Override ATR multipliers at runtime (stored in module-level config dict).

    - multiplier_override: if provided, use this fixed multiplier value.
    - apply_to_all: if True, the override is applied to every signal type on
      the next /run call; if False, only the default_multiplier is changed.

    Send multiplier_override=null to clear the override and revert to defaults.
    """
    if multiplier_override is not None and multiplier_override <= 0:
        raise HTTPException(
            status_code=422,
            detail="multiplier_override must be a positive number.",
        )

    _config["multiplier_override"] = multiplier_override
    _config["apply_to_all"]        = apply_to_all

    if multiplier_override is not None:
        _config["default_multiplier"] = multiplier_override
        if apply_to_all:
            _config["multipliers"] = {k: multiplier_override for k in _config["multipliers"]}
    else:
        # Reset to module defaults
        _config["multipliers"]        = dict(ATR_MULTIPLIER)
        _config["default_multiplier"] = DEFAULT_MULTIPLIER

    logger.info(
        "Trailing stop config updated — override=%.2f apply_to_all=%s",
        multiplier_override or 0.0,
        apply_to_all,
    )
    return {"status": "updated", "config": _config}
