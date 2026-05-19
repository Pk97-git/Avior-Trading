"""
Fundamental & Macro Service — Phase 1
=======================================
Handles:
- Full fundamental field mapping (Revenue, NI, FCF, ROIC, D/E, Op. Margin, EPS)
- US Macro via FRED (CPI, Fed Funds, 10Y, Yield Curve, M2)
- Global Macro via yfinance (Oil, Gold, VIX, Indices, Crypto as macro)
- India Macro (CPI via FRED, RBI Repo Rate via RBI scraper)
"""
import os
import yfinance as yf
import pandas as pd
import math
import pandas_datareader.data as web
import requests
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import CompanyFinancials, MacroEconomicData
from datetime import datetime
from typing import Optional

from app.core.rate_limiter import yahoo_limiter


# ─── Fundamental Service ─────────────────────────────────────────────────────

class FundamentalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _safe_float(self, series: pd.Series, key: str) -> Optional[float]:
        """Safely extract a float from a pandas Series."""
        try:
            val = series.get(key)
            if val is not None and pd.notna(val):
                return float(val)
        except Exception:
            pass
        return None

    def _clean_series(self, series: pd.Series) -> dict:
        """Converts a pandas Series to a dict, replacing NaNs and Infs with None."""
        if series.empty:
            return {}
        cleaned = {}
        for k, v in series.items():
            if pd.isna(v) or (isinstance(v, float) and (math.isinf(v) or math.isnan(v))):
                cleaned[str(k)] = None
            else:
                cleaned[str(k)] = float(v) if isinstance(v, (int, float)) else str(v)
        return cleaned

    async def fetch_financials(self, ticker_symbol: str):
        """
        Fetches full annual financials from yfinance.
        Maps: Revenue, Net Income, FCF, Operating Margin, EPS, D/E, ROIC.
        """

        try:
            # Rate limit
            await yahoo_limiter.acquire()
            
            t = yf.Ticker(ticker_symbol)
            info = t.info

            # yfinance DataFrames — columns are dates, rows are metrics
            financials_df = t.financials       # Income Statement
            balance_df = t.balance_sheet       # Balance Sheet
            cashflow_df = t.cashflow           # Cash Flow

            if financials_df is None or financials_df.empty:
                print(f"  [WARN] No financials for {ticker_symbol}")
                return

            # Transpose so dates are the index
            fin = financials_df.T
            bal = balance_df.T if balance_df is not None and not balance_df.empty else pd.DataFrame()
            cf = cashflow_df.T if cashflow_df is not None and not cashflow_df.empty else pd.DataFrame()

            records = []
            for date in fin.index:
                fin_row = fin.loc[date]
                bal_row = bal.loc[date] if date in bal.index else pd.Series()
                cf_row = cf.loc[date] if date in cf.index else pd.Series()

                # Core Income Statement
                revenue = self._safe_float(fin_row, "Total Revenue")
                net_income = self._safe_float(fin_row, "Net Income")
                operating_income = self._safe_float(fin_row, "Operating Income")
                ebit = self._safe_float(fin_row, "EBIT")

                # Operating Margin
                op_margin = None
                if revenue and operating_income and revenue > 0:
                    op_margin = operating_income / revenue

                # EPS (from info for latest, or compute)
                eps = self._safe_float(fin_row, "Basic EPS") or info.get("trailingEps")

                # Balance Sheet
                total_assets = self._safe_float(bal_row, "Total Assets")
                total_liabilities = self._safe_float(bal_row, "Total Liabilities Net Minority Interest")
                total_equity = self._safe_float(bal_row, "Stockholders Equity")
                total_debt = self._safe_float(bal_row, "Total Debt")

                # D/E Ratio
                debt_to_equity = None
                if total_debt and total_equity and total_equity > 0:
                    debt_to_equity = total_debt / total_equity

                # Cash Flow
                operating_cf = self._safe_float(cf_row, "Operating Cash Flow")
                capex = self._safe_float(cf_row, "Capital Expenditure")
                free_cash_flow = None
                if operating_cf is not None and capex is not None:
                    free_cash_flow = operating_cf + capex  # capex is negative in yfinance

                # ROIC = EBIT * (1 - tax_rate) / Invested Capital
                # Simplified: Net Income / (Total Assets - Current Liabilities)
                roic = None
                current_liabilities = self._safe_float(bal_row, "Current Liabilities")
                if net_income and total_assets and current_liabilities:
                    invested_capital = total_assets - current_liabilities
                    if invested_capital > 0:
                        roic = net_income / invested_capital

                # ROE
                roe = None
                if net_income and total_equity and total_equity > 0:
                    roe = net_income / total_equity

                records.append({
                    "ticker": ticker_symbol,
                    "fiscal_date": date,
                    "report_period": str(date.year),
                    "revenue": revenue,
                    "net_income": net_income,
                    "eps": float(eps) if eps else None,
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "free_cash_flow": free_cash_flow,
                    "pe_ratio": float(info.get("trailingPE")) if info.get("trailingPE") else None,
                    "debt_to_equity": debt_to_equity,
                    "roe": roe,
                    "roic": roic,
                    "operating_margin": op_margin,
                    "income_statement": self._clean_series(fin_row),
                    "balance_sheet": self._clean_series(bal_row),
                    "cash_flow": self._clean_series(cf_row),
                })

            if records:
                stmt = pg_insert(CompanyFinancials).values(records)
                update_dict = {
                    "revenue": stmt.excluded.revenue,
                    "net_income": stmt.excluded.net_income,
                    "eps": stmt.excluded.eps,
                    "total_assets": stmt.excluded.total_assets,
                    "total_liabilities": stmt.excluded.total_liabilities,
                    "free_cash_flow": stmt.excluded.free_cash_flow,
                    "pe_ratio": stmt.excluded.pe_ratio,
                    "debt_to_equity": stmt.excluded.debt_to_equity,
                    "roe": stmt.excluded.roe,
                    "roic": stmt.excluded.roic,
                    "operating_margin": stmt.excluded.operating_margin,
                    "income_statement": stmt.excluded.income_statement,
                    "balance_sheet": stmt.excluded.balance_sheet,
                    "cash_flow": stmt.excluded.cash_flow,
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=["ticker", "fiscal_date"],
                    set_=update_dict
                )
                await self.db.execute(stmt)
                await self.db.commit()
                print(f"  Upserted {len(records)} financial records for {ticker_symbol}")

        except Exception as e:
            print(f"  [ERROR] Financials for {ticker_symbol}: {e}")
            await self.db.rollback()


