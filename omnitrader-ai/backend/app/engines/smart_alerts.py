"""
engines/smart_alerts.py
=======================
SmartAlertEngine — scans market data every 15 minutes and fires alerts
when user-defined conditions are met.

Alert types:
  EARNINGS_APPROACHING  — earnings report within N days for portfolio/watchlist stocks
  INSIDER_SPIKE         — unusual insider buying (volume > threshold shares)
  RSI_OVERBOUGHT        — RSI-14 > threshold (default 70)
  RSI_OVERSOLD          — RSI-14 < threshold (default 30)
  SENTIMENT_SHIFT       — avg sentiment last 24h shifted > threshold vs 7-day baseline
  OPTIONS_ACTIVITY      — unusual IV spike or volume vs open interest ratio
  PRICE_TARGET          — price crossed above/below a target level
  SCORE_CHANGE          — AI score crossed threshold (e.g. score fell below 50)
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data import Alert, AlertRule, AutomationRule  # noqa: F401

logger = logging.getLogger(__name__)


class SmartAlertEngine:
    """
    Checks all active AlertRule rows and fires alerts when conditions are met.
    Designed to be called on a recurring schedule (e.g. every 15 minutes).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_all_checks(self) -> dict:
        """
        Load all active AlertRules, dispatch each group to the appropriate
        check method, fire notifications, and return a summary dict.
        """
        result = await self.db.execute(
            select(AlertRule).where(AlertRule.is_active == True)  # noqa: E712
        )
        rules: list[AlertRule] = list(result.scalars().all())

        # Group rules by alert_type
        groups: dict[str, list[AlertRule]] = {}
        for rule in rules:
            groups.setdefault(rule.alert_type, []).append(rule)

        fired_alerts: list[dict] = []

        dispatch = {
            "EARNINGS_APPROACHING": self._check_earnings_approaching,
            "INSIDER_SPIKE":        self._check_insider_spike,
            "RSI_OVERBOUGHT":       self._check_rsi_levels,
            "RSI_OVERSOLD":         self._check_rsi_levels,
            "SENTIMENT_SHIFT":      self._check_sentiment_shift,
            "OPTIONS_ACTIVITY":     self._check_options_activity,
            "PRICE_TARGET":         self._check_price_target,
            "SCORE_CHANGE":         self._check_score_change,
        }

        for alert_type, type_rules in groups.items():
            handler = dispatch.get(alert_type)
            if handler is None:
                logger.warning("No handler for alert_type=%s", alert_type)
                continue
            try:
                alerts = await handler(type_rules)
                fired_alerts.extend(alerts)
            except Exception as exc:
                logger.error("Error in handler for %s: %s", alert_type, exc, exc_info=True)

        # Persist + notify each fired alert
        for alert in fired_alerts:
            rule = alert.pop("_rule", None)
            if rule is not None:
                await self._fire_alert(alert, rule)

        try:
            await self.db.commit()
        except Exception as exc:
            logger.error("Failed to commit alert updates: %s", exc)
            await self.db.rollback()

        return {
            "checked": len(rules),
            "fired": len(fired_alerts),
            "alerts": fired_alerts,
        }

    # ------------------------------------------------------------------
    # Check methods
    # ------------------------------------------------------------------

    async def _check_earnings_approaching(self, rules: list[AlertRule]) -> list[dict]:
        alerts: list[dict] = []

        for rule in rules:
            if not self._should_fire(rule):
                continue

            days_ahead = (rule.condition or {}).get("days_ahead", 7)
            sql = text("""
                SELECT eh.ticker, eh.report_date, eh.eps_estimate, s.name,
                       EXTRACT(DAY FROM (eh.report_date::timestamptz - NOW())) AS days_away
                FROM earnings_history eh
                JOIN stocks s ON s.ticker = eh.ticker
                WHERE eh.report_date BETWEEN NOW() AND NOW() + :days_ahead * INTERVAL '1 day'
                  AND eh.report_date > NOW()
            """)
            try:
                rows = (await self.db.execute(sql, {"days_ahead": days_ahead})).fetchall()
            except Exception as exc:
                logger.warning("earnings_approaching query failed: %s", exc)
                continue

            for row in rows:
                ticker, report_date, eps_estimate, name, days_away = (
                    row.ticker, row.report_date, row.eps_estimate, row.name, row.days_away
                )
                if rule.ticker and ticker != rule.ticker:
                    continue
                alerts.append({
                    "type": "EARNINGS_APPROACHING",
                    "ticker": ticker,
                    "headline": f"{name} reports earnings in {days_away:.0f} days",
                    "detail": {
                        "report_date": str(report_date),
                        "eps_estimate": eps_estimate,
                    },
                    "severity": "HIGH" if days_away <= 2 else "MEDIUM",
                    "_rule": rule,
                })

        return alerts

    async def _check_insider_spike(self, rules: list[AlertRule]) -> list[dict]:
        alerts: list[dict] = []

        for rule in rules:
            if not self._should_fire(rule):
                continue

            min_shares = (rule.condition or {}).get("min_shares", 10_000)
            sql = text("""
                SELECT it.ticker, it.insider_name, it.transaction_type,
                       it.shares, it.total_value AS value_usd, it.transaction_date, s.name
                FROM insider_transactions it
                JOIN stocks s ON s.ticker = it.ticker
                WHERE it.transaction_date >= NOW() - INTERVAL '7 days'
                  AND it.transaction_type = 'BUY'
                  AND it.shares >= :min_shares
                ORDER BY it.shares DESC
                LIMIT 20
            """)
            try:
                rows = (await self.db.execute(sql, {"min_shares": min_shares})).fetchall()
            except Exception as exc:
                logger.warning("insider_spike query failed: %s", exc)
                continue

            for row in rows:
                ticker = row.ticker
                if rule.ticker and ticker != rule.ticker:
                    continue
                insider_name = row.insider_name
                shares = row.shares
                value_usd = row.value_usd
                name = row.name
                alerts.append({
                    "type": "INSIDER_SPIKE",
                    "ticker": ticker,
                    "headline": f"Insider buying: {insider_name} bought {shares:,.0f} shares of {name}",
                    "detail": {
                        "insider": insider_name,
                        "shares": shares,
                        "value_usd": value_usd,
                    },
                    "severity": "HIGH" if shares > 100_000 else "MEDIUM",
                    "_rule": rule,
                })

        return alerts

    async def _check_rsi_levels(self, rules: list[AlertRule]) -> list[dict]:
        alerts: list[dict] = []

        sql = text("""
            SELECT t.ticker, t.rsi_14, s.name, s.sector, sp.close AS price
            FROM stock_technicals t
            JOIN stocks s ON s.ticker = t.ticker
            LEFT JOIN LATERAL (
                SELECT close FROM stock_prices WHERE ticker = t.ticker ORDER BY time DESC LIMIT 1
            ) sp ON true
            WHERE t.rsi_14 IS NOT NULL
        """)
        try:
            rows = (await self.db.execute(sql)).fetchall()
        except Exception as exc:
            logger.warning("rsi_levels query failed: %s", exc)
            return alerts

        row_map = {row.ticker: row for row in rows}

        for rule in rules:
            if not self._should_fire(rule):
                continue

            condition = rule.condition or {}
            is_overbought = rule.alert_type == "RSI_OVERBOUGHT"

            if is_overbought:
                threshold = condition.get("threshold", 70)
            else:
                threshold = condition.get("threshold", 30)

            candidates = list(row_map.values())
            if rule.ticker:
                candidates = [r for r in candidates if r.ticker == rule.ticker]

            for row in candidates:
                rsi = row.rsi_14
                ticker = row.ticker
                name = row.name
                sector = row.sector
                price = row.price

                if is_overbought and rsi <= threshold:
                    continue
                if not is_overbought and rsi >= threshold:
                    continue

                label = "overbought" if rsi > 70 else "oversold"
                alert_type = "RSI_OVERBOUGHT" if is_overbought else "RSI_OVERSOLD"
                alerts.append({
                    "type": alert_type,
                    "ticker": ticker,
                    "headline": f"{name} RSI at {rsi:.1f} — {label}",
                    "detail": {
                        "rsi_14": rsi,
                        "price": price,
                        "sector": sector,
                    },
                    "severity": "HIGH" if (rsi > 80 or rsi < 20) else "MEDIUM",
                    "_rule": rule,
                })

        return alerts

    async def _check_sentiment_shift(self, rules: list[AlertRule]) -> list[dict]:
        alerts: list[dict] = []

        sql = text("""
            SELECT ticker,
                   AVG(CASE WHEN published_at >= NOW() - INTERVAL '24 hours' THEN sentiment_score END) AS recent_avg,
                   AVG(CASE WHEN published_at < NOW() - INTERVAL '24 hours'
                             AND published_at >= NOW() - INTERVAL '8 days' THEN sentiment_score END) AS baseline_avg,
                   COUNT(*) FILTER (WHERE published_at >= NOW() - INTERVAL '24 hours') AS recent_count
            FROM news_sentiment
            WHERE published_at >= NOW() - INTERVAL '8 days'
            GROUP BY ticker
            HAVING COUNT(*) FILTER (WHERE published_at >= NOW() - INTERVAL '24 hours') >= 2
        """)
        try:
            rows = (await self.db.execute(sql)).fetchall()
        except Exception as exc:
            logger.warning("sentiment_shift query failed: %s", exc)
            return alerts

        for rule in rules:
            if not self._should_fire(rule):
                continue

            threshold = (rule.condition or {}).get("threshold", 0.3)

            for row in rows:
                ticker = row.ticker
                recent_avg = row.recent_avg
                baseline_avg = row.baseline_avg

                if rule.ticker and ticker != rule.ticker:
                    continue
                if recent_avg is None or baseline_avg is None:
                    continue

                shift = recent_avg - baseline_avg
                if abs(shift) <= threshold:
                    continue

                direction = "turned positive" if recent_avg > baseline_avg else "turned negative"
                alerts.append({
                    "type": "SENTIMENT_SHIFT",
                    "ticker": ticker,
                    "headline": f"Sentiment shift for {ticker}: {direction} ({shift:+.2f} from baseline)",
                    "detail": {
                        "recent_avg": recent_avg,
                        "baseline_avg": baseline_avg,
                        "shift": shift,
                    },
                    "severity": "HIGH" if abs(shift) > 0.5 else "MEDIUM",
                    "_rule": rule,
                })

        return alerts

    async def _check_options_activity(self, rules: list[AlertRule]) -> list[dict]:
        alerts: list[dict] = []

        sql = text("""
            SELECT DISTINCT ON (ticker)
                ticker,
                implied_volatility, volume, open_interest,
                CASE WHEN open_interest > 0 THEN volume::float / open_interest ELSE 0 END AS vol_oi_ratio,
                expiry, strike, option_type
            FROM options_chain
            WHERE time >= NOW() - INTERVAL '1 day'
              AND volume > 0
            ORDER BY ticker, vol_oi_ratio DESC
        """)
        try:
            rows = (await self.db.execute(sql)).fetchall()
        except Exception as exc:
            logger.warning("options_activity query failed: %s", exc)
            return alerts

        for rule in rules:
            if not self._should_fire(rule):
                continue

            vol_oi_threshold = (rule.condition or {}).get("vol_oi_threshold", 3.0)

            for row in rows:
                ticker = row.ticker
                if rule.ticker and ticker != rule.ticker:
                    continue

                vol_oi_ratio = row.vol_oi_ratio
                if vol_oi_ratio <= vol_oi_threshold:
                    continue

                iv = row.implied_volatility
                strike = row.strike
                expiry = row.expiry
                option_type = row.option_type

                alerts.append({
                    "type": "OPTIONS_ACTIVITY",
                    "ticker": ticker,
                    "headline": f"Unusual options activity: {ticker} {option_type} vol/OI = {vol_oi_ratio:.1f}x",
                    "detail": {
                        "strike": strike,
                        "expiry": str(expiry),
                        "vol_oi_ratio": vol_oi_ratio,
                        "iv": iv,
                    },
                    "severity": "HIGH" if vol_oi_ratio > 10 else "MEDIUM",
                    "_rule": rule,
                })

        return alerts

    async def _check_price_target(self, rules: list[AlertRule]) -> list[dict]:
        alerts: list[dict] = []

        for rule in rules:
            if not self._should_fire(rule):
                continue
            if not rule.ticker:
                logger.debug("PRICE_TARGET rule %d has no ticker — skipping", rule.id)
                continue

            condition = rule.condition or {}
            target = condition.get("target")
            direction = condition.get("direction", "above")
            if target is None:
                logger.warning("PRICE_TARGET rule %d missing 'target' in condition", rule.id)
                continue

            sql = text(
                "SELECT close FROM stock_prices WHERE ticker = :ticker ORDER BY time DESC LIMIT 1"
            )
            try:
                row = (await self.db.execute(sql, {"ticker": rule.ticker})).fetchone()
            except Exception as exc:
                logger.warning("price_target query failed for %s: %s", rule.ticker, exc)
                continue

            if row is None:
                continue

            close = row.close
            triggered = (
                (direction == "above" and close >= target) or
                (direction == "below" and close <= target)
            )
            if not triggered:
                continue

            alerts.append({
                "type": "PRICE_TARGET",
                "ticker": rule.ticker,
                "headline": f"{rule.ticker} hit price target: ${close:.2f} ({direction} ${target:.2f})",
                "detail": {
                    "price": close,
                    "target": target,
                    "direction": direction,
                },
                "severity": "HIGH",
                "_rule": rule,
            })

        return alerts

    async def _check_score_change(self, rules: list[AlertRule]) -> list[dict]:
        alerts: list[dict] = []

        sql = text("""
            SELECT ticker, final_score, signal, analysis_date
            FROM ai_analysis
            WHERE analysis_date >= NOW() - INTERVAL '2 days'
        """)
        try:
            rows = (await self.db.execute(sql)).fetchall()
        except Exception as exc:
            logger.warning("score_change query failed: %s", exc)
            return alerts

        for rule in rules:
            if not self._should_fire(rule):
                continue

            condition = rule.condition or {}
            threshold = condition.get("threshold", 50)
            direction = condition.get("direction", "below")

            for row in rows:
                ticker = row.ticker
                if rule.ticker and ticker != rule.ticker:
                    continue

                final_score = row.final_score
                signal = row.signal

                triggered = (
                    (direction == "below" and final_score <= threshold) or
                    (direction == "above" and final_score >= threshold)
                )
                if not triggered:
                    continue

                alerts.append({
                    "type": "SCORE_CHANGE",
                    "ticker": ticker,
                    "headline": f"{ticker} AI score {direction} threshold: {final_score}/100 ({signal})",
                    "detail": {
                        "score": final_score,
                        "signal": signal,
                        "threshold": threshold,
                    },
                    "severity": "HIGH" if final_score < 35 or final_score > 80 else "MEDIUM",
                    "_rule": rule,
                })

        return alerts

    # ------------------------------------------------------------------
    # Notification dispatch
    # ------------------------------------------------------------------

    async def _fire_alert(self, alert: dict, rule: AlertRule) -> None:
        """Persist the alert to the DB, send notifications, and update rule metadata."""
        # 1. Persist to the alerts table
        db_alert = Alert(
            ticker=alert.get("ticker"),
            generated_at=datetime.now(timezone.utc),
            signal=alert.get("type"),
            headline=alert.get("headline"),
            thesis=alert.get("detail"),
            is_read=False,
        )
        self.db.add(db_alert)

        # 2. Send via notifications service (non-blocking)
        notify_via = rule.notify_via or []
        if "email" in notify_via or "slack" in notify_via:
            try:
                from app.services.notifications import NotificationService
                svc = NotificationService()
                await svc.send_alert(
                    ticker=alert.get("ticker", "MARKET"),
                    signal=alert.get("type"),
                    headline=alert.get("headline"),
                    thesis_bullets=list(alert.get("detail", {}).values()),
                    final_score=None,
                )
            except Exception as exc:
                logger.warning("Notification failed: %s", exc)

        # 3. Update rule metadata
        rule.last_triggered_at = datetime.now(timezone.utc)
        rule.trigger_count = (rule.trigger_count or 0) + 1

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _should_fire(self, rule: AlertRule, cooldown_hours: int = 4) -> bool:
        """Return True if the rule has not fired within the cooldown window."""
        if rule.last_triggered_at:
            hours_since = (
                datetime.now(timezone.utc) - rule.last_triggered_at
            ).total_seconds() / 3600
            return hours_since >= cooldown_hours
        return True
