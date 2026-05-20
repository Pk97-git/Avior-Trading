from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Date, ForeignKey, Boolean, Index, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from app.db.base import Base
import datetime



class Stock(Base):
    __tablename__ = "stocks"

    ticker = Column(String, primary_key=True, index=True)
    name = Column(String)
    sector = Column(String)
    industry = Column(String)
    country = Column(String)          # "US" / "IN"
    meta_data = Column(JSONB)
    is_fo_banned   = Column(Boolean, default=False, nullable=False, server_default="false")
    fo_ban_updated = Column(DateTime(timezone=True), nullable=True)

    prices = relationship("StockPrice", back_populates="stock")


class StockPrice(Base):
    __tablename__ = "stock_prices"

    time = Column(DateTime(timezone=True), primary_key=True, index=True)
    ticker = Column(String, ForeignKey("stocks.ticker"), primary_key=True)

    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    adj_close = Column(Float)

    stock = relationship("Stock", back_populates="prices")


class MarketSnapshot(Base):
    """Vector DB snapshots for the Historical Memory Agent."""
    __tablename__ = "market_snapshots"

    time = Column(DateTime(timezone=True), primary_key=True)
    regime_label = Column(String)

    # pgvector embedding (1536-dim for OpenAI / 768-dim for local models)
    embedding = Column(Vector(1536))

    # Raw feature snapshot for cosine similarity fallback and reconstruction
    features = Column(JSONB)


class CompanyFinancials(Base):
    __tablename__ = "company_financials"

    ticker = Column(String, ForeignKey("stocks.ticker"), primary_key=True)
    fiscal_date = Column(DateTime, primary_key=True)
    report_period = Column(String)    # "Q1", "FY2023"

    revenue = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)
    eps_estimate    = Column(Float, nullable=True)   # analyst consensus EPS estimate
    eps_surprise_pct = Column(Float, nullable=True)  # (actual - estimate) / |estimate| * 100
    total_assets = Column(Float)
    total_liabilities = Column(Float)
    free_cash_flow = Column(Float)

    pe_ratio = Column(Float)
    debt_to_equity = Column(Float)
    roe = Column(Float)
    roic = Column(Float)
    operating_margin = Column(Float)

    income_statement = Column(JSONB)
    balance_sheet = Column(JSONB)
    cash_flow = Column(JSONB)

    stock = relationship("Stock", back_populates="financials")


# Attach financials relationship to Stock after CompanyFinancials is defined
Stock.financials = relationship("CompanyFinancials", back_populates="stock")


class MacroEconomicData(Base):
    __tablename__ = "macro_data"

    time = Column(DateTime(timezone=True), primary_key=True)
    indicator = Column(String, primary_key=True)   # "CPI", "US10Y", "VIX"
    value = Column(Float)
    source = Column(String)                         # "FRED", "Yahoo"


class InstitutionalFlow(Base):
    __tablename__ = "institutional_flows"

    date = Column(DateTime, primary_key=True)
    entity_type = Column(String, primary_key=True)  # "FII", "DII", "13F_HEDGE_FUND"
    market = Column(String, primary_key=True)        # "INDIA", "US"

    buy_value = Column(Float)
    sell_value = Column(Float)
    net_value = Column(Float)
    meta_data = Column(JSONB)


class NewsSentiment(Base):
    __tablename__ = "news_sentiment"

    time = Column(DateTime(timezone=True), primary_key=True)
    ticker = Column(String, ForeignKey("stocks.ticker"), primary_key=True)

    headline = Column(String)
    source = Column(String)
    url = Column(String)
    sentiment_score = Column(Float)    # −1.0 to +1.0
    confidence = Column(Float)
    event_type = Column(String, nullable=True)   # EARNINGS_BEAT, EARNINGS_MISS, GUIDANCE_RAISE, GUIDANCE_CUT, INSIDER_BUY, M&A_TARGET, CEO_CHANGE, BUYBACK, FDA_APPROVAL, MACRO_SHOCK, NONE


