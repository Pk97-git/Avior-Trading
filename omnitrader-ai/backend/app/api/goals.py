"""
goals.py — Investment goal tracking endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.goal_tracker import GoalTrackerService
from app.models.market_data import InvestmentGoal
from sqlalchemy import select

router = APIRouter(prefix="/api/v1/goals", tags=["goals"])


class GoalCreate(BaseModel):
    goal_type: str
    name: str
    target_amount: float
    target_date: date
    monthly_contribution: float = 0.0
    currency: str = "USD"
    risk_profile: str = "MODERATE"
    expected_return_pct: Optional[float] = None
    notes: Optional[str] = None


class GoalUpdate(BaseModel):
    goal_type: Optional[str] = None
    name: Optional[str] = None
    target_amount: Optional[float] = None
    target_date: Optional[date] = None
    monthly_contribution: Optional[float] = None
    currency: Optional[str] = None
    risk_profile: Optional[str] = None
    expected_return_pct: Optional[float] = None
    notes: Optional[str] = None


@router.get("")
async def list_goals(
    user_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """List all investment goals with progress for a user."""
    svc = GoalTrackerService(db)
    return await svc.list_goals(user_id=user_id)


@router.post("", status_code=201)
async def create_goal(
    body: GoalCreate,
    user_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Create a new investment goal."""
    svc = GoalTrackerService(db)
    data = body.model_dump(exclude_none=False)
    goal = await svc.create_goal(user_id=user_id, data=data)
    return await svc.compute_progress(goal)


@router.get("/{goal_id}")
async def get_goal(
    goal_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single investment goal with progress."""
    result = await db.execute(select(InvestmentGoal).where(InvestmentGoal.id == goal_id))
    goal = result.scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    svc = GoalTrackerService(db)
    return await svc.compute_progress(goal)


@router.put("/{goal_id}")
async def update_goal(
    goal_id: int,
    body: GoalUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing investment goal."""
    svc = GoalTrackerService(db)
    data = body.model_dump(exclude_none=True)
    progress = await svc.update_goal(goal_id=goal_id, data=data)
    if progress is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return progress


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an investment goal."""
    svc = GoalTrackerService(db)
    deleted = await svc.delete_goal(goal_id=goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
