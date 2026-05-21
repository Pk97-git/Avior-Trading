"""
Data Ingestion API Router
==========================
Endpoints for the frontend Data Ingestion Dashboard:
  GET /api/v1/ingestion/status        — health/status of all sources
  GET /api/v1/ingestion/prices        — latest price data preview
  GET /api/v1/ingestion/fundamentals  — latest fundamentals preview
  GET /api/v1/ingestion/macro         — latest macro data
  GET /api/v1/ingestion/institutional — FII/DII + bulk deals
  GET /api/v1/ingestion/sentiment     — latest news & sentiment scores
  GET /api/v1/ingestion/promoter      — promoter holding changes
  POST /api/v1/ingestion/trigger/{source} — manually trigger a fetch
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, desc
from app.db.session import AsyncSessionLocal
from app.models.market_data import (
    Stock, StockPrice, CompanyFinancials, MacroEconomicData,
    InstitutionalFlow, NewsSentiment, PromoterHolding
)
from typing import List, Optional
from datetime import datetime, timedelta
import yfinance as yf

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ─── Status Overview ──────────────────────────────────────────────────────────

@router.get("/status")
async def get_ingestion_status(db: AsyncSession = Depends(get_db)):
    """
    Returns health status for all data sources:
    - Row counts
    - Latest record timestamp
    - Staleness (hours since last update)
    - Status: OK / STALE / EMPTY
    """
    now = datetime.utcnow()
    sources = []

    async def source_stat(name: str, table, time_col, label: str,
                           stale_hours: int = 24, extra_filter=None, join_stock: bool = False):
        try:
            # 1. Basic Stats (Rows, Latest)
            q = select(func.count(), func.max(time_col))
            if extra_filter is not None:
                q = q.where(extra_filter)
            result = await db.execute(q.select_from(table))
            count_val, latest = result.one()
            
            # 2. Distinct Stock Counts (US vs India)
            us_stocks, in_stocks = 0, 0
            
            if join_stock:
                # Join with Stock table to group by country
                stmt = select(Stock.country, func.count(func.distinct(table.ticker)))\
                       .join(Stock, table.ticker == Stock.ticker)\
                       .group_by(Stock.country)
                if extra_filter is not None:
                    stmt = stmt.where(extra_filter)
                res = await db.execute(stmt)
                for country, cnt in res.all():
                    if country == 'US': us_stocks = cnt
                    elif country == 'IN': in_stocks = cnt
            
            elif hasattr(table, "market"):
                # Institutional flows have 'market' column
                stmt = select(table.market, func.count(func.distinct(table.entity_type)))\
                       .group_by(table.market)
                if extra_filter is not None:
                    stmt = stmt.where(extra_filter)
                res = await db.execute(stmt)
                for market, cnt in res.all():
                    if market == 'US': us_stocks = cnt # Approx entity count
                    elif market == 'INDIA': in_stocks = cnt

            # Status Checking
            if latest is None:
                status = "EMPTY"
                staleness = None
            else:
                age = (now - latest.replace(tzinfo=None)).total_seconds() / 3600
                staleness = round(age, 1)
                status = "OK" if age < stale_hours else "STALE"
            
            return {
                "source": name,
                "label": label,
                "row_count": count_val or 0,
                "stock_count": us_stocks + in_stocks if join_stock else 0,
                "us_count": us_stocks,
                "india_count": in_stocks,
                "latest": latest.isoformat() if latest else None,
                "staleness_hours": staleness,
                "status": status,
            }
        except Exception as e:
            return {"source": name, "label": label, "row_count": 0, "stock_count": 0,
                    "latest": None, "staleness_hours": None, "status": "ERROR",
                    "error": str(e)}

    # Aggregating Stats
    sources.append(await source_stat("prices", StockPrice, StockPrice.time, "Price OHLCV", join_stock=True))
    sources.append(await source_stat("fundamentals", CompanyFinancials, CompanyFinancials.fiscal_date, "Fundamentals", stale_hours=168, join_stock=True))
    sources.append(await source_stat("macro_us", MacroEconomicData, MacroEconomicData.time, "US Macro (FRED)",
                                     extra_filter=MacroEconomicData.source == "FRED"))
    sources.append(await source_stat("macro_global", MacroEconomicData, MacroEconomicData.time, "Global Macro (Yahoo)",
                                     extra_filter=MacroEconomicData.source == "yfinance"))
    sources.append(await source_stat("institutional", InstitutionalFlow, InstitutionalFlow.date, "FII/DII Flows"))
    sources.append(await source_stat("sentiment", NewsSentiment, NewsSentiment.time, "News Sentiment", join_stock=True))
    sources.append(await source_stat("promoter", PromoterHolding, PromoterHolding.quarter_end, "Promoter Holdings", stale_hours=24 * 90, join_stock=True))

    # Universe Count Breakdown
    try:
        stmt = select(Stock.country, func.count(Stock.ticker)).group_by(Stock.country)
        univ_res = await db.execute(stmt)
        univ_map = {row[0]: row[1] for row in univ_res.all()}
        univ_us = univ_map.get("US", 0)
        univ_in = univ_map.get("IN", 0)
        stock_count_val = univ_us + univ_in
    except Exception:
        stock_count_val, univ_us, univ_in = 0, 0, 0

    sources.append({
        "source": "universe",
        "label": "Stock Universe",
        "row_count": stock_count_val,
        "stock_count": stock_count_val,
        "us_count": univ_us,
        "india_count": univ_in,
        "latest": None,
        "staleness_hours": None,
        "status": "OK" if stock_count_val > 0 else "EMPTY",
    })

    total_rows = sum(s["row_count"] for s in sources)
    ok_count = sum(1 for s in sources if s["status"] == "OK")

    return {
        "overall_status": "OK" if ok_count >= len(sources) - 2 else "PARTIAL", # Relaxed check
        "ok_sources": ok_count,
        "total_sources": len(sources),
        "total_rows": total_rows,
        "checked_at": now.isoformat(),
        "sources": sources,
    }

@router.get("/health")
async def get_data_health(db: AsyncSession = Depends(get_db)):
    """
    Returns the coverage statistics of the active universe.
    """
    from app.ingestion.core.completeness import DataCompletenessMonitor
    monitor = DataCompletenessMonitor(db)
    return await monitor.get_coverage_stats()


# ─── Prices Preview ───────────────────────────────────────────────────────────

@router.get("/prices")
async def get_prices(
    ticker: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(50, le=10000),
    db: AsyncSession = Depends(get_db)
):
    q = select(StockPrice).join(Stock).order_by(desc(StockPrice.time)).limit(limit)
    if ticker:
        q = q.where(StockPrice.ticker == ticker.upper())
    if country:
        q = q.where(Stock.country == country.upper())
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "time": r.time.isoformat(),
            "ticker": r.ticker,
            "open": round(r.open, 4) if r.open else None,
            "high": round(r.high, 4) if r.high else None,
            "low": round(r.low, 4) if r.low else None,
            "close": round(r.close, 4) if r.close else None,
            "volume": int(r.volume) if r.volume else None,
        }
        for r in rows
    ]


# ─── Price Tickers List ───────────────────────────────────────────────────────

@router.get("/tickers")
async def get_tickers(
    search: Optional[str] = None,
    country: Optional[str] = None,
    sector: Optional[str] = None,
    has_data: Optional[bool] = None,
    min_years: Optional[float] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns paginated stock universe with rich filtering.
    Supports: search, country, sector, has_data, min_years of history.
    Returns: ticker, name, sector, country, has_data, first_date, last_date, years_of_data, is_current
    """
    today = datetime.utcnow().date()

    # ── Price stats for all tickers ──────────────────────────────────────────
    price_stats_q = text("""
        SELECT ticker,
               MIN(time)::date AS first_date,
               MAX(time)::date AS last_date
        FROM stock_prices
        GROUP BY ticker
    """)
    price_res = await db.execute(price_stats_q)
    price_stats: dict = {}
    for r in price_res.all():
        years = round((r.last_date - r.first_date).days / 365.25, 1) if r.first_date and r.last_date else 0
        price_stats[r.ticker] = {
            "first_date": r.first_date.isoformat() if r.first_date else None,
            "last_date": r.last_date.isoformat() if r.last_date else None,
            "years": years,
            "is_current": r.last_date >= (today - timedelta(days=4)) if r.last_date else False,
        }

    # ── Filter stocks ─────────────────────────────────────────────────────────
    base_q = select(Stock)
    if search:
        term = f"%{search}%"
        base_q = base_q.where(Stock.ticker.ilike(term) | Stock.name.ilike(term))
    if country and country.upper() != "ALL":
        base_q = base_q.where(Stock.country == country.upper())
    if sector and sector.lower() != "all":
        base_q = base_q.where(Stock.sector.ilike(f"%{sector}%"))

    all_res = await db.execute(base_q.order_by(Stock.ticker))
    all_stocks = all_res.scalars().all()

    # Python-side filters that depend on price_stats
    filtered = []
    for s in all_stocks:
        ps = price_stats.get(s.ticker)
        stock_has_data = ps is not None
        if has_data is True and not stock_has_data:
            continue
        if has_data is False and stock_has_data:
            continue
        if min_years is not None:
            if not stock_has_data or ps["years"] < min_years:
                continue
        filtered.append((s, ps))

    total = len(filtered)
    page_items = filtered[(page - 1) * limit : page * limit]

    result_data = []
    for s, ps in page_items:
        result_data.append({
            "ticker": s.ticker,
            "name": s.name,
            "sector": s.sector,
            "country": s.country,
            "has_data": ps is not None,
            "first_date": ps["first_date"] if ps else None,
            "last_date": ps["last_date"] if ps else None,
            "years_of_data": ps["years"] if ps else None,
            "is_current": ps["is_current"] if ps else False,
        })

    return {"total": total, "page": page, "limit": limit, "data": result_data}


