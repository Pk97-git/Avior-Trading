import logging
from datetime import datetime, timezone
from prefect import flow, task
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.services.screener import SwingScreener
from app.agents.swing import SwingTradeAgent
from app.models.market_data import Alert
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

@task(name="Screen High-Probability Swing Setups", log_prints=True)
async def screen_setups(country: str = "US") -> list:
    async with AsyncSessionLocal() as db:
        screener = SwingScreener(db)
        # Find the top 5 setups based on fundamentals + moving averages
        setups = await screener.find_high_potential_setups(country=country, limit=5)
        return setups

@task(name="Generate Proactive Trade Plan", log_prints=True)
async def generate_trade_plan(ticker: str) -> dict:
    async with AsyncSessionLocal() as db:
        agent = SwingTradeAgent(db, ticker)
        report = await agent.analyze()
        
        # Save as an Alert so the Frontend sees it instantly
        if "error" not in report:
            alert = Alert(
                ticker=ticker,
                generated_at=datetime.now(timezone.utc),
                signal="PROACTIVE_SWING",
                previous_signal=None,
                final_score=85, # Estimated high probability 
                headline=f"Swing Setup: {ticker} (Stop: ${report['stop_loss']} | Target: ${report['take_profit']})",
                thesis=[report["setup_thesis"]],
                image_url=report.get("chart_url"),
                is_read=False
            )
            db.add(alert)
            await db.commit()
            
        return report

@flow(name="Proactive Swing Trading Screener", log_prints=True)
async def swing_trading_flow(country: str = "US"):
    """
    1. Screens the entire universe for fundamental + technical overlap.
    2. Runs advanced ATR calculations and Vision checks on the top 5 setups.
    3. Fires Alerts to the dashboard showing entry, stop, and take-profit levels.
    """
    logger.info(f"Starting Proactive Swing Screener for {country} Market...")
    
    # 1. Fast SQL filtering
    setups = await screen_setups(country=country)
    
    if not setups:
        logger.info("No high-potential setups found today.")
        return
        
    logger.info(f"Found {len(setups)} setups! Generating actionable trading plans...")
    
    # 2. Run Heavy AI logic on filtered setups
    results = []
    for setup in setups:
        ticker = setup["ticker"]
        logger.info(f"Analyzing Setup: {ticker}")
        report = await generate_trade_plan(ticker)
        results.append(report)
        
    logger.info("Swing Screener Flow Complete! Alerts dispatched to Dashboard.")
    return results

if __name__ == "__main__":
    import asyncio
    asyncio.run(swing_trading_flow())
