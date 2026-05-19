"""
Earnings Calendar Service
=========================
Fetches upcoming earnings dates, historical earnings reactions, and scores
pre-earnings setups using yfinance data and AIAnalysis DB records.

All yfinance calls are wrapped in asyncio.to_thread() so they don't block
the event loop, and each ticker is individually guarded by try/except.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.market_data import AIAnalysis

logger = logging.getLogger(__name__)


class EarningsCalendarService:

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """Convert a value to float, returning None if conversion fails."""
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_earnings_date(raw) -> Optional[datetime]:
        """
        ticker.calendar['Earnings Date'] can be a list, Timestamp, or string.
        Returns a timezone-aware datetime or None.
        """
        if raw is None:
            return None
        if isinstance(raw, list):
            if not raw:
                return None
            raw = raw[0]
        if isinstance(raw, datetime):
            if raw.tzinfo is None:
                raw = raw.replace(tzinfo=timezone.utc)
            return raw
        if hasattr(raw, "to_pydatetime"):
            dt = raw.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        try:
            dt = pd.Timestamp(raw).to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    # ── Public methods ─────────────────────────────────────────────────────────

    async def get_upcoming_earnings(
        self, tickers: list[str], days_ahead: int = 30
    ) -> list[dict]:
        """
        For each ticker fetch the next earnings date via yfinance.
        Returns dicts sorted by days_until ascending, filtered to within
        days_ahead days from today.
        """
        now = datetime.now(tz=timezone.utc)
        cutoff = now + timedelta(days=days_ahead)

        async def _fetch_one(ticker: str) -> Optional[dict]:
            try:
                def _yf_work():
                    t = yf.Ticker(ticker)
                    calendar = t.calendar          # dict or None
                    info = t.info or {}
                    history = t.history(period="1y", auto_adjust=True)
                    try:
                        earnings_dates_df = t.earnings_dates
                    except Exception:
                        earnings_dates_df = None
                    return calendar, info, history, earnings_dates_df

                calendar, info, history, earnings_dates_df = await asyncio.to_thread(_yf_work)

                if not calendar:
                    return None

                raw_date = calendar.get("Earnings Date")
                earnings_dt = self._parse_earnings_date(raw_date)
                if earnings_dt is None:
                    return None

                if earnings_dt < now or earnings_dt > cutoff:
                    return None

                days_until = int((earnings_dt - now).total_seconds() / 86400)

                # ── Last 4 earnings reactions ──────────────────────────────────
                last_4_reactions: list[float] = []
                if (
                    earnings_dates_df is not None
                    and not earnings_dates_df.empty
                    and not history.empty
                ):
                    try:
                        history.index = pd.DatetimeIndex(history.index).tz_localize(
                            "UTC", ambiguous="infer"
                        ) if history.index.tzinfo is None else history.index.tz_convert("UTC")

                        past_dates = earnings_dates_df.index[
                            earnings_dates_df.index < now
                        ].sort_values(ascending=False)[:4]

                        for ed in past_dates:
                            ed_utc = pd.Timestamp(ed).tz_convert("UTC")
                            # find the trading day on/after ed and the day before
                            prices_after = history[history.index >= ed_utc]["Close"]
                            prices_before = history[history.index < ed_utc]["Close"]
                            if prices_after.empty or prices_before.empty:
                                continue
                            price_after = float(prices_after.iloc[0])
                            price_before = float(prices_before.iloc[-1])
                            if price_before != 0:
                                reaction = (price_after - price_before) / price_before * 100
                                last_4_reactions.append(round(reaction, 2))
                    except Exception as exc:
                        logger.debug("Reaction calc failed for %s: %s", ticker, exc)

                expected_move_pct: float = 0.0
                if last_4_reactions:
                    expected_move_pct = round(
                        sum(abs(r) for r in last_4_reactions) / len(last_4_reactions), 2
                    )

                # ── Beat rate ──────────────────────────────────────────────────
                beat_rate = 0.0
                if (
                    earnings_dates_df is not None
                    and not earnings_dates_df.empty
                ):
                    try:
                        past_df = earnings_dates_df[earnings_dates_df.index < now].head(4)
                        eps_est_col = next(
                            (c for c in past_df.columns if "estimate" in c.lower()), None
                        )
                        eps_act_col = next(
                            (c for c in past_df.columns if "actual" in c.lower() or "reported" in c.lower()), None
                        )
                        if eps_est_col and eps_act_col and not past_df.empty:
                            beats = (
                                past_df[eps_act_col].dropna()
                                > past_df[eps_est_col].dropna()
                            )
                            aligned = beats.dropna()
                            if len(aligned) > 0:
                                beat_rate = round(aligned.sum() / len(aligned), 2)
                    except Exception as exc:
                        logger.debug("Beat rate calc failed for %s: %s", ticker, exc)

                # ── EPS fields from info ───────────────────────────────────────
                consensus_estimate = self._safe_float(info.get("epsForward") or info.get("epsCurrentYear"))
                prior_eps = self._safe_float(info.get("trailingEps"))

                return {
                    "ticker": ticker,
                    "company_name": info.get("longName") or info.get("shortName") or ticker,
                    "earnings_date": earnings_dt.isoformat(),
                    "days_until": days_until,
                    "expected_move_pct": expected_move_pct,
                    "last_4_reactions": last_4_reactions,
                    "consensus_estimate": consensus_estimate,
                    "prior_eps": prior_eps,
                    "beat_rate": beat_rate,
                    "market_cap": self._safe_float(info.get("marketCap")),
                    "sector": info.get("sector"),
                    "country": info.get("country"),
                }

            except Exception as exc:
                logger.debug("Earnings fetch failed for %s: %s", ticker, exc)
                return None

        tasks = [_fetch_one(t) for t in tickers]
        results = await asyncio.gather(*tasks)
        upcoming = [r for r in results if r is not None]
        upcoming.sort(key=lambda x: x["days_until"])
        return upcoming

    async def get_ticker_earnings_history(self, ticker: str) -> dict:
        """
        Return the last 8 quarters of earnings data for one ticker, including
        EPS estimates, actuals, surprise %, and price reaction on earnings day.
        """
        def _yf_work():
            t = yf.Ticker(ticker)
            info = t.info or {}
            try:
                earnings_dates_df = t.earnings_dates
            except Exception:
                earnings_dates_df = None
            try:
                quarterly_earnings = t.quarterly_earnings
            except Exception:
                quarterly_earnings = None
            history = t.history(period="2y", auto_adjust=True)
            return info, earnings_dates_df, quarterly_earnings, history

        try:
            info, earnings_dates_df, quarterly_earnings, history = await asyncio.to_thread(_yf_work)
        except Exception as exc:
            logger.warning("get_ticker_earnings_history failed for %s: %s", ticker, exc)
            return {"ticker": ticker, "history": []}

        history_list: list[dict] = []

        try:
            if earnings_dates_df is not None and not earnings_dates_df.empty:
                # Ensure history has tz-aware index
                if not history.empty:
                    if history.index.tzinfo is None:
                        history.index = pd.DatetimeIndex(history.index).tz_localize("UTC")
                    else:
                        history.index = history.index.tz_convert("UTC")

                eps_est_col = next(
                    (c for c in earnings_dates_df.columns if "estimate" in c.lower()), None
                )
                eps_act_col = next(
                    (c for c in earnings_dates_df.columns
                     if "actual" in c.lower() or "reported" in c.lower()), None
                )
                surprise_col = next(
                    (c for c in earnings_dates_df.columns if "surprise" in c.lower()), None
                )

                past_df = earnings_dates_df[
                    earnings_dates_df.index < datetime.now(tz=timezone.utc)
                ].head(8)

                for ed, row in past_df.iterrows():
                    ed_utc = pd.Timestamp(ed).tz_convert("UTC")

                    eps_est = self._safe_float(row.get(eps_est_col) if eps_est_col else None)
                    eps_act = self._safe_float(row.get(eps_act_col) if eps_act_col else None)

                    surprise_pct: Optional[float] = None
                    if surprise_col:
                        surprise_pct = self._safe_float(row.get(surprise_col))
                    elif eps_est is not None and eps_act is not None and eps_est != 0:
                        surprise_pct = round((eps_act - eps_est) / abs(eps_est) * 100, 2)

                    price_day_before: Optional[float] = None
                    price_day_after: Optional[float] = None
                    reaction_pct: Optional[float] = None

                    if not history.empty:
                        prices_before = history[history.index < ed_utc]["Close"]
                        prices_after = history[history.index >= ed_utc]["Close"]
                        if not prices_before.empty:
                            price_day_before = round(float(prices_before.iloc[-1]), 4)
                        if not prices_after.empty:
                            price_day_after = round(float(prices_after.iloc[0]), 4)
                        if price_day_before and price_day_after and price_day_before != 0:
                            reaction_pct = round(
                                (price_day_after - price_day_before) / price_day_before * 100, 2
                            )

                    history_list.append({
                        "fiscal_date": ed_utc.date().isoformat(),
                        "eps_estimate": eps_est,
                        "eps_actual": eps_act,
                        "surprise_pct": surprise_pct,
                        "price_day_before": price_day_before,
                        "price_day_after": price_day_after,
                        "reaction_pct": reaction_pct,
                    })

        except Exception as exc:
            logger.warning("History parse failed for %s: %s", ticker, exc)

        return {"ticker": ticker, "history": history_list}

    async def score_pre_earnings_setup(self, ticker: str, db: AsyncSession) -> dict:
        """
        Score a pre-earnings opportunity from 0–100 using AI analysis data
        stored in the DB combined with live yfinance earnings metrics.
        """
        # ── Pull latest AIAnalysis from DB ─────────────────────────────────────
        stmt = (
            select(AIAnalysis)
            .where(AIAnalysis.ticker == ticker)
            .order_by(AIAnalysis.analysis_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        ai_row: Optional[AIAnalysis] = result.scalar_one_or_none()

        base_score: float = float(ai_row.final_score) if ai_row and ai_row.final_score is not None else 50.0
        technical_score: int = ai_row.technical_score if ai_row and ai_row.technical_score is not None else 0

        # ── Fetch earnings metrics via yfinance ────────────────────────────────
        def _yf_work():
            t = yf.Ticker(ticker)
            calendar = t.calendar or {}
            info = t.info or {}
            try:
                earnings_dates_df = t.earnings_dates
            except Exception:
                earnings_dates_df = None
            history = t.history(period="1y", auto_adjust=True)
            return calendar, info, earnings_dates_df, history

        try:
            calendar, info, earnings_dates_df, history = await asyncio.to_thread(_yf_work)
        except Exception as exc:
            logger.warning("score_pre_earnings_setup yf failed for %s: %s", ticker, exc)
            calendar, info, earnings_dates_df, history = {}, {}, None, pd.DataFrame()

        now = datetime.now(tz=timezone.utc)

        # ── Next earnings date ─────────────────────────────────────────────────
        earnings_dt = self._parse_earnings_date(calendar.get("Earnings Date") if calendar else None)
        days_until: int = -1
        earnings_date_str: Optional[str] = None
        if earnings_dt is not None and earnings_dt > now:
            days_until = int((earnings_dt - now).total_seconds() / 86400)
            earnings_date_str = earnings_dt.isoformat()

        # ── Last 4 reactions & beat rate ───────────────────────────────────────
        last_4_reactions: list[float] = []
        beat_rate: float = 0.0

        if earnings_dates_df is not None and not earnings_dates_df.empty:
            try:
                if not history.empty:
                    if history.index.tzinfo is None:
                        history.index = pd.DatetimeIndex(history.index).tz_localize("UTC")
                    else:
                        history.index = history.index.tz_convert("UTC")

                past_dates = earnings_dates_df.index[
                    earnings_dates_df.index < now
                ].sort_values(ascending=False)[:4]

                for ed in past_dates:
                    ed_utc = pd.Timestamp(ed).tz_convert("UTC")
                    prices_after = history[history.index >= ed_utc]["Close"]
                    prices_before = history[history.index < ed_utc]["Close"]
                    if prices_after.empty or prices_before.empty:
                        continue
                    price_after = float(prices_after.iloc[0])
                    price_before = float(prices_before.iloc[-1])
                    if price_before != 0:
                        last_4_reactions.append(
                            round((price_after - price_before) / price_before * 100, 2)
                        )

                # Beat rate
                eps_est_col = next(
                    (c for c in earnings_dates_df.columns if "estimate" in c.lower()), None
                )
                eps_act_col = next(
                    (c for c in earnings_dates_df.columns
                     if "actual" in c.lower() or "reported" in c.lower()), None
                )
                if eps_est_col and eps_act_col:
                    past_df = earnings_dates_df[earnings_dates_df.index < now].head(4)
                    beats = past_df[eps_act_col].dropna() > past_df[eps_est_col].dropna()
                    aligned = beats.dropna()
                    if len(aligned) > 0:
                        beat_rate = round(aligned.sum() / len(aligned), 2)

            except Exception as exc:
                logger.debug("Scoring calc error for %s: %s", ticker, exc)

        expected_move_pct: float = 0.0
        if last_4_reactions:
            expected_move_pct = round(
                sum(abs(r) for r in last_4_reactions) / len(last_4_reactions), 2
            )

        last_reaction: float = last_4_reactions[0] if last_4_reactions else 0.0

        # ── Scoring formula ────────────────────────────────────────────────────
        score = base_score
        score += beat_rate * 20
        score += min(expected_move_pct * 2, 15)
        if technical_score >= 70:
            score += 10
        if last_reaction < 0 and expected_move_pct < 3:
            score -= 20

        setup_score = max(0, min(100, round(score)))

        if setup_score >= 70:
            recommendation = "PLAY"
        elif setup_score <= 40:
            recommendation = "AVOID"
        else:
            recommendation = "NEUTRAL"

        return {
            "ticker": ticker,
            "setup_score": setup_score,
            "beat_rate": beat_rate,
            "expected_move_pct": expected_move_pct,
            "days_until": days_until,
            "earnings_date": earnings_date_str,
            "recommendation": recommendation,
        }
