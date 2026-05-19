"""
Sentiment & News Service — Phase 4
=====================================
Handles:
- RSS feeds: Moneycontrol, CNBC, Reuters, Economic Times
- Reddit API (r/investing, r/IndiaInvestments, r/stocks)
- Stocktwits message volume
- LLM-based sentiment scoring (Gemini Pro / OpenAI fallback)
"""
import asyncio
import feedparser
import requests
import re
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.market_data import NewsSentiment
from datetime import datetime
from typing import List, Dict, Optional


# ─── LLM Sentiment Scorer ────────────────────────────────────────────────────

class LLMSentimentScorer:
    """
    Scores news headlines using LLM (Gemini Pro).
    Falls back to rule-based scoring if API key not set.
    """

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.use_llm = bool(self.api_key)
        self.provider = "Groq" if os.getenv("GROQ_API_KEY") else ("Gemini" if os.getenv("GEMINI_API_KEY") else "OpenAI")
        if self.use_llm:
            print(f"  LLM Sentiment: Using {self.provider}")
        else:
            print("  LLM Sentiment: No API key — using rule-based fallback")

    def _rule_based_score(self, text: str) -> tuple[float, float]:
        """Returns (score, confidence) using keyword matching."""
        positive_words = [
            "surge", "rally", "gain", "rise", "beat", "strong", "growth", "bullish",
            "record", "profit", "upgrade", "buy", "outperform", "breakout", "boom",
            "expansion", "recovery", "upside", "positive", "robust"
        ]
        negative_words = [
            "fall", "drop", "crash", "loss", "miss", "weak", "decline", "bearish",
            "sell", "downgrade", "cut", "risk", "concern", "fear", "recession",
            "contraction", "downside", "negative", "warning", "collapse"
        ]
        text_lower = text.lower()
        pos = sum(1 for w in positive_words if w in text_lower)
        neg = sum(1 for w in negative_words if w in text_lower)
        total = pos + neg
        if total == 0:
            return 0.0, 0.3
        score = (pos - neg) / total
        confidence = min(total / 5.0, 0.8)  # More keywords = higher confidence, max 0.8
        return score, confidence

    def _llm_score_batch_groq(self, headlines: List[str]) -> List[tuple[float, float]]:
        import json
        from groq import Groq
        
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines)])
        
        system_prompt = '''You are a strict financial sentiment API. Score each headline for financial market sentiment.
Return ONLY a JSON array of objects with "score" (-1.0 to 1.0) and "confidence" (0.0 to 1.0).
-1.0 = very bearish, 0.0 = neutral, 1.0 = very bullish.
The output MUST be valid JSON like: [{"score": 0.5, "confidence": 0.8}]'''

        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Headlines:\n{headlines_text}"}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            # groq json_mode requires the output to be an object, not a raw array.
            # We must trick it lightly or parse it safely
            raw_text = completion.choices[0].message.content
            
            # Try parsing direct array
            try:
                results = json.loads(raw_text)
                if isinstance(results, dict):
                    # If wrapped in an object like {"results": [...]}
                    for k, v in results.items():
                        if isinstance(v, list):
                            results = v
                            break
            except Exception as e:
                print(f"  [WARN] Groq JSON parse error: {e}")
                results = []

            if not isinstance(results, list):
                print(f"  [WARN] Groq did not return a list: {results}")
                results = []

            return [(float(r.get("score", 0)), float(r.get("confidence", 0))) for r in results]
            
        except Exception as e:
            print(f"  [WARN] Groq LLM scoring failed ({e}), using rule-based")
            return [self._rule_based_score(h) for h in headlines]

    def _llm_score_batch(self, headlines: List[str]) -> List[tuple[float, float]]:
        """Scores a batch of headlines using the configured LLM."""
        if os.getenv("GROQ_API_KEY"):
            return self._llm_score_batch_groq(headlines)
        
        # Original Gemini Fallback
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel("gemini-pro")

            headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines)])
            prompt = f"""Score each headline for financial market sentiment.
Return ONLY a JSON array of objects with "score" (-1.0 to 1.0) and "confidence" (0.0 to 1.0).
-1.0 = very bearish, 0.0 = neutral, 1.0 = very bullish.

Headlines:
{headlines_text}

Return format: [{{"score": 0.5, "confidence": 0.8}}, ...]"""

            response = model.generate_content(prompt)
            import json
            text = response.text.strip()
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            results = json.loads(text)
            return [(r["score"], r["confidence"]) for r in results]

        except Exception as e:
            print(f"  [WARN] LLM scoring failed ({e}), using rule-based")
            return [self._rule_based_score(h) for h in headlines]

    def score(self, headline: str) -> tuple[float, float]:
        """Score a single headline. Returns (score, confidence)."""
        if self.use_llm:
            results = self._llm_score_batch([headline])
            return results[0] if results else self._rule_based_score(headline)
        return self._rule_based_score(headline)

    def score_batch(self, headlines: List[str]) -> List[tuple[float, float]]:
        """Score a batch of headlines efficiently."""
        if self.use_llm and headlines:
            # Batch in groups of 20 to stay within token limits
            results = []
            for i in range(0, len(headlines), 20):
                batch = headlines[i:i+20]
                results.extend(self._llm_score_batch(batch))
            return results
        return [self._rule_based_score(h) for h in headlines]



