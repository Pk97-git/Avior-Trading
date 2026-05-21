"""
rebalance.py — AI portfolio rebalancing endpoints
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.rebalancer import RebalancerService

router = APIRouter(prefix="/api/v1/rebalance", tags=["rebalance"])


@router.get("/concentration")
async def concentration_analysis(db: AsyncSession = Depends(get_db)):
    """Sector, country, single-stock concentration with NL alerts."""
    svc = RebalancerService(db)
    return await svc.analyze_concentration()


@router.get("/suggestions")
async def rebalancing_suggestions(
    risk_profile: str = Query("MODERATE", description="CONSERVATIVE | MODERATE | AGGRESSIVE"),
    db: AsyncSession = Depends(get_db),
):
    """AI-generated rebalancing trade suggestions ranked by priority."""
    svc = RebalancerService(db)
    return await svc.get_rebalancing_report(risk_profile=risk_profile)


@router.get("/positions")
async def consolidated_positions(db: AsyncSession = Depends(get_db)):
    """Consolidated view of all positions across all broker accounts."""
    svc = RebalancerService(db)
    return {"positions": await svc.get_consolidated_positions()}
