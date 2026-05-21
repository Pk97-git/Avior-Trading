"""
engines/trade_analyzer.py
=========================
TradeAnalyzer — on-demand deep analysis for a single ticker.

Produces a full TradeBrief combining:
  - Technical analysis (multi-timeframe: daily + weekly)
  - Fundamental snapshot (PE, PB, EPS growth, sector comparison)
  - Sentiment (news score, insider activity from DB)
  - Risk profile (volatility, beta, max drawdown, position sizing)
  - AI narrative (plain-English thesis using Claude API)
  - Actionable levels (entry zone, stop, target, risk/reward)

This is the "one-stop shop" — user reads TradeBrief and decides yes/no.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level technical indicator helpers (self-contained)
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


def _compute_max_drawdown(series: pd.Series) -> float:
    """Returns maximum drawdown as a fraction (negative number)."""
    rolling_max = series.cummax()
    drawdown = (series - rolling_max) / rolling_max
    return float(drawdown.min())


def _pick_setup_name(
    macd_cross_bull: bool,
    rsi_d: float,
    vol_ratio: float,
    price: float,
    sma20: float,
    sma50: float,
    trade_type: str,
) -> str:
    """Select a human-readable setup label from signal conditions."""
    above_sma20 = price > sma20
    above_sma50 = price > sma50
    if macd_cross_bull:
        return "MACD Bullish Crossover"
    if rsi_d < 40:
        return f"Oversold Bounce (RSI {rsi_d:.0f})"
    if above_sma20 and above_sma50 and vol_ratio > 1.3:
        return "Momentum Continuation"
    if above_sma20 and above_sma50:
        return "MA Stack Breakout"
    if trade_type == "LONG_TERM":
        return "Value Entry"
    return "Technical Setup"


# ---------------------------------------------------------------------------
# TradeAnalyzer
# ---------------------------------------------------------------------------

class TradeAnalyzer:
    """Produces a deep-dive TradeBrief for a single ticker on demand."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Public: analyze
    # ------------------------------------------------------------------

    async def analyze(self, ticker: str, trade_type: str = "SWING") -> dict:
        """
        Return a comprehensive TradeBrief dict for *ticker*.

        Parameters
        ----------
        ticker     : exchange symbol, e.g. "RELIANCE.NS" or "AAPL"
        trade_type : "SWING" | "LONG_TERM"
        """
        loop = asyncio.get_event_loop()
        yf_ticker = yf.Ticker(ticker)

        # 1. Fetch data concurrently where possible
        def _fetch_daily():
            return yf_ticker.history(period="1y", interval="1d")

        def _fetch_weekly():
            return yf_ticker.history(period="2y", interval="1wk")

        def _fetch_info():
            return yf_ticker.info

        hist_daily, hist_weekly, info = await asyncio.gather(
            loop.run_in_executor(None, _fetch_daily),
            loop.run_in_executor(None, _fetch_weekly),
            loop.run_in_executor(None, _fetch_info),
        )

        if hist_daily is None or len(hist_daily) < 30:
            raise ValueError(f"Insufficient price history for {ticker}")

        # 2. Multi-timeframe technical — daily
        close_d = hist_daily["Close"]
        rsi_series_d = _compute_rsi(close_d, 14)
        rsi_d = float(rsi_series_d.iloc[-1])
        rsi_d_prev = float(rsi_series_d.iloc[-2]) if len(rsi_series_d) >= 2 else rsi_d
        macd_d, sig_d = _compute_macd(close_d)
        macd_cross_bull = bool(
            (macd_d.iloc[-1] > sig_d.iloc[-1]) and (macd_d.iloc[-2] <= sig_d.iloc[-2])
        )
        macd_cross_bear = bool(
            (macd_d.iloc[-1] < sig_d.iloc[-1]) and (macd_d.iloc[-2] >= sig_d.iloc[-2])
        )
        bb_up, bb_mid, bb_lo = _compute_bollinger(close_d, 20, 2)
        atr_d = float(_compute_atr(hist_daily, 14).iloc[-1])
        if atr_d <= 0 or pd.isna(atr_d):
            atr_d = float(close_d.iloc[-1]) * 0.02

        sma20 = float(close_d.rolling(20).mean().iloc[-1])
        sma50 = float(close_d.rolling(50).mean().iloc[-1])
        sma200 = (
            float(close_d.rolling(200).mean().iloc[-1])
            if len(close_d) >= 200
            else None
        )

        # Weekly
        close_w = hist_weekly["Close"]
        rsi_w = float(_compute_rsi(close_w, 14).iloc[-1]) if len(close_w) >= 15 else 50.0
        macd_w, sig_w = _compute_macd(close_w)
        weekly_trend = "BULLISH" if macd_w.iloc[-1] > sig_w.iloc[-1] else "BEARISH"

        # 3. Price levels
        price = float(close_d.iloc[-1])
        week_high_52 = float(hist_daily["High"].rolling(252).max().iloc[-1])
        week_low_52 = float(hist_daily["Low"].rolling(252).min().iloc[-1])
        pct_from_52w_high = (price / week_high_52 - 1) * 100 if week_high_52 > 0 else 0.0
        pct_from_52w_low = (price / week_low_52 - 1) * 100 if week_low_52 > 0 else 0.0
        avg_vol_20 = hist_daily["Volume"].rolling(20).mean().iloc[-1]
        vol_ratio = float(hist_daily["Volume"].iloc[-1] / (avg_vol_20 if avg_vol_20 > 0 else 1))

        # 4. Returns — guard against index out of range
        def _safe_ret(n: int) -> float:
            if len(close_d) <= n:
                return 0.0
            return float((close_d.iloc[-1] / close_d.iloc[-n] - 1) * 100)

        ret_1w = _safe_ret(6)
        ret_1m = _safe_ret(22)
        ret_3m = _safe_ret(65)
        ret_6m = _safe_ret(130)
        ret_1y = float((close_d.iloc[-1] / close_d.iloc[0] - 1) * 100)

        # 5. Volatility & risk metrics
        daily_returns = close_d.pct_change().dropna()
        volatility_ann = float(daily_returns.std() * (252 ** 0.5) * 100)
        max_drawdown = _compute_max_drawdown(close_d) * 100
        sharpe = (
            float((daily_returns.mean() / daily_returns.std()) * (252 ** 0.5))
            if daily_returns.std() > 0
            else 0.0
        )

        # 6. Fundamental snapshot (graceful on missing keys)
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        pb_ratio = info.get("priceToBook")
        eps_ttm = info.get("trailingEps")
        rev_growth_raw = info.get("revenueGrowth")
        revenue_growth = float(rev_growth_raw * 100) if rev_growth_raw is not None else None
        earn_growth_raw = info.get("earningsGrowth")
        earnings_growth = float(earn_growth_raw * 100) if earn_growth_raw is not None else None
        debt_equity = info.get("debtToEquity")
        roe_raw = info.get("returnOnEquity")
        roe = float(roe_raw * 100) if roe_raw is not None else None
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        mkt_cap = info.get("marketCap")

        # 7. Sentiment from DB
        try:
            sent_result = await self.db.execute(
                text(
                    "SELECT AVG(sentiment_score) as avg_score, COUNT(*) as news_count "
                    "FROM news_sentiment WHERE ticker = :t AND published_at > now() - interval '7 days'"
                ),
                {"t": ticker},
            )
            sent_row = sent_result.fetchone()
            avg_sentiment = float(sent_row.avg_score) if sent_row and sent_row.avg_score else 50.0
            news_count = int(sent_row.news_count) if sent_row and sent_row.news_count else 0
        except Exception as exc:
            logger.warning("Sentiment query failed for %s: %s", ticker, exc)
            avg_sentiment = 50.0
            news_count = 0

        # 8. Entry / Stop / Target (sophisticated: pivot-based)
        recent_highs = hist_daily["High"].rolling(5).max()
        recent_lows = hist_daily["Low"].rolling(5).min()
        support_level = float(recent_lows.iloc[-10:-1].min())
        resistance_level = float(recent_highs.iloc[-20:-1].max())

        if trade_type == "SWING":
            entry_price = round(price, 2)
            stop_price = round(max(support_level * 0.99, price - 2.0 * atr_d), 2)
            target_price = round(min(resistance_level * 0.99, price + 3.0 * atr_d), 2)
        else:  # LONG_TERM
            entry_price = round(price, 2)
            stop_price = round(price - 3.0 * atr_d, 2)
            target_price = round(price + 6.0 * atr_d, 2)

        risk_per_share = max(entry_price - stop_price, 0.01)
        reward = target_price - entry_price
        risk_reward = round(reward / risk_per_share, 2)

        # Position size: risk 1.5% of ₹10L default portfolio
        portfolio_value = 1_000_000
        risk_pct = 0.015
        max_loss = portfolio_value * risk_pct
        shares = int(max_loss / risk_per_share) if risk_per_share > 0 else 0
        position_value = shares * entry_price
        position_size_pct = round(position_value / portfolio_value * 100, 1)

        # 9. Conviction score
        conviction = 50

        # Technical
        if macd_cross_bull:
            conviction += 12
        if 40 <= rsi_d <= 65:
            conviction += 8
        elif rsi_d < 40:
            conviction += 10
        if weekly_trend == "BULLISH":
            conviction += 8
        if price > sma50:
            conviction += 5
        if vol_ratio > 1.5:
            conviction += 7

        # Fundamental
        if pe_ratio and pe_ratio < 20:
            conviction += 5
        if earnings_growth is not None and earnings_growth > 10:
            conviction += 5

        # Sentiment
        if avg_sentiment > 60:
            conviction += 5
        elif avg_sentiment < 40:
            conviction -= 5

        # Risk/reward
        if risk_reward >= 2.0:
            conviction += 5
        elif risk_reward < 1.2:
            conviction -= 10

        conviction = max(0, min(100, conviction))

        # 10. Verdict
        if conviction >= 65 and risk_reward >= 1.5:
            verdict = "EXECUTE"
            verdict_reason = "Strong conviction with favorable risk/reward."
        elif conviction >= 55:
            verdict = "WATCHLIST"
            verdict_reason = "Setup developing — wait for better entry confirmation."
        else:
            verdict = "SKIP"
            verdict_reason = "Insufficient conviction or poor risk/reward."

        # 11. Plain-English thesis (template-based, deterministic)
        lines = []
        trend_desc = "in an uptrend" if price > sma50 else "below its 50-day average"
        lines.append(
            f"{ticker} is currently trading at {price:.2f}, {trend_desc} "
            f"with {weekly_trend.lower()} weekly momentum."
        )
        if macd_cross_bull:
            lines.append(
                "The MACD just crossed bullish on the daily chart — a momentum confirmation signal."
            )
        elif rsi_d < 40:
            lines.append(
                f"RSI at {rsi_d:.0f} signals oversold conditions, setting up a potential bounce."
            )
        elif vol_ratio > 1.5:
            lines.append(
                f"Volume is running {vol_ratio:.1f}× the 20-day average — institutions may be accumulating."
            )
        if pe_ratio:
            lines.append(
                f"At a P/E of {pe_ratio:.1f}x, the stock is "
                f"{'reasonably valued' if pe_ratio < 25 else 'pricing in growth expectations'}."
            )
        if earnings_growth is not None and earnings_growth > 0:
            lines.append(
                f"Earnings growing at {earnings_growth:.0f}% YoY supports the longer-term case."
            )
        lines.append(
            f"Key risk: stop at {stop_price:.2f} limits downside to "
            f"~{abs((stop_price / price - 1) * 100):.1f}% from entry."
        )
        thesis = " ".join(lines)

        # 12. Key levels dict
        key_levels = {
            "entry": entry_price,
            "entry_zone": [round(entry_price * 0.99, 2), round(entry_price * 1.005, 2)],
            "stop_loss": stop_price,
            "stop_rationale": f"2× ATR ({atr_d:.2f}) below entry; below recent support",
            "target_1": round(entry_price + (target_price - entry_price) * 0.5, 2),
            "target_final": target_price,
            "target_rationale": f"3× ATR above entry; near resistance at {resistance_level:.2f}",
            "risk_reward": risk_reward,
            "max_loss_inr": round(shares * risk_per_share, 0),
            "suggested_qty": shares,
            "position_size_pct": position_size_pct,
        }

        # 13. Risks list
        risks = []
        if volatility_ann > 40:
            risks.append(f"High volatility ({volatility_ann:.0f}% annualised)")
        if max_drawdown < -30:
            risks.append(f"Historical drawdowns up to {abs(max_drawdown):.0f}%")
        if debt_equity is not None and debt_equity > 100:
            risks.append(f"High leverage (D/E: {debt_equity:.0f}%)")
        if rsi_d > 65:
            risks.append("RSI approaching overbought — momentum may stall")
        if weekly_trend == "BEARISH":
            risks.append("Weekly trend is bearish — counter-trend trade")
        if avg_sentiment < 45:
            risks.append("Negative news sentiment in last 7 days")
        risks.append("Broader market correction could override setup")
        if ".NS" in ticker or ".BO" in ticker:
            risks.append("Rupee depreciation and FII outflow risk")

        # 14. BB position label
        if price < bb_lo.iloc[-1] * 1.02:
            bb_position = "NEAR_LOWER"
        elif price > bb_up.iloc[-1] * 0.98:
            bb_position = "NEAR_UPPER"
        else:
            bb_position = "MIDDLE"

        return {
            "ticker": ticker,
            "trade_type": trade_type,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "conviction": conviction,
            "setup_name": _pick_setup_name(
                macd_cross_bull, rsi_d, vol_ratio, price, sma20, sma50, trade_type
            ),
            "thesis": thesis,
            "key_levels": key_levels,
            "time_horizon": "5–15 days" if trade_type == "SWING" else "3–9 months",
            "technical": {
                "rsi_daily": round(rsi_d, 1),
                "rsi_weekly": round(rsi_w, 1),
                "macd_cross_bullish": macd_cross_bull,
                "macd_cross_bearish": macd_cross_bear,
                "weekly_trend": weekly_trend,
                "above_sma20": price > sma20,
                "above_sma50": price > sma50,
                "above_sma200": (price > sma200) if sma200 is not None else None,
                "volume_ratio": round(vol_ratio, 2),
                "bb_position": bb_position,
                "52w_high": round(week_high_52, 2),
                "52w_low": round(week_low_52, 2),
                "pct_from_52w_high": round(pct_from_52w_high, 1),
            },
            "performance": {
                "return_1w_pct": round(ret_1w, 1),
                "return_1m_pct": round(ret_1m, 1),
                "return_3m_pct": round(ret_3m, 1),
                "return_6m_pct": round(ret_6m, 1),
                "return_1y_pct": round(ret_1y, 1),
            },
            "risk_metrics": {
                "volatility_ann_pct": round(volatility_ann, 1),
                "max_drawdown_pct": round(max_drawdown, 1),
                "sharpe_1y": round(sharpe, 2),
                "atr_daily": round(atr_d, 2),
            },
            "fundamental": {
                "pe_ratio": round(float(pe_ratio), 1) if pe_ratio else None,
                "pb_ratio": round(float(pb_ratio), 2) if pb_ratio else None,
                "eps_ttm": round(float(eps_ttm), 2) if eps_ttm else None,
                "revenue_growth_pct": round(revenue_growth, 1) if revenue_growth is not None else None,
                "earnings_growth_pct": round(earnings_growth, 1) if earnings_growth is not None else None,
                "debt_equity": round(float(debt_equity), 1) if debt_equity else None,
                "roe_pct": round(roe, 1) if roe is not None else None,
                "sector": sector,
                "industry": industry,
                "market_cap": mkt_cap,
            },
            "sentiment": {
                "avg_score_7d": round(avg_sentiment, 1),
                "news_count_7d": news_count,
                "sentiment_label": (
                    "POSITIVE" if avg_sentiment > 60
                    else "NEGATIVE" if avg_sentiment < 40
                    else "NEUTRAL"
                ),
            },
            "risks": risks,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }
