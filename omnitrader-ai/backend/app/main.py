"""
OmniTrader AI — FastAPI Application
=====================================
Startup lifecycle:
  1. On boot → run schema migrations (safe ALTER TABLE ADD COLUMN IF NOT EXISTS)
  2. Check if stock_prices < 100 rows → auto-trigger full historical load
  3. Schedule prices_intraday_flow()        5× per weekday (6:30, 8:00, 14:00, 17:30, 20:30 UTC)
  4. Schedule prices_india_eod_flow()       at 10:45 UTC weekdays (45 min after NSE close)
  5. Schedule prices_us_eod_flow()          at 21:00 UTC weekdays (30 min after NYSE close)
  6. Schedule prices_nightly_gap_fill_flow() at 00:00 UTC daily (auto-backfill gaps/new IPOs)
  7. Schedule daily_ingest_flow()           at 22:00 UTC weekdays (macro/sentiment/snapshots)
  8. Schedule agents_daily_flow()           at 23:00 UTC weekdays (full agent batch scoring)
  9. Schedule swing_trading_flow()          at 00:30 UTC weekdays (proactive swing setups)
 10. Schedule weekly_ingest_flow()          every Sunday at 02:00 UTC
 11. Schedule walk_forward_run()            every Sunday at 03:00 UTC (signal quality validation)
 12. Schedule monthly_ingest_flow()         at 03:00 UTC on 1st of every month (13F, promoter)
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.api import ingestion, agents
from app.api import signals as signals_router
from app.api import watchlist as watchlist_router
from app.api import backtest as backtest_router

logger = logging.getLogger("omnitrader")

# ─── Scheduler ────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler(timezone="UTC")


# ── Price flows ────────────────────────────────────────────────────────────────

async def run_prices_intraday():
    logger.info("[Scheduler] Starting prices_intraday_flow...")
    from app.flows.prices_flow import prices_intraday_flow
    await prices_intraday_flow()

async def run_prices_india_eod():
    logger.info("[Scheduler] Starting prices_india_eod_flow...")
    from app.flows.prices_flow import prices_india_eod_flow
    await prices_india_eod_flow()

async def run_prices_us_eod():
    logger.info("[Scheduler] Starting prices_us_eod_flow...")
    from app.flows.prices_flow import prices_us_eod_flow
    await prices_us_eod_flow()

async def run_prices_gap_fill():
    logger.info("[Scheduler] Starting prices_nightly_gap_fill_flow...")
    from app.flows.prices_flow import prices_nightly_gap_fill_flow
    await prices_nightly_gap_fill_flow()


# ── Ingestion flows ────────────────────────────────────────────────────────────

async def run_daily():
    logger.info("[Scheduler] Starting daily_ingest_flow...")
    from app.flows.orchestrator import daily_ingest_flow
    await daily_ingest_flow()
    logger.info("[Scheduler] daily_ingest_flow complete.")


async def run_agents_daily():
    logger.info("[Scheduler] Starting agents_daily_flow...")
    from app.flows.agents_flow import agents_daily_flow
    await agents_daily_flow()
    logger.info("[Scheduler] agents_daily_flow complete.")


async def run_weekly():
    logger.info("[Scheduler] Starting weekly_ingest_flow...")
    from app.flows.orchestrator import weekly_ingest_flow
    await weekly_ingest_flow()
    logger.info("[Scheduler] weekly_ingest_flow complete.")


async def run_monthly():
    logger.info("[Scheduler] Starting monthly_ingest_flow...")
    from app.flows.orchestrator import monthly_ingest_flow
    await monthly_ingest_flow()
    logger.info("[Scheduler] monthly_ingest_flow complete.")


# ── Strategy flows ─────────────────────────────────────────────────────────────

async def run_swing():
    logger.info("[Scheduler] Starting swing_trading_flow (US + India)...")
    from app.flows.swing_flow import swing_trading_flow
    await swing_trading_flow(country="US")
    await swing_trading_flow(country="IN")
    logger.info("[Scheduler] swing_trading_flow complete.")


async def walk_forward_run():
    logger.info("[Scheduler] Starting WalkForwardValidator...")
    from app.agents.validator import WalkForwardValidator
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        validator = WalkForwardValidator(db)
        result = await validator.run()
        logger.info("[Scheduler] WalkForwardValidator result: %s", result)


async def check_and_run_initial_load():
    """
    On boot: if stock_prices has fewer than 100 rows, trigger the full
    historical load as a background task so the DB is seeded automatically.
    """
    try:
        from app.db.session import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            res = await db.execute(text("SELECT COUNT(*) FROM stock_prices"))
            count = res.scalar() or 0

        if count < 100:
            logger.info("[Boot] %d price rows found — triggering full initial load.", count)
            from app.flows.orchestrator import full_initial_load_flow
            asyncio.create_task(full_initial_load_flow())
        else:
            logger.info("[Boot] %s price rows present — skipping initial load.", f"{count:,}")
    except Exception as e:
        logger.error("[Boot] Initial load check failed: %s", e)


# ─── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("OmniTrader AI starting up...")

    # ── Run schema migrations (safe, idempotent) ───────────────────────────────
    try:
        from app.db.init_db import run_migrations
        from app.db.session import engine
        from app.db.base import Base
        from app.models.market_data import (  # noqa: F401 — ensure all models registered
            Stock, StockPrice, CompanyFinancials, MacroEconomicData, MarketSnapshot,
            NewsSentiment, InstitutionalFlow, PromoterHolding, RegimeLabel,
            ChartSnapshot, AIAnalysis, Alert, Watchlist,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await run_migrations()
        logger.info("[Boot] Schema up to date.")
    except Exception as e:
        logger.error("[Boot] Schema migration failed: %s", e)

    # ── Intraday price refresh: 5× per weekday ─────────────────────────────────
    for hour, minute in [(6, 30), (8, 0), (14, 0), (17, 30), (20, 30)]:
        scheduler.add_job(
            run_prices_intraday,
            CronTrigger(hour=hour, minute=minute, day_of_week="mon-fri"),
            id=f"prices_intraday_{hour:02d}{minute:02d}",
            replace_existing=True,
        )

    # ── EOD price syncs ────────────────────────────────────────────────────────
    scheduler.add_job(run_prices_india_eod, CronTrigger(hour=10, minute=45, day_of_week="mon-fri"),
                      id="prices_india_eod", replace_existing=True)
    scheduler.add_job(run_prices_us_eod, CronTrigger(hour=21, minute=0, day_of_week="mon-fri"),
                      id="prices_us_eod", replace_existing=True)

    # ── Nightly gap fill: runs at midnight UTC every day ──────────────────────
    scheduler.add_job(run_prices_gap_fill, CronTrigger(hour=0, minute=0),
                      id="prices_gap_fill", replace_existing=True)

    # ── Daily ingestion pipeline ───────────────────────────────────────────────
    scheduler.add_job(run_daily, CronTrigger(hour=22, minute=0, day_of_week="mon-fri"),
                      id="daily_ingest", replace_existing=True)
    scheduler.add_job(run_agents_daily, CronTrigger(hour=23, minute=0, day_of_week="mon-fri"),
                      id="agents_daily", replace_existing=True)

    # ── Proactive swing screener: 00:30 UTC (after midnight gap fill) ──────────
    scheduler.add_job(run_swing, CronTrigger(hour=0, minute=30, day_of_week="mon-fri"),
                      id="swing_trading", replace_existing=True)

    # ── Weekly deep refresh + validation ──────────────────────────────────────
    scheduler.add_job(run_weekly, CronTrigger(day_of_week="sun", hour=2, minute=0),
                      id="weekly_ingest", replace_existing=True)
    scheduler.add_job(walk_forward_run, CronTrigger(day_of_week="sun", hour=3, minute=0),
                      id="walk_forward_validation", replace_existing=True)

    # ── Monthly: 13F + promoter holdings ──────────────────────────────────────
    scheduler.add_job(run_monthly, CronTrigger(day=1, hour=3, minute=0),
                      id="monthly_ingest", replace_existing=True)

    scheduler.start()
    logger.info(
        "[Scheduler] Jobs registered:\n"
        "  Intraday prices:  6:30, 8:00, 14:00, 17:30, 20:30 UTC (weekdays)\n"
        "  India EOD:        10:45 UTC weekdays\n"
        "  US EOD:           21:00 UTC weekdays\n"
        "  Nightly gap fill: 00:00 UTC daily\n"
        "  Daily ingest:     22:00 UTC weekdays\n"
        "  Agent scoring:    23:00 UTC weekdays\n"
        "  Swing screener:   00:30 UTC weekdays\n"
        "  Weekly refresh:   Sun 02:00 UTC\n"
        "  Walk-forward:     Sun 03:00 UTC\n"
        "  Monthly 13F:      1st of month 03:00 UTC"
    )

    asyncio.create_task(check_and_run_initial_load())

    yield

    scheduler.shutdown(wait=False)
    logger.info("OmniTrader AI shut down cleanly.")


# ─── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.include_router(ingestion.router)
app.include_router(agents.router,              prefix="/api/v1/agents",    tags=["agents"])
app.include_router(signals_router.router,      prefix="/api/v1/agents",    tags=["signals"])
app.include_router(watchlist_router.router,    prefix="/api/v1/watchlist", tags=["watchlist"])
app.include_router(backtest_router.router,     prefix="/api/v1/backtest",  tags=["backtest"])

import os
from fastapi.staticfiles import StaticFiles
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def root():
    return {"message": "OmniTrader AI Backend is Running", "status": "active"}


@app.get("/health")
async def health_check():
    jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
    return {"status": "healthy", "scheduled_jobs": jobs}
