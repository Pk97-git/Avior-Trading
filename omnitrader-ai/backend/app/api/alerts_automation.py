"""
api/alerts_automation.py
========================
Smart Alerts & Automation Platform endpoints.

AlertRule CRUD:
  GET    /api/v1/automation/alert-rules         — list all rules
  POST   /api/v1/automation/alert-rules         — create rule
  PUT    /api/v1/automation/alert-rules/{id}    — update rule
  DELETE /api/v1/automation/alert-rules/{id}    — delete rule
  POST   /api/v1/automation/alert-rules/run     — manually trigger alert check

AutomationRule CRUD:
  GET    /api/v1/automation/rules               — list all rules
  POST   /api/v1/automation/rules               — create rule
  PUT    /api/v1/automation/rules/{id}          — update rule
  DELETE /api/v1/automation/rules/{id}          — delete rule
  POST   /api/v1/automation/rules/{id}/run      — manually run a rule now

Status:
  GET    /api/v1/automation/status              — summary of all active rules + last runs
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update, delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

logger = logging.getLogger("omnitrader")

# ── Try importing models (may not exist if migration hasn't run yet) ──────────
try:
    from app.models.market_data import AlertRule, AutomationRule
    _MODELS_AVAILABLE = True
except ImportError:
    AlertRule = None        # type: ignore
    AutomationRule = None   # type: ignore
    _MODELS_AVAILABLE = False

router = APIRouter()

# ── Valid rule type constants ─────────────────────────────────────────────────

VALID_ALERT_TYPES = {
    "EARNINGS_APPROACHING",
    "INSIDER_SPIKE",
    "RSI_OVERBOUGHT",
    "RSI_OVERSOLD",
    "SENTIMENT_SHIFT",
    "OPTIONS_ACTIVITY",
    "PRICE_TARGET",
    "SCORE_CHANGE",
}

VALID_AUTOMATION_TYPES = {
    "AUTO_REBALANCE",
    "AUTO_SIP",
    "AUTO_STOP_LOSS",
    "AUTO_HEDGE",
}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    name: str
    ticker: str | None = None
    alert_type: str
    condition: dict[str, Any] | None = None
    notify_via: list[str] | None = None


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    ticker: str | None = None
    alert_type: str | None = None
    condition: dict[str, Any] | None = None
    notify_via: list[str] | None = None
    is_active: bool | None = None


class AutomationRuleCreate(BaseModel):
    name: str
    rule_type: str
    config: dict[str, Any] | None = None


class AutomationRuleUpdate(BaseModel):
    name: str | None = None
    rule_type: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


# ─────────────────────────────────────────────────────────────────────────────
# AlertRule endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/alert-rules")
async def list_alert_rules(db: AsyncSession = Depends(get_db)):
    """List all AlertRules ordered by creation date."""
    if not _MODELS_AVAILABLE:
        return {"error": "AlertRule model not available — migration may not have run yet", "rules": []}

    result = await db.execute(
        select(AlertRule).order_by(AlertRule.created_at.desc())
    )
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "ticker": r.ticker,
                "alert_type": r.alert_type,
                "condition": r.condition,
                "notify_via": r.notify_via,
                "is_active": r.is_active,
                "created_at": str(r.created_at),
                "last_triggered_at": str(r.last_triggered_at) if r.last_triggered_at else None,
                "trigger_count": r.trigger_count,
            }
            for r in rules
        ]
    }


@router.post("/alert-rules")
async def create_alert_rule(body: AlertRuleCreate, db: AsyncSession = Depends(get_db)):
    """Create a new AlertRule."""
    if not _MODELS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AlertRule model not available")

    if body.alert_type not in VALID_ALERT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid alert_type '{body.alert_type}'. Must be one of: {sorted(VALID_ALERT_TYPES)}",
        )

    rule = AlertRule(
        name=body.name,
        ticker=body.ticker,
        alert_type=body.alert_type,
        condition=body.condition or {},
        notify_via=body.notify_via or [],
        is_active=True,
        created_at=datetime.now(timezone.utc),
        trigger_count=0,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return {"status": "created", "id": rule.id, "name": rule.name, "alert_type": rule.alert_type}


@router.put("/alert-rules/{rule_id}")
async def update_alert_rule(
    rule_id: int,
    body: AlertRuleUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Partially update an AlertRule by id."""
    if not _MODELS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AlertRule model not available")

    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"AlertRule {rule_id} not found")

    if body.alert_type is not None and body.alert_type not in VALID_ALERT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid alert_type '{body.alert_type}'. Must be one of: {sorted(VALID_ALERT_TYPES)}",
        )

    updates: dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await db.execute(
            update(AlertRule).where(AlertRule.id == rule_id).values(**updates)
        )
        await db.commit()

    return {"status": "updated", "id": rule_id}


