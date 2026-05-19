"""
research_query.py
=================
Handles natural language research queries about stocks using Claude tool-use.
Claude decides which data to fetch, calls tools, synthesizes a research report.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from anthropic import AsyncAnthropic

logger = logging.getLogger("omnitrader.services.research_query")

# ── Tool definitions for Claude ────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_stock_fundamentals",
        "description": (
            "Fetch the latest fundamental financial data for a stock ticker, "
            "including revenue, EPS, PE ratio, debt/equity, ROE, and other "
            "key financial metrics from company_financials."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "The stock ticker symbol (e.g. AAPL, MSFT).",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_technical_indicators",
        "description": (
            "Fetch the latest technical indicators for a stock ticker, "
            "including moving averages, RSI, MACD, Bollinger Bands, ATR, "
            "and volume ratio from stock_technicals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "The stock ticker symbol.",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_analyst_ratings",
        "description": (
            "Fetch analyst ratings for a stock ticker, including average price "
            "target and counts of buy/hold/sell recommendations from analyst_ratings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "The stock ticker symbol.",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_news_sentiment",
        "description": (
            "Fetch recent news sentiment for a stock ticker, including the "
            "average sentiment score and top recent headlines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "The stock ticker symbol.",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days of news to look back (default 7).",
                    "default": 7,
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_macro_context",
        "description": (
            "Fetch current macro-economic context including VIX (fear gauge), "
            "DXY (US dollar index), US 10-year Treasury yield, and Gold price "
            "from macro_data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_pair_trades",
        "description": (
            "Fetch active statistical arbitrage pair trade signals that involve "
            "a given ticker, including the paired stock, spread z-score, and signal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "The stock ticker symbol to look up pair trades for.",
                }
            },
            "required": ["ticker"],
        },
    },
]


# ── DB query helpers ───────────────────────────────────────────────────────────


async def _query_stock_fundamentals(db: AsyncSession, ticker: str) -> dict:
    result = await db.execute(
        text("""
            SELECT ticker, fiscal_date, report_period,
                   revenue, net_income, eps, eps_estimate, eps_surprise_pct,
                   pe_ratio, debt_to_equity, roe, roic, operating_margin,
                   free_cash_flow, total_assets, total_liabilities
            FROM company_financials
            WHERE ticker = :ticker
            ORDER BY fiscal_date DESC
            LIMIT 1
        """),
        {"ticker": ticker.upper()},
    )
    row = result.fetchone()
    if not row:
        return {"error": f"No fundamental data found for {ticker}"}
    return {
        "ticker": row.ticker,
        "fiscal_date": str(row.fiscal_date) if row.fiscal_date else None,
        "report_period": row.report_period,
        "revenue": row.revenue,
        "net_income": row.net_income,
        "eps": row.eps,
        "eps_estimate": row.eps_estimate,
        "eps_surprise_pct": row.eps_surprise_pct,
        "pe_ratio": row.pe_ratio,
        "debt_to_equity": row.debt_to_equity,
        "roe": row.roe,
        "roic": row.roic,
        "operating_margin": row.operating_margin,
        "free_cash_flow": row.free_cash_flow,
        "total_assets": row.total_assets,
        "total_liabilities": row.total_liabilities,
    }


async def _query_technical_indicators(db: AsyncSession, ticker: str) -> dict:
    result = await db.execute(
        text("""
            SELECT ticker, date,
                   sma_20, sma_50, sma_200, ema_9, ema_21,
                   rsi_14, macd, macd_signal, macd_hist,
                   atr_14, bb_upper, bb_lower, bb_mid,
                   vol_ratio, week_52_high, week_52_low,
                   rs_vs_spx, price_zscore_20d, bb_squeeze
            FROM stock_technicals
            WHERE ticker = :ticker
            ORDER BY date DESC
            LIMIT 1
        """),
        {"ticker": ticker.upper()},
    )
    row = result.fetchone()
    if not row:
        return {"error": f"No technical data found for {ticker}"}
    return {
        "ticker": row.ticker,
        "date": str(row.date) if row.date else None,
        "sma_20": row.sma_20,
        "sma_50": row.sma_50,
        "sma_200": row.sma_200,
        "ema_9": row.ema_9,
        "ema_21": row.ema_21,
        "rsi_14": row.rsi_14,
        "macd": row.macd,
        "macd_signal": row.macd_signal,
        "macd_hist": row.macd_hist,
        "atr_14": row.atr_14,
        "bb_upper": row.bb_upper,
        "bb_lower": row.bb_lower,
        "bb_mid": row.bb_mid,
        "vol_ratio": row.vol_ratio,
        "week_52_high": row.week_52_high,
        "week_52_low": row.week_52_low,
        "rs_vs_spx": row.rs_vs_spx,
        "price_zscore_20d": row.price_zscore_20d,
        "bb_squeeze": row.bb_squeeze,
    }


async def _query_analyst_ratings(db: AsyncSession, ticker: str) -> dict:
    result = await db.execute(
        text("""
            SELECT
                AVG(price_target) FILTER (WHERE price_target IS NOT NULL) AS avg_target,
                COUNT(*) FILTER (WHERE to_grade ILIKE ANY(ARRAY['buy','strong buy','overweight','outperform'])) AS buy_count,
                COUNT(*) FILTER (WHERE to_grade ILIKE ANY(ARRAY['hold','neutral','market perform','equal weight'])) AS hold_count,
                COUNT(*) FILTER (WHERE to_grade ILIKE ANY(ARRAY['sell','underperform','underweight'])) AS sell_count,
                MAX(date) AS latest_date
            FROM analyst_ratings
            WHERE ticker = :ticker
              AND date >= NOW() - INTERVAL '90 days'
        """),
        {"ticker": ticker.upper()},
    )
    row = result.fetchone()
    if not row or row.latest_date is None:
        return {"error": f"No analyst ratings found for {ticker} in the last 90 days"}
    return {
        "ticker": ticker.upper(),
        "avg_price_target": round(row.avg_target, 2) if row.avg_target else None,
        "buy_count": row.buy_count or 0,
        "hold_count": row.hold_count or 0,
        "sell_count": row.sell_count or 0,
        "latest_rating_date": str(row.latest_date),
    }


async def _query_news_sentiment(db: AsyncSession, ticker: str, days: int = 7) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Average sentiment
    avg_result = await db.execute(
        text("""
            SELECT AVG(sentiment_score) AS avg_score, COUNT(*) AS total
            FROM news_sentiment
            WHERE ticker = :ticker AND time >= :cutoff
        """),
        {"ticker": ticker.upper(), "cutoff": cutoff},
    )
    avg_row = avg_result.fetchone()

    # Top headlines (most recent 5)
    headlines_result = await db.execute(
        text("""
            SELECT headline, sentiment_score, event_type, time
            FROM news_sentiment
            WHERE ticker = :ticker AND time >= :cutoff
            ORDER BY time DESC
            LIMIT 5
        """),
        {"ticker": ticker.upper(), "cutoff": cutoff},
    )
    headlines = [
        {
            "headline": r.headline,
            "sentiment_score": r.sentiment_score,
            "event_type": r.event_type,
            "time": str(r.time),
        }
        for r in headlines_result.fetchall()
    ]

    return {
        "ticker": ticker.upper(),
        "days": days,
        "avg_sentiment_score": round(avg_row.avg_score, 3) if avg_row and avg_row.avg_score else None,
        "total_articles": avg_row.total if avg_row else 0,
        "top_headlines": headlines,
    }


async def _query_macro_context(db: AsyncSession) -> dict:
    indicators = ["VIX", "DXY", "US10Y", "Gold"]
    result = await db.execute(
        text("""
            SELECT DISTINCT ON (indicator)
                indicator, value, time
            FROM macro_data
            WHERE indicator = ANY(:indicators)
            ORDER BY indicator, time DESC
        """),
        {"indicators": indicators},
    )
    rows = result.fetchall()
    if not rows:
        return {"error": "No macro data available"}

    macro = {}
    for row in rows:
        macro[row.indicator] = {
            "value": row.value,
            "as_of": str(row.time),
        }
    return {"macro_indicators": macro}


async def _query_pair_trades(db: AsyncSession, ticker: str) -> dict:
    ticker_upper = ticker.upper()
    result = await db.execute(
        text("""
            SELECT symbol_a, symbol_b, signal, signal_strength,
                   spread_zscore, correlation_90d, cointegration_pvalue,
                   last_updated
            FROM pair_trades
            WHERE (symbol_a = :ticker OR symbol_b = :ticker)
              AND signal != 'NEUTRAL'
            ORDER BY ABS(spread_zscore) DESC NULLS LAST
            LIMIT 5
        """),
        {"ticker": ticker_upper},
    )
    rows = result.fetchall()
    if not rows:
        return {"ticker": ticker_upper, "pairs": [], "message": "No active pair trade signals found"}

    pairs = [
        {
            "symbol_a": row.symbol_a,
            "symbol_b": row.symbol_b,
            "signal": row.signal,
            "signal_strength": row.signal_strength,
            "spread_zscore": row.spread_zscore,
            "correlation_90d": row.correlation_90d,
            "cointegration_pvalue": row.cointegration_pvalue,
            "last_updated": str(row.last_updated) if row.last_updated else None,
        }
        for row in rows
    ]
    return {"ticker": ticker_upper, "pairs": pairs}


# ── Tool executor ──────────────────────────────────────────────────────────────


async def _execute_tool(db: AsyncSession, tool_name: str, tool_input: dict) -> Any:
    """Dispatch a tool call to the corresponding DB query function."""
    if tool_name == "get_stock_fundamentals":
        return await _query_stock_fundamentals(db, tool_input.get("ticker", ""))
    elif tool_name == "get_technical_indicators":
        return await _query_technical_indicators(db, tool_input.get("ticker", ""))
    elif tool_name == "get_analyst_ratings":
        return await _query_analyst_ratings(db, tool_input.get("ticker", ""))
    elif tool_name == "get_news_sentiment":
        return await _query_news_sentiment(
            db,
            tool_input.get("ticker", ""),
            days=int(tool_input.get("days", 7)),
        )
    elif tool_name == "get_macro_context":
        return await _query_macro_context(db)
    elif tool_name == "get_pair_trades":
        return await _query_pair_trades(db, tool_input.get("ticker", ""))
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ── Main service ───────────────────────────────────────────────────────────────


class ResearchQueryService:
    """
    Processes natural language research queries about stocks.
    Uses Claude with tool-use to gather relevant data and synthesize a report.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = AsyncAnthropic()

    async def ask(self, query: str) -> dict:
        """
        Send query to Claude with all 6 tools defined.
        Implements tool-calling loop until Claude produces a final text response.

        Returns:
            {
                "answer": str,
                "tools_used": list[str],
                "ticker": str | None,
            }
        """
        messages = [{"role": "user", "content": query}]
        tools_used: list[str] = []
        ticker_found: Optional[str] = None
        final_text = ""

        # System prompt to guide Claude
        system_prompt = (
            "You are OmniTrader AI, an expert stock research assistant. "
            "When asked about a stock or market condition, use the available tools "
            "to gather relevant data, then synthesize a concise research report. "
            "Always cite the data sources you used. Be specific and actionable."
        )

        max_iterations = 10  # safety limit on tool-call rounds
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            response = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )

            # Check stop reason
            if response.stop_reason == "end_turn":
                # Extract text from response
                for block in response.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                break

            if response.stop_reason == "tool_use":
                # Collect all tool_use blocks
                tool_use_blocks = [
                    block for block in response.content if block.type == "tool_use"
                ]

                if not tool_use_blocks:
                    # No tool calls despite tool_use stop reason — extract text and stop
                    for block in response.content:
                        if hasattr(block, "text"):
                            final_text = block.text
                    break

                # Add assistant's response to message history
                messages.append({"role": "assistant", "content": response.content})

                # Execute all tool calls and collect results
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name = tool_block.name
                    tool_input = tool_block.input or {}

                    if tool_name not in tools_used:
                        tools_used.append(tool_name)

                    # Extract ticker if mentioned in tool input
                    if "ticker" in tool_input and not ticker_found:
                        ticker_found = str(tool_input["ticker"]).upper()

                    logger.info(
                        "Executing tool %s with input %s", tool_name, tool_input
                    )

                    try:
                        tool_result = await _execute_tool(self.db, tool_name, tool_input)
                        result_content = json.dumps(tool_result)
                    except Exception as exc:
                        logger.error("Tool %s failed: %s", tool_name, exc)
                        result_content = json.dumps({"error": str(exc)})

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": result_content,
                        }
                    )

                # Add tool results to messages
                messages.append({"role": "user", "content": tool_results})

            else:
                # Unexpected stop reason — extract any text and stop
                for block in response.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                break

        if not final_text:
            final_text = "Unable to generate a research report for this query."

        logger.info(
            "Research query completed: tools_used=%s ticker=%s",
            tools_used,
            ticker_found,
        )

        return {
            "answer": final_text,
            "tools_used": tools_used,
            "ticker": ticker_found,
        }
