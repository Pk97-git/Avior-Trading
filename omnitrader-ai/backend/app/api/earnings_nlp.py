"""
api/earnings_nlp.py
====================
GET  /earnings-nlp/{ticker}       — analyse earnings tone for a ticker
GET  /earnings-nlp/recent/movers  — stocks with strong earnings tone signals
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.engines.earnings_nlp import analyse_earnings_tone

router = APIRouter()
logger = logging.getLogger(__name__)

EARNINGS_KEYWORDS = [
    "earnings", "quarter", "Q1", "Q2", "Q3", "Q4", "results",
    "revenue", "profit", "EPS", "guidance", "outlook", "forecast",
    "beat", "miss", "raised", "lowered", "analyst", "upgrade", "downgrade",
]


@router.get("/recent/movers")
async def get_earnings_movers(
    country: str = Query("ALL"),
    limit:   int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """
    Find stocks with the most earnings-related news in the last 30 days
    — these are likely post-earnings movers worth analysing.
    """
    country_clause = "" if country.upper() == "ALL" else "AND s.country = :country"
    params: dict = {}
    if country.upper() != "ALL":
        params["country"] = country.upper()

    try:
        result = await db.execute(text(f"""
            SELECT s.ticker, s.name, s.sector, s.country,
                   COUNT(ns.id) as news_count,
                   AVG(ns.sentiment_score) as avg_sentiment,
                   MAX(ns.published_at) as latest_news
            FROM stocks s
            JOIN news_sentiment ns ON ns.ticker = s.ticker
            WHERE ns.published_at >= NOW() - INTERVAL '30 days'
              AND (
                LOWER(ns.headline) LIKE '%earnings%'
                OR LOWER(ns.headline) LIKE '%quarter%'
                OR LOWER(ns.headline) LIKE '%results%'
                OR LOWER(ns.headline) LIKE '%guidance%'
              )
              {country_clause}
            GROUP BY s.ticker, s.name, s.sector, s.country
            HAVING COUNT(ns.id) >= 2
            ORDER BY COUNT(ns.id) DESC, ABS(AVG(ns.sentiment_score)) DESC
            LIMIT :limit
        """), {**params, "limit": limit})
        rows = result.fetchall()
    except Exception as e:
        logger.warning("Movers query failed: %s", e)
        rows = []

    movers = []
    for r in rows:
        avg_sent = float(r.avg_sentiment) if r.avg_sentiment else 0
        tone_estimate = "BULLISH_TONE" if avg_sent > 0.2 else "BEARISH_TONE" if avg_sent < -0.2 else "NEUTRAL_TONE"
        movers.append({
            "ticker":         r.ticker,
            "name":           r.name,
            "sector":         r.sector,
            "country":        r.country,
            "news_count":     r.news_count,
            "avg_sentiment":  round(avg_sent, 3),
            "tone_estimate":  tone_estimate,
            "latest_news":    str(r.latest_news)[:10] if r.latest_news else None,
        })

    return {"count": len(movers), "movers": movers}


@router.get("/{ticker}")
async def get_earnings_tone(
    ticker: str,
    days:   int = Query(45, ge=7, le=90, description="Days of news to analyse"),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyse earnings call tone for a ticker from recent news.
    Fetches earnings-related news from DB and runs Groq NLP.
    """
    t = ticker.strip().upper()

    # Build keyword filter
    keyword_conditions = " OR ".join([f"LOWER(headline) LIKE '%{kw.lower()}%'" for kw in EARNINGS_KEYWORDS[:8]])

    try:
        result = await db.execute(text(f"""
            SELECT ns.headline, ns.summary, ns.published_at,
                   ns.sentiment_score, ns.sentiment_magnitude
            FROM news_sentiment ns
            WHERE ns.ticker = :ticker
              AND ns.published_at >= NOW() - INTERVAL ':days days'
              AND ({keyword_conditions})
            ORDER BY ns.published_at DESC
            LIMIT 20
        """), {"ticker": t, "days": days})
        news_rows = result.fetchall()
    except Exception as e:
        logger.warning("News query failed: %s", e)
        news_rows = []

    # Also get sector
    try:
        s_result = await db.execute(text("SELECT sector FROM stocks WHERE ticker = :t"), {"t": t})
        s_row = s_result.fetchone()
        sector = s_row.sector if s_row else ""
    except Exception:
        sector = ""

    news_items = [
        {
            "headline":       r.headline,
            "summary":        r.summary or "",
            "published_at":   str(r.published_at)[:10] if r.published_at else "",
            "sentiment_score": float(r.sentiment_score) if r.sentiment_score else 0,
        }
        for r in news_rows
    ]

    analysis = await analyse_earnings_tone(t, sector=sector, news_items=news_items)
    return analysis