@router.delete("/alert-rules/{rule_id}")
async def delete_alert_rule(
    rule_id: int,
    hard: bool = Query(False, description="If True, permanently delete the rule"),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (deactivate) or hard-delete an AlertRule."""
    if not _MODELS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AlertRule model not available")

    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"AlertRule {rule_id} not found")

    if hard:
        await db.execute(delete(AlertRule).where(AlertRule.id == rule_id))
        await db.commit()
        return {"status": "deleted", "id": rule_id}
    else:
        await db.execute(
            update(AlertRule).where(AlertRule.id == rule_id).values(is_active=False)
        )
        await db.commit()
        return {"status": "deactivated", "id": rule_id}


@router.post("/alert-rules/run")
async def run_alert_rules(db: AsyncSession = Depends(get_db)):
    """Manually trigger the SmartAlertEngine to check all active AlertRules now."""
    try:
        from app.engines.smart_alerts import SmartAlertEngine
        engine = SmartAlertEngine(db)
        result = await engine.run_all_checks()
        return {"status": "completed", **result}
    except Exception as exc:
        logger.error("[AlertsAPI] Manual alert run failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# AutomationRule endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/rules")
async def list_automation_rules(db: AsyncSession = Depends(get_db)):
    """List all AutomationRules ordered by creation date."""
    if not _MODELS_AVAILABLE:
        return {"error": "AutomationRule model not available — migration may not have run yet", "rules": []}

    result = await db.execute(
        select(AutomationRule).order_by(AutomationRule.created_at.desc())
    )
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "rule_type": r.rule_type,
                "config": r.config,
                "is_active": r.is_active,
                "created_at": str(r.created_at),
                "last_run_at": str(r.last_run_at) if r.last_run_at else None,
                "next_run_at": str(r.next_run_at) if r.next_run_at else None,
                "run_count": r.run_count,
                "last_result": r.last_result,
            }
            for r in rules
        ]
    }


@router.post("/rules")
async def create_automation_rule(body: AutomationRuleCreate, db: AsyncSession = Depends(get_db)):
    """Create a new AutomationRule."""
    if not _MODELS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AutomationRule model not available")

    if body.rule_type not in VALID_AUTOMATION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid rule_type '{body.rule_type}'. Must be one of: {sorted(VALID_AUTOMATION_TYPES)}",
        )

    rule = AutomationRule(
        name=body.name,
        rule_type=body.rule_type,
        config=body.config or {},
        is_active=True,
        created_at=datetime.now(timezone.utc),
        run_count=0,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    return {"status": "created", "id": rule.id, "name": rule.name, "rule_type": rule.rule_type}


@router.put("/rules/{rule_id}")
async def update_automation_rule(
    rule_id: int,
    body: AutomationRuleUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Partially update an AutomationRule by id."""
    if not _MODELS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AutomationRule model not available")

    result = await db.execute(select(AutomationRule).where(AutomationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"AutomationRule {rule_id} not found")

    if body.rule_type is not None and body.rule_type not in VALID_AUTOMATION_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid rule_type '{body.rule_type}'. Must be one of: {sorted(VALID_AUTOMATION_TYPES)}",
        )

    updates: dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await db.execute(
            update(AutomationRule).where(AutomationRule.id == rule_id).values(**updates)
        )
        await db.commit()

    return {"status": "updated", "id": rule_id}


@router.delete("/rules/{rule_id}")
async def delete_automation_rule(
    rule_id: int,
    hard: bool = Query(False, description="If True, permanently delete the rule"),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (deactivate) or hard-delete an AutomationRule."""
    if not _MODELS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AutomationRule model not available")

    result = await db.execute(select(AutomationRule).where(AutomationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"AutomationRule {rule_id} not found")

    if hard:
        await db.execute(delete(AutomationRule).where(AutomationRule.id == rule_id))
        await db.commit()
        return {"status": "deleted", "id": rule_id}
    else:
        await db.execute(
            update(AutomationRule).where(AutomationRule.id == rule_id).values(is_active=False)
        )
        await db.commit()
        return {"status": "deactivated", "id": rule_id}


@router.post("/rules/{rule_id}/run")
async def run_automation_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """Manually trigger a specific AutomationRule to run now."""
    if not _MODELS_AVAILABLE:
        raise HTTPException(status_code=503, detail="AutomationRule model not available")

    result = await db.execute(select(AutomationRule).where(AutomationRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"AutomationRule {rule_id} not found")

    try:
        from app.engines.automation import AutomationEngine
        engine = AutomationEngine(db)
        handler = engine._get_handler(rule.rule_type)
        if handler is None:
            raise HTTPException(status_code=400, detail=f"Unknown rule_type: {rule.rule_type}")

        run_result = await handler(rule)

        # Update bookkeeping
        now = datetime.now(timezone.utc)
        await db.execute(
            update(AutomationRule)
            .where(AutomationRule.id == rule_id)
            .values(
                last_run_at=now,
                run_count=(rule.run_count or 0) + 1,
                last_result=run_result,
                next_run_at=engine._compute_next_run(rule),
            )
        )
        await db.commit()

        return {"status": "executed", "rule_id": rule_id, "name": rule.name, "result": run_result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[AutomationAPI] Manual rule run %d failed: %s", rule_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Status endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/status")
async def automation_status(db: AsyncSession = Depends(get_db)):
    """
    Summary of all active AlertRules and AutomationRules, including last runs
    and upcoming scheduled executions.
    """
    if not _MODELS_AVAILABLE:
        return {
            "error": "Models not available — migration may not have run yet",
            "alert_rules": {},
            "automation_rules": {},
        }

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    # ── AlertRule stats ───────────────────────────────────────────────────────
    try:
        total_alerts_r = await db.execute(
            select(func.count()).select_from(AlertRule)
        )
        total_alerts = total_alerts_r.scalar() or 0

        active_alerts_r = await db.execute(
            select(func.count()).select_from(AlertRule).where(AlertRule.is_active == True)  # noqa: E712
        )
        active_alerts = active_alerts_r.scalar() or 0

        fired_24h_r = await db.execute(
            select(func.count()).select_from(AlertRule).where(
                AlertRule.last_triggered_at >= cutoff_24h
            )
        )
        fired_24h = fired_24h_r.scalar() or 0

        top_fired_r = await db.execute(
            select(AlertRule)
            .where(AlertRule.trigger_count > 0)
            .order_by(AlertRule.trigger_count.desc())
            .limit(5)
        )
        top_fired = [
            {
                "id": r.id,
                "name": r.name,
                "alert_type": r.alert_type,
                "trigger_count": r.trigger_count,
                "last_triggered_at": str(r.last_triggered_at) if r.last_triggered_at else None,
            }
            for r in top_fired_r.scalars().all()
        ]

        alert_stats = {
            "total": total_alerts,
            "active": active_alerts,
            "fired_last_24h": fired_24h,
            "top_fired": top_fired,
        }
    except Exception as exc:
        logger.warning("[AutomationAPI] Alert stats query failed: %s", exc)
        alert_stats = {"error": str(exc)}

    # ── AutomationRule stats ──────────────────────────────────────────────────
    try:
        total_auto_r = await db.execute(
            select(func.count()).select_from(AutomationRule)
        )
        total_auto = total_auto_r.scalar() or 0

        active_auto_r = await db.execute(
            select(func.count()).select_from(AutomationRule).where(
                AutomationRule.is_active == True  # noqa: E712
            )
        )
        active_auto = active_auto_r.scalar() or 0

        next_runs_r = await db.execute(
            select(AutomationRule)
            .where(AutomationRule.is_active == True)  # noqa: E712
            .order_by(AutomationRule.next_run_at.asc().nullsfirst())
            .limit(10)
        )
        next_runs = [
            {
                "id": r.id,
                "name": r.name,
                "rule_type": r.rule_type,
                "next_run_at": str(r.next_run_at) if r.next_run_at else None,
                "last_run_at": str(r.last_run_at) if r.last_run_at else None,
                "run_count": r.run_count,
            }
            for r in next_runs_r.scalars().all()
        ]

        automation_stats = {
            "total": total_auto,
            "active": active_auto,
            "next_runs": next_runs,
        }
    except Exception as exc:
        logger.warning("[AutomationAPI] Automation stats query failed: %s", exc)
        automation_stats = {"error": str(exc)}

    return {
        "alert_rules": alert_stats,
        "automation_rules": automation_stats,
    }
