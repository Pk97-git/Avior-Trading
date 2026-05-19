from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Index
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
    """Full 5-agent scoring engine results + executive decision per ticker per day."""
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
    signal      = Column(String)            # STRONG_BUY / ACCUMULATE / AVOID / DISTRIBUTION
    regime      = Column(String)            # macro regime label at time of analysis

    # ── Per-agent narrative theses ────────────────────────────────────────────
    fundamental_thesis   = Column(JSONB)    # list[str]
    technical_thesis     = Column(JSONB)
    macro_thesis         = Column(JSONB)
    institutional_thesis = Column(JSONB)
    sentiment_thesis     = Column(JSONB)
    memory_thesis        = Column(JSONB)
    vision_score         = Column(Integer)  # 0–100 from VisionAgent (chart pattern analysis)
    vision_thesis        = Column(JSONB)    # list[str] — chart pattern observations
    signal_thesis        = Column(JSONB)    # executive summary bullets


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
