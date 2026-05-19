"""
Fetches analyst upgrades/downgrades from yfinance ticker.upgrades_downgrades.
Returns a DataFrame with: Firm, ToGrade, FromGrade, Action (up/down/init/reit)
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.market_data import AnalystRating

logger = logging.getLogger("omnitrader.analyst")

class AnalystRatingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch_for_ticker(self, ticker: str, days_back: int = 90) -> list[dict]:
        """
        Fetch analyst rating changes via yfinance ticker.upgrades_downgrades.
        The DataFrame has index=Date, columns=[Firm, ToGrade, FromGrade, Action].
        Action values: 'up' = upgrade, 'down' = downgrade, 'init' = initiation, 'reit' = reiteration

        Map Action to standard labels:
        - 'up' → 'upgrade'
        - 'down' → 'downgrade'
        - 'init' → 'init'
        - 'reit' → 'reiterate'

        Filter to last days_back days.
        Also fetch price_target from ticker.analyst_price_targets if available.

        Return list of dicts: {
            ticker, date, firm, action, from_grade, to_grade, price_target
        }
        """
        try:
            import yfinance as yf

            def _fetch():
                t = yf.Ticker(ticker)
                df = t.upgrades_downgrades
                if df is None or df.empty:
                    return []

                cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
                results = []

                # Reset index to get Date as column
                if df.index.name == 'GradeDate' or 'Date' in str(df.index.name):
                    df = df.reset_index()
                    date_col = df.columns[0]  # First column after reset is the date
                else:
                    df = df.reset_index()
                    date_col = 'GradeDate' if 'GradeDate' in df.columns else df.columns[0]

                for _, row in df.iterrows():
                    try:
                        date_val = row[date_col]
                        if hasattr(date_val, 'to_pydatetime'):
                            date_val = date_val.to_pydatetime()
                        if hasattr(date_val, 'replace') and date_val.tzinfo is None:
                            date_val = date_val.replace(tzinfo=timezone.utc)
                        if isinstance(date_val, datetime) and date_val < cutoff:
                            continue

                        action_raw = str(row.get("Action", "") or "").lower()
                        action_map = {'up': 'upgrade', 'down': 'downgrade',
                                     'init': 'init', 'reit': 'reiterate', 'main': 'reiterate'}
                        action = action_map.get(action_raw, action_raw)

                        results.append({
                            "ticker":       ticker,
                            "date":         date_val,
                            "firm":         str(row.get("Firm", "") or "")[:100],
                            "action":       action,
                            "from_grade":   str(row.get("FromGrade", "") or "")[:50],
                            "to_grade":     str(row.get("ToGrade", "") or "")[:50],
                            "price_target": None,
                        })
                    except Exception:
                        continue

                # Try to get price target from analyst_price_targets
                try:
                    pt = t.analyst_price_targets
                    if pt and hasattr(pt, 'get'):
                        mean_pt = pt.get('mean') or pt.get('Mean')
                        if mean_pt and results:
                            results[0]["price_target"] = float(mean_pt)
                except Exception:
                    pass

                return results

            return await asyncio.to_thread(_fetch)

        except Exception as e:
            logger.warning("[Analyst] Failed for %s: %s", ticker, e)
            return []

    async def upsert_ratings(self, ratings: list[dict]) -> int:
        if not ratings:
            return 0

        inserted = 0
        for r in ratings:
            existing = await self.db.execute(
                select(AnalystRating).where(
                    AnalystRating.ticker == r["ticker"],
                    AnalystRating.date == r["date"],
                    AnalystRating.firm == r["firm"],
                    AnalystRating.action == r["action"],
                ).limit(1)
            )
            if existing.scalars().first():
                continue

            row = AnalystRating(**r)
            self.db.add(row)
            inserted += 1

        if inserted:
            await self.db.commit()
        return inserted

    async def run_batch(self, tickers: list[str]) -> dict:
        processed = 0
        inserted  = 0
        errors    = 0

        for ticker in tickers:
            try:
                ratings = await self.fetch_for_ticker(ticker)
                n = await self.upsert_ratings(ratings)
                inserted  += n
                processed += 1
            except Exception as e:
                logger.error("[Analyst] Error for %s: %s", ticker, e)
                errors += 1
            await asyncio.sleep(0.2)

        return {"processed": processed, "inserted": inserted, "errors": errors}

    async def get_recent_for_ticker(self, ticker: str, days: int = 30) -> list[dict]:
        """Query DB for recent analyst ratings for one ticker."""
        from datetime import timedelta
        from sqlalchemy import text
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            select(AnalystRating)
            .where(AnalystRating.ticker == ticker, AnalystRating.date >= cutoff)
            .order_by(AnalystRating.date.desc())
            .limit(20)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id, "ticker": r.ticker, "date": r.date.isoformat() if r.date else None,
                "firm": r.firm, "action": r.action, "from_grade": r.from_grade,
                "to_grade": r.to_grade, "price_target": r.price_target,
            }
            for r in rows
        ]


class ShortInterestService:
    """Fetch short interest data from yfinance ticker.info fields."""

    @staticmethod
    async def fetch_for_ticker(ticker: str) -> dict:
        """
        Returns: {
            ticker, short_ratio, short_percent_float, shares_short,
            shares_float, shares_outstanding, days_to_cover
        }
        Uses yfinance ticker.info:
        - shortRatio: days to cover (= shares_short / avg_daily_volume)
        - shortPercentOfFloat: short % of float
        - sharesShort: raw short shares
        - floatShares: float shares
        - sharesOutstanding
        """
        try:
            import yfinance as yf

            def _fetch():
                info = yf.Ticker(ticker).info
                if not info:
                    return {}
                return {
                    "ticker":                ticker,
                    "short_ratio":           info.get("shortRatio"),
                    "short_percent_float":   info.get("shortPercentOfFloat"),
                    "shares_short":          info.get("sharesShort"),
                    "shares_float":          info.get("floatShares"),
                    "shares_outstanding":    info.get("sharesOutstanding"),
                    "days_to_cover":         info.get("shortRatio"),  # same as shortRatio
                    "avg_volume":            info.get("averageVolume"),
                    "forward_pe":            info.get("forwardPE"),
                    "peg_ratio":             info.get("pegRatio"),
                    "price_to_book":         info.get("priceToBook"),
                    "enterprise_to_ebitda":  info.get("enterpriseToEbitda"),
                }

            return await asyncio.to_thread(_fetch)

        except Exception as e:
            logging.getLogger("omnitrader.short").warning("ShortInterest failed for %s: %s", ticker, e)
            return {}