RSS_FEEDS = {
    "Moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "CNBC": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "Reuters_Markets": "https://feeds.reuters.com/news/wealth",   # updated — businessNews is dead
    "Economic_Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Livemint": "https://www.livemint.com/rss/markets",
    "BBC_Business": "https://feeds.bbci.co.uk/news/business/rss.xml",  # fallback source
}


class SentimentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._scorer = LLMSentimentScorer()  # uses LLM if API key set, else rule-based

    async def _upsert_sentiment(self, records: List[Dict]):
        if not records:
            return
        stmt = pg_insert(NewsSentiment).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["time", "ticker"])
        await self.db.execute(stmt)
        await self.db.commit()

    def _extract_tickers_from_text(self, text: str, known_tickers: List[str]) -> List[str]:
        """Regex-based ticker extraction ensuring full word boundaries."""
        found = []
        for ticker in known_tickers:
            # Match ticker symbol strictly with word boundaries
            base = ticker.replace(".NS", "").replace("-USD", "")
            # \b ensures we match "A" in "Company A acquires..." but not "A" in "Abc"
            if re.search(rf'\b{re.escape(base)}\b', text, re.IGNORECASE):
                found.append(ticker)
        return found if found else ["MARKET"]  # fallback to market-level

    def _simple_sentiment_score(self, text: str) -> float:
        """
        Rule-based sentiment scoring (no LLM dependency for Phase 1).
        Returns -1.0 (very negative) to +1.0 (very positive).
        LLM scoring is plugged in Phase 4.
        """
        positive_words = ["surge", "rally", "gain", "rise", "beat", "strong", "growth",
                          "bullish", "record", "profit", "upgrade", "buy", "outperform"]
        negative_words = ["fall", "drop", "crash", "loss", "miss", "weak", "decline",
                          "bearish", "sell", "downgrade", "cut", "risk", "concern", "fear"]

        text_lower = text.lower()
        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)

        total = pos_count + neg_count
        if total == 0:
            return 0.0
        return (pos_count - neg_count) / total

    async def fetch_rss_news(self, known_tickers: List[str] = None):
        """
        Fetches headlines from RSS feeds and scores sentiment.
        """
        if known_tickers is None:
            known_tickers = ["AAPL", "MSFT", "RELIANCE", "TCS", "INFY", "NIFTY", "SENSEX"]

        records = []
        for source_name, feed_url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:20]:  # Latest 20 per source
                    title = entry.get("title", "")
                    link = entry.get("link", "")
                    published = entry.get("published_parsed")

                    if not title:
                        continue

                    pub_dt = datetime(*published[:6]) if published else datetime.utcnow()
                    score, confidence = self._scorer.score(title)
                    tickers = self._extract_tickers_from_text(title, known_tickers)

                    for ticker in tickers[:1]:  # One record per headline
                        records.append({
                            "time": pub_dt,
                            "ticker": ticker,
                            "headline": title[:500],
                            "source": source_name,
                            "url": link[:500],
                            "sentiment_score": score,
                            "confidence": confidence,
                        })

            except Exception as e:
                print(f"  [ERROR] RSS {source_name}: {e}")

        await self._upsert_sentiment(records)
        print(f"  Ingested {len(records)} news sentiment records")

    async def fetch_reddit_sentiment(self, subreddits: List[str] = None):
        """
        Fetches Reddit post titles from investing subreddits.
        Uses Reddit's public JSON API (no auth needed for read-only).
        """
        if subreddits is None:
            subreddits = ["investing", "stocks", "IndiaInvestments", "IndianStockMarket"]

        records = []
        for sub in subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
                headers = {"User-Agent": "OmniTrader/1.0"}
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code != 200:
                    continue

                posts = response.json().get("data", {}).get("children", [])
                for post in posts:
                    data = post.get("data", {})
                    title = data.get("title", "")
                    score = data.get("score", 0)
                    created = data.get("created_utc", 0)

                    if not title or score < 10:  # Filter low-engagement posts
                        continue

                    pub_dt = datetime.utcfromtimestamp(created)
                    sentiment, _conf = self._scorer.score(title)

                    # Map to the US or India index so it satisfies the TimescaleDB FK Constraint 
                    # instead of the illegal text 'MARKET'
                    index_ticker = "^NSEI" if "India" in sub else "^GSPC"

                    records.append({
                        "time": pub_dt,
                        "ticker": index_ticker,
                        "headline": title[:500],
                        "source": f"Reddit_r/{sub}",
                        "url": f"https://reddit.com{data.get('permalink', '')}",
                        "sentiment_score": sentiment,
                        "confidence": min(score / 1000, 1.0),  # Upvotes as confidence proxy
                    })

            except Exception as e:
                print(f"  [ERROR] Reddit r/{sub}: {e}")

        await self._upsert_sentiment(records)
        print(f"  Ingested {len(records)} Reddit sentiment records")

    async def fetch_stocktwits_sentiment(self, tickers: List[str]):
        """
        Fetches Stocktwits message stream for ticker-level sentiment.
        Public API, no auth required.
        """
        records = []
        for ticker in tickers:
            try:
                url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
                response = requests.get(url, timeout=10)

                if response.status_code != 200:
                    continue

                messages = response.json().get("messages", [])
                for msg in messages[:10]:
                    body = msg.get("body", "")
                    entities = msg.get("entities", {})
                    sentiment_data = entities.get("sentiment", {})
                    st_sentiment = sentiment_data.get("basic", "Neutral")

                    score_map = {"Bullish": 0.7, "Bearish": -0.7, "Neutral": 0.0}
                    score = score_map.get(st_sentiment, 0.0)

                    created_at = msg.get("created_at", "")
                    try:
                        pub_dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
                    except Exception:
                        pub_dt = datetime.utcnow()

                    records.append({
                        "time": pub_dt,
                        "ticker": ticker,
                        "headline": body[:500],
                        "source": "Stocktwits",
                        "url": f"https://stocktwits.com/symbol/{ticker}",
                        "sentiment_score": score,
                        "confidence": 0.6,
                    })

            except Exception as e:
                print(f"  [ERROR] Stocktwits {ticker}: {e}")

        await self._upsert_sentiment(records)
        print(f"  Ingested {len(records)} Stocktwits sentiment records")

    async def fetch_yahoo_finance_news(self, tickers: List[str]):
        """Fetch Yahoo Finance news for specific tickers — covers small/mid caps."""
        import yfinance as yf

        records = []
        loop = asyncio.get_event_loop()

        for ticker in tickers[:50]:  # limit to 50 per call
            try:
                def _fetch(t=ticker):
                    stock = yf.Ticker(t)
                    return stock.news  # list of dicts with title, publisher, link, providerPublishTime

                news_items = await loop.run_in_executor(None, _fetch)
                if not news_items:
                    continue

                for item in news_items[:5]:  # top 5 per ticker
                    title = item.get("title", "")
                    if not title:
                        continue
                    pub_time = item.get("providerPublishTime", 0)
                    pub_dt = datetime.utcfromtimestamp(pub_time) if pub_time else datetime.utcnow()
                    score, confidence = self._scorer.score(title)

                    records.append({
                        "time": pub_dt,
                        "ticker": ticker,
                        "headline": title[:500],
                        "source": f"Yahoo_{item.get('publisher', 'Finance')}",
                        "url": item.get("link", "")[:500],
                        "sentiment_score": score,
                        "confidence": confidence,
                    })
            except Exception as e:
                print(f"  [WARN] Yahoo news {ticker}: {e}")

        await self._upsert_sentiment(records)
        print(f"  Yahoo Finance: ingested {len(records)} records for {len(tickers)} tickers")

    async def fetch_finviz_news(self, tickers: List[str]):
        """Scrape FinViz news for ticker-specific headlines."""
        records = []
        loop = asyncio.get_event_loop()

        for ticker in tickers[:30]:  # limit requests
            try:
                url = f"https://finviz.com/quote.ashx?t={ticker}"
                headers = {"User-Agent": "Mozilla/5.0 (compatible; OmniTrader/1.0)"}

                def _scrape(t=ticker, u=url):
                    resp = requests.get(u, headers=headers, timeout=8)
                    if resp.status_code != 200:
                        return []
                    # Parse news table: anchor tags with class "tab-link-news"
                    titles = re.findall(r'<a[^>]+class="tab-link-news"[^>]*>([^<]+)</a>', resp.text)
                    return titles[:5]

                titles = await loop.run_in_executor(None, _scrape)
                for title in titles:
                    score, confidence = self._scorer.score(title)
                    records.append({
                        "time": datetime.utcnow(),
                        "ticker": ticker,
                        "headline": title[:500],
                        "source": "FinViz",
                        "url": f"https://finviz.com/quote.ashx?t={ticker}",
                        "sentiment_score": score,
                        "confidence": confidence,
                    })
            except Exception as e:
                print(f"  [WARN] FinViz {ticker}: {e}")

            await asyncio.sleep(0.5)  # polite rate limiting

        await self._upsert_sentiment(records)
        print(f"  FinViz: ingested {len(records)} records for {len(tickers)} tickers")