# ─── Macro Service ────────────────────────────────────────────────────────────

class MacroService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _upsert_macro(self, records: list):
        """Batch upsert macro records, ignoring duplicates."""
        if not records:
            return
        stmt = pg_insert(MacroEconomicData).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["time", "indicator"])
        await self.db.execute(stmt)
        await self.db.commit()

    async def fetch_fred_data(self, series_id: str, indicator_name: str):
        """
        Fetches full history from FRED via pandas_datareader.
        """
        try:
            start = datetime(2000, 1, 1)
            end = datetime.now()
            df = web.DataReader(series_id, "fred", start, end)

            records = []
            for index, row in df.iterrows():
                val = row[series_id]
                if pd.notna(val):
                    records.append({
                        "time": index,
                        "indicator": indicator_name,
                        "value": float(val),
                        "source": "FRED",
                    })

            await self._upsert_macro(records)
            print(f"  Ingested {len(records)} records for {indicator_name} (FRED)")

        except Exception as e:
            print(f"  [ERROR] FRED {indicator_name}: {e}")
            await self.db.rollback()

    async def fetch_global_macro(self, period: str = "max"):
        """
        Fetches global macro time series via yfinance.
        Includes Oil, Gold, VIX, Indices, Crypto (as macro indicators), FX.
        period="max" for initial load, "2d" for daily update.
        """
        macro_tickers = {
            # FX
            "USD_INR": "INR=X",
            "USD_INDEX": "DX-Y.NYB",   # DXY Dollar Index
            # Commodities
            "Crude_Oil_WTI": "CL=F",
            "Brent_Crude": "BZ=F",
            "Gold": "GC=F",
            "Silver": "SI=F",
            # Volatility
            "VIX_US": "^VIX",
            "VIX_India": "^INDIAVIX",
            # Indices
            "SP500": "^GSPC",
            "Nifty50": "^NSEI",
            "NASDAQ": "^IXIC",
            "BankNifty": "^NSEBANK",
            # Crypto (Macro Regime inputs)
            "Bitcoin": "BTC-USD",
            "Ethereum": "ETH-USD",
            # Bonds (yield proxies via ETF)
            "US_10Y_ETF": "IEF",       # iShares 7-10Y Treasury
            "US_TIP_ETF": "TIP",       # Inflation-Protected
        }

        for indicator, ticker_symbol in macro_tickers.items():
            try:
                # Rate limit
                await yahoo_limiter.acquire()
                
                t = yf.Ticker(ticker_symbol)
                hist = t.history(period=period, auto_adjust=True)

                if hist.empty:
                    print(f"  [WARN] No data for {indicator} ({ticker_symbol})")
                    continue

                records = []
                for index, row in hist.iterrows():
                    if pd.notna(row["Close"]):
                        records.append({
                            "time": index,
                            "indicator": indicator,
                            "value": float(row["Close"]),
                            "source": "Yahoo",
                        })

                await self._upsert_macro(records)
                print(f"  Ingested {len(records)} records for {indicator}")

            except Exception as ex:
                print(f"  [ERROR] {indicator} ({ticker_symbol}): {ex}")

    async def fetch_rbi_repo_rate(self):
        """
        Fetches RBI Repo Rate from the RBI DBIE API.
        Endpoint: https://api.rbi.org.in/api/v1/series/DBIE
        Falls back to a hardcoded recent value if API is unavailable.
        """
        try:
            # RBI DBIE API — Series for Repo Rate
            url = "https://api.rbi.org.in/api/v1/series/DBIE?seriesId=BSR1:IIPR:REPO"
            headers = {"Accept": "application/json"}
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                records = []
                # Parse RBI response format
                for item in data.get("data", []):
                    try:
                        dt = datetime.strptime(item["date"], "%Y-%m-%d")
                        val = float(item["value"])
                        records.append({
                            "time": dt,
                            "indicator": "RBI_REPO_RATE",
                            "value": val,
                            "source": "RBI",
                        })
                    except Exception:
                        continue

                if records:
                    await self._upsert_macro(records)
                    print(f"  Ingested {len(records)} RBI Repo Rate records")
                else:
                    raise ValueError("Empty RBI response")
            else:
                raise ConnectionError(f"RBI API returned {response.status_code}")

        except Exception as e:
            print(f"  [WARN] RBI API unavailable ({e}). Using fallback value.")
            # Fallback: store the last known rate. Value should be updated whenever
            # the RBI MPC announces a change (env var RBI_REPO_RATE_FALLBACK overrides).
            fallback_rate = float(os.environ.get("RBI_REPO_RATE_FALLBACK", "6.25"))
            fallback = [{
                "time": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
                "indicator": "RBI_REPO_RATE",
                "value": fallback_rate,
                "source": "RBI_MANUAL",
            }]
            await self._upsert_macro(fallback)

    async def fetch_all_us_macro(self):
        """Fetches all US FRED macro series."""
        fred_series = {
            "CPI_US": "CPIAUCSL",
            "FED_FUNDS_RATE": "FEDFUNDS",
            "US_10Y_YIELD": "DGS10",
            "US_2Y_YIELD": "DGS2",
            "US_YIELD_CURVE_10Y_2Y": "T10Y2Y",
            "US_M2_MONEY_SUPPLY": "M2SL",
            "US_UNEMPLOYMENT": "UNRATE",
            "US_PCE_INFLATION": "PCEPI",   # Fed's preferred inflation measure
        }
        for indicator, series_id in fred_series.items():
            await self.fetch_fred_data(series_id, indicator)

    async def fetch_all_india_macro(self):
        """Fetches all India macro data."""
        # India CPI via FRED
        await self.fetch_fred_data("INDCPMINDKSN", "CPI_INDIA")
        # RBI Repo Rate
        await self.fetch_rbi_repo_rate()
