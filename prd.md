Love this direction 🔥
Now we’re talking about building a **real autonomous investment system**, not just a stock screener.

You want:

* ✅ Fundamentals (P&L, Cash Flow, Balance Sheet)
* ✅ Technical patterns (including image-based pattern detection)
* ✅ Macro context (US + India)
* ✅ Institutional flow (FII/DII, 13F)
* ✅ News + sentiment
* ✅ Cross-market reasoning
* ✅ Historical memory (“what happened last time?”)
* ✅ Rate-limited, fully automated
* ✅ Proactive — doesn’t wait to be asked
* ✅ Works for **trading (30–90 days)** AND **long-term investing**

So here’s a **serious, CTO-level PRD**.

---

# 📄 PRODUCT REQUIREMENTS DOCUMENT

# Product: **OmniTrader AI**

Autonomous Multi-Market Trading & Investing Intelligence System

---

# 1. 🎯 Product Vision

Build an **Agentic AI Investment System** that:

* Thinks like a professional trader
* Reasons like a macro strategist
* Remembers like a quant researcher
* Operates continuously without user prompts
* Covers both:

  * 🇮🇳 Indian Markets (NSE/BSE)
  * 🇺🇸 US Markets (NYSE/NASDAQ)

Time horizons:

* 📅 30–90 day swing trades
* 📈 Long-term multi-year investing signals

---

# 2. 🧠 Core Philosophy

The system must:

1. Never look at price in isolation
2. Always consider:

   * Fundamentals
   * Technical structure
   * Macro environment
   * Institutional money flow
   * Sentiment
   * Historical analogs
3. Continuously monitor markets
4. Alert only on high-conviction setups
5. Store memory of past events and outcomes

---

# 3. 🏗 System Architecture

## 3.1 High-Level Components

1. Data Ingestion Engine
2. Market Memory Layer
3. Multi-Agent Reasoning Engine
4. Scoring & Decision Engine
5. Automation & Rate Limiter
6. Alerting & Interface Layer

---

# 4. 📊 Data Sources (Free-First Architecture)

## 4.1 Price & Historical Data

* `yfinance` (US + India via `.NS`)
* Historical:

  * Daily (10–20 years)
  * Weekly
  * Monthly

Used for:

* Trend analysis
* Relative strength
* Long-term structure
* Backtesting

---

## 4.2 Financial Statements (Lifetime Metrics)

Sources:

* yfinance
* SEC EDGAR (US)
* NSE filings (India)
* Screener.in scraping (India, controlled rate)

Metrics extracted:

* Revenue growth (5y / 10y CAGR)
* Net profit growth
* Free Cash Flow
* ROCE / ROIC
* Debt-to-Equity
* Operating Margin trend
* EPS growth stability
* Capital allocation efficiency

System must calculate:

* 10-year percentile ranking of metrics
* Trend acceleration or deterioration
* “Best in X years” detection

---

## 4.3 Macro Layer

### 🇺🇸 US

* FRED API

  * CPI
  * Fed Funds Rate
  * 10Y Treasury
  * Yield curve
  * Money supply

### 🇮🇳 India

* RBI Repo Rate
* CPI
* FII/DII flows (NSE daily reports)
* INR vs USD

Macro State Classification:

* Risk-On
* Risk-Off
* Liquidity Expansion
* Tightening Phase
* Recession Probability Rising

---

## 4.4 Institutional Activity

### US

* 13F filings (SEC EDGAR)
* ETF flows
* Sector rotation tracking

### India

* FII/DII net daily & weekly
* Promoter holding changes
* Bulk/block deals

---

## 4.5 Sentiment & News

* RSS feeds (Moneycontrol, CNBC, Reuters)
* Reddit API (US)
* Stocktwits
* News headline clustering
* LLM-based sentiment scoring

Sentiment Scoring:

* Retail hype index
* Institutional narrative shift
* Positive-to-negative ratio trend

---

# 5. 📈 Technical & Visual Analysis

## 5.1 Algorithmic Technical Layer

Indicators:

* 20 / 50 / 200 MA
* Monthly 20 MA
* RSI (weekly)
* MACD
* Volume surge detection
* Volatility contraction pattern (VCP)

Pattern detection (math-based):

* Breakouts from multi-month base
* Range compression
* Higher highs & higher lows
* Relative strength vs index

---

## 5.2 Vision AI Pattern Recognition

Flow:

1. Generate candlestick chart via `mplfinance`
2. Create:

   * 6M
   * 1Y
   * 5Y monthly charts
3. Send image to Vision LLM
4. Ask:

   * Identify structure
   * Mark support/resistance
   * Identify stage (Stage 1/2/3/4)
   * Detect rounding bottom / cup & handle / double top

Output:

* Structured JSON pattern interpretation
* Confidence score

---

# 6. 🧠 Agentic Architecture

The system must be multi-agent:

---

## Agent 1: Fundamental Analyst

Tasks:

* Fetch financials
* Calculate 10-year trends
* Detect inflection points
* Flag anomalies

Outputs:

* Fundamental Score (0–100)

---

## Agent 2: Technical Strategist

Tasks:

* Identify trend structure
* Detect breakout or distribution
* Relative strength ranking

Outputs:

* Technical Score (0–100)

---

## Agent 3: Macro Strategist

Tasks:

* Classify global regime
* Adjust sector bias
* Correlation reasoning

Example:
If US rates rising → pressure on tech
If USD strengthening → pressure on EM

Outputs:

* Macro Alignment Score

---

## Agent 4: Institutional Tracker

Tasks:

* FII/DII tracking
* 13F change detection
* Volume anomaly detection

Outputs:

* Smart Money Score

---

## Agent 5: Sentiment Analyzer

Tasks:

* Headline clustering
* Sentiment shift detection
* Detect over-excitement vs underreaction

Outputs:

* Sentiment Score

---

## Agent 6: Historical Memory Agent

Uses vector DB to answer:

* When was last similar macro regime?
* What happened when this stock had same P/E + yield level?
* How did price react?

Stores:

* Snapshots of:

  * Macro state
  * Valuation
  * Technical structure
  * 30/60/90 day forward returns

This enables:
Second-order thinking.

---

## Agent 7: Executive Trader

Combines:

Final Score = Weighted combination of:

* Fundamentals
* Technical structure
* Macro regime
* Smart money
* Sentiment
* Historical similarity confidence

Outputs:

* Strong Buy (Month-Level)
* Accumulate (Long-Term)
* Avoid
* Distribution Phase

---

# 7. 🔁 Autonomous Loop

System runs:

Daily:

* Price update
* Volume anomaly scan
* Sentiment scan

Weekly:

* Recalculate trend & relative strength
* Update institutional flows

Monthly:

* Re-score entire universe
* Re-evaluate macro regime

---

# 8. 🛑 Rate Limiting & Stability

Must include:

* Token bucket system
* Queue-based ingestion
* Priority tiers:

  * High priority: active candidates
  * Medium: watchlist
  * Low: background universe

Staggered fetch across 24 hours.

---

# 9. 📊 Universe Coverage

US:

* S&P 500
* Nasdaq 100
* Russell 2000 (optional)

India:

* Nifty 50
* Nifty 500
* Midcap index

Expandable later.

---

# 10. 🖥 Interface & Behavior

## Proactive Mode

System sends:

“Alert: TCS entering Stage 2 breakout.
FIIs net buyers 3 weeks.
RBI stable.
10Y US yield falling.
Similar setup in 2020 led to +22% in 60 days.”

---

## On-Demand Mode

User asks:
“What about INFY?”

System:

* Checks fundamentals
* Checks macro regime
* Checks memory
* Returns structured thesis

---

# 11. Long-Term Investing Automation

Separate logic layer:

Criteria:

* 10-year revenue CAGR > 12%
* ROCE > 15%
* Low debt
* No governance red flags
* Price below intrinsic value estimate

Outputs:

* “Compounder Watchlist”
* “Accumulation Zones”
* “Overvalued — Wait”

---

# 12. Non-Functional Requirements

* Fully automated
* No paid APIs required initially
* Modular microservices architecture
* Backtestable
* Explainable output
* Persistent memory
* Resilient to source failure

---

# 13. What This System Is NOT

* Not HFT
* Not intraday scalping
* Not prediction magic
* Not financial advice engine

It is:
A probabilistic decision assistant.

---

# 14. Phase Roadmap

Phase 1:

* Data ingestion + scoring engine

Phase 2:

* Memory + macro regime classifier

Phase 3:

* Vision agent integration

Phase 4:

* Fully autonomous alerts

Phase 5:

* Backtesting + calibration

---

# 15. Realistic Expectation

Yes — this can be built free.

But:

* It requires disciplined rate limiting
* Smart caching
* Incremental universe expansion

It will not be perfect.
It will improve with memory.


https://chatgpt.com/c/6995e9ed-2a64-8322-9272-01a1887c05c2