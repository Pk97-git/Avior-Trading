import asyncio
from app.db.session import engine
from app.db.base import Base
from app.models.market_data import Stock, StockPrice, CompanyFinancials, MacroEconomicData, MarketSnapshot

async def init_models():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created.")

if __name__ == "__main__":
    asyncio.run(init_models())