class PromoterHolding(Base):
    """India: quarterly NSE shareholding pattern."""
    __tablename__ = "promoter_holdings"

    ticker = Column(String, ForeignKey("stocks.ticker"), primary_key=True)
    quarter_end = Column(DateTime, primary_key=True)

    promoter_pct = Column(Float)
    fii_pct = Column(Float)
    dii_pct = Column(Float)
    public_pct = Column(Float)
    promoter_pct_change = Column(Float)

    source = Column(String)
    meta_data = Column(JSONB)


class RegimeLabel(Base):
    """Computed macro regime labels — used by Historical Memory Engine."""
    __tablename__ = "regime_labels"

    time = Column(DateTime(timezone=True), primary_key=True)

    regime = Column(String)               # "Risk-On", "Risk-Off", …
    regime_confidence = Column(Float)
    stability_score = Column(Float)
    transition_state = Column(String)
    transition_prob = Column(Float)
    features = Column(JSONB)


class ChartSnapshot(Base):
    """Generated chart images for Vision Agent (Phase 4)."""
    __tablename__ = "chart_snapshots"

    ticker = Column(String, ForeignKey("stocks.ticker"), primary_key=True)
    generated_at = Column(DateTime(timezone=True), primary_key=True)
    timeframe = Column(String, primary_key=True)    # "6M", "1Y", "5Y"

    image_path = Column(String)
    pattern_json = Column(JSONB)
    vision_score = Column(Float)
    vision_summary = Column(String)


class AIAnalysis(Base):
    """Full agent scoring engine results + executive decision per ticker per day."""
    __tablename__ = "ai_analysis"

    ticker = Column(String, ForeignKey("stocks.ticker"), primary_key=True)
    analysis_date = Column(DateTime(timezone=True), primary_key=True)

    # ── Individual agent scores (0–100) ───────────────────────────────────────
    fundamental_score   = Column(Integer)
    technical_score     = Column(Integer)
    macro_score         = Column(Integer)
    institutional_score = Column(Integer)
    sentiment_score     = Column(Integer)
    memory_confidence   = Column(Float)     # 0.0–1.0

    # ── Executive Trader output ───────────────────────────────────────────────
    final_score = Column(Integer)           # weighted composite 0–100
    signal      = Column(String)            # BUY / HOLD / REDUCE / SELL
    regime      = Column(String)            # macro regime label at time of analysis

    # ── Per-agent narrative theses ────────────────────────────────────────────
    fundamental_thesis   = Column(JSONB)    # list[str]
    technical_thesis     = Column(JSONB)
    macro_thesis         = Column(JSONB)
    institutional_thesis = Column(JSONB)
    sentiment_thesis     = Column(JSONB)
    memory_thesis        = Column(JSONB)
    vision_score         = Column(Integer)  # 0–100 from VisionAgent
    vision_thesis        = Column(JSONB)    # list[str]
    signal_thesis        = Column(JSONB)    # executive summary bullets

    # ── Phase 2: Strategist outputs ───────────────────────────────────────────
    factor_scores           = Column(JSONB)   # {value, growth, momentum, quality, low_vol} z-scores
    cross_asset_sensitivity = Column(JSONB)   # {US10Y, VIX, DXY, Oil, Gold} betas

    # ── Phase 3: Risk outputs ─────────────────────────────────────────────────
    calibrated_prob  = Column(Float)          # Platt-scaled win probability
    kelly_fraction   = Column(Float)          # Half-Kelly position fraction
    max_position_pct = Column(Float)          # max position as % of portfolio

    # ── Memory agent analogs ──────────────────────────────────────────────────
    analogs = Column(JSONB)                   # list of historical analog dicts

    # ── Trade levels (ATR-based) ──────────────────────────────────────────────
    entry_price  = Column(Float)              # latest close at time of analysis
    stop_loss    = Column(Float)              # entry - 2×ATR
    take_profit  = Column(Float)              # entry + 6×ATR (3:1 R:R)
    atr_14       = Column(Float)              # 14-day ATR used for levels


