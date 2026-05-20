"""
services/copilot.py
===================
OmniTrader AI Copilot — conversational layer over the full platform.

Handles multi-turn conversations with:
  • 12 DB tools covering portfolio, prices, news, macro, signals, screener
  • Session memory (in-memory, 2h TTL, 100 max sessions)
  • Rich responses: answer + charts + citations + trade actions + follow-ups

Example questions handled:
  "Why did my portfolio fall today?"
  "Best AI stocks under $100?"
  "Compare Indian IT sector with US tech."
  "Should I sell Tesla?"
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from anthropic import AsyncAnthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Tool definitions ───────────────────────────────────────────────────────────

COPILOT_TOOLS = [
    {
        "name": "get_portfolio",
        "description": (
            "Get the user's current open portfolio positions: tickers, entry prices, "
            "current prices, unrealised P&L, allocation % by sector and country. "
            "Use for 'how is my portfolio doing', 'what do I own', allocation questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_portfolio_attribution",
        "description": (
            "Explain what drove the portfolio's P&L over a period. "
            "Returns top gainers, top losers, and total P&L. "
            "Use for 'why did my portfolio fall/rise today' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Look-back days (1 = today, 7 = last week)",
                    "default": 1,
                }
            },
        },
    },
    {
        "name": "get_stock_data",
        "description": (
            "Get comprehensive data for a stock: price, AI score (0–100), signal "
            "(BUY/HOLD/REDUCE/SELL), fundamentals (P/E, EPS growth, revenue), "
            "technicals (RSI, MACD, ATR), and the latest analysis thesis. "
            "Use for any question about a specific stock."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker, e.g. AAPL, TSLA, RELIANCE.NS",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_price_history",
        "description": (
            "Get OHLCV price history for a stock. Returns data for chart rendering. "
            "Use when showing price charts, trends, or performance over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {
                    "type": "integer",
                    "description": "Days of history (default 30)",
                    "default": 30,
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_news",
        "description": (
            "Get recent news headlines and sentiment for a stock or the overall market. "
            "Returns event types (EARNINGS_BEAT, GUIDANCE_RAISE, REGULATORY_ACTION, etc.) "
            "and sentiment scores. Use for 'what's happening with X' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker; omit for market-wide news",
                },
                "days": {"type": "integer", "default": 7},
            },
        },
    },
    {
        "name": "get_market_overview",
        "description": (
            "Get current macro regime (Risk-On/Risk-Off/Tightening/etc.), VIX level, "
            "FII/DII flows for India, index performance (SPX, NIFTY 50), and "
            "cross-assets (Gold, Oil WTI, DXY, INR/USD, US 10Y). "
            "Use for macro/market context questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "screen_stocks",
        "description": (
            "Screen for stocks matching criteria. Use for 'best AI stocks under $100', "
            "'top BUY signals in India IT sector', 'highest scored US tech stocks', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "US or IN (omit for both)"},
                "sector": {"type": "string", "description": "Sector name (omit for all)"},
                "signal": {
                    "type": "string",
                    "description": "BUY, HOLD, REDUCE, or SELL (omit for all)",
                },
                "min_score": {
                    "type": "number",
                    "description": "Minimum AI score 0–100",
                },
                "max_price": {
                    "type": "number",
                    "description": "Max price in USD or INR",
                },
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "compare_stocks",
        "description": (
            "Side-by-side comparison of 2–4 stocks: price change, AI scores, "
            "fundamentals, and signals. Use for 'compare X vs Y' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2–4 stock tickers",
                },
                "days": {
                    "type": "integer",
                    "description": "Performance window days",
                    "default": 30,
                },
            },
            "required": ["tickers"],
        },
    },
    {
        "name": "get_sector_analysis",
        "description": (
            "Get sector rotation data: momentum scores, top/bottom performers per sector, "
            "sector vs benchmark returns. Use for sector comparison questions like "
            "'Indian IT vs US tech' or 'which sectors are leading'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": "Specific sector; omit for full rotation view",
                },
                "country": {
                    "type": "string",
                    "description": "US or IN; omit for both",
                },
            },
        },
    },
    {
        "name": "get_trade_recommendation",
        "description": (
            "Get the AI trade recommendation for a stock: signal, score, entry price, "
            "stop loss, take profit, and detailed reasoning. "
            "Use for 'should I buy/sell X?' questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_portfolio_risk",
        "description": (
            "Get portfolio risk metrics: Sharpe ratio, beta vs benchmark, "
            "sector concentration, largest drawdown, Value-at-Risk estimate. "
            "Use for 'is my portfolio risky?' or risk assessment questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_earnings_calendar",
        "description": (
            "Get upcoming earnings dates for portfolio stocks or a specific ticker. "
            "Returns date, consensus EPS estimate, and prior quarter result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Specific ticker; omit for portfolio-wide",
                },
                "days_ahead": {"type": "integer", "default": 14},
            },
        },
    },
]

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are OmniTrader AI Copilot, an expert portfolio manager and financial \
analyst for both Indian (NSE/BSE) and US (NYSE/NASDAQ) markets.

You have access to real-time data through 12 tools covering the user's portfolio, \
AI-powered signals (0–100 scores across fundamental/technical/sentiment/macro/risk), \
price history, news, macro regime, sector rotation, and earnings.

Rules:
1. ALWAYS call tools to get live data before answering — never rely on training data for prices or scores.
2. Cite specific numbers: "TSLA scored 42/100 (REDUCE) as of today", "portfolio fell ₹12,400 (−2.1%)".
3. For "why did X happen" → check price history + news + macro regime.
4. For "should I buy/sell X" → get_trade_recommendation + get_stock_data + check market regime.
5. For comparisons → use compare_stocks or get_sector_analysis.
6. For screening → use screen_stocks with criteria extracted from the question.
7. Format: prices 2 dp, percentages 1 dp, scores as X/100. Use ₹ for INR, $ for USD.
8. Lead with the direct answer (1–2 sentences), then support with data.
9. Mark high-risk situations with ⚠️.
10. End every response with exactly 3 follow-up questions the user might want to ask next, \
prefixed with "**Follow-up questions:**" on its own line.

When a chart would help: include "CHART_REQUEST: <ticker> <days>d" anywhere in your response \
and the system will attach chart data automatically.

Keep responses focused and actionable. No disclaimers about not being a financial advisor."""


