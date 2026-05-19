import logging
from typing import List, Dict
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

class SwingScreener:
    """
    Proactively screens the entire 11,000+ stock universe in milliseconds
    using native PostgreSQL queries. Filters for stocks that have strong
    fundamental bedrock (growth, profitability) AND bullish technical structure.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def find_high_potential_setups(self, country: str = "US", limit: int = 10) -> List[Dict]:
        """
        Runs a heavy SQL join to find stocks in an active uptrend
        with solid recent financial performance.
        """
        # We need to find stocks where:
        # 1. Price is above the 50-day moving average
        # 2. 50-day moving average is above the 200-day moving average (Uptrend)
        # 3. Revenue > 0 and Net Income > 0 in latest earnings
        
        # To do this natively without running agents on 11k stocks:
        # We'll use a CTE to calculate moving averages for the last few days,
        # then join with company_financials.
        
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
        
        query = text(f"""
            WITH recent_prices AS (
                SELECT ticker, 
                       close, 
                       volume,
                       AVG(close) OVER(PARTITION BY ticker ORDER BY time ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) as sma_50,
                       AVG(close) OVER(PARTITION BY ticker ORDER BY time ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) as sma_200,
                       ROW_NUMBER() OVER(PARTITION BY ticker ORDER BY time DESC) as rn
                FROM stock_prices
                WHERE time >= :one_year_ago
            ),
            latest_prices AS (
                SELECT * FROM recent_prices WHERE rn = 1
            ),
            latest_financials AS (
                SELECT ticker, revenue, net_income, roe,
                       ROW_NUMBER() OVER(PARTITION BY ticker ORDER BY fiscal_date DESC) as rn
                FROM company_financials
            )
            SELECT s.ticker, s.name, s.sector,
                   p.close, p.sma_50, p.sma_200, p.volume,
                   f.revenue, f.net_income, f.roe
            FROM stocks s
            JOIN latest_prices p ON s.ticker = p.ticker
            JOIN latest_financials f ON s.ticker = f.ticker AND f.rn = 1
            WHERE s.country = :country
              -- Technical Filter: Uptrend (Price > 50 > 200)
              AND p.close > p.sma_50 
              AND p.sma_50 > p.sma_200
              -- Liquidity Filter
              AND p.close > 5.0
              AND p.volume > 500000
              -- Fundamental Filter: Profitable
              AND f.net_income > 0
              AND f.revenue > 0
            ORDER BY (p.close - p.sma_50)/p.sma_50 ASC -- closest to 50 SMA (pullback entry)
            LIMIT :limit
        """)
        
        try:
            result = await self.db.execute(query, {
                "country": country, 
                "limit": limit,
                "one_year_ago": one_year_ago
            })
            rows = result.fetchall()
            
            setups = []
            for r in rows:
                setups.append({
                    "ticker": r.ticker,
                    "name": r.name,
                    "close": r.close,
                    "sma_50": r.sma_50,
                    "sma_200": r.sma_200,
                    "revenue": r.revenue,
                    "net_income": r.net_income
                })
                
            logger.info(f"[SwingScreener] Found {len(setups)} proactive swing setups for {country}.")
            return setups
            
        except Exception as e:
            logger.error(f"[SwingScreener] Error executing screener: {e}")
            return []
