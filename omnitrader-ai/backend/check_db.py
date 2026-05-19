import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    try:
        async with engine.connect() as conn:
            print("\n--- STOCKS UNIVERSE ---")
            res = await conn.execute(text("SELECT COUNT(*) as total FROM stocks;"))
            row = res.fetchone()
            print(f"Total Stocks Tracked: {row.total}")

            print("\n--- PRICE DATA ---")
            res = await conn.execute(text("SELECT COUNT(DISTINCT ticker) as distinct_tickers, COUNT(*) as total_rows FROM stock_prices;"))
            row = res.fetchone()
            print(f"Stocks with Historical Price Data: {row.distinct_tickers}")
            print(f"Total Historical Price Rows: {row.total_rows}")

            print("\n--- FUNDAMENTALS DATA ---")
            res = await conn.execute(text("SELECT COUNT(DISTINCT ticker) as distinct_tickers, COUNT(*) as total_rows FROM company_financials;"))
            row = res.fetchone()
            print(f"Stocks with Financial Statements: {row.distinct_tickers}")
            print(f"Total Financial Statement Rows: {row.total_rows}")

            print("\n--- INGESTION QUEUE PENDING & RUNNING ---")
            res = await conn.execute(text("SELECT source, status, COUNT(*) as task_count FROM ingestion_tasks WHERE status IN ('PENDING', 'RUNNING') GROUP BY source, status;"))
            rows = res.fetchall()
            if not rows:
                print("Queue is empty. All scheduled data is fully ingested!")
            for r in rows:
                print(f"{r.source} [{r.status}]: {r.task_count} tasks")
    except Exception as e:
        print(f"Error querying DB: {e}")

asyncio.run(main())
