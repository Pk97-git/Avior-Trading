from typing import Optional, List, Dict, Tuple
"""
agents/runner.py
================
run_all_agents() — orchestrates all 10 agents + ExecutiveTrader for a
single ticker, persists the result to AIAnalysis, and fires an Alert
if the signal has changed — with 4-hour cooldown deduplication.

Agent Pipeline:
  Phase 1 Core:    Fundamental, Technical, Macro, Institutional, Sentiment, Memory, Vision
  Phase 2 Strategist: Factor, CrossAsset, (Portfolio for context)
  Phase 3 Risk:    CalibrationEngine, SizingEngine, ExecutionModel
  Executive:       Regime-adaptive weighted combination

Alert Gating:
  - Only fires if signal CHANGED, OR
  - Same signal but last alert > ALERT_COOLDOWN_HOURS ago
  - Deduplicates within 24h for same ticker + signal + score range (±5)
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.market_data import AIAnalysis, Alert, Stock
from app.agents.fundamental import FundamentalAgent
from app.agents.technical import TechnicalAgent
from app.agents.macro import MacroAgent
from app.agents.institutional import InstitutionalAgent
from app.agents.sentiment import SentimentAgent
from app.agents.memory import MemoryAgent
from app.agents.vision import VisionAgent
from app.agents.factor import FactorAgent
from app.agents.cross_asset import CrossAssetAgent
from app.agents.portfolio import PortfolioAgent
from app.agents.calibration import CalibrationEngine
from app.agents.sizing import SizingEngine
from app.agents.execution import ExecutionModel
from app.agents.executive import ExecutiveTrader
try:
    from app.agents.transcript import TranscriptAgent
    _TRANSCRIPT_AVAILABLE = True
except ImportError:
    _TRANSCRIPT_AVAILABLE = False

try:
    from app.agents.risk import RiskAgent
    _RISK_AGENT_AVAILABLE = True
except ImportError:
    _RISK_AGENT_AVAILABLE = False

try:
    from app.agents.news import NewsAgent
    _NEWS_AGENT_AVAILABLE = True
except ImportError:
    _NEWS_AGENT_AVAILABLE = False

try:
    from app.agents.market import MarketAgent
    _MARKET_AGENT_AVAILABLE = True
except ImportError:
    _MARKET_AGENT_AVAILABLE = False

try:
    from app.agents.execution_agent import ExecutionAgent
    _EXECUTION_AGENT_AVAILABLE = True
except ImportError:
    _EXECUTION_AGENT_AVAILABLE = False

logger = logging.getLogger(__name__)

ALERT_COOLDOWN_HOURS  = 4
ALERT_DEDUP_HOURS     = 24
ALERT_SCORE_TOLERANCE = 5   # within ±5 points = "same" for dedup purposes


async def _previous_signal(db: AsyncSession, ticker: str) -> Optional[str]:
    stmt = (
        select(AIAnalysis.signal)
        .where(AIAnalysis.ticker == ticker)
        .order_by(AIAnalysis.analysis_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.fetchone()
    return row.signal if row else None


async def _upsert_analysis(db: AsyncSession, ticker: str, analysis_date: datetime, data: dict) -> None:
    safe_data = {k: v for k, v in data.items() if hasattr(AIAnalysis, k)}
    stmt = pg_insert(AIAnalysis).values(
        ticker=ticker,
        analysis_date=analysis_date,
        **safe_data,
    ).on_conflict_do_update(
        index_elements=["ticker", "analysis_date"],
        set_=safe_data,
    )
    await db.execute(stmt)


async def _should_create_alert(
    db: AsyncSession,
    ticker: str,
    signal: str,
    previous_signal: Optional[str],
    final_score: int,
) -> bool:
    """
    Returns True if an alert should be created.
    Rules:
      1. Signal changed → always alert
      2. Same signal → only alert if:
         a. No alert in last ALERT_COOLDOWN_HOURS
         b. AND no duplicate (same ticker, signal, score ±5) in last ALERT_DEDUP_HOURS
    """
    if previous_signal != signal:
        return True   # Signal changed — always fire

    cutoff_cooldown = datetime.now(timezone.utc) - timedelta(hours=ALERT_COOLDOWN_HOURS)
    cutoff_dedup    = datetime.now(timezone.utc) - timedelta(hours=ALERT_DEDUP_HOURS)

    # Check cooldown
    res = await db.execute(text("""
        SELECT COUNT(*) FROM alerts
        WHERE ticker = :ticker AND generated_at >= :cutoff
    """), {"ticker": ticker, "cutoff": cutoff_cooldown})
    recent_count = res.scalar()
    if recent_count and recent_count > 0:
        logger.info("[AlertGate] %s: same signal, within cooldown window — suppressed.", ticker)
        return False

    # Check dedup (same score range)
    res = await db.execute(text("""
        SELECT COUNT(*) FROM alerts
        WHERE ticker = :ticker AND signal = :signal
          AND ABS(final_score - :score) <= :tol
          AND generated_at >= :dedup_cutoff
    """), {
        "ticker": ticker,
        "signal": signal,
        "score": final_score,
        "tol": ALERT_SCORE_TOLERANCE,
        "dedup_cutoff": cutoff_dedup,
    })
    dup_count = res.scalar()
    if dup_count and dup_count > 0:
        logger.info("[AlertGate] %s: duplicate alert suppressed (same signal+score within 24h).", ticker)
        return False

    return True


async def _create_alert(
    db: AsyncSession,
    ticker: str,
    signal: str,
    previous_signal: Optional[str],
    final_score: int,
    signal_thesis: list[str],
) -> None:
    direction = "new" if previous_signal is None else f"{previous_signal} → {signal}"
    headline  = f"{ticker}: signal {direction} (score {final_score}/100)"
    alert = Alert(
        ticker=ticker,
        generated_at=datetime.now(timezone.utc),
        signal=signal,
        previous_signal=previous_signal,
        final_score=final_score,
        headline=headline,
        thesis=signal_thesis[:5],
        is_read=False,
    )
    db.add(alert)

    # Fire notifications (non-blocking — errors are caught and logged)
    try:
        from app.services.notifications import NotificationService
        notif = NotificationService()
        await notif.send_alert(ticker, signal, previous_signal, final_score, signal_thesis[:3])
    except Exception as e:
        logger.warning("Notification failed for %s: %s", ticker, e)


async def run_all_agents(db: AsyncSession, ticker: str) -> dict:
    """
    Run all agents for `ticker`. Returns full analysis dict.
    Also persists result and fires a gated alert if warranted.
    """
    ticker = ticker.upper()
    logger.info("Running all agents for %s", ticker)

    analysis_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Circuit breaker gate — skip analysis if market conditions say HALT ──
    from app.engines.circuit_breaker import CircuitBreakerEngine
    cb = CircuitBreakerEngine(db)
    cb_state = await cb.check()
    if not cb_state["trading_allowed"]:
        logger.warning("[CircuitBreaker] HALT for %s — reasons: %s", ticker, cb_state["reasons"])
        # Still return a minimal result so callers don't crash
        return {
            "ticker": ticker,
            "analysis_date": analysis_date.isoformat(),
            "signal": "REDUCE",
            "final_score": 30,
            "regime": "Unknown",
            "circuit_breaker": cb_state,
            "signal_thesis": cb_state["reasons"],
        }
    elif cb_state["caution"]:
        logger.info("[CircuitBreaker] CAUTION for %s — %s", ticker, cb_state["reasons"])
        # Continue analysis but flag it in the result

    # ── Phase 1: Core agents (run sequentially to avoid asyncpg session conflicts) ──
    try:
        fund_result = await FundamentalAgent(db, ticker).analyze()
    except Exception as e:
        fund_result = e

    try:
        tech_result = await TechnicalAgent(db, ticker).analyze()
    except Exception as e:
        tech_result = e

    try:
        macro_result = await MacroAgent(db, ticker).analyze()
    except Exception as e:
        macro_result = e

    market_result = {"score": 50, "thesis": [], "market_regime": "Unknown"}
    if _MARKET_AGENT_AVAILABLE:
        try:
            market_result = await MarketAgent(db, ticker).analyze()
        except Exception as e:
            logger.debug("MarketAgent failed for %s: %s", ticker, e)

    try:
        inst_result = await InstitutionalAgent(db, ticker).analyze()
    except Exception as e:
        inst_result = e

    try:
        sent_result = await SentimentAgent(db, ticker).analyze()
    except Exception as e:
        sent_result = e

    try:
        mem_result = await MemoryAgent(db, ticker).analyze()
    except Exception as e:
        mem_result = e

    try:
        vision_result = await VisionAgent(db, ticker).analyze()
    except Exception as e:
        vision_result = e

    risk_result = {"score": 50, "thesis": [], "risk_flags": []}
    if _RISK_AGENT_AVAILABLE:
        try:
            risk_result = await RiskAgent(db, ticker).analyze()
        except Exception as e:
            logger.debug("RiskAgent failed for %s: %s", ticker, e)

    news_result = {"score": 50, "thesis": [], "breaking_event": None}
    if _NEWS_AGENT_AVAILABLE:
        try:
            news_result = await NewsAgent(db, ticker).analyze()
        except Exception as e:
            logger.debug("NewsAgent failed for %s: %s", ticker, e)

    transcript_result = {"score": 50, "thesis": [], "summary": None}
    if _TRANSCRIPT_AVAILABLE:
        try:
            transcript_result = await TranscriptAgent(db, ticker).analyze()
        except Exception as e:
            logger.debug("TranscriptAgent failed for %s: %s", ticker, e)

    def _safe(result, default_score=50, name=""):
        if isinstance(result, Exception):
            logger.error("Agent %s failed for %s: %s", name, ticker, result)
            return {"score": default_score, "thesis": [f"{name} agent failed."]}
        return result

    fund_result   = _safe(fund_result,   name="Fundamental")
    tech_result   = _safe(tech_result,   name="Technical")
    macro_result  = _safe(macro_result,  name="Macro")
    inst_result   = _safe(inst_result,   name="Institutional")
    sent_result   = _safe(sent_result,   name="Sentiment")
    mem_result    = _safe(mem_result,    name="Memory")
    vision_result = _safe(vision_result, name="Vision")

    # Blend market conditions into macro score (market internals refine economic view)
    if market_result.get("thesis"):
        m_delta = market_result["score"] - 50
        macro_result["score"] = max(0, min(100, macro_result["score"] + round(m_delta * 0.20)))
        macro_result.setdefault("thesis", []).extend(market_result["thesis"])

    # Blend breaking news (48h) into sentiment score — news velocity matters
    if news_result.get("thesis"):
        n_delta = news_result["score"] - 50
        sent_result["score"] = max(0, min(100, sent_result["score"] + round(n_delta * 0.25)))
        sent_result.setdefault("thesis", []).extend(news_result["thesis"])

    # Blend transcript guidance/tone into fundamental score (minor adjustment)
    if transcript_result.get("thesis"):
        t_delta = transcript_result["score"] - 50  # -50 to +50
        fund_result["score"] = max(0, min(100, fund_result["score"] + round(t_delta * 0.15)))
        fund_result.setdefault("thesis", []).extend(transcript_result["thesis"])

    regime = macro_result.get("regime", "Unknown")

    # ── Phase 2: Strategist agents (run sequentially to avoid asyncpg conflicts) ──
    try:
        factor_result = await FactorAgent(db, ticker).analyze()
    except Exception as e:
        factor_result = e

    try:
        cross_asset_result = await CrossAssetAgent(db, ticker).analyze()
    except Exception as e:
        cross_asset_result = e

    try:
        portfolio_result = await PortfolioAgent(db, ticker).analyze()
    except Exception as e:
        portfolio_result = e

    factor_result       = _safe(factor_result,       name="Factor") if isinstance(factor_result, Exception) else factor_result
    cross_asset_result  = _safe(cross_asset_result,  name="CrossAsset") if isinstance(cross_asset_result, Exception) else cross_asset_result
    portfolio_result    = _safe(portfolio_result,    name="Portfolio") if isinstance(portfolio_result, Exception) else portfolio_result

    # ── Load walk-forward weight nudges (written by WalkForwardValidator weekly) ──
    weight_nudge: dict[str, float] = {}
    try:
        nudge_res = await db.execute(text("""
            SELECT indicator, value FROM macro_data
            WHERE indicator LIKE 'WEIGHT_NUDGE_%'
              AND source = 'walk_forward_validator'
              AND time >= NOW() - INTERVAL '7 days'
            ORDER BY time DESC
        """))
        seen: set[str] = set()
        for row in nudge_res.fetchall():
            agent = row.indicator.replace("WEIGHT_NUDGE_", "").lower()
            if agent not in seen:
                weight_nudge[agent] = float(row.value)
                seen.add(agent)
    except Exception:
        pass  # Fall back to static REGIME_WEIGHTS

    # ── ExecutiveTrader (regime-adaptive) ───────────────────────────────────
    executive = ExecutiveTrader()
    exec_result = executive.decide(
        fundamental_score   = fund_result["score"],
        technical_score     = tech_result["score"],
        macro_score         = macro_result["score"],
        institutional_score = inst_result["score"],
        sentiment_score     = sent_result["score"],
        vision_score        = vision_result.get("score", 50),
        factor_score        = factor_result.get("score", 50),
        risk_score          = risk_result["score"],
        fundamental_thesis   = fund_result.get("thesis"),
        technical_thesis     = tech_result.get("thesis"),
        macro_thesis         = macro_result.get("thesis"),
        institutional_thesis = inst_result.get("thesis"),
        sentiment_thesis     = sent_result.get("thesis"),
        vision_thesis        = vision_result.get("thesis"),
        factor_thesis        = factor_result.get("thesis"),
        risk_thesis          = risk_result.get("thesis"),
        regime               = regime,
        weight_nudge         = weight_nudge or None,
    )

    exec_agent_result = {"score": 50, "thesis": [], "should_execute": True, "execution_notes": ""}
    if _EXECUTION_AGENT_AVAILABLE:
        try:
            exec_agent_result = await ExecutionAgent(db, ticker).analyze(
                final_score=exec_result["final_score"]
            )
        except Exception as e:
            logger.debug("ExecutionAgent failed for %s: %s", ticker, e)

    # ── Phase 3: Risk sizing pipeline ───────────────────────────────────────
    calibrator = CalibrationEngine(db)
    await calibrator.fit()
    calibrated_prob = calibrator.predict(exec_result["final_score"])

    sizing = SizingEngine(db, ticker)
    sizing_result = await sizing.compute(
        calibrated_prob,
        exec_result["final_score"],
        caution_mode=cb_state.get("caution", False),
    )

    execution = ExecutionModel(db, ticker)
    exec_cost_result = await execution.adjust(sizing_result["kelly_fraction"])

    final_kelly = exec_cost_result["adjusted_kelly"]
    final_position_pct = round(final_kelly * 100, 2)

    # ── Assemble full analysis dict ─────────────────────────────────────────
    data = {
        # Core scores
        "fundamental_score":       fund_result["score"],
        "technical_score":         tech_result["score"],
        "macro_score":             macro_result["score"],
        "institutional_score":     inst_result["score"],
        "sentiment_score":         sent_result["score"],
        "memory_confidence":       mem_result.get("confidence", 0.0),
        "vision_score":            vision_result.get("score", 50),
        "final_score":             exec_result["final_score"],
        "signal":                  exec_result["signal"],
        "regime":                  regime,
        # Theses
        "fundamental_thesis":      fund_result.get("thesis", []),
        "technical_thesis":        tech_result.get("thesis", []),
        "macro_thesis":            macro_result.get("thesis", []),
        "institutional_thesis":    inst_result.get("thesis", []),
        "sentiment_thesis":        sent_result.get("thesis", []),
        "memory_thesis":           mem_result.get("thesis", []),
        "vision_thesis":           vision_result.get("thesis", []),
        "signal_thesis":           exec_result["signal_thesis"],
        # Phase 2: strategist outputs (now stored in DB)
        "factor_scores":           factor_result.get("factor_scores", {}),
        "cross_asset_sensitivity": cross_asset_result.get("cross_asset_sensitivity", {}),
        # Phase 3: risk outputs (now stored in DB)
        "calibrated_prob":         calibrated_prob,
        "kelly_fraction":          final_kelly,
        "max_position_pct":        final_position_pct,
        # Memory analogs (stored so GET analysis returns them without re-running)
        "analogs":                 mem_result.get("analogs", []),
        # Trade levels from SizingEngine
        "entry_price":             sizing_result.get("entry_price"),
        "stop_loss":               sizing_result.get("stop_loss"),
        "take_profit":             sizing_result.get("take_profit"),
        "atr_14":                  sizing_result.get("atr_14"),
        # Transcript intelligence
        "earnings_summary":        transcript_result.get("summary"),
        # Risk agent outputs
        "risk_score":              risk_result["score"],
        "risk_flags":              risk_result.get("risk_flags", []),
        "risk_thesis":             risk_result.get("thesis", []),
        # Breaking news
        "breaking_news":           news_result.get("breaking_event"),
        # Market internals (MarketAgent)
        "market_regime":           market_result.get("market_regime", "Unknown"),
        "market_score":            market_result.get("score", 50),
        # Execution gate (ExecutionAgent)
        "should_execute":          exec_agent_result.get("should_execute", True),
        "execution_notes":         exec_agent_result.get("execution_notes", ""),
    }

    # ── Persist ──────────────────────────────────────────────────────────────
    try:
        previous = await _previous_signal(db, ticker)
        await _upsert_analysis(db, ticker, analysis_date, data)

        if await _should_create_alert(db, ticker, exec_result["signal"], previous, exec_result["final_score"]):
            await _create_alert(
                db, ticker,
                signal=exec_result["signal"],
                previous_signal=previous,
                final_score=exec_result["final_score"],
                signal_thesis=exec_result["signal_thesis"],
            )

        await db.commit()
        logger.info("Saved analysis for %s: signal=%s score=%d kelly=%.1f%%",
                    ticker, exec_result["signal"], exec_result["final_score"], final_position_pct)

        # Auto-execution (opt-in via AUTO_EXECUTE env var)
        import os
        if os.getenv("AUTO_EXECUTE", "false").lower() == "true":
            try:
                from app.services.order_manager import OrderManager
                order_mgr = OrderManager(db)
                signal = exec_result["signal"]

                if signal == "BUY":
                    await order_mgr.submit_from_analysis(ticker, exec_result, sizing_result)
                    logger.info("[AutoExec] BUY order submitted for %s", ticker)

                elif signal == "REDUCE":
                    # Partial exit — reduce position by 50%
                    pos_res = await db.execute(text("""
                        SELECT id, quantity, avg_price FROM portfolio_positions
                        WHERE ticker = :t AND status = 'OPEN' LIMIT 1
                    """), {"t": ticker})
                    pos = pos_res.fetchone()
                    if pos and pos.quantity > 0:
                        reduce_qty = max(1, pos.quantity // 2)
                        await order_mgr.submit_reduce(ticker, reduce_qty, exec_result)
                        logger.info("[AutoExec] REDUCE order (%d shares) submitted for %s", reduce_qty, ticker)

                elif signal == "SELL":
                    pos_res = await db.execute(text("""
                        SELECT id, quantity FROM portfolio_positions
                        WHERE ticker = :t AND status = 'OPEN' LIMIT 1
                    """), {"t": ticker})
                    pos = pos_res.fetchone()
                    if pos and pos.quantity > 0:
                        await order_mgr.submit_sell(ticker, pos.quantity, exec_result)
                        logger.info("[AutoExec] SELL order submitted for %s", ticker)
            except Exception as e:
                logger.error("[AutoExec] Order submission failed for %s: %s", ticker, e)

    except Exception as e:
        await db.rollback()
        logger.error("Failed to persist analysis for %s: %s", ticker, e)

    return {
        "ticker": ticker,
        "analysis_date": analysis_date.isoformat(),
        **data,
        # Extra fields not in DB columns (returned to API caller only)
        "portfolio_diversification": portfolio_result.get("diversification_score"),
        "correlated_peer": portfolio_result.get("correlated_peer"),
        "execution_note": exec_cost_result.get("execution_note"),
        "volatility_note": sizing_result.get("volatility_note"),
        "circuit_breaker": cb_state,
    }