# ─── Sector Breakdown ────────────────────────────────────────────────────────

@router.get("/sector-breakdown")
async def get_sector_breakdown(db: AsyncSession = Depends(get_db)):
    """Returns stock count by sector and country, for filter dropdowns and charts."""
    q = text("""
        SELECT sector, country, COUNT(*) as total,
               COUNT(DISTINCT sp.ticker) as with_data
        FROM stocks s
        LEFT JOIN (SELECT DISTINCT ticker FROM stock_prices) sp ON s.ticker = sp.ticker
        WHERE s.sector IS NOT NULL AND s.sector != 'Unknown'
        GROUP BY sector, country
        ORDER BY total DESC
    """)
    res = await db.execute(q)
    sectors = {}
    countries = set()
    for r in res.all():
        key = r.sector
        if key not in sectors:
            sectors[key] = {"sector": key, "total": 0, "with_data": 0, "countries": {}}
        sectors[key]["total"] += r.total
        sectors[key]["with_data"] += r.with_data
        sectors[key]["countries"][r.country] = r.total
        countries.add(r.country)

    return {
        "sectors": list(sectors.values()),
        "countries": sorted(countries),
    }


# ─── Trigger Now (Background Task via asyncio) ───────────────────────────────

@router.post("/trigger-now/{flow}")
async def trigger_now(flow: str):
    """
    Immediately spawns an ingestion flow as a background asyncio task.

    Composite flows:
      full_initial_load, daily, weekly, monthly

    Price flows:
      prices_backfill, prices_intraday, india_eod, us_eod,
      prices_high, prices_medium, prices_low

    Individual data tasks:
      fundamentals, macro_us, macro_india, macro_global,
      fii_dii, bulk_deals, sec_13f, options, sector_etfs, promoter,
      sentiment_rss, sentiment_reddit, sentiment_stocktwits,
      charts, snapshots

    Strategy / validation:
      swing_us, swing_india, walk_forward
    """
    import asyncio
    # Composite orchestrator flows
    from app.flows.orchestrator import (
        full_initial_load_flow, daily_ingest_flow,
        weekly_ingest_flow, monthly_ingest_flow,
    )
    # Individual data-type flows and tasks (canonical locations)
    from app.flows.prices_flow import (
        prices_nightly_gap_fill_flow, prices_intraday_flow,
        prices_india_eod_flow, prices_us_eod_flow,
        task_prices_high, task_prices_medium, task_prices_low,
    )
    from app.flows.fundamentals_flow import task_fundamentals
    from app.flows.macro_flow import task_macro_us, task_macro_india, task_macro_global
    from app.flows.institutional_flow import (
        task_fii_dii, task_bulk_deals, task_sector_etfs,
        task_options_pc, task_sec_13f, task_promoter_holdings,
    )
    from app.flows.sentiment_flow import (
        task_sentiment_rss, task_sentiment_reddit, task_sentiment_stocktwits,
    )
    from app.flows.computed_flow import task_charts, task_snapshots
    from app.flows.swing_flow import swing_trading_flow

    async def _run_walk_forward():
        from app.db.session import AsyncSessionLocal
        from app.agents.validator import WalkForwardValidator
        async with AsyncSessionLocal() as db:
            validator = WalkForwardValidator(db)
            await validator.run()

    flow_map = {
        # ── Composite flows ─────────────────────────────────────
        "full_initial_load": full_initial_load_flow,
        "daily":             daily_ingest_flow,
        "weekly":            weekly_ingest_flow,
        "monthly":           monthly_ingest_flow,
        # ── Price flows ─────────────────────────────────────────
        "prices_gap_fill":   prices_nightly_gap_fill_flow,
        "prices_intraday":   prices_intraday_flow,
        "india_eod":         prices_india_eod_flow,
        "us_eod":            prices_us_eod_flow,
        "prices_high":       task_prices_high,
        "prices_medium":     task_prices_medium,
        "prices_low":        task_prices_low,
        # ── Individual data-type tasks ──────────────────────────
        "fundamentals":      task_fundamentals,
        "macro_us":          task_macro_us,
        "macro_india":       task_macro_india,
        "macro_global":      task_macro_global,
        "fii_dii":           task_fii_dii,
        "bulk_deals":        task_bulk_deals,
        "sec_13f":           task_sec_13f,
        "options":           task_options_pc,
        "sector_etfs":       task_sector_etfs,
        "promoter":          task_promoter_holdings,
        "sentiment_rss":     task_sentiment_rss,
        "sentiment_reddit":  task_sentiment_reddit,
        "sentiment_stocktwits": task_sentiment_stocktwits,
        "charts":            task_charts,
        "snapshots":         task_snapshots,
        # ── Strategy / validation ────────────────────────────────
        "swing_us":          lambda: swing_trading_flow(country="US"),
        "swing_india":       lambda: swing_trading_flow(country="IN"),
        "walk_forward":      _run_walk_forward,
    }

    if flow not in flow_map:
        raise HTTPException(status_code=400, detail=f"Unknown flow. Valid: {list(flow_map.keys())}")

    async def _run():
        try:
            await flow_map[flow]()
        except Exception as e:
            print(f"[TriggerNow] Error in {flow}: {e}")

    asyncio.create_task(_run())
    return {"status": "started", "flow": flow, "message": f"'{flow}' launched in background. Check server logs for progress."}




