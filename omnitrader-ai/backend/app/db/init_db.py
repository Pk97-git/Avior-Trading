import asyncio
from app.db.session import engine
from app.db.base import Base

# Import ALL models so Base.metadata knows about every table
from app.models.market_data import (
    Stock, StockPrice, CompanyFinancials, MacroEconomicData, MarketSnapshot,
    NewsSentiment, InstitutionalFlow, PromoterHolding, RegimeLabel,
    ChartSnapshot, AIAnalysis, Alert, Watchlist, PortfolioPosition, Order,
    InsiderTransaction, AnalystRating, StockTechnicals,
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
    # Stock technicals pre-computed indicator table
    "CREATE TABLE IF NOT EXISTS stock_technicals (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, date DATE NOT NULL, sma_20 FLOAT, sma_50 FLOAT, sma_200 FLOAT, ema_9 FLOAT, ema_21 FLOAT, rsi_14 FLOAT, macd FLOAT, macd_signal FLOAT, macd_hist FLOAT, atr_14 FLOAT, bb_upper FLOAT, bb_lower FLOAT, bb_mid FLOAT, vol_ratio FLOAT, week_52_high FLOAT, week_52_low FLOAT, rs_vs_spx FLOAT, rs_vs_nsei FLOAT, CONSTRAINT uq_stock_technicals_ticker_date UNIQUE (ticker, date))",
    "CREATE INDEX IF NOT EXISTS idx_stock_technicals_ticker ON stock_technicals (ticker)",
    "CREATE INDEX IF NOT EXISTS idx_stock_technicals_date ON stock_technicals (date)",
    # Short interest
    "CREATE TABLE IF NOT EXISTS short_interest (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, date DATE NOT NULL, short_ratio FLOAT, short_pct_float FLOAT, shares_short BIGINT, CONSTRAINT uq_short_interest_ticker_date UNIQUE (ticker, date))",
    "CREATE INDEX IF NOT EXISTS idx_short_interest_ticker ON short_interest (ticker)",
    # Dividends
    "CREATE TABLE IF NOT EXISTS dividends (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, ex_date DATE NOT NULL, amount FLOAT, yield_fwd FLOAT, div_cagr_5y FLOAT, CONSTRAINT uq_dividend_ticker_exdate UNIQUE (ticker, ex_date))",
    "CREATE INDEX IF NOT EXISTS idx_dividends_ticker ON dividends (ticker)",
    "CREATE INDEX IF NOT EXISTS idx_dividends_ex_date ON dividends (ex_date)",
    # F&O ban + earnings surprise columns
    "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS is_fo_banned BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS fo_ban_updated TIMESTAMPTZ",
    "ALTER TABLE company_financials ADD COLUMN IF NOT EXISTS eps_estimate FLOAT",
    "ALTER TABLE company_financials ADD COLUMN IF NOT EXISTS eps_surprise_pct FLOAT",
    # Intraday 15-minute bars
    "CREATE TABLE IF NOT EXISTS intraday_prices (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, time TIMESTAMPTZ NOT NULL, open FLOAT, high FLOAT, low FLOAT, close FLOAT, volume FLOAT, CONSTRAINT uq_intraday_ticker_time UNIQUE (ticker, time))",
    "CREATE INDEX IF NOT EXISTS ix_intraday_ticker_time ON intraday_prices (ticker, time)",
    # F&O option chain snapshots
    "CREATE TABLE IF NOT EXISTS fo_chain_snapshots (id SERIAL PRIMARY KEY, symbol VARCHAR NOT NULL, snapshot_time TIMESTAMPTZ NOT NULL, expiry DATE NOT NULL, strike FLOAT NOT NULL, option_type VARCHAR NOT NULL, oi FLOAT, change_oi FLOAT, volume FLOAT, ltp FLOAT, iv FLOAT, max_pain FLOAT, CONSTRAINT uq_fo_chain UNIQUE (symbol, snapshot_time, expiry, strike, option_type))",
    "CREATE INDEX IF NOT EXISTS ix_fo_chain_symbol_time ON fo_chain_snapshots (symbol, snapshot_time)",
    # India corporate actions
    "CREATE TABLE IF NOT EXISTS corporate_actions (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, ex_date DATE NOT NULL, action_type VARCHAR NOT NULL, details JSONB, source VARCHAR, CONSTRAINT uq_corp_action UNIQUE (ticker, ex_date, action_type))",
    "CREATE INDEX IF NOT EXISTS ix_corp_action_ticker_date ON corporate_actions (ticker, ex_date)",
    # Mutual fund NAV
    "CREATE TABLE IF NOT EXISTS mutual_fund_nav (id SERIAL PRIMARY KEY, scheme_code VARCHAR NOT NULL, scheme_name VARCHAR, fund_house VARCHAR, category VARCHAR, date DATE NOT NULL, nav FLOAT, CONSTRAINT uq_mf_nav_scheme_date UNIQUE (scheme_code, date))",
    "CREATE INDEX IF NOT EXISTS ix_mf_nav_scheme_date ON mutual_fund_nav (scheme_code, date)",
    # Mutual fund holdings
    "CREATE TABLE IF NOT EXISTS mutual_fund_holdings (id SERIAL PRIMARY KEY, scheme_code VARCHAR NOT NULL, disclosure_date DATE NOT NULL, ticker VARCHAR, company_name VARCHAR, isin VARCHAR, market_value FLOAT, pct_net_assets FLOAT, shares_held BIGINT, CONSTRAINT uq_mf_holding UNIQUE (scheme_code, disclosure_date, ticker))",
    "CREATE INDEX IF NOT EXISTS ix_mf_holding_ticker ON mutual_fund_holdings (ticker)",
    # SEC EDGAR filings
    "CREATE TABLE IF NOT EXISTS sec_filings (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, cik VARCHAR NOT NULL, filing_type VARCHAR NOT NULL, filed_date DATE NOT NULL, period_end DATE NOT NULL, accession_no VARCHAR, filing_url VARCHAR, xbrl_metrics JSONB, risk_factors TEXT, CONSTRAINT uq_sec_filing UNIQUE (ticker, filing_type, period_end))",
    "CREATE INDEX IF NOT EXISTS ix_sec_filing_ticker_date ON sec_filings (ticker, filed_date)",
    # US equity options chain snapshots
    "CREATE TABLE IF NOT EXISTS us_options_snapshots (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, snapshot_date DATE NOT NULL, expiry DATE NOT NULL, strike FLOAT NOT NULL, option_type VARCHAR NOT NULL, bid FLOAT, ask FLOAT, last_price FLOAT, volume FLOAT, open_interest FLOAT, implied_vol FLOAT, delta FLOAT, gamma FLOAT, theta FLOAT, vega FLOAT, in_the_money BOOLEAN, CONSTRAINT uq_us_options UNIQUE (ticker, snapshot_date, expiry, strike, option_type))",
    "CREATE INDEX IF NOT EXISTS ix_us_options_ticker_date ON us_options_snapshots (ticker, snapshot_date)",
    # RBI press releases
    "CREATE TABLE IF NOT EXISTS rbi_announcements (id SERIAL PRIMARY KEY, published_date TIMESTAMPTZ NOT NULL, title VARCHAR NOT NULL, category VARCHAR, url VARCHAR NOT NULL, summary TEXT, sentiment_score FLOAT, is_policy_rate BOOLEAN DEFAULT FALSE, CONSTRAINT uq_rbi_url UNIQUE (url))",
    "CREATE INDEX IF NOT EXISTS ix_rbi_pub_date ON rbi_announcements (published_date)",
    # Google Trends interest scores
    "CREATE TABLE IF NOT EXISTS google_trends (id SERIAL PRIMARY KEY, ticker VARCHAR REFERENCES stocks(ticker) ON DELETE CASCADE, date DATE NOT NULL, interest_score INTEGER, keyword VARCHAR, geo VARCHAR, trend_7d_avg FLOAT, CONSTRAINT uq_gtrends_ticker_date UNIQUE (ticker, date))",
    "CREATE INDEX IF NOT EXISTS ix_gtrends_ticker_date ON google_trends (ticker, date)",
]