class Alert(Base):
    """Signal-change alerts generated by the ExecutiveTrader after each scoring run."""
    __tablename__ = "alerts"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    ticker         = Column(String, ForeignKey("stocks.ticker"), index=True)
    generated_at   = Column(DateTime(timezone=True), index=True)

    signal          = Column(String)        # new signal
    previous_signal = Column(String)        # signal before this run (None = first time)
    final_score     = Column(Integer)
    headline        = Column(String)        # one-line human-readable summary
    thesis          = Column(JSONB)         # top 3 bullets from executive
    image_url       = Column(String)        # path to generated visual chart
    is_read         = Column(Boolean, default=False)

    stock = relationship("Stock")

    __table_args__ = (
        Index("ix_alerts_generated_at_signal", "generated_at", "signal"),
    )


class Watchlist(Base):
    """User watchlist — tickers the trader wants to monitor closely."""
    __tablename__ = "watchlist"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    ticker     = Column(String, ForeignKey("stocks.ticker"), nullable=False, index=True)
    added_at   = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    notes      = Column(Text, nullable=True)
    priority   = Column(String, default="MEDIUM")   # HIGH / MEDIUM / LOW
    is_active  = Column(Boolean, default=True)

    stock = relationship("Stock")

    __table_args__ = (
        Index("ix_watchlist_ticker_active", "ticker", "is_active"),
    )


class PortfolioPosition(Base):
    """Portfolio positions with full P&L tracking."""
    __tablename__ = "portfolio_positions"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    ticker         = Column(String, ForeignKey("stocks.ticker"), nullable=False, index=True)
    entry_date     = Column(DateTime(timezone=True), nullable=False)
    entry_price    = Column(Float, nullable=False)
    shares         = Column(Float, nullable=False)          # fractional allowed
    position_value = Column(Float)                           # entry_price * shares
    stop_loss      = Column(Float)
    take_profit    = Column(Float)
    signal         = Column(String)                          # BUY / HOLD / REDUCE / SELL
    regime         = Column(String)                          # macro regime at entry
    notes          = Column(Text)
    # Closing fields
    is_open            = Column(Boolean, default=True, index=True)
    exit_date          = Column(DateTime(timezone=True))
    exit_price         = Column(Float)
    exit_reason        = Column(String)                      # MANUAL / STOP / TARGET / SIGNAL
    realized_pnl       = Column(Float)                       # exit_value - entry_value
    realized_pnl_pct   = Column(Float)

    stock = relationship("Stock")

    __table_args__ = (
        Index("ix_portfolio_ticker_open", "ticker", "is_open"),
    )


class Order(Base):
    """Tracks all order submissions — paper, Zerodha, and Alpaca."""
    __tablename__ = "orders"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    ticker          = Column(String, ForeignKey("stocks.ticker"), nullable=False, index=True)
    created_at      = Column(DateTime(timezone=True), index=True)
    side            = Column(String)          # BUY / SELL
    order_type      = Column(String)          # MARKET / LIMIT
    qty             = Column(Float)           # shares / units requested
    limit_price     = Column(Float)           # None for MARKET orders
    broker          = Column(String)          # PAPER / ZERODHA / ALPACA
    broker_order_id = Column(String)          # ID returned by the broker
    status          = Column(String, default="PENDING")  # PENDING / FILLED / CANCELLED / REJECTED
    filled_qty      = Column(Float)
    filled_price    = Column(Float)
    filled_at       = Column(DateTime(timezone=True))
    signal          = Column(String)          # the AI signal that triggered this order
    final_score     = Column(Integer)
    notes           = Column(Text)
    portfolio_position_id = Column(Integer, ForeignKey("portfolio_positions.id"), nullable=True)

    stock = relationship("Stock")

    __table_args__ = (
        Index("ix_orders_ticker_status", "ticker", "status"),
    )


class InsiderTransaction(Base):
    """SEC Form 4 insider buy/sell transactions."""
    __tablename__ = "insider_transactions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    ticker          = Column(String, ForeignKey("stocks.ticker"), nullable=False, index=True)
    filed_date      = Column(DateTime(timezone=True), index=True)
    transaction_date = Column(DateTime(timezone=True))
    insider_name    = Column(String)
    insider_role    = Column(String)   # "CEO", "CFO", "Director", "10% Owner", etc.
    transaction_type = Column(String)  # "P" = Purchase, "S" = Sale, "A" = Award
    shares          = Column(Float)
    price_per_share = Column(Float)
    total_value     = Column(Float)    # shares * price
    shares_owned_after = Column(Float)
    form_type       = Column(String, default="4")  # "4" or "4/A"
    sec_url         = Column(String)

    stock = relationship("Stock")

    __table_args__ = (
        Index("ix_insider_ticker_date", "ticker", "filed_date"),
    )


