import asyncio
from sqlalchemy import text
from app.db.session import engine

async def check():
    print("Connecting to TimescaleDB...")
    async with engine.connect() as conn:
        print("\n--- RECENT PRICE INGESTION ---")
        try:
            res = await conn.execute(text("SELECT MAX(time) FROM stock_prices"))
            print(f"Latest price point in DB: {res.scalar()}")
        except Exception as e:
            print(f"Error reading prices: {e}")

        print("\n--- AGENT ANALYSIS TABLE DEEP DIVE ---")
        try:
            res = await conn.execute(text("SELECT COUNT(*) FROM ai_analysis"))
            print(f"Total AI Analyses generated: {res.scalar()}")
            
            res = await conn.execute(text("SELECT ticker, analysis_date, final_score FROM ai_analysis ORDER BY analysis_date DESC LIMIT 3"))
            print("\nLatest 3 Analyses:")
            for r in res.fetchall():
                print(f" - {r.ticker} @ {r.analysis_date} | Final Score: {r.final_score}")
        except Exception as e:
            print(f"Error reading ai_analysis: {e}")
            
        print("\n--- SWING SIGNALS ---")
        try:
            res = await conn.execute(text("SELECT COUNT(*) FROM swing_signals"))
            print(f"Total Swing Signals generated: {res.scalar()}")
        except Exception as e:
            print(f"Error reading swing signals: {e}")

if __name__ == '__main__':
    asyncio.run(check())