_TIMESCALE_HYPERTABLES = [
    # (table_name, time_column, chunk_interval)
    ("stock_prices",     "time",          "7 days"),
    ("intraday_prices",  "time",          "1 day"),
    ("news_sentiment",   "time",          "7 days"),
    ("macro_data",       "time",          "30 days"),
    ("fo_chain_snapshots", "snapshot_time", "1 day"),
]


async def setup_timescaledb():
    """
    Activate TimescaleDB extension and convert key time-series tables to hypertables.
    Safe to call repeatedly — uses IF NOT EXISTS guards.
    """
    async with engine.begin() as conn:
        try:
            await conn.execute(__import__('sqlalchemy').text(
                "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"
            ))
        except Exception as e:
            print(f"  [TimescaleDB] Extension setup: {e}")
            return  # TimescaleDB not installed — skip hypertable creation

        for table, col, interval in _TIMESCALE_HYPERTABLES:
            try:
                await conn.execute(__import__('sqlalchemy').text(f"""
                    SELECT create_hypertable('{table}', '{col}',
                        chunk_time_interval => INTERVAL '{interval}',
                        if_not_exists => TRUE,
                        migrate_data => TRUE)
                """))
                print(f"  [TimescaleDB] Hypertable: {table} ({col}, {interval})")
            except Exception as e:
                print(f"  [TimescaleDB] {table}: {e}")
    print("TimescaleDB setup complete.")


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
    await setup_timescaledb()
    print("Database tables created/verified.")


if __name__ == "__main__":
    asyncio.run(init_models())