class AnalystRating(Base):
    """Analyst upgrade/downgrade/initiation events."""
    __tablename__ = "analyst_ratings"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    ticker       = Column(String, ForeignKey("stocks.ticker"), nullable=False, index=True)
    date         = Column(DateTime(timezone=True), index=True)
    firm         = Column(String)
    action       = Column(String)   # "upgrade", "downgrade", "init", "reiterate"
    from_grade   = Column(String)   # "Hold", "Neutral", "Sell"
    to_grade     = Column(String)   # "Buy", "Strong Buy", "Overweight"
    price_target = Column(Float)    # New price target if given

    stock = relationship("Stock")

    __table_args__ = (
        Index("ix_analyst_ticker_date", "ticker", "date"),
    )


class StockTechnicals(Base):
    __tablename__ = "stock_technicals"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_stock_technicals_ticker_date"),
        {"timescaledb_hypertable": False},
    )
    id         = Column(Integer, primary_key=True, autoincrement=True)
    ticker     = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    date       = Column(Date, nullable=False, index=True)

    # Trend
    sma_20     = Column(Float)
    sma_50     = Column(Float)
    sma_200    = Column(Float)
    ema_9      = Column(Float)
    ema_21     = Column(Float)

    # Momentum
    rsi_14     = Column(Float)   # 0–100
    macd       = Column(Float)   # MACD line (12 EMA - 26 EMA)
    macd_signal = Column(Float)  # 9-day EMA of MACD
    macd_hist  = Column(Float)   # macd - macd_signal

    # Volatility
    atr_14     = Column(Float)   # Average True Range (14 days)
    bb_upper   = Column(Float)   # Bollinger upper band (20, 2σ)
    bb_lower   = Column(Float)   # Bollinger lower band (20, 2σ)
    bb_mid     = Column(Float)   # Bollinger midline (= SMA 20)

    # Volume
    vol_ratio  = Column(Float)   # today's volume / 20-day avg volume

    # Key levels
    week_52_high = Column(Float)
    week_52_low  = Column(Float)

    # Relative Strength vs benchmark
    rs_vs_spx  = Column(Float)   # 3-month % return / SPX 3-month % return
    rs_vs_nsei = Column(Float)   # 3-month % return / Nifty 3-month % return (India stocks only)

    # Mean reversion / volatility signals
    vwap             = Column(Float, nullable=True)   # daily VWAP from intraday 15m bars
    bb_bandwidth     = Column(Float, nullable=True)   # (bb_upper-bb_lower)/bb_mid*100
    bb_squeeze       = Column(Boolean, nullable=True) # True if bandwidth < 10th percentile trailing 126d
    price_zscore_20d = Column(Float, nullable=True)   # (close - sma_20) / 20d rolling std

    # Fibonacci levels (50-day swing)
    fib_high_50d = Column(Float, nullable=True)   # 50-day swing high
    fib_low_50d  = Column(Float, nullable=True)   # 50-day swing low
    fib_236      = Column(Float, nullable=True)   # 23.6% retracement from low
    fib_382      = Column(Float, nullable=True)   # 38.2% retracement
    fib_500      = Column(Float, nullable=True)   # 50.0% retracement
    fib_618      = Column(Float, nullable=True)   # 61.8% golden ratio retracement
    fib_pct_pos  = Column(Float, nullable=True)   # price position in fib range (0=low, 1=high)


class ShortInterest(Base):
    __tablename__ = "short_interest"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_short_interest_ticker_date"),
    )
    id              = Column(Integer, primary_key=True, autoincrement=True)
    ticker          = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    date            = Column(Date, nullable=False, index=True)
    short_ratio     = Column(Float)       # days to cover
    short_pct_float = Column(Float)       # % of float sold short (0.0–1.0)
    shares_short    = Column(BigInteger, nullable=True)