# ─── Fundamentals Preview ─────────────────────────────────────────────────────

@router.get("/fundamentals")
async def get_fundamentals(
    ticker: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    q = select(CompanyFinancials).join(Stock).order_by(desc(CompanyFinancials.fiscal_date)).limit(limit)
    if ticker:
        q = q.where(CompanyFinancials.ticker == ticker.upper())
    if country:
        q = q.where(Stock.country == country.upper())
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "ticker": r.ticker,
            "fiscal_date": r.fiscal_date.isoformat() if r.fiscal_date else None,
            "revenue": r.revenue,
            "net_income": r.net_income,
            "eps": r.eps,
            "free_cash_flow": r.free_cash_flow,
            "debt_to_equity": r.debt_to_equity,
            "roe": r.roe,
            "pe_ratio": r.pe_ratio,
        }
        for r in rows
    ]


# ─── Macro Preview ────────────────────────────────────────────────────────────

@router.get("/macro")
async def get_macro(
    indicator: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db)
):
    q = select(MacroEconomicData).order_by(desc(MacroEconomicData.time)).limit(limit)
    if indicator:
        q = q.where(MacroEconomicData.indicator == indicator)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "time": r.time.isoformat(),
            "indicator": r.indicator,
            "value": r.value,
            "source": r.source,
        }
        for r in rows
    ]


@router.get("/macro/indicators")
async def get_macro_indicators(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MacroEconomicData.indicator, MacroEconomicData.source, func.count())
        .group_by(MacroEconomicData.indicator, MacroEconomicData.source)
        .order_by(MacroEconomicData.indicator)
    )
    return [{"indicator": r[0], "source": r[1], "count": r[2]} for r in result.all()]


# ─── Institutional Preview ────────────────────────────────────────────────────

@router.get("/institutional")
async def get_institutional(
    market: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = Query(60, le=500),
    db: AsyncSession = Depends(get_db)
):
    q = select(InstitutionalFlow).order_by(desc(InstitutionalFlow.date)).limit(limit)
    if market:
        q = q.where(InstitutionalFlow.market == market.upper())
    if entity_type:
        q = q.where(InstitutionalFlow.entity_type == entity_type.upper())
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "date": r.date.isoformat(),
            "entity_type": r.entity_type,
            "market": r.market,
            "buy_value": r.buy_value,
            "sell_value": r.sell_value,
            "net_value": r.net_value,
        }
        for r in rows
    ]


# ─── Sentiment Preview ────────────────────────────────────────────────────────

@router.get("/sentiment")
async def get_sentiment(
    ticker: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    q = select(NewsSentiment).join(Stock).order_by(desc(NewsSentiment.time)).limit(limit)
    if ticker:
        q = q.where(NewsSentiment.ticker == ticker.upper())
    if country:
        q = q.where(Stock.country == country.upper())
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "time": r.time.isoformat(),
            "ticker": r.ticker,
            "headline": r.headline,
            "source": r.source,
            "url": r.url,
            "sentiment_score": r.sentiment_score,
            "confidence": r.confidence,
        }
        for r in rows
    ]