# ── Session store ──────────────────────────────────────────────────────────────

class _SessionStore:
    MAX = 100
    TTL = 7_200  # 2 hours

    def __init__(self) -> None:
        self._s: OrderedDict[str, dict] = OrderedDict()

    def get_or_create(self, sid: str) -> list:
        now = time.time()
        self._evict(now)
        if sid not in self._s:
            if len(self._s) >= self.MAX:
                self._s.popitem(last=False)
            self._s[sid] = {"msgs": [], "ts": now}
        else:
            self._s.move_to_end(sid)
        self._s[sid]["ts"] = now
        return self._s[sid]["msgs"]

    def save(self, sid: str, msgs: list) -> None:
        if sid in self._s:
            self._s[sid]["msgs"] = msgs
            self._s[sid]["ts"] = time.time()

    def history(self, sid: str) -> list[dict]:
        return [
            {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else "[tool interaction]"}
            for m in self._s.get(sid, {}).get("msgs", [])
            if isinstance(m.get("content"), str)
        ]

    def delete(self, sid: str) -> None:
        self._s.pop(sid, None)

    def _evict(self, now: float) -> None:
        dead = [k for k, v in self._s.items() if now - v["ts"] > self.TTL]
        for k in dead:
            del self._s[k]


_store = _SessionStore()


# ── CopilotService ─────────────────────────────────────────────────────────────

