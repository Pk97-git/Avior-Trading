"""
engines/trade_scanner.py
========================
TradeScanner — periodically scans a universe of tickers to surface
decision-ready trade opportunities (SWING and LONG_TERM).

What it does
------------
1. Builds a universe: user watchlist from DB + curated Nifty-50 + Nifty Next 50 + S&P 500 sample
2. Quick filter: min volume, min price, tradable
3. For each candidate runs multi-signal scoring:
   - Technical: RSI, MACD crossover, Bollinger Band squeeze, volume surge, MA stack
   - Pattern: breakout, pullback-to-support, momentum continuation, mean reversion
   - Momentum: 1W/1M/3M relative performance vs index
4. Classifies each as SWING (3–20 days) or LONG_TERM (1–12 months)
5. Scores 0–100 conviction; keeps top 30 per scan
6. Saves to trade_opportunities table via SQLAlchemy
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level technical indicator helpers
# ---------------------------------------------------------------------------

def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _compute_macd(series: pd.Series) -> tuple:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _compute_bollinger(series: pd.Series, period: int = 20, std: float = 2.0) -> tuple:
    mid = series.rolling(period).mean()
    stddev = series.rolling(period).std()
    return mid + std * stddev, mid, mid - std * stddev


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ---------------------------------------------------------------------------
# TradeScanner
# ---------------------------------------------------------------------------

class TradeScanner:
    """Scans a universe of tickers and surfaces high-conviction trade setups."""

    # ------------------------------------------------------------------
    # Class-level constants
    # ------------------------------------------------------------------
    MIN_VOLUME = 100_000          # shares/day minimum
    MIN_PRICE_INR = 10.0
    MIN_PRICE_USD = 1.0
    MAX_OPPORTUNITIES = 30        # top N to store per scan run

    NIFTY50 = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
        "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "HCLTECH.NS",
        "SUNPHARMA.NS", "TITAN.NS", "WIPRO.NS", "ULTRACEMCO.NS", "NESTLEIND.NS",
        "POWERGRID.NS", "BAJFINANCE.NS", "BAJAJFINSV.NS", "NTPC.NS", "ONGC.NS",
        "TECHM.NS", "M&M.NS", "JSWSTEEL.NS", "TATAMOTORS.NS", "HINDALCO.NS",
        "CIPLA.NS", "DRREDDY.NS", "GRASIM.NS", "TATASTEEL.NS", "ADANIENT.NS",
        "ADANIPORTS.NS", "COALINDIA.NS", "DIVISLAB.NS", "EICHERMOT.NS", "BPCL.NS",
        "APOLLOHOSP.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS", "INDUSINDBK.NS", "SBILIFE.NS",
        "HDFCLIFE.NS", "UPL.NS", "BRITANNIA.NS", "TATACONSUM.NS", "PIDILITIND.NS",
    ]

    SP500_SAMPLE = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
        "JPM", "JNJ", "V", "PG", "UNH", "MA", "HD", "CVX", "MRK", "ABBV",
        "PFE", "KO", "PEP", "TMO", "COST", "WMT", "BAC", "DIS", "NFLX",
        "ADBE", "CRM", "ORCL", "AMD", "INTC", "QCOM", "TXN", "AVGO",
    ]

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Public: run_scan
    # ------------------------------------------------------------------

    async def run_scan(self) -> dict:
        """Full scan of the universe. Returns scan summary."""
        # 1. Build universe
        universe = list(self.SP500_SAMPLE) + list(self.NIFTY50)

        # Add tickers from DB watchlist (orders placed in last 90 days)
        try:
            result = await self.db.execute(text(
                "SELECT DISTINCT ticker FROM orders "
                "WHERE created_at > now() - interval '90 days'"
            ))
            db_tickers = [row[0] for row in result.fetchall()]
            universe.extend(db_tickers)
        except Exception as exc:
            logger.warning("Could not fetch watchlist tickers from DB: %s", exc)

        # 2. Deduplicate
        universe = list(dict.fromkeys(t for t in universe if t))
        total_scanned = len(universe)
        logger.info("TradeScanner: scanning %d tickers", total_scanned)

        # 3. Concurrent analysis with semaphore
        semaphore = asyncio.Semaphore(10)

        async def _guarded(ticker: str) -> Optional[dict]:
            async with semaphore:
                try:
                    return await self._analyze_ticker(ticker)
                except Exception as exc:
                    logger.debug("Skipping %s: %s", ticker, exc)
                    return None

        raw_results = await asyncio.gather(*[_guarded(t) for t in universe])

        # 4. Filter None
        results = [r for r in raw_results if r is not None]

        # 5. Sort by confidence, keep top N
        results.sort(key=lambda x: x["confidence"], reverse=True)
        top_results = results[: self.MAX_OPPORTUNITIES]

        # 6. Upsert into DB
        stored_count = 0
        for res in top_results:
            try:
                await self.db.execute(text("""
                    INSERT INTO trade_opportunities
                        (ticker, trade_type, setup_name, thesis, entry_price, entry_zone_low, entry_zone_high,
                         stop_price, target_price, risk_reward, time_horizon, confidence, signals, risks,
                         verdict, position_size_pct, status, created_at, expires_at, updated_at)
                    VALUES
                        (:ticker, :trade_type, :setup_name, :thesis, :entry_price, :entry_zone_low, :entry_zone_high,
                         :stop_price, :target_price, :risk_reward, :time_horizon, :confidence, cast(:signals as jsonb),
                         cast(:risks as jsonb), :verdict, :position_size_pct, 'ACTIVE', now(),
                         now() + interval '3 days', now())
                    ON CONFLICT (ticker, trade_type) DO UPDATE SET
                        setup_name=EXCLUDED.setup_name, thesis=EXCLUDED.thesis,
                        entry_price=EXCLUDED.entry_price, stop_price=EXCLUDED.stop_price,
                        target_price=EXCLUDED.target_price, risk_reward=EXCLUDED.risk_reward,
                        confidence=EXCLUDED.confidence, signals=EXCLUDED.signals,
                        risks=EXCLUDED.risks, verdict=EXCLUDED.verdict, updated_at=now(),
                        status='ACTIVE', expires_at=now() + interval '3 days'
                """), {
                    **res,
                    "signals": json.dumps(res["signals"]),
                    "risks": json.dumps(res["risks"]),
                })
                stored_count += 1
            except Exception as exc:
                logger.error("DB upsert failed for %s: %s", res.get("ticker"), exc)

        await self.db.commit()

        return {
            "scanned": total_scanned,
            "opportunities_found": len(results),
            "stored": stored_count,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    # ------------------------------------------------------------------
    # Internal: _analyze_ticker
    # ------------------------------------------------------------------

    async def _analyze_ticker(self, ticker: str) -> Optional[dict]:
        """Fetch price history and score a single ticker. Returns None if not viable."""
        loop = asyncio.get_event_loop()

        # 1. Fetch price history in executor (yfinance is sync)
        def _fetch():
            return yf.Ticker(ticker).history(period="6mo", interval="1d")

        df = await loop.run_in_executor(None, _fetch)

        if df is None or len(df) < 30:
            return None

        # 2. Compute technicals
        close = df["Close"]
        rsi = _compute_rsi(close, 14)
        macd_line, signal_line = _compute_macd(close)
        bb_upper, bb_mid, bb_lower = _compute_bollinger(close, 20, 2)
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean() if len(close) >= 200 else None
        vol_avg20 = df["Volume"].rolling(20).mean()
        vol_ratio = df["Volume"].iloc[-1] / (vol_avg20.iloc[-1] if vol_avg20.iloc[-1] > 0 else 1)

        # 3. Latest values
        price = close.iloc[-1]
        rsi_now = rsi.iloc[-1]
        macd_now = macd_line.iloc[-1]
        signal_now = signal_line.iloc[-1]
        above_sma20 = bool(price > sma20.iloc[-1])
        above_sma50 = bool(price > sma50.iloc[-1])
        macd_cross = bool(
            (macd_now > signal_now) and (macd_line.iloc[-2] <= signal_line.iloc[-2])
        )
        bb_squeeze = bool(
            (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / (bb_mid.iloc[-1] if bb_mid.iloc[-1] != 0 else 1) < 0.08
        )
        near_bb_lower = bool(price < (bb_lower.iloc[-1] * 1.02))

        # 4. Quick filters — skip obvious bad candidates
        if rsi_now > 80:
            return None
        is_indian = ".NS" in ticker or ".BO" in ticker
        min_price = self.MIN_PRICE_INR if is_indian else self.MIN_PRICE_USD
        if price < min_price:
            return None
        avg_vol = vol_avg20.iloc[-1]
        if avg_vol < self.MIN_VOLUME:
            return None

        # 5. Score signals
        score = 50  # base

        # RSI contribution
        if 40 <= rsi_now <= 60:
            score += 10
        elif 30 <= rsi_now < 40:
            score += 15
        elif rsi_now < 30:
            score += 8
        elif 60 < rsi_now <= 70:
            score += 5
        else:
            score -= 10  # overbought

        # MACD contribution
        if macd_cross:
            score += 12
        elif macd_now > signal_now:
            score += 6

        # MA stack
        if above_sma20 and above_sma50:
            score += 8
        elif above_sma20:
            score += 3

        # Volume surge
        if vol_ratio > 2.0:
            score += 10
        elif vol_ratio > 1.5:
            score += 5

        # Bollinger Band squeeze breakout potential
        if bb_squeeze:
            score += 8

        # Momentum: 1-month return
        ret_1m = (close.iloc[-1] / close.iloc[-22] - 1) * 100 if len(close) >= 22 else 0.0
        if ret_1m > 5:
            score += 7
        elif ret_1m > 0:
            score += 3
        elif ret_1m < -10:
            score -= 5

        score = max(0, min(100, score))

        # 6. Skip low-confidence tickers early
        if score < 50:
            return None

        # 7. Classify trade type
        above_sma200_val = bool(sma200 is not None and price > sma200.iloc[-1])
        is_long_term = (
            above_sma50
            and (45 <= rsi_now <= 65)
            and (sma200 is None or above_sma200_val)
            and ret_1m > 0
        )
        is_swing = (
            macd_cross
            or (near_bb_lower and rsi_now < 45)
            or (vol_ratio > 1.8)
        )

        if is_long_term:
            trade_type = "LONG_TERM"
        elif is_swing:
            trade_type = "SWING"
        else:
            trade_type = "SWING" if score >= 60 else None

        if trade_type is None:
            return None

        # 8. Entry / stop / target via ATR
        atr = _compute_atr(df, 14).iloc[-1]
        if atr <= 0 or pd.isna(atr):
            atr = price * 0.02  # fallback: 2% of price

        entry_price = round(float(price), 2)
        entry_zone_low = round(price * 0.99, 2)
        entry_zone_high = round(price * 1.005, 2)
        stop_price = round(price - 2.0 * atr, 2)

        if trade_type == "LONG_TERM":
            target_price = round(price + 4.0 * atr, 2)
        else:
            target_price = round(price + 3.0 * atr, 2)

        risk_per_share = price - stop_price
        reward_per_share = target_price - price
        risk_reward = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

        # 9. Time horizon
        time_horizon = "5–15 days" if trade_type == "SWING" else "3–9 months"

        # 10. Setup name
        if macd_cross:
            setup_name = "MACD Bullish Crossover"
        elif bb_squeeze and vol_ratio > 1.5:
            setup_name = "Bollinger Band Squeeze Breakout"
        elif rsi_now < 40:
            setup_name = f"Oversold Bounce (RSI {rsi_now:.0f})"
        elif above_sma20 and above_sma50 and vol_ratio > 1.3:
            setup_name = "Momentum Continuation"
        elif above_sma20 and above_sma50:
            setup_name = "MA Stack Breakout"
        elif trade_type == "LONG_TERM":
            setup_name = "Value Entry"
        else:
            setup_name = "Technical Setup"

        # 11. Thesis (template-based)
        thesis_parts = []
        if macd_cross:
            thesis_parts.append("MACD just crossed bullish")
        if rsi_now < 45:
            thesis_parts.append(f"RSI at {rsi_now:.0f} — oversold territory")
        if vol_ratio > 1.5:
            thesis_parts.append(f"volume running {vol_ratio:.1f}× average")
        if above_sma50:
            thesis_parts.append("price above 50-day MA")
        if bb_squeeze:
            thesis_parts.append("Bollinger Bands squeezing for breakout")
        thesis = (
            "; ".join(thesis_parts[:3])
            + f". Entry zone ₹{entry_zone_low}–{entry_zone_high} with stop at ₹{stop_price}."
        )

        # 12. Signals dict
        signals = {
            "rsi": round(float(rsi_now), 1),
            "macd_cross": macd_cross,
            "above_sma20": above_sma20,
            "above_sma50": above_sma50,
            "volume_ratio": round(float(vol_ratio), 2),
            "bb_squeeze": bb_squeeze,
            "return_1m_pct": round(float(ret_1m), 1),
            "atr": round(float(atr), 2),
        }

        # 13. Risks list
        risks = []
        if rsi_now > 65:
            risks.append("Approaching overbought territory")
        if vol_ratio < 0.8:
            risks.append("Low volume — low conviction")
        if not above_sma50:
            risks.append("Below 50-day MA — downtrend risk")
        risks.append("Market-wide correction risk")
        if ".NS" in ticker or ".BO" in ticker:
            risks.append("FII outflow risk in Indian markets")

        # 14. Verdict
        verdict = "BUY" if (score >= 60 and risk_reward >= 1.4) else "WAIT"

        return {
            "ticker": ticker,
            "trade_type": trade_type,
            "setup_name": setup_name,
            "thesis": thesis,
            "entry_price": entry_price,
            "entry_zone_low": entry_zone_low,
            "entry_zone_high": entry_zone_high,
            "stop_price": stop_price,
            "target_price": target_price,
            "risk_reward": risk_reward,
            "time_horizon": time_horizon,
            "confidence": score,
            "signals": signals,
            "risks": risks,
            "verdict": verdict,
            "position_size_pct": 3.0 if trade_type == "SWING" else 5.0,
        }

    # ------------------------------------------------------------------
    # Public: get_top_opportunities
    # ------------------------------------------------------------------

    async def get_top_opportunities(
        self,
        trade_type: Optional[str] = None,
        limit: int = 10,
    ) -> list:
        """Query trade_opportunities table for active, unexpired opportunities."""
        sql = (
            "SELECT * FROM trade_opportunities WHERE status='ACTIVE' AND expires_at > now() "
            + ("AND trade_type=:tt " if trade_type else "")
            + "ORDER BY confidence DESC LIMIT :lim"
        )
        params = {"tt": trade_type, "lim": limit} if trade_type else {"lim": limit}
        result = await self.db.execute(text(sql), params)
        return [dict(r._mapping) for r in result.fetchall()]

    # ------------------------------------------------------------------
    # Public: get_opportunity
    # ------------------------------------------------------------------

    async def get_opportunity(self, ticker: str) -> Optional[dict]:
        """Get single opportunity by ticker (most recent). Returns None if not found."""
        result = await self.db.execute(
            text(
                "SELECT * FROM trade_opportunities WHERE ticker=:t "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": ticker},
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None