# ─── Promoter Holdings Preview ────────────────────────────────────────────────

@router.get("/promoter")
async def get_promoter(
    ticker: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db)
):
    q = select(PromoterHolding).join(Stock).order_by(desc(PromoterHolding.quarter_end)).limit(limit)
    if ticker:
        q = q.where(PromoterHolding.ticker == ticker.upper())
    if country:
        q = q.where(Stock.country == country.upper())
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "ticker": r.ticker,
            "quarter_end": r.quarter_end.isoformat() if r.quarter_end else None,
            "promoter_pct": r.promoter_pct,
            "fii_pct": r.fii_pct,
            "dii_pct": r.dii_pct,
            "public_pct": r.public_pct,
            "promoter_pct_change": r.promoter_pct_change,
        }
        for r in rows
    ]


@router.post("/trigger/{source}")
async def trigger_ingestion(source: str):
    """Manually trigger a data fetch for a given source."""
    valid_sources = ["prices", "macro", "institutional", "sentiment", "promoter", "universe"]
    if source not in valid_sources:
        raise HTTPException(status_code=400, detail=f"Unknown source. Valid: {valid_sources}")

    return {
        "status": "triggered",
        "source": source,
        "message": f"Fetch for '{source}' queued. Check Prefect dashboard for progress.",
        "triggered_at": datetime.utcnow().isoformat(),
    }


# ─── Data Progress ────────────────────────────────────────────────────────────