class CopilotService:
    """
    Conversational AI layer. Each call to `chat()` continues a session.
    Returns rich response: answer, charts, citations, trade actions, follow-ups.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.client = AsyncAnthropic()

    # ── Public entry point ─────────────────────────────────────────────────────

    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
    ) -> dict:
        if not session_id:
            session_id = str(uuid.uuid4())

        messages = _store.get_or_create(session_id)
        messages.append({"role": "user", "content": message})

        charts: list[dict] = []
        citations: list[dict] = []
        tools_used: list[str] = []
        final_text = ""

        for _ in range(12):  # max tool-call rounds
            resp = await self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=COPILOT_TOOLS,
                messages=messages,
            )

            if resp.stop_reason == "end_turn":
                for block in resp.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                break

            if resp.stop_reason == "tool_use":
                tool_blocks = [b for b in resp.content if b.type == "tool_use"]
                if not tool_blocks:
                    for block in resp.content:
                        if hasattr(block, "text"):
                            final_text = block.text
                    break

                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for tb in tool_blocks:
                    tools_used.append(tb.name)
                    tool_result, tool_charts, tool_cites = await self._run_tool(
                        tb.name, tb.input or {}
                    )
                    charts.extend(tool_charts)
                    citations.extend(tool_cites)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": tb.id,
                        "content": tool_result,
                    })
                messages.append({"role": "user", "content": results})

        # Inline CHART_REQUEST directives from the answer text
        inline_charts = await self._extract_inline_charts(final_text)
        charts.extend(inline_charts)
        # Strip CHART_REQUEST lines from visible answer
        clean_answer = "\n".join(
            l for l in final_text.splitlines()
            if not l.strip().startswith("CHART_REQUEST:")
        )

        # Parse follow-up questions from answer
        follow_ups, clean_answer = self._parse_follow_ups(clean_answer)

        _store.save(session_id, messages)

        return {
            "session_id": session_id,
            "answer": clean_answer.strip(),
            "charts": charts,
            "citations": citations,
            "actions": self._extract_actions(citations, tools_used),
            "follow_ups": follow_ups,
            "tools_used": list(dict.fromkeys(tools_used)),
        }

    def get_history(self, session_id: str) -> list[dict]:
        return _store.history(session_id)

    def clear_session(self, session_id: str) -> None:
        _store.delete(session_id)

    # ── Tool dispatcher ────────────────────────────────────────────────────────

    async def _run_tool(
        self, name: str, inp: dict
    ) -> tuple[str, list[dict], list[dict]]:
        """Run a tool. Returns (json_result, charts, citations)."""
        try:
            fn = getattr(self, f"_tool_{name}", None)
            if fn is None:
                return json.dumps({"error": f"Unknown tool: {name}"}), [], []
            return await fn(inp)
        except Exception as exc:
            logger.warning("[Copilot] tool %s failed: %s", name, exc)
            return json.dumps({"error": str(exc)}), [], []

    # ── Tool implementations ───────────────────────────────────────────────────

    async def _tool_get_portfolio(self, _: dict) -> tuple[str, list, list]:
        rows = await self.db.execute(text("""
            SELECT pp.ticker, pp.entry_price, pp.shares, pp.stop_loss, pp.take_profit,
                   pp.signal, pp.entry_date,
                   s.name, s.sector, s.country,
                   sp.close AS current_price
            FROM portfolio_positions pp
            LEFT JOIN stocks s ON s.ticker = pp.ticker
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices
                WHERE ticker = pp.ticker ORDER BY time DESC LIMIT 1
            ) sp ON true
            WHERE pp.is_open = TRUE
            ORDER BY pp.entry_date DESC
        """))
        positions = rows.fetchall()
        if not positions:
            return json.dumps({"positions": [], "total_value": 0, "note": "No open positions"}), [], []

        items = []
        total_value = 0.0
        total_cost = 0.0
        by_sector: dict[str, float] = {}
        by_country: dict[str, float] = {}

        for p in positions:
            cur = p.current_price or p.entry_price
            value = (cur or 0) * p.shares
            cost = p.entry_price * p.shares
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost else 0
            total_value += value
            total_cost += cost
            sec = p.sector or "Unknown"
            cnt = p.country or "US"
            by_sector[sec] = by_sector.get(sec, 0) + value
            by_country[cnt] = by_country.get(cnt, 0) + value
            items.append({
                "ticker": p.ticker, "name": p.name,
                "sector": sec, "country": cnt,
                "shares": p.shares, "entry_price": round(p.entry_price, 2),
                "current_price": round(cur, 2) if cur else None,
                "value": round(value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl_pct, 2),
                "signal": p.signal,
            })

        total_pnl = total_value - total_cost
        result = {
            "positions": items,
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_unrealized_pnl": round(total_pnl, 2),
            "total_unrealized_pnl_pct": round((total_pnl / total_cost * 100) if total_cost else 0, 2),
            "sector_allocation": {k: round(v / total_value * 100, 1) for k, v in by_sector.items()} if total_value else {},
            "country_allocation": {k: round(v / total_value * 100, 1) for k, v in by_country.items()} if total_value else {},
        }
        charts = [{
            "type": "pie",
            "title": "Portfolio Sector Allocation",
            "data": [{"label": k, "value": round(v, 1)} for k, v in result["sector_allocation"].items()],
        }]
        cites = [{"source": "Portfolio Positions", "count": len(items)}]
        return json.dumps(result), charts, cites

    async def _tool_get_portfolio_attribution(self, inp: dict) -> tuple[str, list, list]:
        days = int(inp.get("days", 1))
        since = datetime.now(timezone.utc) - timedelta(days=days)

        rows = await self.db.execute(text("""
            SELECT pp.ticker, pp.shares,
                   s.name, s.sector,
                   sp_now.close   AS price_now,
                   sp_then.close  AS price_then
            FROM portfolio_positions pp
            LEFT JOIN stocks s ON s.ticker = pp.ticker
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices WHERE ticker = pp.ticker
                ORDER BY time DESC LIMIT 1
            ) sp_now ON true
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices WHERE ticker = pp.ticker AND time <= :since
                ORDER BY time DESC LIMIT 1
            ) sp_then ON true
            WHERE pp.is_open = TRUE
        """), {"since": since})
        positions = rows.fetchall()

        contributors = []
        for p in positions:
            if not p.price_now or not p.price_then:
                continue
            pnl = (p.price_now - p.price_then) * p.shares
            pnl_pct = (p.price_now - p.price_then) / p.price_then * 100
            contributors.append({
                "ticker": p.ticker, "name": p.name, "sector": p.sector,
                "price_change_pct": round(pnl_pct, 2),
                "pnl_contribution": round(pnl, 2),
                "shares": p.shares,
            })

        contributors.sort(key=lambda x: x["pnl_contribution"], reverse=True)
        total_pnl = sum(c["pnl_contribution"] for c in contributors)

        result = {
            "period_days": days,
            "total_pnl": round(total_pnl, 2),
            "top_gainers": contributors[:3],
            "top_losers": contributors[-3:][::-1],
            "all_contributors": contributors,
        }
        charts = [{
            "type": "bar",
            "title": f"Portfolio P&L Attribution ({days}d)",
            "data": [{"label": c["ticker"], "value": c["pnl_contribution"]} for c in contributors],
        }]
        cites = [{"source": f"Portfolio P&L last {days} day(s)", "total_pnl": round(total_pnl, 2)}]
        return json.dumps(result), charts, cites

    async def _tool_get_stock_data(self, inp: dict) -> tuple[str, list, list]:
        ticker = inp.get("ticker", "").upper()

        # Latest analysis
        ana = await self.db.execute(text("""
            SELECT a.signal, a.final_score, a.fundamental_score, a.technical_score,
                   a.sentiment_score, a.macro_score, a.risk_score,
                   a.entry_price, a.stop_loss, a.take_profit, a.signal_thesis,
                   a.analysis_date, a.regime,
                   f.pe_ratio, f.eps_growth, f.revenue_growth, f.roe, f.debt_to_equity,
                   t.rsi_14, t.macd_signal, t.atr_14, t.sma_50, t.sma_200,
                   s.name, s.sector, s.country,
                   sp.close AS current_price
            FROM ai_analysis a
            LEFT JOIN stock_fundamentals f ON f.ticker = a.ticker
            LEFT JOIN stock_technicals t ON t.ticker = a.ticker
            LEFT JOIN stocks s ON s.ticker = a.ticker
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices WHERE ticker = a.ticker ORDER BY time DESC LIMIT 1
            ) sp ON true
            WHERE a.ticker = :ticker
            ORDER BY a.analysis_date DESC LIMIT 1
        """), {"ticker": ticker})
        row = ana.fetchone()

        if not row:
            return json.dumps({"error": f"No data found for {ticker}"}), [], []

        result = {
            "ticker": ticker,
            "name": row.name,
            "sector": row.sector,
            "country": row.country,
            "current_price": round(row.current_price, 2) if row.current_price else None,
            "signal": row.signal,
            "ai_score": row.final_score,
            "score_breakdown": {
                "fundamental": row.fundamental_score,
                "technical": row.technical_score,
                "sentiment": row.sentiment_score,
                "macro": row.macro_score,
                "risk": row.risk_score,
            },
            "entry_price": round(row.entry_price, 2) if row.entry_price else None,
            "stop_loss": round(row.stop_loss, 2) if row.stop_loss else None,
            "take_profit": round(row.take_profit, 2) if row.take_profit else None,
            "thesis": row.signal_thesis,
            "analysis_date": str(row.analysis_date)[:10] if row.analysis_date else None,
            "regime": row.regime,
            "fundamentals": {
                "pe_ratio": round(row.pe_ratio, 2) if row.pe_ratio else None,
                "eps_growth": round(row.eps_growth, 2) if row.eps_growth else None,
                "revenue_growth": round(row.revenue_growth, 2) if row.revenue_growth else None,
                "roe": round(row.roe, 2) if row.roe else None,
                "debt_to_equity": round(row.debt_to_equity, 2) if row.debt_to_equity else None,
            },
            "technicals": {
                "rsi_14": round(row.rsi_14, 1) if row.rsi_14 else None,
                "macd_signal": row.macd_signal,
                "atr_14": round(row.atr_14, 4) if row.atr_14 else None,
                "sma_50": round(row.sma_50, 2) if row.sma_50 else None,
                "sma_200": round(row.sma_200, 2) if row.sma_200 else None,
            },
        }
        cites = [{"source": "AI Analysis", "ticker": ticker, "score": row.final_score, "signal": row.signal}]
        return json.dumps(result), [], cites

    async def _tool_get_price_history(self, inp: dict) -> tuple[str, list, list]:
        ticker = inp.get("ticker", "").upper()
        days = int(inp.get("days", 30))
        since = datetime.now(timezone.utc) - timedelta(days=days)

        rows = await self.db.execute(text("""
            SELECT time::date AS date, open, high, low, close, volume
            FROM stock_prices
            WHERE ticker = :ticker AND time >= :since
            ORDER BY time ASC
        """), {"ticker": ticker, "since": since})
        data = rows.fetchall()

        chart_data = [
            {
                "date": str(r.date),
                "open": round(r.open, 2) if r.open else None,
                "high": round(r.high, 2) if r.high else None,
                "low": round(r.low, 2) if r.low else None,
                "close": round(r.close, 2) if r.close else None,
                "volume": int(r.volume) if r.volume else 0,
            }
            for r in data
        ]

        # Performance summary
        if len(chart_data) >= 2:
            start_price = chart_data[0]["close"] or 0
            end_price = chart_data[-1]["close"] or 0
            change_pct = ((end_price - start_price) / start_price * 100) if start_price else 0
        else:
            change_pct = 0

        charts = [{
            "type": "candlestick",
            "title": f"{ticker} — {days}d Price",
            "ticker": ticker,
            "data": chart_data,
        }]
        result = {
            "ticker": ticker,
            "days": days,
            "bars": len(chart_data),
            "change_pct": round(change_pct, 2),
            "latest_close": chart_data[-1]["close"] if chart_data else None,
        }
        return json.dumps(result), charts, []

    async def _tool_get_news(self, inp: dict) -> tuple[str, list, list]:
        ticker = inp.get("ticker")
        days = int(inp.get("days", 7))
        since = datetime.now(timezone.utc) - timedelta(days=days)

        if ticker:
            rows = await self.db.execute(text("""
                SELECT headline, sentiment_score, event_type, source, published_at
                FROM news_sentiment
                WHERE ticker = :ticker AND published_at >= :since
                ORDER BY published_at DESC LIMIT 20
            """), {"ticker": ticker.upper(), "since": since})
        else:
            rows = await self.db.execute(text("""
                SELECT ticker, headline, sentiment_score, event_type, source, published_at
                FROM news_sentiment
                WHERE published_at >= :since
                ORDER BY ABS(sentiment_score) DESC LIMIT 20
            """), {"since": since})

        items = []
        for r in rows.fetchall():
            items.append({
                "ticker": getattr(r, "ticker", ticker),
                "headline": r.headline,
                "sentiment": round(r.sentiment_score, 3) if r.sentiment_score else None,
                "event_type": r.event_type,
                "source": r.source,
                "published_at": str(r.published_at)[:16] if r.published_at else None,
            })

        avg_sent = sum(i["sentiment"] for i in items if i["sentiment"]) / max(len(items), 1)
        result = {
            "ticker": ticker,
            "days": days,
            "count": len(items),
            "avg_sentiment": round(avg_sent, 3),
            "sentiment_label": "Positive" if avg_sent > 0.1 else "Negative" if avg_sent < -0.1 else "Neutral",
            "items": items,
        }
        cites = [{"source": "News Sentiment DB", "articles": len(items), "avg_sentiment": round(avg_sent, 3)}]
        return json.dumps(result), [], cites

    async def _tool_get_market_overview(self, _: dict) -> tuple[str, list, list]:
        # Macro regime
        try:
            from app.engines.regime import MacroRegimeClassifier
            from app.db.session import get_db
            classifier = MacroRegimeClassifier(self.db)
            regime_data = await classifier.classify()
        except Exception:
            regime_data = {"regime": "Unknown", "confidence": 0.0}

        # Cross assets
        assets_q = await self.db.execute(text("""
            SELECT DISTINCT ON (indicator) indicator, value, time
            FROM macro_data
            WHERE indicator IN ('VIX', 'GC=F', 'CL=F', 'DX-Y.NYB', 'US10Y', 'INR=X')
            ORDER BY indicator, time DESC
        """))
        cross = {r.indicator: round(r.value, 2) for r in assets_q.fetchall() if r.value}

        # FII/DII net last 5 days
        fii_q = await self.db.execute(text("""
            SELECT entity_type, SUM(net_value) AS net
            FROM institutional_flows
            WHERE market = 'INDIA' AND date >= NOW() - INTERVAL '5 days'
            GROUP BY entity_type
        """))
        fii = {r.entity_type: round(r.net, 0) for r in fii_q.fetchall() if r.net}

        result = {
            "regime": regime_data.get("regime"),
            "regime_confidence": regime_data.get("confidence"),
            "cross_assets": {
                "vix": cross.get("VIX"),
                "gold": cross.get("GC=F"),
                "oil_wti": cross.get("CL=F"),
                "dxy": cross.get("DX-Y.NYB"),
                "us_10y": cross.get("US10Y"),
                "inr_usd": cross.get("INR=X"),
            },
            "fii_dii_5d": fii,
        }
        cites = [{"source": "Macro Regime Engine + FRED + NSE Flows"}]
        return json.dumps(result), [], cites

    async def _tool_screen_stocks(self, inp: dict) -> tuple[str, list, list]:
        conditions = ["a.analysis_date >= NOW() - INTERVAL '2 days'"]
        params: dict[str, Any] = {}

        if inp.get("country"):
            conditions.append("s.country = :country")
            params["country"] = inp["country"].upper()
        if inp.get("sector"):
            conditions.append("s.sector ILIKE :sector")
            params["sector"] = f"%{inp['sector']}%"
        if inp.get("signal"):
            conditions.append("a.signal = :signal")
            params["signal"] = inp["signal"].upper()
        if inp.get("min_score") is not None:
            conditions.append("a.final_score >= :min_score")
            params["min_score"] = float(inp["min_score"])
        if inp.get("max_price") is not None:
            conditions.append("sp.close <= :max_price")
            params["max_price"] = float(inp["max_price"])

        limit = min(int(inp.get("limit", 10)), 25)
        where = " AND ".join(conditions)

        rows = await self.db.execute(text(f"""
            SELECT a.ticker, s.name, s.sector, s.country,
                   a.signal, a.final_score, a.signal_thesis,
                   sp.close AS price
            FROM ai_analysis a
            JOIN stocks s ON s.ticker = a.ticker
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices WHERE ticker = a.ticker ORDER BY time DESC LIMIT 1
            ) sp ON true
            WHERE {where}
            ORDER BY a.final_score DESC
            LIMIT :limit
        """), {**params, "limit": limit})

        items = [
            {
                "ticker": r.ticker, "name": r.name,
                "sector": r.sector, "country": r.country,
                "signal": r.signal, "score": r.final_score,
                "price": round(r.price, 2) if r.price else None,
                "thesis": (r.signal_thesis or "")[:120],
            }
            for r in rows.fetchall()
        ]
        result = {"count": len(items), "criteria": inp, "stocks": items}
        cites = [{"source": "AI Analysis Screener", "matches": len(items)}]
        return json.dumps(result), [], cites

    async def _tool_compare_stocks(self, inp: dict) -> tuple[str, list, list]:
        tickers = [t.upper() for t in (inp.get("tickers") or [])[:4]]
        days = int(inp.get("days", 30))
        if not tickers:
            return json.dumps({"error": "No tickers provided"}), [], []

        since = datetime.now(timezone.utc) - timedelta(days=days)
        comparisons = []
        perf_chart: list[dict] = []

        for ticker in tickers:
            row = await self.db.execute(text("""
                SELECT a.signal, a.final_score, a.fundamental_score, a.technical_score,
                       a.sentiment_score, s.name, s.sector, s.country,
                       sp_now.close AS price_now, sp_then.close AS price_then
                FROM ai_analysis a
                LEFT JOIN stocks s ON s.ticker = a.ticker
                LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker = a.ticker ORDER BY time DESC LIMIT 1) sp_now ON true
                LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker = a.ticker AND time <= :since ORDER BY time DESC LIMIT 1) sp_then ON true
                WHERE a.ticker = :ticker ORDER BY a.analysis_date DESC LIMIT 1
            """), {"ticker": ticker, "since": since})
            r = row.fetchone()
            if not r:
                continue
            change = ((r.price_now - r.price_then) / r.price_then * 100) if r.price_now and r.price_then else None
            comparisons.append({
                "ticker": ticker, "name": r.name, "sector": r.sector, "country": r.country,
                "signal": r.signal, "score": r.final_score,
                "fundamental_score": r.fundamental_score,
                "technical_score": r.technical_score,
                "sentiment_score": r.sentiment_score,
                "price": round(r.price_now, 2) if r.price_now else None,
                f"change_{days}d_pct": round(change, 2) if change is not None else None,
            })
            if change is not None:
                perf_chart.append({"label": ticker, "value": round(change, 2)})

        charts = [{
            "type": "bar",
            "title": f"{' vs '.join(tickers)} — {days}d Performance (%)",
            "data": perf_chart,
        }] if perf_chart else []
        cites = [{"source": "AI Analysis + Prices", "tickers": tickers}]
        return json.dumps({"comparison": comparisons}), charts, cites

    async def _tool_get_sector_analysis(self, inp: dict) -> tuple[str, list, list]:
        sector_filter = inp.get("sector")
        country_filter = inp.get("country")

        conditions = ["a.analysis_date >= NOW() - INTERVAL '2 days'"]
        params: dict = {}
        if sector_filter:
            conditions.append("s.sector ILIKE :sector")
            params["sector"] = f"%{sector_filter}%"
        if country_filter:
            conditions.append("s.country = :country")
            params["country"] = country_filter.upper()

        where = " AND ".join(conditions)
        rows = await self.db.execute(text(f"""
            SELECT s.sector, s.country,
                   COUNT(*) AS n,
                   AVG(a.final_score) AS avg_score,
                   SUM(CASE WHEN a.signal = 'BUY' THEN 1 ELSE 0 END) AS buys,
                   SUM(CASE WHEN a.signal = 'SELL' THEN 1 ELSE 0 END) AS sells,
                   AVG(sp.close_change_pct) AS avg_price_change
            FROM ai_analysis a
            JOIN stocks s ON s.ticker = a.ticker
            LEFT JOIN LATERAL (
                SELECT (close - LAG(close) OVER (PARTITION BY ticker ORDER BY time)) / NULLIF(LAG(close) OVER (PARTITION BY ticker ORDER BY time), 0) * 100 AS close_change_pct
                FROM stock_prices WHERE ticker = a.ticker ORDER BY time DESC LIMIT 1
            ) sp ON true
            WHERE {where}
            GROUP BY s.sector, s.country
            ORDER BY avg_score DESC
        """), params)

        sectors = [
            {
                "sector": r.sector, "country": r.country,
                "stock_count": r.n,
                "avg_score": round(r.avg_score, 1) if r.avg_score else None,
                "buy_signals": int(r.buys or 0),
                "sell_signals": int(r.sells or 0),
                "avg_price_change_pct": round(r.avg_price_change, 2) if r.avg_price_change else None,
            }
            for r in rows.fetchall()
        ]

        charts = [{
            "type": "bar",
            "title": "Sector Average AI Score",
            "data": [{"label": f"{s['sector']} ({s['country']})", "value": s["avg_score"]} for s in sectors if s["avg_score"]],
        }]
        cites = [{"source": "Sector Rotation Engine", "sectors": len(sectors)}]
        return json.dumps({"sectors": sectors}), charts, cites

    async def _tool_get_trade_recommendation(self, inp: dict) -> tuple[str, list, list]:
        ticker = inp.get("ticker", "").upper()
        row = await self.db.execute(text("""
            SELECT signal, final_score, entry_price, stop_loss, take_profit,
                   signal_thesis, atr_14, regime, analysis_date,
                   fundamental_score, technical_score, sentiment_score,
                   macro_score, risk_score
            FROM ai_analysis
            WHERE ticker = :ticker
            ORDER BY analysis_date DESC LIMIT 1
        """), {"ticker": ticker})
        r = row.fetchone()
        if not r:
            return json.dumps({"error": f"No AI analysis for {ticker}"}), [], []

        rr = None
        if r.entry_price and r.stop_loss and r.take_profit:
            risk = r.entry_price - r.stop_loss
            reward = r.take_profit - r.entry_price
            rr = round(reward / risk, 2) if risk > 0 else None

        result = {
            "ticker": ticker,
            "recommendation": r.signal,
            "confidence_score": r.final_score,
            "entry_price": round(r.entry_price, 2) if r.entry_price else None,
            "stop_loss": round(r.stop_loss, 2) if r.stop_loss else None,
            "take_profit": round(r.take_profit, 2) if r.take_profit else None,
            "risk_reward_ratio": rr,
            "atr_14": round(r.atr_14, 4) if r.atr_14 else None,
            "regime": r.regime,
            "thesis": r.signal_thesis,
            "as_of": str(r.analysis_date)[:10] if r.analysis_date else None,
            "score_breakdown": {
                "fundamental": r.fundamental_score,
                "technical": r.technical_score,
                "sentiment": r.sentiment_score,
                "macro": r.macro_score,
                "risk": r.risk_score,
            },
        }
        cites = [{"source": "AI Analysis Engine", "ticker": ticker, "signal": r.signal, "score": r.final_score}]
        return json.dumps(result), [], cites

    async def _tool_get_portfolio_risk(self, _: dict) -> tuple[str, list, list]:
        # Re-use the risk API logic
        try:
            from app.api.risk import _portfolio_risk_data
            data = await _portfolio_risk_data(self.db)
            cites = [{"source": "Portfolio Risk Engine"}]
            return json.dumps(data), [], cites
        except Exception:
            pass

        # Fallback: basic concentration
        rows = await self.db.execute(text("""
            SELECT pp.ticker, pp.shares,
                   s.sector, s.country,
                   sp.close AS price
            FROM portfolio_positions pp
            LEFT JOIN stocks s ON s.ticker = pp.ticker
            LEFT JOIN LATERAL (SELECT close FROM stock_prices WHERE ticker = pp.ticker ORDER BY time DESC LIMIT 1) sp ON true
            WHERE pp.is_open = TRUE
        """))
        positions = rows.fetchall()
        total = sum((p.price or 0) * p.shares for p in positions)
        holdings = [
            {"ticker": p.ticker, "weight_pct": round((p.price or 0) * p.shares / total * 100, 2) if total else 0}
            for p in positions
        ]
        holdings.sort(key=lambda x: x["weight_pct"], reverse=True)
        result = {
            "total_positions": len(positions),
            "top_holdings": holdings[:5],
            "note": "Full Sharpe/Beta calculation requires price history",
        }
        return json.dumps(result), [], [{"source": "Portfolio Positions"}]

    async def _tool_get_earnings_calendar(self, inp: dict) -> tuple[str, list, list]:
        ticker = inp.get("ticker")
        days_ahead = int(inp.get("days_ahead", 14))
        until = datetime.now(timezone.utc) + timedelta(days=days_ahead)

        if ticker:
            rows = await self.db.execute(text("""
                SELECT ticker, report_date, period, eps_estimate, eps_actual,
                       revenue_estimate, revenue_actual, surprise_pct
                FROM earnings_history
                WHERE ticker = :ticker AND report_date <= :until
                ORDER BY report_date DESC LIMIT 5
            """), {"ticker": ticker.upper(), "until": until})
        else:
            # Portfolio-wide
            rows = await self.db.execute(text("""
                SELECT eh.ticker, eh.report_date, eh.period,
                       eh.eps_estimate, eh.eps_actual, eh.surprise_pct,
                       s.name
                FROM earnings_history eh
                JOIN portfolio_positions pp ON pp.ticker = eh.ticker
                JOIN stocks s ON s.ticker = eh.ticker
                WHERE pp.is_open = TRUE AND eh.report_date BETWEEN NOW() AND :until
                ORDER BY eh.report_date ASC
            """), {"until": until})

        items = [
            {
                "ticker": r.ticker,
                "name": getattr(r, "name", None),
                "report_date": str(r.report_date)[:10] if r.report_date else None,
                "period": r.period,
                "eps_estimate": round(r.eps_estimate, 4) if r.eps_estimate else None,
                "eps_actual": round(r.eps_actual, 4) if r.eps_actual else None,
                "surprise_pct": round(r.surprise_pct, 2) if r.surprise_pct else None,
            }
            for r in rows.fetchall()
        ]
        cites = [{"source": "Earnings Calendar", "events": len(items)}]
        return json.dumps({"events": items, "days_ahead": days_ahead}), [], cites

    # ── Response helpers ───────────────────────────────────────────────────────

    async def _extract_inline_charts(self, text: str) -> list[dict]:
        """Parse CHART_REQUEST: TICKER Nd directives and fetch chart data."""
        import re
        charts = []
        for m in re.finditer(r"CHART_REQUEST:\s*(\S+)\s+(\d+)d", text):
            ticker, days = m.group(1).upper(), int(m.group(2))
            _, ticker_charts, _ = await self._tool_get_price_history({"ticker": ticker, "days": days})
            charts.extend(ticker_charts)
        return charts

    def _parse_follow_ups(self, text: str) -> tuple[list[str], str]:
        """Extract follow-up questions block from the answer text."""
        import re
        follow_ups = []
        marker = "**Follow-up questions:**"
        if marker in text:
            parts = text.split(marker, 1)
            clean = parts[0].rstrip()
            questions_block = parts[1].strip()
            for line in questions_block.splitlines():
                line = line.strip().lstrip("0123456789.-) •*").strip()
                if line and "?" in line:
                    follow_ups.append(line)
            return follow_ups[:3], clean
        # Fallback: look for numbered questions at end
        lines = text.splitlines()
        q_lines = [l.strip() for l in lines[-6:] if l.strip().endswith("?")]
        if q_lines:
            cut = text.rfind(q_lines[0])
            return q_lines[:3], text[:cut].rstrip()
        return [], text

    def _extract_actions(self, citations: list[dict], tools_used: list[str]) -> list[dict]:
        """Build trade action suggestions from citations."""
        actions = []
        for c in citations:
            if c.get("source") == "AI Analysis Engine" and c.get("ticker"):
                sig = c.get("signal", "")
                ticker = c["ticker"]
                if sig == "BUY":
                    actions.append({
                        "type": "BUY", "ticker": ticker,
                        "label": f"Buy {ticker}",
                        "endpoint": f"/api/v1/orders/submit/{ticker}",
                        "urgency": "NORMAL" if c.get("score", 0) < 80 else "HIGH",
                    })
                elif sig in ("SELL", "REDUCE"):
                    actions.append({
                        "type": sig, "ticker": ticker,
                        "label": f"{'Sell' if sig == 'SELL' else 'Reduce'} {ticker}",
                        "endpoint": f"/api/v1/orders/manual",
                        "urgency": "HIGH" if sig == "SELL" else "NORMAL",
                    })
        return actions
