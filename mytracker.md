For any active stock in the OmniTrader AI universe (whether it's a US mega-cap like Apple or an Indian stock from the Nifty 500), our ingestion engine automatically builds a rich, multi-dimensional "Data Profile" spanning several years.

Here is exactly what we fetch and calculate for every stock in the database:

1. Market & Price History (The "Technical" Layer)
We download the maximum total history available for every ticker. This updates daily at midnight.

Daily OHLCV: Open, High, Low, Close, and Volume.
Adjusted Prices: Factoring in historical stock splits and dividend payouts to ensure accurate charts.
This powers our charting UI widgets and the AI Technical Agent's Moving Average (20/50/200) and RSI calculations.
2. Deep Financial Statements (The "Fundamental" Layer)
We ingest up to 5 years of full audited corporate filings directly via Yahoo Finance APIs on a weekly basis.

Income Statements (JSON): Revenue, Operating Income, Taxes, Net Income, EBIT, EBITDA.
Balance Sheets (JSON): Total Assets, Current/Long-term Liabilities, Total Debt, Stockholders' Equity.
Cash Flow Statements (JSON): Operating Cash Flow, Capex.
Auto-Calculated Ratios: Free Cash Flow (FCF), Return on Invested Capital (ROIC), Return on Equity (ROE), Debt-to-Equity (D/E), and Operating Margins.
3. News & AI Sentiment (The "Narrative" Layer)
We scrape continuous pipelines from top financial news sites (CNBC, Bloomberg, Reuters, Economic Times, Livemint, Moneycontrol).

Headlines & Sources: Every article mentioning the specific company name or ticker exactly.
LLM Sentiment Scoring: Our built-in Sentiment Engine processes the headline text to assign a mathematical 

sentiment_score
 ranging from -1.0 (Panic/Bearish) to +1.0 (Euphoric/Bullish).
4. Ownership & Flow (The "Institutional" Layer)
Tracking "smart money" movements (this specifically targets the Indian NSE stocks as per the PRD right now).

Shareholding Patterns: Exactly what percentage of the stock is held by the Corporate Promoters vs. Foreign Institutional Investors (FIIs) vs. Domestic Institutions (DIIs) vs. Retail Public.
5. Autonomous AI Engine Outputs
While we don't "fetch" this from outside, our internal AI Scoring Agents digest all the data above to generate proprietary insights:

Fundamental Conviction Score (0-100): Looking at compounding EPS growth and clean balance sheets.
Technical Conviction Score (0-100): Looking at trend stability (Stage 2 Uptrends) and volume breakouts.
Human-Readable Theses: A generated bullet-list explaining why the AI assigned the scores it did.