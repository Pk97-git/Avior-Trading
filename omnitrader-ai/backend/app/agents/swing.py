import logging
import os
from typing import Optional, Dict
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.agents.vision import VisionAgent
from app.agents.runner import run_all_agents
import mplfinance as mpf
import pandas as pd
from groq import Groq

logger = logging.getLogger(__name__)

class SwingTradeAgent:
    """
    Takes a screened high-potential ticker, calculates precise risk metrics
    (Stop Loss, Take Profit, ATR, Max Risk), generates a chart image, 
    and uses a LLM taking ALL agent context (fundamental, macro, sentiment)
    to generate an actionable, proactive trade setup for the user.
    """

    def __init__(self, db: AsyncSession, ticker: str):
        self.db = db
        self.ticker = ticker.upper()

    async def _get_recent_prices(self, days=150) -> pd.DataFrame:
        query = text("""
            SELECT time as Date, open as Open, high as High, low as Low, close as Close, volume as Volume
            FROM stock_prices
            WHERE ticker = :ticker
              AND time >= :since
            ORDER BY time ASC
        """)
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(query, {"ticker": self.ticker, "since": since})
        rows = result.fetchall()
        
        if not rows:
            return pd.DataFrame()
            
        df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)
        return df

    async def _get_atr(self, df: pd.DataFrame) -> float:
        """ATR-14 from pre-computed stock_technicals; falls back to raw calculation."""
        try:
            result = await self.db.execute(text("""
                SELECT atr_14 FROM stock_technicals
                WHERE ticker = :ticker AND atr_14 IS NOT NULL
                ORDER BY date DESC LIMIT 1
            """), {"ticker": self.ticker})
            row = result.fetchone()
            if row and row.atr_14:
                return float(row.atr_14)
        except Exception:
            pass
        # Fallback: compute from raw OHLCV
        high_low = df['High'] - df['Low']
        high_close = (df['High'] - df['Close'].shift()).abs()
        low_close = (df['Low'] - df['Close'].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return float(true_range.rolling(14).mean().iloc[-1])

    def _generate_chart(self, df: pd.DataFrame, stop_loss: float, take_profit: float) -> str:
        """Draws the visual chart with support/resistance lines and saves it."""
        try:
            os.makedirs("app/static/charts", exist_ok=True)
            fname = f"app/static/charts/{self.ticker}_swing_setup.png"
            
            # Define horizontal lines for Stop Loss (Red) and Take Profit (Green)
            hlines = dict(hlines=[stop_loss, take_profit], colors=['r', 'g'], linestyle='--', linewidths=[2,2])
            
            # Slice the last 90 days for a cleaner zoomed-in look
            plot_df = df.iloc[-90:] if len(df) > 90 else df
            
            mpf.plot(
                plot_df, 
                type='candle', 
                volume=True, 
                hlines=hlines,
                mav=(20, 50), 
                style='yahoo', 
                title=f"{self.ticker} Proactive Swing Setup",
                savefig=dict(fname=fname, dpi=150, bbox_inches='tight')
            )
            return f"/static/charts/{self.ticker}_swing_setup.png"
        except Exception as e:
            logger.error(f"Chart generation failed for {self.ticker}: {e}")
            return ""

    async def _generate_setup_thesis(self, 
                                     current_price: float, 
                                     stop_loss: float, 
                                     take_profit: float,
                                     risk_reward: float,
                                     omni_data: dict,
                                     vision_result: dict) -> str:
        """Uses Groq to write a professional hedge-fund style trade setup with Omni Context."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return "No GROQ_API_KEY provided for synthesis."
            
        try:
            client = Groq(api_key=api_key)
            
            # Build the rich context block from all agents
            context = f"FUNDAMENTAL: Score {omni_data.get('fundamental_score', 50)}/100\n"
            if omni_data.get("fundamental_thesis"):
                 context += f" - {omni_data['fundamental_thesis'][0]}\n"
                 
            context += f"MACRO REGIME: {omni_data.get('macro_regime', 'Unknown')}\n"
            if omni_data.get("macro_thesis"):
                 context += f" - {omni_data['macro_thesis'][0]}\n"
                 
            context += f"INSTITUTIONAL FLOW: Score {omni_data.get('institutional_score', 50)}/100\n"
            if omni_data.get("institutional_thesis"):
                 context += f" - {omni_data['institutional_thesis'][0]}\n"
                 
            context += f"SENTIMENT: Score {omni_data.get('sentiment_score', 50)}/100\n"
            if omni_data.get("sentiment_thesis"):
                 context += f" - {omni_data['sentiment_thesis'][0]}\n"
                 
            pattern = vision_result.get('pattern', 'Uptrend Pullback')
            vision_obs = "\\n- ".join(vision_result.get('thesis', []))

            prompt = (
                f"You are a master swing trader teaching the user. You found a proactive setup for {self.ticker}.\n"
                f"Current Price: ${current_price:.2f}\n"
                f"Stop Loss: ${stop_loss:.2f} (Calculated using 2x ATR cushion below support)\n"
                f"Take Profit: ${take_profit:.2f}\n"
                f"Risk/Reward Ratio: {risk_reward:.1f}x\n"
                f"Technical Pattern on Chart: {pattern}\n"
                f"Vision Agent Observations:\n- {vision_obs}\n\n"
                f"--- OMNI-DATA CONTEXT STEERING THE TRADE ---\n{context}\n\n"
                f"Write a comprehensive 2-paragraph actionable trading plan predicting the movement. "
                f"In the first paragraph, weave the fundamental, macro, institutional, and technical context together to prove WHY this stock is a great setup. "
                f"In the second paragraph, explain EXACTLY WHY the stop loss and take profit are placed at these levels (to teach the user risk management). Be decisive and professional."
            )
            
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=450
            )
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.warning(f"Failed to generate thesis: {e}")
            return "Failed to synthesize setup strategy."

    async def analyze(self) -> dict:
        """
        Calculates Stop Loss and Take profit, requests Vision evaluation,
        fetches full OmniData context (Fundamentals/Macro), draws physical charts,
        and generates a cohesive strategy report.
        """
        df = await self._get_recent_prices()
        if len(df) < 50:
            return {"error": "Not enough price data for setup."}

        current_price = df['Close'].iloc[-1]
        
        # Risk Management Math (2x ATR Stop Loss, 3:1 Reward/Risk)
        atr = await self._get_atr(df)
        stop_loss = current_price - (atr * 2)
        risk_per_share = current_price - stop_loss
        take_profit = current_price + (risk_per_share * 3)
        rr_ratio = (take_profit - current_price) / risk_per_share

        # 1. Fetch FULL context from all 10 agents
        try:
            omni_data = await run_all_agents(self.db, self.ticker)
        except Exception as e:
            logger.error(f"Failed to run omni-agents for {self.ticker}: {e}")
            omni_data = {}

        # 2. Vision Check
        vision_agent = VisionAgent(self.db, self.ticker)
        vision_result = await vision_agent.analyze()

        # 3. Generate visual chart with support/resistance lines plotted
        chart_url = self._generate_chart(df, stop_loss, take_profit)

        # 4. Synthesize final LLM Thesis
        thesis = await self._generate_setup_thesis(
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=rr_ratio,
            omni_data=omni_data,
            vision_result=vision_result
        )

        return {
            "ticker": self.ticker,
            "current_price": round(current_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "risk_reward": round(rr_ratio, 2),
            "setup_thesis": thesis,
            "vision_pattern": vision_result.get("pattern"),
            "chart_url": chart_url
        }
