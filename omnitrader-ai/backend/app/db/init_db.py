import asyncio
from app.db.session import engine
from app.db.base import Base

# Import ALL models so Base.metadata knows about every table
from app.models.market_data import (
    Stock, StockPrice, CompanyFinancials, MacroEconomicData, MarketSnapshot,
    NewsSentiment, InstitutionalFlow, PromoterHolding, RegimeLabel,
    ChartSnapshot, AIAnalysis, Alert, Watchlist, PortfolioPosition, Order,
    InsiderTransaction, AnalystRating,
)

# New columns added to existing tables — applied as safe ALTER TABLE migrations
_MIGRATIONS = [
    # AIAnalysis Phase 2+3 columns (added after initial schema)
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS factor_scores JSONB",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS cross_asset_sensitivity JSONB",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS calibrated_prob FLOAT",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS kelly_fraction FLOAT",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS max_position_pct FLOAT",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS analogs JSONB",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS entry_price FLOAT",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS stop_loss FLOAT",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS take_profit FLOAT",
    "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS atr_14 FLOAT",
    # Order table: portfolio_position_id added after initial orders schema
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS portfolio_position_id INTEGER",
    # Insider transactions and analyst ratings new columns
    "ALTER TABLE insider_transactions ADD COLUMN IF NOT EXISTS form_type VARCHAR",
    "ALTER TABLE analyst_ratings ADD COLUMN IF NOT EXISTS price_target FLOAT",
]


async def run_migrations():
    """Apply schema migrations for new columns on existing tables."""
    async with engine.begin() as conn:
        for sql in _MIGRATIONS:
            try:
                await conn.execute(__import__('sqlalchemy').text(sql))
            except Exception as e:
                print(f"  [Migration] {sql[:60]}... → {e}")
    print("Migrations applied.")


async def init_models(drop_first: bool = False):
    """Create all tables. Pass drop_first=True only for a full reset."""
    async with engine.begin() as conn:
        if drop_first:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations()
    print("Database tables created/verified.")


if __name__ == "__main__":
    asyncio.run(init_models())
