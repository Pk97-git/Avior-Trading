"""
tax.py — Tax optimization endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.tax_optimizer import TaxOptimizerService

router = APIRouter(prefix="/api/v1/tax", tags=["tax"])


@router.get("/summary")
async def tax_summary(db: AsyncSession = Depends(get_db)):
    """Full-year tax summary: realized gains, estimated liability, breakdown by term/country."""
    svc = TaxOptimizerService(db)
    return await svc.get_portfolio_tax_summary()


@router.get("/harvest")
async def harvest_opportunities(db: AsyncSession = Depends(get_db)):
    """Tax-loss harvesting opportunities: positions with losses + estimated tax savings."""
    svc = TaxOptimizerService(db)
    return await svc.get_harvesting_opportunities()


@router.get("/year-end")
async def year_end_report(db: AsyncSession = Depends(get_db)):
    """Year-end tax planning report: combined summary + harvesting + recommendations."""
    svc = TaxOptimizerService(db)
    return await svc.get_year_end_summary()