@router.get("/data-progress")
async def get_data_progress(db: AsyncSession = Depends(get_db)):
    """
    Returns a rich breakdown of data ingestion progress across the universe:
    - Overall coverage stats (total, ingested, current-to-date)
    - Breakdown by years of history (0, <1yr, 1-3yr, 3-5yr, 5-10yr, 10+ yr)
    - Breakdown by country (US / IN)
    - Sample of recently ingested stocks
    """
    today = datetime.utcnow().date()
    four_days_ago = today - timedelta(days=4)  # Covers weekends + market holidays

    try:
        # 1. Total universe
        total_res = await db.execute(text("SELECT COUNT(*) FROM stocks"))
        total = total_res.scalar() or 0

        # 2. Per-ticker stats: min_date, max_date, row_count, country
        stats_query = text("""
            SELECT
                sp.ticker,
                s.country,
                MIN(sp.time)::date  AS first_date,
                MAX(sp.time)::date  AS last_date,
                COUNT(*)            AS row_count
            FROM stock_prices sp
            JOIN stocks s ON sp.ticker = s.ticker
            GROUP BY sp.ticker, s.country
        """)
        stats_res = await db.execute(stats_query)
        rows = stats_res.all()

        # 3. Classify each ticker
        buckets = {
            "no_data": 0,
            "partial_lt1yr": 0,
            "partial_1_3yr": 0,
            "partial_3_5yr": 0,
            "partial_5_10yr": 0,
            "full_10yr_plus": 0,
        }
        current_count = 0   # stocks with data up to today (within 4 days)
        us_count = 0
        in_count = 0
        sample_current = []
        sample_pending = []

        ticker_map = {}
        for row in rows:
            ticker_map[row.ticker] = row

        for row in rows:
            years = (row.last_date - row.first_date).days / 365.25
            if years < 1:
                buckets["partial_lt1yr"] += 1
            elif years < 3:
                buckets["partial_1_3yr"] += 1
            elif years < 5:
                buckets["partial_3_5yr"] += 1
            elif years < 10:
                buckets["partial_5_10yr"] += 1
            else:
                buckets["full_10yr_plus"] += 1

            is_current = row.last_date >= four_days_ago
            if is_current:
                current_count += 1
                if len(sample_current) < 5:
                    sample_current.append({
                        "ticker": row.ticker,
                        "country": row.country,
                        "first_date": row.first_date.isoformat(),
                        "last_date": row.last_date.isoformat(),
                        "years": round(years, 1),
                        "rows": row.row_count,
                    })

            if row.country == "US":
                us_count += 1
            elif row.country == "IN":
                in_count += 1

        ingested = len(rows)
        buckets["no_data"] = total - ingested

        # 4. Sample of pending tickers (in stocks but not in prices)
        pending_query = text("""
            SELECT s.ticker, s.country, s.name
            FROM stocks s
            WHERE s.ticker NOT IN (SELECT DISTINCT ticker FROM stock_prices)
            LIMIT 5
        """)
        pending_res = await db.execute(pending_query)
        sample_pending = [
            {"ticker": r.ticker, "country": r.country, "name": r.name}
            for r in pending_res.all()
        ]

        return {
            "total_universe": total,
            "ingested": ingested,
            "current_to_date": current_count,
            "not_yet_ingested": buckets["no_data"],
            "by_years": {
                "lt_1yr": buckets["partial_lt1yr"],
                "1_to_3yr": buckets["partial_1_3yr"],
                "3_to_5yr": buckets["partial_3_5yr"],
                "5_to_10yr": buckets["partial_5_10yr"],
                "10yr_plus": buckets["full_10yr_plus"],
            },
            "by_country": {
                "US": us_count,
                "IN": in_count,
                "other": ingested - us_count - in_count,
            },
            "sample_current": sample_current,
            "sample_pending": sample_pending,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Live Active Jobs Tracking ───────────────────────────────────────────────

@router.get("/active-jobs")
async def get_active_jobs():
    """
    Scans OS processes to detect manual python backfiller scripts running in the background.
    Also parses the tail of common .log files in the backend directory to provide a history of completed jobs.
    """
    import subprocess
    import os
    import glob
    from pathlib import Path
    
    jobs = []
    
    # ── 1. Check for Active Running Scripts ──
    try:
        ps_out = subprocess.check_output(["pgrep", "-f", "run_catchup_backfill.py"], text=True)
        if ps_out:
            jobs.append({
                "job_id": "catchup_backfill",
                "name": "Automated Catch-up Backfill",
                "status": "RUNNING",
                "progress_text": "Fetching recent missing dates...",
                "progress_pct": None
            })
    except subprocess.CalledProcessError:
        pass

    try:
        ps_out = subprocess.check_output(["pgrep", "-f", "run_continuous_backfill.py"], text=True)
        if ps_out:
            jobs.append({
                "job_id": "historical_backfill",
                "name": "Continuous Historical Backfill",
                "status": "RUNNING",
                "progress_text": "Fetching massive 10yr+ history...",
                "progress_pct": None
            })
    except subprocess.CalledProcessError:
        pass


    # ── 2. Parse Completed Job History from Log Files ──
    history = []
    backend_dir = Path(__file__).parent.parent.parent
    log_files = glob.glob(str(backend_dir / "*.log"))

    for log_path in log_files:
        file_name = os.path.basename(log_path)
        
        # We only care about specific log files generated by our backfillers
        if file_name not in ["fundamentals_backfill.log", "promoter_ingest.log"]:
            continue
            
        try:
            # Read the last ~20 lines
            out = subprocess.check_output(["tail", "-n", "20", log_path], text=True)
            lines = out.strip().split('\n')
            
            # Look for success markers
            status = "UNKNOWN"
            summary_msg = "Completed recently."
            
            for line in reversed(lines):
                if "✅" in line or "complete in" in line.lower():
                    status = "COMPLETED"
                    summary_msg = line.strip()
                    break
                    
            # If we didn't find a clean completion marker, it might still be running 
            # or it died unexpectedly. We will check if its process is active to be sure.
            is_active = False
            script_name = f"run_{file_name.replace('.log', '.py')}"
            try:
                if subprocess.check_output(["pgrep", "-f", script_name], text=True):
                    is_active = True
            except:
                pass
                
            if is_active:
                jobs.append({
                    "job_id": file_name,
                    "name": file_name.replace('_', ' ').replace('.log', '').title(),
                    "status": "RUNNING",
                    "progress_text": f"Writing to {file_name}...",
                    "progress_pct": None
                })
            else:
                if status == "UNKNOWN":
                    # Looks like it died or was cancelled mid-run without printing ✅
                    status = "CANCELLED / ERROR"
                    summary_msg = "Process terminated before printing completion summary."
                    
                # Get file modification time
                mtime = os.path.getmtime(log_path)
                from datetime import datetime
                ended_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                
                history.append({
                    "job_name": file_name.replace('_', ' ').replace('.log', '').title(),
                    "file": file_name,
                    "status": status,
                    "ended_at": ended_at,
                    "summary": summary_msg
                })
                
        except Exception as e:
            print(f"Error parsing log file {log_path}: {e}")

    # Sort history by newest first
    history.sort(key=lambda x: x["ended_at"], reverse=True)

    return {
        "active_jobs": jobs,
        "job_history": history
    }




# ── GET /ingestion/freshness ──────────────────────────────────────────────────

@router.get("/freshness")
async def get_data_freshness(db: AsyncSession = Depends(get_db)):
    """
    Return data freshness status — how stale the price data is.
    Used by the frontend to show a warning banner when data is old.
    """
    import datetime as dt

    result = await db.execute(
        text("SELECT MAX(date) as last_date, MAX(created_at) as last_ts FROM stock_prices")
    )
    row = result.fetchone()

    last_date = row.last_date if row else None
    last_ts   = row.last_ts   if row else None

    now_utc = dt.datetime.now(dt.timezone.utc)

    # Hours since last price row was written
    if last_ts:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=dt.timezone.utc)
        hours_stale = round((now_utc - last_ts).total_seconds() / 3600, 1)
    else:
        hours_stale = None

    # Data is stale if > 6 hours old on a weekday, or > 72h on weekend
    is_weekend = now_utc.weekday() >= 5
    stale_threshold = 72 if is_weekend else 6
    is_stale = (hours_stale is not None and hours_stale > stale_threshold)

    warning = None
    if is_stale and hours_stale is not None:
        h = int(hours_stale)
        warning = f"Price data is {h}h old — refresh the ingestion pipeline to get the latest quotes."

    return {
        "last_price_date": str(last_date) if last_date else None,
        "last_price_ts":   last_ts.isoformat() if last_ts else None,
        "hours_stale":     hours_stale,
        "is_stale":        is_stale,
        "stale_threshold_h": stale_threshold,
        "warning":         warning,
    }