class Dividend(Base):
    __tablename__ = "dividends"
    __table_args__ = (
        UniqueConstraint("ticker", "ex_date", name="uq_dividend_ticker_exdate"),
    )
    id          = Column(Integer, primary_key=True, autoincrement=True)
    ticker      = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    ex_date     = Column(Date, nullable=False, index=True)
    amount      = Column(Float)
    yield_fwd   = Column(Float)       # forward annual yield %
    div_cagr_5y = Column(Float)       # 5-year dividend growth CAGR %


class IntradayPrice(Base):
    """15-minute OHLCV bars for intraday analysis."""
    __tablename__ = "intraday_prices"
    __table_args__ = (
        UniqueConstraint("ticker", "time", name="uq_intraday_ticker_time"),
        Index("ix_intraday_ticker_time", "ticker", "time"),
    )

    id     = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    time   = Column(DateTime(timezone=True), nullable=False, index=True)
    open   = Column(Float)
    high   = Column(Float)
    low    = Column(Float)
    close  = Column(Float)
    volume = Column(Float)


class FoChainSnapshot(Base):
    """NSE F&O option chain snapshot by strike (Nifty/BankNifty). Captured every 15 min during NSE session."""
    __tablename__ = "fo_chain_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "snapshot_time", "expiry", "strike", "option_type",
                         name="uq_fo_chain"),
        Index("ix_fo_chain_symbol_time", "symbol", "snapshot_time"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    symbol        = Column(String, nullable=False)          # "NIFTY", "BANKNIFTY"
    snapshot_time = Column(DateTime(timezone=True), nullable=False, index=True)
    expiry        = Column(Date, nullable=False)
    strike        = Column(Float, nullable=False)
    option_type   = Column(String, nullable=False)          # "CE" or "PE"
    oi            = Column(Float)                           # open interest (contracts)
    change_oi     = Column(Float)                           # OI change from prev bar
    volume        = Column(Float)
    ltp           = Column(Float)                           # last traded price
    iv            = Column(Float)                           # implied volatility %
    max_pain      = Column(Float, nullable=True)            # max pain strike for this expiry


class CorporateAction(Base):
    """India (NSE/BSE) corporate actions: dividends, splits, bonuses, rights."""
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint("ticker", "ex_date", "action_type", name="uq_corp_action"),
        Index("ix_corp_action_ticker_date", "ticker", "ex_date"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    ticker      = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    ex_date     = Column(Date, nullable=False, index=True)
    action_type = Column(String, nullable=False)            # "DIVIDEND", "SPLIT", "BONUS", "RIGHTS"
    details     = Column(JSONB)                             # ratio, amount, record_date, etc.
    source      = Column(String)                            # "NSE", "BSE", "YFINANCE"


class MutualFundNav(Base):
    """AMFI mutual fund NAV — daily NAV per scheme."""
    __tablename__ = "mutual_fund_nav"
    __table_args__ = (
        UniqueConstraint("scheme_code", "date", name="uq_mf_nav_scheme_date"),
        Index("ix_mf_nav_scheme_date", "scheme_code", "date"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    scheme_code = Column(String, nullable=False, index=True)
    scheme_name = Column(String)
    fund_house  = Column(String)
    category    = Column(String)                            # "Equity", "Debt", "Hybrid"
    date        = Column(Date, nullable=False, index=True)
    nav         = Column(Float)


class MutualFundHolding(Base):
    """AMFI monthly portfolio disclosures — top holdings per scheme."""
    __tablename__ = "mutual_fund_holdings"
    __table_args__ = (
        UniqueConstraint("scheme_code", "disclosure_date", "ticker", name="uq_mf_holding"),
        Index("ix_mf_holding_ticker", "ticker"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    scheme_code     = Column(String, nullable=False, index=True)
    disclosure_date = Column(Date, nullable=False, index=True)
    ticker          = Column(String, index=True)            # NSE symbol (may not be in stocks table)
    company_name    = Column(String)
    isin            = Column(String)
    market_value    = Column(Float)                         # in crores INR
    pct_net_assets  = Column(Float)                         # % of scheme AUM
    shares_held     = Column(BigInteger, nullable=True)


class SecFiling(Base):
    """SEC EDGAR 10-K and 10-Q filings with XBRL-extracted key metrics."""
    __tablename__ = "sec_filings"
    __table_args__ = (
        UniqueConstraint("ticker", "filing_type", "period_end", name="uq_sec_filing"),
        Index("ix_sec_filing_ticker_date", "ticker", "filed_date"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    ticker       = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    cik          = Column(String, nullable=False)               # SEC CIK number (zero-padded 10 digits)
    filing_type  = Column(String, nullable=False)               # "10-K" or "10-Q"
    filed_date   = Column(Date, nullable=False, index=True)
    period_end   = Column(Date, nullable=False)                 # fiscal period end date
    accession_no = Column(String)                               # SEC accession number
    filing_url   = Column(String)                               # EDGAR filing index URL
    xbrl_metrics = Column(JSONB)                                # key XBRL extracted numbers
    risk_factors = Column(Text, nullable=True)                  # extracted Risk Factors text (truncated)


class UsOptionsSnapshot(Base):
    """US equity options chain snapshot — per strike, per expiry."""
    __tablename__ = "us_options_snapshots"
    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_date", "expiry", "strike", "option_type",
                         name="uq_us_options"),
        Index("ix_us_options_ticker_date", "ticker", "snapshot_date"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    ticker        = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    expiry        = Column(Date, nullable=False)
    strike        = Column(Float, nullable=False)
    option_type   = Column(String, nullable=False)              # "call" or "put"
    bid           = Column(Float)
    ask           = Column(Float)
    last_price    = Column(Float)
    volume        = Column(Float)
    open_interest = Column(Float)
    implied_vol   = Column(Float)                               # as decimal (0.25 = 25%)
    delta         = Column(Float, nullable=True)
    gamma         = Column(Float, nullable=True)
    theta         = Column(Float, nullable=True)
    vega          = Column(Float, nullable=True)
    in_the_money  = Column(Boolean, nullable=True)


class RbiAnnouncement(Base):
    """RBI press releases and monetary policy announcements."""
    __tablename__ = "rbi_announcements"
    __table_args__ = (
        UniqueConstraint("url", name="uq_rbi_url"),
        Index("ix_rbi_pub_date", "published_date"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    published_date = Column(DateTime(timezone=True), nullable=False, index=True)
    title          = Column(String, nullable=False)
    category       = Column(String)                             # "Monetary Policy", "Regulation", "Data Release"
    url            = Column(String, nullable=False)
    summary        = Column(Text, nullable=True)                # first ~500 chars of body
    sentiment_score = Column(Float, nullable=True)              # −1.0 to +1.0 (hawkish/dovish)
    is_policy_rate  = Column(Boolean, default=False)            # True if repo rate changed


class GoogleTrendsData(Base):
    """Google Trends search interest score for ticker names."""
    __tablename__ = "google_trends"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_gtrends_ticker_date"),
        Index("ix_gtrends_ticker_date", "ticker", "date"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    ticker         = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    date           = Column(Date, nullable=False, index=True)
    interest_score = Column(Integer)                            # 0–100 Google Trends scale
    keyword        = Column(String)                             # search term used
    geo            = Column(String)                             # "US", "IN", ""
    trend_7d_avg   = Column(Float, nullable=True)               # rolling 7-day avg for smoothing


class ValuationMetrics(Base):
    """Computed valuation metrics: DCF, EV/EBITDA, P/B, P/S, PEG."""
    __tablename__ = "valuation_metrics"
    __table_args__ = (
        UniqueConstraint("ticker", "computed_date", name="uq_valuation_ticker_date"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    ticker        = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    computed_date = Column(Date, nullable=False, index=True)
    current_price = Column(Float)

    # Relative valuation
    pe_ratio      = Column(Float, nullable=True)   # P/E (from company_financials)
    pb_ratio      = Column(Float, nullable=True)   # Price / Book Value per share
    ps_ratio      = Column(Float, nullable=True)   # Price / Sales per share
    peg_ratio     = Column(Float, nullable=True)   # PE / EPS growth rate
    ev_ebitda     = Column(Float, nullable=True)   # Enterprise Value / EBITDA
    ev            = Column(Float, nullable=True)   # Enterprise Value (market cap + debt - cash)

    # Intrinsic / DCF
    dcf_value         = Column(Float, nullable=True)   # DCF intrinsic value per share
    wacc              = Column(Float, nullable=True)   # WACC used for DCF (%)
    terminal_growth   = Column(Float, nullable=True)   # terminal growth rate used (%)
    margin_of_safety  = Column(Float, nullable=True)   # (dcf_value - price) / dcf_value * 100

    # Summary
    valuation_label   = Column(String, nullable=True)  # "DEEP_VALUE", "FAIR", "OVERVALUED", "EXPENSIVE"
    composite_score   = Column(Float, nullable=True)   # 0-100 valuation attractiveness (100=cheapest)


class CandlestickPattern(Base):
    """Detected candlestick patterns per ticker per date."""
    __tablename__ = "candlestick_patterns"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_candle_ticker_date"),
    )

    id             = Column(Integer, primary_key=True, autoincrement=True)
    ticker         = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    date           = Column(Date, nullable=False, index=True)
    patterns       = Column(JSONB)       # list of {name, direction, strength} dicts
    dominant       = Column(String, nullable=True)  # strongest detected pattern name
    signal         = Column(String, nullable=True)  # "BULLISH", "BEARISH", "NEUTRAL", "REVERSAL_UP", "REVERSAL_DOWN"
    pattern_count  = Column(Integer, default=0)


class EarningsTranscript(Base):
    """Earnings call transcript summary (from SEC 8-K or external source)."""
    __tablename__ = "earnings_transcripts"
    __table_args__ = (
        UniqueConstraint("ticker", "earnings_date", name="uq_transcript_ticker_date"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    ticker          = Column(String, ForeignKey("stocks.ticker", ondelete="CASCADE"), nullable=False, index=True)
    earnings_date   = Column(Date, nullable=False, index=True)
    fiscal_period   = Column(String, nullable=True)   # "Q1 2025", "FY 2024"
    source_url      = Column(String, nullable=True)
    raw_text        = Column(Text, nullable=True)     # truncated to ~3000 chars for context
    ai_summary      = Column(Text, nullable=True)     # Claude 3-5 sentence summary
    management_tone = Column(String, nullable=True)   # "BULLISH", "CAUTIOUS", "BEARISH"
    key_topics      = Column(JSONB, nullable=True)    # list of key topics/themes mentioned
    sentiment_score = Column(Float, nullable=True)    # -1.0 to +1.0
    guidance_change = Column(String, nullable=True)   # "RAISED", "LOWERED", "MAINTAINED", "NONE"


class PairTrade(Base):
    """Statistical arbitrage pair — cointegrated stock pairs with spread tracking."""
    __tablename__ = "pair_trades"
    __table_args__ = (
        UniqueConstraint("symbol_a", "symbol_b", name="uq_pair_trade"),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    symbol_a             = Column(String, nullable=False, index=True)
    symbol_b             = Column(String, nullable=False, index=True)
    sector               = Column(String, nullable=True)
    cointegration_pvalue = Column(Float, nullable=True)   # Engle-Granger p-value (<0.05 = cointegrated)
    correlation_90d      = Column(Float, nullable=True)   # 90-day Pearson correlation
    spread_mean          = Column(Float, nullable=True)   # historical spread mean
    spread_std           = Column(Float, nullable=True)   # historical spread std dev
    spread_zscore        = Column(Float, nullable=True)   # current spread z-score
    hedge_ratio          = Column(Float, nullable=True)   # OLS beta (shares of B per 1 share of A)
    signal               = Column(String, nullable=True)  # "LONG_A_SHORT_B", "LONG_B_SHORT_A", "NEUTRAL"
    signal_strength      = Column(String, nullable=True)  # "STRONG", "MODERATE", "WEAK"
    last_updated         = Column(DateTime(timezone=True), nullable=True, index=True)
