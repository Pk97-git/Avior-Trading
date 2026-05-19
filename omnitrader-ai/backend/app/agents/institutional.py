from typing import Optional, List, Dict, Tuple
"""
agents/institutional.py
=======================
InstitutionalAgent — tracks smart-money behaviour for a ticker.

India tickers (.NS / .BO):
  • FII 30-day net flow trend (institutional_flows, entity_type='FII', market='INDIA')
  • Promoter holding change from previous quarter (promoter_holdings)

US tickers:
  • Volume anomaly: vol_ratio from stock_technicals (pre-computed)

Scoring rubric (starts at 50):
  Strong FII net buying (> +500 Cr aggregate)  → +20
  Moderate FII buying                          → +10
  FII net selling                              → −15
  Promoter holding increased                   → +15
  Promoter holding decreased                   → −10
  Volume spike > 2× 90d avg (US)              → +10
  Volume drought < 0.5× 90d avg               → −5
"""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class InstitutionalAgent:
    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker

    def _is_india(self) -> bool:
        return ".NS" in self.ticker or ".BO" in self.ticker

    async def _fii_net_30d(self) -> Optional[float]:
        """Sum of FII net_value over the last 30 trading days (India only)."""
        since = datetime.now(timezone.utc) - timedelta(days=35)
        query = text("""
            SELECT COALESCE(SUM(net_value), 0) AS total_net
            FROM institutional_flows
            WHERE entity_type = 'FII'
              AND market = 'INDIA'
              AND date >= :since
        """)
        result = await self.db.execute(query, {"since": since})
        row = result.fetchone()
        return row.total_net if row else None

    async def _promoter_delta(self) -> Optional[float]:
        """
        Change in promoter holding % from previous quarter to latest (India only).
        Returns None if < 2 quarters of data.
        """
        query = text("""
            SELECT promoter_pct, quarter_end
            FROM promoter_holdings
            WHERE ticker = :ticker
            ORDER BY quarter_end DESC
            LIMIT 2
        """)
        result = await self.db.execute(query, {"ticker": self.ticker})
        rows = result.fetchall()
        if len(rows) < 2:
            return None
        return rows[0].promoter_pct - rows[1].promoter_pct

    async def _volume_anomaly(self) -> Optional[float]:
        """Volume ratio vs 20-day avg (pre-computed in stock_technicals)."""
        result = await self.db.execute(text("""
            SELECT vol_ratio FROM stock_technicals
            WHERE ticker = :ticker AND vol_ratio IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """), {"ticker": self.ticker})
        row = result.fetchone()
        return row.vol_ratio if row else None

    async def _short_interest(self) -> dict | None:
        """Latest short interest from short_interest table (US equities)."""
        result = await self.db.execute(text("""
            SELECT short_ratio, short_pct_float, date
            FROM short_interest
            WHERE ticker = :ticker
            ORDER BY date DESC LIMIT 1
        """), {"ticker": self.ticker})
        row = result.fetchone()
        if not row:
            return None
        return {
            "short_ratio":     row.short_ratio,
            "short_pct_float": row.short_pct_float,
        }

    async def _fo_ban_check(self) -> bool:
        """Returns True if this India stock is currently in F&O ban period."""
        result = await self.db.execute(text("""
            SELECT is_fo_banned FROM stocks WHERE ticker = :t
        """), {"t": self.ticker})
        row = result.fetchone()
        return bool(row and row.is_fo_banned)

    async def _insider_signal(self) -> Optional[dict]:
        """
        Recent insider transactions from Form 4 filings (last 90 days).
        Returns dict with purchase_count, sale_count, net_value, or None if no data.
        """
        result = await self.db.execute(text("""
            SELECT transaction_type,
                   COUNT(*) AS cnt,
                   COALESCE(SUM(total_value), 0) AS total_val
            FROM insider_transactions
            WHERE ticker = :ticker
              AND filed_date >= NOW() - INTERVAL '90 days'
            GROUP BY transaction_type
        """), {"ticker": self.ticker})
        rows = result.fetchall()
        if not rows:
            return None
        data = {r.transaction_type: {"count": r.cnt, "value": float(r.total_val)} for r in rows}
        return data

    async def _analyst_signal(self) -> Optional[dict]:
        """
        Recent analyst rating changes (last 30 days).
        Returns dict with upgrade_count, downgrade_count, or None if no data.
        """
        result = await self.db.execute(text("""
            SELECT action, COUNT(*) AS cnt
            FROM analyst_ratings
            WHERE ticker = :ticker
              AND date >= NOW() - INTERVAL '30 days'
            GROUP BY action
        """), {"ticker": self.ticker})
        rows = result.fetchall()
        if not rows:
            return None
        return {r.action: r.cnt for r in rows}

    async def analyze(self) -> dict:
        """
        Returns:
            {"score": int, "thesis": list[str]}
        """
        score  = 50
        thesis = []

        if self._is_india():
            # ── FII net flow ──────────────────────────────────────────────────
            try:
                fii_net = await self._fii_net_30d()
                if fii_net is not None:
                    if fii_net > 5000:
                        score += 20
                        thesis.append(f"FIIs strong net buyers (+₹{fii_net:,.0f} Cr in last 30 days).")
                    elif fii_net > 500:
                        score += 10
                        thesis.append(f"FIIs net buyers (+₹{fii_net:,.0f} Cr) — positive flow.")
                    elif fii_net < -500:
                        score -= 15
                        thesis.append(f"FIIs net sellers (₹{fii_net:,.0f} Cr) — institutional exit signal.")
                    else:
                        thesis.append(f"FII flows neutral (₹{fii_net:,.0f} Cr).")
            except Exception as e:
                logger.warning("FII flow fetch for %s: %s", self.ticker, e)
                thesis.append("FII flow data unavailable.")

            # ── Promoter holdings ─────────────────────────────────────────────
            try:
                delta = await self._promoter_delta()
                if delta is not None:
                    if delta > 0.5:
                        score += 15
                        thesis.append(f"Promoter holding increased by {delta:.1f}% — strong insider confidence.")
                    elif delta < -0.5:
                        score -= 10
                        thesis.append(f"Promoter holding decreased by {abs(delta):.1f}% — insider selling.")
                    else:
                        thesis.append(f"Promoter holding stable (Δ{delta:+.1f}%).")
                else:
                    thesis.append("Insufficient promoter holding history.")
            except Exception as e:
                logger.warning("Promoter delta fetch for %s: %s", self.ticker, e)
                thesis.append("Promoter holding data unavailable.")

            # ── F&O Ban ───────────────────────────────────────────────────────
            try:
                if await self._fo_ban_check():
                    score -= 8
                    thesis.append("Stock in F&O ban period — new derivative positions restricted; liquidity impacted.")
            except Exception as e:
                logger.warning("F&O ban check for %s: %s", self.ticker, e)

        else:
            # ── US: volume anomaly ────────────────────────────────────────────
            try:
                vol_ratio = await self._volume_anomaly()
                if vol_ratio is not None:
                    if vol_ratio > 2.0:
                        score += 10
                        thesis.append(f"Volume spike: {vol_ratio:.1f}× 90-day average — institutional interest.")
                    elif vol_ratio > 1.3:
                        score += 5
                        thesis.append(f"Above-average volume ({vol_ratio:.1f}×) — mild accumulation signal.")
                    elif vol_ratio < 0.5:
                        score -= 5
                        thesis.append(f"Volume drought ({vol_ratio:.1f}×) — lack of conviction.")
                    else:
                        thesis.append(f"Normal volume ({vol_ratio:.1f}× 90d avg).")
                else:
                    thesis.append("Insufficient volume history for anomaly detection.")
            except Exception as e:
                logger.warning("Volume anomaly fetch for %s: %s", self.ticker, e)
                thesis.append("Volume data unavailable.")

            # ── Short Interest ────────────────────────────────────────────────
            try:
                si = await self._short_interest()
                if si:
                    pct = si.get("short_pct_float") or 0
                    days = si.get("short_ratio") or 0
                    if pct > 0.20:
                        score -= 12
                        thesis.append(f"High short interest: {pct*100:.1f}% of float — heavy bearish bet or squeeze risk.")
                    elif pct > 0.10:
                        score -= 5
                        thesis.append(f"Elevated short interest: {pct*100:.1f}% of float — notable bearish positioning.")
                    elif pct < 0.02 and pct > 0:
                        score += 5
                        thesis.append(f"Very low short interest: {pct*100:.1f}% — market not betting against this stock.")
                    if days > 10:
                        thesis.append(f"Short squeeze risk: {days:.1f} days to cover.")
            except Exception as e:
                logger.warning("Short interest fetch for %s: %s", self.ticker, e)

        # ── Insider transactions (both markets) ────────────────────────────────
        try:
            insider = await self._insider_signal()
            if insider:
                purchases = insider.get("P", {})
                sales     = insider.get("S", {})
                p_count   = purchases.get("count", 0)
                s_count   = sales.get("count", 0)
                p_val     = purchases.get("value", 0)

                if p_count >= 3:
                    score += 12
                    thesis.append(f"Cluster insider buying: {p_count} purchases in last 90 days — strong insider conviction.")
                elif p_count >= 1 and p_val > 100_000:
                    score += 6
                    thesis.append(f"Insider purchase >${p_val/1e6:.1f}M in last 90 days — positive signal.")
                elif s_count >= 3 and p_count == 0:
                    score -= 8
                    thesis.append(f"Insider selling: {s_count} sales in last 90 days — watch for distribution.")
        except Exception as e:
            logger.warning("Insider signal fetch for %s: %s", self.ticker, e)

        # ── Analyst ratings (both markets) ────────────────────────────────────
        try:
            analyst = await self._analyst_signal()
            if analyst:
                upgrades   = analyst.get("upgrade", 0)
                downgrades = analyst.get("downgrade", 0)
                inits      = analyst.get("init", 0)

                if upgrades >= 2:
                    score += 8
                    thesis.append(f"{upgrades} analyst upgrade(s) in last 30 days — bullish catalyst.")
                elif upgrades >= 1:
                    score += 4
                    thesis.append(f"Analyst upgrade in last 30 days.")
                if inits >= 1 and upgrades == 0:
                    score += 3
                    thesis.append(f"{inits} new analyst coverage initiation(s) — growing institutional attention.")
                if downgrades >= 2:
                    score -= 8
                    thesis.append(f"{downgrades} analyst downgrade(s) in last 30 days — bearish signal.")
                elif downgrades >= 1:
                    score -= 4
                    thesis.append(f"Analyst downgrade in last 30 days.")
        except Exception as e:
            logger.warning("Analyst signal fetch for %s: %s", self.ticker, e)

        score = max(0, min(100, score))
        logger.info("InstitutionalAgent %s: score=%d", self.ticker, score)
        return {"score": score, "thesis": thesis}
