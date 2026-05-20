"""
goal_tracker.py
===============
GoalTrackerService — tracks progress toward investment goals.

Goal types:
  RETIREMENT       — long-horizon growth; default 8% pa return (AGGRESSIVE mix)
  HOUSE            — medium-horizon; default 6% pa (MODERATE)
  PASSIVE_INCOME   — yield-focused; target monthly income = target_amount/12
  AGGRESSIVE_GROWTH — high-growth; default 12% pa
  CUSTOM           — user-sets expected_return_pct

Progress formula (compound interest + monthly contributions):
  FV = PV·(1+r)^n  +  PMT·[(1+r)^n − 1]/r
  where r = monthly rate, n = months remaining, PV = current_amount, PMT = monthly_contribution

Gap: shortfall = target_amount − FV (negative = surplus)
Savings boost needed: solve for PMT given FV = target_amount
"""
import math
import logging
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import InvestmentGoal

logger = logging.getLogger("omnitrader.services.goal_tracker")

DEFAULT_RETURNS = {
    "RETIREMENT":        0.08,
    "HOUSE":             0.06,
    "PASSIVE_INCOME":    0.05,
    "AGGRESSIVE_GROWTH": 0.12,
    "CUSTOM":            0.07,
}

RISK_ASSET_MIX = {
    "CONSERVATIVE": {"equity": 0.30, "debt": 0.60, "gold": 0.10},
    "MODERATE":     {"equity": 0.60, "debt": 0.30, "gold": 0.10},
    "AGGRESSIVE":   {"equity": 0.85, "debt": 0.10, "gold": 0.05},
}


def _goal_message(goal_type: str, on_track: bool, shortfall: float, projected_fv: float, target: float) -> str:
    if on_track:
        if goal_type == "PASSIVE_INCOME":
            return "On track — projected portfolio generates passive income target."
        elif goal_type == "RETIREMENT":
            return f"Retirement goal on track. Projected corpus: {projected_fv:,.0f}."
        else:
            return "Goal on track."
    else:
        return f"Behind target by {shortfall:,.0f}. Increase monthly contributions or extend timeline."


class GoalTrackerService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_portfolio_value(self) -> float:
        result = await self.db.execute(
            text("SELECT COALESCE(SUM(current_value), 0) FROM portfolio_positions WHERE status = 'OPEN'")
        )
        return float(result.scalar() or 0.0)

    def _project_future_value(self, pv: float, monthly_rate: float, months: int, pmt: float) -> float:
        if monthly_rate == 0:
            return pv + pmt * months
        return pv * (1 + monthly_rate) ** months + pmt * ((1 + monthly_rate) ** months - 1) / monthly_rate

    def _months_to_goal_date(self, target_date: date) -> int:
        today = date.today()
        return max(0, (target_date.year - today.year) * 12 + (target_date.month - today.month))

    def _required_monthly_pmt(self, pv: float, r: float, n: int, fv_target: float) -> float:
        if n == 0 or r == 0:
            return max(0, fv_target - pv)
        result = (fv_target - pv * (1 + r) ** n) * r / ((1 + r) ** n - 1)
        return max(0, result)

    async def compute_progress(self, goal: InvestmentGoal) -> dict:
        months = self._months_to_goal_date(goal.target_date)
        annual_return = goal.expected_return_pct or DEFAULT_RETURNS.get(goal.goal_type, 0.07)
        monthly_rate = annual_return / 12
        projected_fv = self._project_future_value(
            goal.current_amount, monthly_rate, months, goal.monthly_contribution
        )
        progress_pct = (
            min(100, round(goal.current_amount / goal.target_amount * 100, 1))
            if goal.target_amount > 0
            else 0
        )
        on_track = projected_fv >= goal.target_amount
        shortfall = max(0, goal.target_amount - projected_fv)
        required_monthly = (
            self._required_monthly_pmt(goal.current_amount, monthly_rate, months, goal.target_amount)
            if not on_track
            else None
        )
        asset_mix = RISK_ASSET_MIX.get(goal.risk_profile or "MODERATE", RISK_ASSET_MIX["MODERATE"])

        return {
            "id": goal.id,
            "name": goal.name,
            "goal_type": goal.goal_type,
            "target_amount": goal.target_amount,
            "current_amount": goal.current_amount,
            "target_date": goal.target_date.isoformat(),
            "months_remaining": months,
            "projected_future_value": round(projected_fv, 2),
            "progress_pct": progress_pct,
            "on_track": on_track,
            "shortfall": round(shortfall, 2),
            "required_monthly_contribution": round(required_monthly, 2) if required_monthly is not None else None,
            "current_monthly_contribution": goal.monthly_contribution,
            "annual_return_assumed_pct": round(annual_return * 100, 1),
            "recommended_asset_mix": asset_mix,
            "risk_profile": goal.risk_profile,
            "currency": goal.currency,
            "message": _goal_message(goal.goal_type, on_track, shortfall, projected_fv, goal.target_amount),
        }

    async def list_goals(self, user_id: str = "default") -> list[dict]:
        result = await self.db.execute(
            select(InvestmentGoal).where(InvestmentGoal.user_id == user_id)
        )
        goals = result.scalars().all()

        portfolio_value = await self.get_portfolio_value()

        output = []
        for goal in goals:
            goal.current_amount = portfolio_value
            await self.db.commit()
            progress = await self.compute_progress(goal)
            output.append(progress)
        return output

    async def create_goal(self, user_id: str, data: dict) -> InvestmentGoal:
        goal = InvestmentGoal(user_id=user_id, **data)
        self.db.add(goal)
        await self.db.commit()
        await self.db.refresh(goal)
        return goal

    async def update_goal(self, goal_id: int, data: dict) -> Optional[dict]:
        result = await self.db.execute(
            select(InvestmentGoal).where(InvestmentGoal.id == goal_id)
        )
        goal = result.scalar_one_or_none()
        if goal is None:
            return None
        for key, value in data.items():
            if hasattr(goal, key):
                setattr(goal, key, value)
        await self.db.commit()
        await self.db.refresh(goal)
        return await self.compute_progress(goal)

    async def delete_goal(self, goal_id: int) -> bool:
        result = await self.db.execute(
            select(InvestmentGoal).where(InvestmentGoal.id == goal_id)
        )
        goal = result.scalar_one_or_none()
        if goal is None:
            return False
        await self.db.delete(goal)
        await self.db.commit()
        return True
