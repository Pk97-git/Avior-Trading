"""
engines/candlestick_patterns.py
================================
Professional candlestick pattern detection engine — 62 patterns.

Covers every category a seasoned technical analyst uses:
  Single-candle  : Doji (4 types), Hammer, Inverted Hammer, Hanging Man,
                   Shooting Star, Marubozu (bull/bear), Spinning Top,
                   High Wave, Belt Hold (bull/bear)
  Two-candle     : Engulfing (bull/bear), Harami (bull/bear + cross),
                   Piercing Line, Dark Cloud Cover, Kicker (bull/bear),
                   Tweezer Bottom/Top, On Neck, In Neck, Meeting Lines (bull/bear),
                   Matching Low
  Three-candle   : Morning/Evening Star, Morning/Evening Doji Star,
                   Abandoned Baby (bull/bear), Three White Soldiers,
                   Three Black Crows, Three Inside Up/Down,
                   Three Outside Up/Down, Advance Block, Deliberation,
                   Two Crows, Unique Three River Bottom
  Complex (4-5c) : Rising/Falling Three Methods, Upside/Downside Tasuki Gap,
                   Mat Hold, Separating Lines (bull/bear)
  Chart structure: Double Bottom/Top, Head & Shoulders / Inverse H&S,
                   Bullish/Bearish Flag, Bullish/Bearish Pennant,
                   Ascending/Descending/Symmetrical Triangle,
                   Falling/Rising Wedge, Cup & Handle, Rounding Bottom

Usage:
    engine = CandlestickPatternEngine(df)   # df: open/high/low/close/volume
    matches = engine.detect_all(lookback=60)
    latest  = engine.detect_recent(n_candles=3)
    summary = engine.pattern_summary()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Enums ──────────────────────────────────────────────────────────────────────

class PatternBias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

class PatternCategory(str, Enum):
    REVERSAL     = "reversal"
    CONTINUATION = "continuation"
    INDECISION   = "indecision"
    STRUCTURE    = "structure"


# ── Pattern metadata registry ──────────────────────────────────────────────────

@dataclass
class PatternMeta:
    code:             str
    name:             str
    bias:             PatternBias
    category:         PatternCategory
    strength:         int
    reliability_pct:  float
    description:      str
    entry_suggestion: str
    stop_suggestion:  str
    emoji:            str = "◈"

PATTERN_REGISTRY: list[PatternMeta] = [
    # ── Single ────────────────────────────────────────────────────────────────
    PatternMeta("DOJI","Doji",PatternBias.NEUTRAL,PatternCategory.INDECISION,2,54.0,
        "Open ≈ close — market indecision. Watch for directional follow-through.",
        "Wait for next-candle direction confirmation","Below low (bull) or above high (bear)","◈"),
    PatternMeta("LONG_LEGGED_DOJI","Long-Legged Doji",PatternBias.NEUTRAL,PatternCategory.INDECISION,3,57.0,
        "Doji with very long shadows — extreme indecision, volatile session.",
        "Wait for breakout from range","Stop beyond the long shadow","◈"),
    PatternMeta("GRAVESTONE_DOJI","Gravestone Doji",PatternBias.BEARISH,PatternCategory.REVERSAL,3,62.0,
        "Long upper shadow, almost no lower shadow. Bearish reversal at tops.",
        "Sell/short below Gravestone low","Above Gravestone high","◈"),
    PatternMeta("DRAGONFLY_DOJI","Dragonfly Doji",PatternBias.BULLISH,PatternCategory.REVERSAL,3,63.0,
        "Long lower shadow, almost no upper shadow. Bullish reversal at bottoms.",
        "Buy above Dragonfly high","Below Dragonfly low","◈"),
    PatternMeta("HAMMER","Hammer",PatternBias.BULLISH,PatternCategory.REVERSAL,4,68.0,
        "Long lower shadow (2×+ body), small body near top. Bullish reversal after downtrend.",
        "Buy above Hammer high with volume confirmation","Below Hammer low","🔨"),
    PatternMeta("INVERTED_HAMMER","Inverted Hammer",PatternBias.BULLISH,PatternCategory.REVERSAL,3,62.0,
        "Long upper shadow, small body near bottom after downtrend. Needs confirmation.",
        "Buy on next bullish confirmation candle above body","Below Inverted Hammer low","🔨"),
    PatternMeta("HANGING_MAN","Hanging Man",PatternBias.BEARISH,PatternCategory.REVERSAL,3,59.0,
        "Hammer shape but at uptrend top — warning of exhaustion.",
        "Sell/short below Hanging Man low","Above Hanging Man high","🔴"),
    PatternMeta("SHOOTING_STAR","Shooting Star",PatternBias.BEARISH,PatternCategory.REVERSAL,4,67.0,
        "Long upper shadow after uptrend. Sellers rejected the rally aggressively.",
        "Sell/short below Shooting Star low on confirmation","Above Shooting Star high","⭐"),
    PatternMeta("BULLISH_MARUBOZU","Bullish Marubozu",PatternBias.BULLISH,PatternCategory.CONTINUATION,4,72.0,
        "Strong bullish candle with no shadows — buyers controlled from open to close.",
        "Buy on next open; tight stop below candle low","Below Marubozu low","💚"),
    PatternMeta("BEARISH_MARUBOZU","Bearish Marubozu",PatternBias.BEARISH,PatternCategory.CONTINUATION,4,72.0,
        "Strong bearish candle with no shadows — sellers controlled from open to close.",
        "Sell/short on next open; tight stop above candle high","Above Marubozu high","🔴"),
    PatternMeta("SPINNING_TOP","Spinning Top",PatternBias.NEUTRAL,PatternCategory.INDECISION,2,52.0,
        "Small body, both shadows larger — neither bulls nor bears in control.",
        "Wait for directional breakout","Context-dependent","◈"),
    PatternMeta("HIGH_WAVE","High Wave",PatternBias.NEUTRAL,PatternCategory.INDECISION,2,53.0,
        "Very long shadows both sides, tiny body — exhaustion and indecision after a run.",
        "Wait for directional resolution","Beyond the extreme of the long shadow","◈"),
    PatternMeta("BULLISH_BELT_HOLD","Bullish Belt Hold",PatternBias.BULLISH,PatternCategory.REVERSAL,3,64.0,
        "Opens at low, closes near high after a downtrend — bullish reversal.",
        "Buy on next open above Belt Hold high","Below Belt Hold low","💚"),
    PatternMeta("BEARISH_BELT_HOLD","Bearish Belt Hold",PatternBias.BEARISH,PatternCategory.REVERSAL,3,64.0,
        "Opens at high, closes near low after an uptrend — bearish reversal.",
        "Sell/short on next open below Belt Hold low","Above Belt Hold high","🔴"),
    # ── Two-candle ────────────────────────────────────────────────────────────
    PatternMeta("BULLISH_ENGULFING","Bullish Engulfing",PatternBias.BULLISH,PatternCategory.REVERSAL,5,70.0,
        "Large bullish candle fully engulfs prior bearish body. Strong reversal signal at support.",
        "Buy above Engulfing candle high","Below Engulfing candle low","💚"),
    PatternMeta("BEARISH_ENGULFING","Bearish Engulfing",PatternBias.BEARISH,PatternCategory.REVERSAL,5,70.0,
        "Large bearish candle fully engulfs prior bullish body. Strong reversal at resistance.",
        "Sell/short below Engulfing candle low","Above Engulfing candle high","🔴"),
    PatternMeta("BULLISH_HARAMI","Bullish Harami",PatternBias.BULLISH,PatternCategory.REVERSAL,3,60.0,
        "Small bullish candle inside prior large bearish body — potential reversal, needs confirmation.",
        "Buy on confirmation candle closing above Harami high","Below Harami low","💚"),
    PatternMeta("BEARISH_HARAMI","Bearish Harami",PatternBias.BEARISH,PatternCategory.REVERSAL,3,60.0,
        "Small bearish candle inside prior large bullish body — potential reversal, needs confirmation.",
        "Sell on confirmation candle closing below Harami low","Above Harami high","🔴"),
    PatternMeta("BULLISH_HARAMI_CROSS","Bullish Harami Cross",PatternBias.BULLISH,PatternCategory.REVERSAL,4,65.0,
        "Bullish Harami where the second candle is a Doji — stronger reversal signal.",
        "Buy on confirmation above Doji high","Below Doji low","💚"),
    PatternMeta("BEARISH_HARAMI_CROSS","Bearish Harami Cross",PatternBias.BEARISH,PatternCategory.REVERSAL,4,65.0,
        "Bearish Harami where the second candle is a Doji — stronger reversal signal.",
        "Sell on confirmation below Doji low","Above Doji high","🔴"),
    PatternMeta("PIERCING_LINE","Piercing Line",PatternBias.BULLISH,PatternCategory.REVERSAL,4,67.0,
        "Gap-down open then closes above 50% of prior bearish body — buyers absorbed the gap.",
        "Buy above Piercing candle high","Below Piercing candle low","💚"),
    PatternMeta("DARK_CLOUD_COVER","Dark Cloud Cover",PatternBias.BEARISH,PatternCategory.REVERSAL,4,67.0,
        "Gap-up open then closes below 50% of prior bullish body — sellers absorbed the gap.",
        "Sell/short below Dark Cloud candle low","Above Dark Cloud candle high","🔴"),
    PatternMeta("BULLISH_KICKER","Bullish Kicker",PatternBias.BULLISH,PatternCategory.REVERSAL,5,73.0,
        "Gap-up open after a bearish candle — sudden sentiment shift, most powerful 2-candle reversal.",
        "Buy at market open or on gap confirmation","Below gap low","💚"),
    PatternMeta("BEARISH_KICKER","Bearish Kicker",PatternBias.BEARISH,PatternCategory.REVERSAL,5,73.0,
        "Gap-down open after a bullish candle — sudden sentiment collapse, very powerful reversal.",
        "Sell/short at market open or on gap confirmation","Above gap high","🔴"),
    PatternMeta("TWEEZER_BOTTOM","Tweezer Bottom",PatternBias.BULLISH,PatternCategory.REVERSAL,3,62.0,
        "Two candles with matching lows — strong support tested twice.",
        "Buy on close above Tweezer high","Below Tweezer low","📈"),
    PatternMeta("TWEEZER_TOP","Tweezer Top",PatternBias.BEARISH,PatternCategory.REVERSAL,3,62.0,
        "Two candles with matching highs — strong resistance tested twice.",
        "Sell on close below Tweezer low","Above Tweezer high","📉"),
    PatternMeta("ON_NECK","On Neck",PatternBias.BEARISH,PatternCategory.CONTINUATION,2,56.0,
        "Small bullish closes near prior bearish close — sellers still in control.",
        "Sell/short below On Neck low","Above On Neck high","🔴"),
    PatternMeta("IN_NECK","In Neck",PatternBias.BEARISH,PatternCategory.CONTINUATION,2,56.0,
        "Small bullish slightly penetrates prior bearish close — bearish continuation.",
        "Sell/short below In Neck low","Above prior bearish high","🔴"),
    PatternMeta("MEETING_LINES_BULL","Meeting Lines (Bull)",PatternBias.BULLISH,PatternCategory.REVERSAL,3,60.0,
        "Bearish then bullish candle with same closing price — support identified.",
        "Buy on next bullish close above Meeting Lines high","Below Meeting Lines low","💚"),
    PatternMeta("MEETING_LINES_BEAR","Meeting Lines (Bear)",PatternBias.BEARISH,PatternCategory.REVERSAL,3,60.0,
        "Bullish then bearish candle with same closing price — resistance identified.",
        "Sell on next bearish close below Meeting Lines low","Above Meeting Lines high","🔴"),
    PatternMeta("MATCHING_LOW","Matching Low",PatternBias.BULLISH,PatternCategory.REVERSAL,3,63.0,
        "Two bearish candles closing at the same price — strong support zone.",
        "Buy on next bullish confirmation","Below matching low","💚"),
    # ── Three-candle ──────────────────────────────────────────────────────────
    PatternMeta("MORNING_STAR","Morning Star",PatternBias.BULLISH,PatternCategory.REVERSAL,5,75.0,
        "Large bearish, small star, large bullish closing above 50% of candle-1. Classic bottom reversal.",
        "Buy above Morning Star third candle high","Below Morning Star first candle low","🔨"),
    PatternMeta("EVENING_STAR","Evening Star",PatternBias.BEARISH,PatternCategory.REVERSAL,5,75.0,
        "Large bullish, small star, large bearish closing below 50% of candle-1. Classic top reversal.",
        "Sell/short below Evening Star third candle low","Above Evening Star first candle high","⭐"),
    PatternMeta("MORNING_DOJI_STAR","Morning Doji Star",PatternBias.BULLISH,PatternCategory.REVERSAL,5,79.0,
        "Morning Star where the middle candle is a Doji — even stronger reversal signal.",
        "Buy above third candle high","Below Doji low","🔨"),
    PatternMeta("EVENING_DOJI_STAR","Evening Doji Star",PatternBias.BEARISH,PatternCategory.REVERSAL,5,79.0,
        "Evening Star where the middle candle is a Doji — even stronger reversal signal.",
        "Sell/short below third candle low","Above Doji high","⭐"),
    PatternMeta("ABANDONED_BABY_BULL","Bullish Abandoned Baby",PatternBias.BULLISH,PatternCategory.REVERSAL,5,82.0,
        "Bearish candle, gapped Doji (no shadow overlap), gapped bullish. Rarest, most reliable reversal.",
        "Buy above third candle high","Below Doji low","🔨"),
    PatternMeta("ABANDONED_BABY_BEAR","Bearish Abandoned Baby",PatternBias.BEARISH,PatternCategory.REVERSAL,5,82.0,
        "Bullish candle, gapped Doji (no shadow overlap), gapped bearish. Rarest, most reliable reversal.",
        "Sell below third candle low","Above Doji high","⭐"),
    PatternMeta("THREE_WHITE_SOLDIERS","Three White Soldiers",PatternBias.BULLISH,PatternCategory.CONTINUATION,5,78.0,
        "Three consecutive large bullish candles, each closing near its high. Powerful uptrend continuation.",
        "Buy on breakout above third candle high","Below first soldier's open","🪖"),
    PatternMeta("THREE_BLACK_CROWS","Three Black Crows",PatternBias.BEARISH,PatternCategory.CONTINUATION,5,78.0,
        "Three consecutive large bearish candles, each closing near its low. Powerful downtrend continuation.",
        "Sell/short below third candle low","Above first crow's open","🐦"),
    PatternMeta("THREE_INSIDE_UP","Three Inside Up",PatternBias.BULLISH,PatternCategory.REVERSAL,4,71.0,
        "Bullish Harami followed by bullish confirmation — reversal confirmed.",
        "Buy on open after third candle","Below Harami low","💚"),
    PatternMeta("THREE_INSIDE_DOWN","Three Inside Down",PatternBias.BEARISH,PatternCategory.REVERSAL,4,71.0,
        "Bearish Harami followed by bearish confirmation — reversal confirmed.",
        "Sell/short on open after third candle","Above Harami high","🔴"),
    PatternMeta("THREE_OUTSIDE_UP","Three Outside Up",PatternBias.BULLISH,PatternCategory.REVERSAL,4,72.0,
        "Bullish Engulfing followed by another bullish close — momentum building.",
        "Buy on third candle close","Below Engulfing low","💚"),
    PatternMeta("THREE_OUTSIDE_DOWN","Three Outside Down",PatternBias.BEARISH,PatternCategory.REVERSAL,4,72.0,
        "Bearish Engulfing followed by another bearish close — momentum building.",
        "Sell/short on third candle close","Above Engulfing high","🔴"),
    PatternMeta("ADVANCE_BLOCK","Advance Block",PatternBias.BEARISH,PatternCategory.REVERSAL,3,63.0,
        "Three rising bullish candles with diminishing bodies and longer upper shadows — uptrend losing steam.",
        "Reduce longs; look for short entry on next bearish confirmation","Above third candle high","🔴"),
    PatternMeta("DELIBERATION","Deliberation",PatternBias.BEARISH,PatternCategory.REVERSAL,3,62.0,
        "Two strong bullish candles then a small body near the top — bulls pausing, warning signal.",
        "Reduce longs; sell/short on bearish confirmation","Above third candle high","🔴"),
    PatternMeta("TWO_CROWS","Two Crows",PatternBias.BEARISH,PatternCategory.REVERSAL,3,64.0,
        "Strong bull candle, gap-up bearish, then bearish closing inside first body — distribution.",
        "Sell/short below third candle low","Above second candle high","🔴"),
    PatternMeta("UNIQUE_THREE_RIVER","Unique Three River Bottom",PatternBias.BULLISH,PatternCategory.REVERSAL,3,64.0,
        "Bearish, small Hammer-like inside, small bullish close — rare bottom reversal.",
        "Buy on fourth candle open","Below second candle low","💚"),
    # ── Complex (4-5 candles) ─────────────────────────────────────────────────
    PatternMeta("RISING_THREE_METHODS","Rising Three Methods",PatternBias.BULLISH,PatternCategory.CONTINUATION,4,74.0,
        "Long bull, 3 small bearish inside range, then another long bull. Classic bull continuation.",
        "Buy on fifth candle close above first candle high","Below consolidation low","💚"),
    PatternMeta("FALLING_THREE_METHODS","Falling Three Methods",PatternBias.BEARISH,PatternCategory.CONTINUATION,4,74.0,
        "Long bear, 3 small bullish inside range, then another long bear. Classic bear continuation.",
        "Sell/short on fifth candle close below first candle low","Above consolidation high","🔴"),
    PatternMeta("UPSIDE_TASUKI_GAP","Upside Tasuki Gap",PatternBias.BULLISH,PatternCategory.CONTINUATION,3,65.0,
        "Two bullish candles with a gap, then bearish candle partially fills gap — gap acts as support.",
        "Buy as bearish candle fails to close the gap","Below the gap","💚"),
    PatternMeta("DOWNSIDE_TASUKI_GAP","Downside Tasuki Gap",PatternBias.BEARISH,PatternCategory.CONTINUATION,3,65.0,
        "Two bearish candles with gap down, then bullish candle partially fills gap — gap as resistance.",
        "Sell/short as bullish candle fails to close the gap","Above the gap","🔴"),
    PatternMeta("MAT_HOLD","Mat Hold",PatternBias.BULLISH,PatternCategory.CONTINUATION,3,66.0,
        "Long bull, small pullback bodies staying above first body, then strong bull resumes.",
        "Buy on fifth candle close","Below pullback lows","💚"),
    PatternMeta("SEP_LINES_BULL","Separating Lines (Bull)",PatternBias.BULLISH,PatternCategory.CONTINUATION,3,63.0,
        "Bearish candle then bullish candle with same open — bulls reclaim ground.",
        "Buy on bullish candle","Below shared open","💚"),
    PatternMeta("SEP_LINES_BEAR","Separating Lines (Bear)",PatternBias.BEARISH,PatternCategory.CONTINUATION,3,63.0,
        "Bullish candle then bearish candle with same open — bears reclaim ground.",
        "Sell on bearish candle","Above shared open","🔴"),
    # ── Chart structure ───────────────────────────────────────────────────────
    PatternMeta("DOUBLE_BOTTOM","Double Bottom",PatternBias.BULLISH,PatternCategory.STRUCTURE,4,72.0,
        "Two lows at similar price separated by a peak — strong support confirmed twice.",
        "Buy on break above the peak between the two lows (neckline)","Below double bottom low","📈"),
    PatternMeta("DOUBLE_TOP","Double Top",PatternBias.BEARISH,PatternCategory.STRUCTURE,4,72.0,
        "Two highs at similar price separated by a trough — strong resistance confirmed twice.",
        "Sell/short on break below the trough between the two highs (neckline)","Above double top high","📉"),
    PatternMeta("HEAD_AND_SHOULDERS","Head & Shoulders",PatternBias.BEARISH,PatternCategory.STRUCTURE,5,77.0,
        "Left shoulder, higher head, right shoulder — classic topping pattern.",
        "Sell/short on neckline break with volume","Above right shoulder high","📉"),
    PatternMeta("INVERSE_HEAD_AND_SHOULDERS","Inverse H&S",PatternBias.BULLISH,PatternCategory.STRUCTURE,5,77.0,
        "Inverse H&S — classic bottoming pattern.",
        "Buy on neckline breakout with volume","Below right shoulder low","📈"),
    PatternMeta("BULLISH_FLAG","Bullish Flag",PatternBias.BULLISH,PatternCategory.CONTINUATION,4,71.0,
        "Sharp bullish move then tight downward channel — continuation likely on breakout.",
        "Buy on breakout above upper channel line","Below flag low","🚩"),
    PatternMeta("BEARISH_FLAG","Bearish Flag",PatternBias.BEARISH,PatternCategory.CONTINUATION,4,71.0,
        "Sharp bearish move then tight upward channel — continuation likely on breakdown.",
        "Sell/short on breakdown below lower channel line","Above flag high","🚩"),
    PatternMeta("ASCENDING_TRIANGLE","Ascending Triangle",PatternBias.BULLISH,PatternCategory.CONTINUATION,4,73.0,
        "Flat resistance + rising support — coiling for upside breakout.",
        "Buy on breakout above resistance with volume","Below rising support line","△"),
    PatternMeta("DESCENDING_TRIANGLE","Descending Triangle",PatternBias.BEARISH,PatternCategory.CONTINUATION,4,73.0,
        "Falling resistance + flat support — coiling for downside breakdown.",
        "Sell/short on breakdown below support with volume","Above falling resistance line","△"),
    PatternMeta("SYMMETRICAL_TRIANGLE","Symmetrical Triangle",PatternBias.NEUTRAL,PatternCategory.CONTINUATION,3,60.0,
        "Converging highs and lows — breakout direction determines bias.",
        "Buy above upper trendline or sell below lower trendline","Opposite trendline","△"),
    PatternMeta("FALLING_WEDGE","Falling Wedge",PatternBias.BULLISH,PatternCategory.REVERSAL,4,70.0,
        "Both highs and lows falling but converging — bullish reversal on upper trendline break.",
        "Buy on break above upper trendline with volume","Below wedge low","💚"),
    PatternMeta("RISING_WEDGE","Rising Wedge",PatternBias.BEARISH,PatternCategory.REVERSAL,4,70.0,
        "Both highs and lows rising but converging — bearish reversal on lower trendline break.",
        "Sell/short on break below lower trendline","Above wedge high","🔴"),
    PatternMeta("CUP_AND_HANDLE","Cup & Handle",PatternBias.BULLISH,PatternCategory.CONTINUATION,4,71.0,
        "Rounded bottom (cup) followed by small pullback (handle) — breakout above rim is buy signal.",
        "Buy on breakout above cup rim with volume","Below handle low","📈"),
    PatternMeta("ROUNDING_BOTTOM","Rounding Bottom",PatternBias.BULLISH,PatternCategory.REVERSAL,4,68.0,
        "Gradual rounded base (saucer) — slow accumulation transitioning to uptrend.",
        "Buy on break above the saucer rim","Below saucer low","📈"),
]

_META: dict[str, PatternMeta] = {p.code: p for p in PATTERN_REGISTRY}


# ── Geometry helpers ───────────────────────────────────────────────────────────

def _body(o: float, c: float) -> float:        return abs(c - o)
def _upper_shad(o: float, c: float, h: float) -> float: return h - max(o, c)
def _lower_shad(o: float, c: float, lo: float) -> float: return min(o, c) - lo
def _rng(h: float, lo: float) -> float:        return max(h - lo, 1e-9)
def _bull(o: float, c: float) -> bool:         return c > o
def _bear(o: float, c: float) -> bool:         return o > c

def _is_doji(o: float, c: float, h: float, lo: float, thr: float = 0.06) -> bool:
    return _body(o, c) / _rng(h, lo) < thr

def _is_small(o: float, c: float, h: float, lo: float, thr: float = 0.35) -> bool:
    return _body(o, c) / _rng(h, lo) < thr

def _is_large(o: float, c: float, h: float, lo: float, thr: float = 0.55) -> bool:
    return _body(o, c) / _rng(h, lo) >= thr

def _atr(df: pd.DataFrame, period: int = 14) -> float:
    h = df["high"]; lo = df["low"]; c = df["close"]
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

def _sma(series: pd.Series, n: int, i: int) -> float:
    if i < n: return float(series.iloc[:i+1].mean())
    return float(series.iloc[i-n+1:i+1].mean())

def _rsi(close: pd.Series, i: int, period: int = 14) -> float:
    if i < period + 1: return 50.0
    s = close.iloc[max(0, i-period*2):i+1]
    d = s.diff()
    g = d.clip(lower=0).ewm(span=period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs = g / l.replace(0, 1e-9)
    return float((100 - 100 / (1 + rs)).iloc[-1])

def _prior_return(close: pd.Series, i: int, n: int = 5) -> float:
    if i < n: return 0.0
    return (float(close.iloc[i]) - float(close.iloc[i-n])) / float(close.iloc[i-n] + 1e-9)

def _vol_ratio(volume: pd.Series, i: int, period: int = 20) -> float:
    if i < 5: return 1.0
    avg = float(volume.iloc[max(0, i-period):i].mean())
    if avg <= 0: return 1.0
    return float(volume.iloc[i]) / avg


# ── Context scoring ────────────────────────────────────────────────────────────

def _context(df: pd.DataFrame, i: int, bias: PatternBias) -> tuple[float, list[str], bool]:
    """Returns (score 0-1, notes, volume_confirmed)."""
    notes: list[str] = []
    pts = 0.0; total = 0.0

    close  = df["close"]
    volume = df["volume"]

    # Trend alignment (20-day SMA slope)
    if i >= 10:
        sma_now  = _sma(close, 20, i)
        sma_prev = _sma(close, 20, max(0, i-5))
        if bias == PatternBias.BULLISH:
            if sma_now < sma_prev:
                notes.append("Prior downtrend — ideal for bullish reversal")
                pts += 1.0
            else:
                notes.append("Uptrend context — bullish continuation")
                pts += 0.5
        elif bias == PatternBias.BEARISH:
            if sma_now > sma_prev:
                notes.append("Prior uptrend — ideal for bearish reversal")
                pts += 1.0
            else:
                notes.append("Downtrend context — bearish continuation")
                pts += 0.5
        total += 1.0

    # Volume
    vr = _vol_ratio(volume, i)
    vol_confirmed = vr >= 1.3
    if i >= 5:
        if vr >= 1.5:
            notes.append(f"Strong volume confirmation ({vr:.1f}× average)")
            pts += 1.0
        elif vr >= 1.2:
            notes.append(f"Volume above average ({vr:.1f}×)")
            pts += 0.7
        else:
            notes.append(f"Below-average volume ({vr:.1f}× — weak signal)")
            pts += 0.2
        total += 1.0

    # RSI
    if i >= 15:
        rsi_val = _rsi(close, i)
        if bias == PatternBias.BULLISH:
            if rsi_val < 30:
                notes.append(f"RSI {rsi_val:.0f} — deeply oversold (strong bullish context)")
                pts += 1.0
            elif rsi_val < 45:
                notes.append(f"RSI {rsi_val:.0f} — oversold zone (favourable)")
                pts += 0.7
            elif rsi_val > 70:
                notes.append(f"RSI {rsi_val:.0f} — overbought (weakens bullish signal)")
                pts += 0.1
            else:
                notes.append(f"RSI {rsi_val:.0f} — neutral")
                pts += 0.4
        elif bias == PatternBias.BEARISH:
            if rsi_val > 70:
                notes.append(f"RSI {rsi_val:.0f} — overbought (strong bearish context)")
                pts += 1.0
            elif rsi_val > 55:
                notes.append(f"RSI {rsi_val:.0f} — elevated zone (favourable)")
                pts += 0.7
            elif rsi_val < 30:
                notes.append(f"RSI {rsi_val:.0f} — oversold (weakens bearish signal)")
                pts += 0.1
            else:
                notes.append(f"RSI {rsi_val:.0f} — neutral")
                pts += 0.4
        total += 1.0

    # Proximity to 52-week extreme
    if i >= 50:
        hi52 = float(df["high"].iloc[max(0,i-252):i+1].max())
        lo52 = float(df["low"].iloc[max(0,i-252):i+1].min())
        cur  = float(close.iloc[i])
        if bias == PatternBias.BULLISH and cur < lo52 * 1.06:
            notes.append("Near 52-week low — potential support zone")
            pts += 0.8
            total += 1.0
        elif bias == PatternBias.BEARISH and cur > hi52 * 0.94:
            notes.append("Near 52-week high — potential resistance zone")
            pts += 0.8
            total += 1.0

    score = round(pts / total, 2) if total > 0 else 0.5
    return score, notes, vol_confirmed


# ── Build result dict ──────────────────────────────────────────────────────────

def _make(code: str, candle_index: int, candle_date: str,
          df: pd.DataFrame, i: int) -> dict:
    meta = _META[code]
    score, notes, vol_ok = _context(df, i, meta.bias)
    return {
        "code":             code,
        "name":             meta.name,
        "bias":             meta.bias.value,
        "category":         meta.category.value,
        "strength":         meta.strength,
        "reliability_pct":  meta.reliability_pct,
        "description":      meta.description,
        "entry_suggestion": meta.entry_suggestion,
        "stop_suggestion":  meta.stop_suggestion,
        "emoji":            meta.emoji,
        "candle_index":     candle_index,
        "candle_date":      candle_date,
        "context_score":    score,
        "context_notes":    notes,
        "volume_confirmed": vol_ok,
    }


# ── Single-candle detectors ────────────────────────────────────────────────────

def _single(o, h, l, c):
    """Detect single-candle patterns. Returns list of codes."""
    rn = _rng(h, l)
    body = _body(o, c)
    us = _upper_shad(o, c, h)
    ls = _lower_shad(o, c, l)
    bp = body / rn
    up = us / rn
    lp = ls / rn
    hits = []

    # Doji variants
    if bp < 0.06:
        if up > 0.45 and lp > 0.45:
            hits.append("LONG_LEGGED_DOJI")
        elif up > 0.7 and lp < 0.12:
            hits.append("GRAVESTONE_DOJI")
        elif lp > 0.7 and up < 0.12:
            hits.append("DRAGONFLY_DOJI")
        else:
            hits.append("DOJI")

    # Marubozu (body > 92% of range)
    if bp > 0.92:
        hits.append("BULLISH_MARUBOZU" if _bull(o,c) else "BEARISH_MARUBOZU")

    # Hammer / Hanging Man: long lower shadow, body in upper portion
    if lp >= 0.55 and bp < 0.28 and up <= 0.12:
        hits.append("HAMMER" if _bull(o,c) else "HANGING_MAN")

    # Inverted Hammer / Shooting Star: long upper shadow, body in lower portion
    if up >= 0.55 and bp < 0.28 and lp <= 0.12:
        hits.append("INVERTED_HAMMER" if _bull(o,c) else "SHOOTING_STAR")

    # Spinning Top: small body, both shadows
    if 0.06 <= bp <= 0.32 and up >= 0.25 and lp >= 0.25 and not hits:
        hits.append("SPINNING_TOP")

    # High Wave: tiny body, very long shadows both sides
    if bp < 0.20 and us > body * 2.5 and ls > body * 2.5:
        hits.append("HIGH_WAVE")

    # Belt Hold
    if lp < 0.05 and bp > 0.60 and _bull(o,c):
        hits.append("BULLISH_BELT_HOLD")
    if up < 0.05 and bp > 0.60 and _bear(o,c):
        hits.append("BEARISH_BELT_HOLD")

    return hits


# ── Two-candle detectors ───────────────────────────────────────────────────────

def _double(o1,h1,l1,c1, o,h,l,c):
    """Detect two-candle patterns (prev=1, curr=0). Returns list of codes."""
    hits = []
    body0 = _body(o,c);   body1 = _body(o1,c1)
    is_doji0 = _is_doji(o,c,h,l)
    is_doji1 = _is_doji(o1,c1,h1,l1)

    # Engulfing
    if _bull(o,c) and _bear(o1,c1) and o <= c1 and c >= o1 and body0 > body1:
        hits.append("BULLISH_ENGULFING")
    if _bear(o,c) and _bull(o1,c1) and o >= c1 and c <= o1 and body0 > body1:
        hits.append("BEARISH_ENGULFING")

    # Harami (current body inside prior body)
    if body1 > 0:
        hi_body1 = max(o1,c1); lo_body1 = min(o1,c1)
        hi_body0 = max(o,c);   lo_body0 = min(o,c)
        if hi_body0 < hi_body1 and lo_body0 > lo_body1:  # inside
            if _bear(o1,c1):  # prior bearish
                if is_doji0:
                    hits.append("BULLISH_HARAMI_CROSS")
                elif _bull(o,c):
                    hits.append("BULLISH_HARAMI")
            elif _bull(o1,c1):  # prior bullish
                if is_doji0:
                    hits.append("BEARISH_HARAMI_CROSS")
                elif _bear(o,c):
                    hits.append("BEARISH_HARAMI")

    # Piercing Line
    if (_bear(o1,c1) and _bull(o,c) and
            o < c1 and c > (o1+c1)/2 and c < o1):
        hits.append("PIERCING_LINE")

    # Dark Cloud Cover
    if (_bull(o1,c1) and _bear(o,c) and
            o > c1 and c < (o1+c1)/2 and c > c1):
        hits.append("DARK_CLOUD_COVER")

    # Kicker (gap reversal)
    if _bear(o1,c1) and _bull(o,c) and o > o1 and body0 > 0.5*_rng(h,l):
        hits.append("BULLISH_KICKER")
    if _bull(o1,c1) and _bear(o,c) and o < o1 and body0 > 0.5*_rng(h,l):
        hits.append("BEARISH_KICKER")

    # Tweezer
    if abs(l - l1) / max(l, l1, 1e-9) < 0.002:
        hits.append("TWEEZER_BOTTOM")
    if abs(h - h1) / max(h, h1, 1e-9) < 0.002:
        hits.append("TWEEZER_TOP")

    # On Neck / In Neck
    if _bear(o1,c1) and _bull(o,c) and o < l1:
        pen = (c - c1) / max(_body(o1,c1), 1e-9)
        if abs(pen) < 0.03:
            hits.append("ON_NECK")
        elif 0.0 < pen < 0.25:
            hits.append("IN_NECK")

    # Meeting Lines
    if abs(c - c1) / max(c, c1, 1e-9) < 0.002:
        if _bear(o1,c1) and _bull(o,c):
            hits.append("MEETING_LINES_BULL")
        elif _bull(o1,c1) and _bear(o,c):
            hits.append("MEETING_LINES_BEAR")

    # Matching Low (two bearish with same close)
    if _bear(o1,c1) and _bear(o,c) and abs(c - c1) / max(c, c1, 1e-9) < 0.002:
        hits.append("MATCHING_LOW")

    return hits


# ── Three-candle detectors ─────────────────────────────────────────────────────

def _triple(o2,h2,l2,c2, o1,h1,l1,c1, o,h,l,c):
    hits = []
    body0 = _body(o,c); body1 = _body(o1,c1); body2 = _body(o2,c2)
    rng2 = _rng(h2,l2); rng0 = _rng(h,l)
    is_d1 = _is_doji(o1,c1,h1,l1)

    midpoint2 = (o2+c2)/2

    # Morning Star
    if (_bear(o2,c2) and _is_large(o2,c2,h2,l2) and _is_small(o1,c1,h1,l1) and
            _bull(o,c) and _is_large(o,c,h,l) and c > midpoint2):
        hits.append("MORNING_DOJI_STAR" if is_d1 else "MORNING_STAR")

    # Evening Star
    midpoint2_bull = (o2+c2)/2
    if (_bull(o2,c2) and _is_large(o2,c2,h2,l2) and _is_small(o1,c1,h1,l1) and
            _bear(o,c) and _is_large(o,c,h,l) and c < midpoint2_bull):
        hits.append("EVENING_DOJI_STAR" if is_d1 else "EVENING_STAR")

    # Abandoned Baby
    if (_bear(o2,c2) and _is_large(o2,c2,h2,l2) and is_d1 and
            h1 < l2 and  # doji gaps below candle 2
            _bull(o,c) and l > h1):  # candle 3 gaps above doji
        hits.append("ABANDONED_BABY_BULL")
    if (_bull(o2,c2) and _is_large(o2,c2,h2,l2) and is_d1 and
            l1 > h2 and
            _bear(o,c) and h < l1):
        hits.append("ABANDONED_BABY_BEAR")

    # Three White Soldiers
    if (_bull(o2,c2) and _bull(o1,c1) and _bull(o,c) and
            c > c1 > c2 and
            min(o1, o) > min(c2, o2) * 0.98 and  # each opens within/above prior body
            _upper_shad(o,c,h) < 0.3 * body0 and
            _upper_shad(o1,c1,h1) < 0.3 * body1 and
            _upper_shad(o2,c2,h2) < 0.3 * body2):
        hits.append("THREE_WHITE_SOLDIERS")

    # Three Black Crows
    if (_bear(o2,c2) and _bear(o1,c1) and _bear(o,c) and
            c < c1 < c2 and
            max(o1, o) < max(c2, o2) * 1.02 and
            _lower_shad(o,c,l) < 0.3 * body0 and
            _lower_shad(o1,c1,l1) < 0.3 * body1 and
            _lower_shad(o2,c2,l2) < 0.3 * body2):
        hits.append("THREE_BLACK_CROWS")

    # Three Inside Up: C2 bearish, C1 bullish inside C2, C0 bullish closes above C2 open
    if (_bear(o2,c2) and _bull(o1,c1) and
            o1 > c2 and c1 < o2 and  # C1 inside C2
            _bull(o,c) and c > o2):
        hits.append("THREE_INSIDE_UP")

    # Three Inside Down
    if (_bull(o2,c2) and _bear(o1,c1) and
            o1 < c2 and c1 > o2 and
            _bear(o,c) and c < o2):
        hits.append("THREE_INSIDE_DOWN")

    # Three Outside Up: C2 bearish, C1 bullish engulfs C2, C0 bullish higher
    if (_bear(o2,c2) and _bull(o1,c1) and
            o1 <= c2 and c1 >= o2 and  # C1 engulfs C2
            _bull(o,c) and c > c1):
        hits.append("THREE_OUTSIDE_UP")

    # Three Outside Down
    if (_bull(o2,c2) and _bear(o1,c1) and
            o1 >= c2 and c1 <= o2 and
            _bear(o,c) and c < c1):
        hits.append("THREE_OUTSIDE_DOWN")

    # Advance Block: three bullish but diminishing
    if (_bull(o2,c2) and _bull(o1,c1) and _bull(o,c) and c > c1 > c2 and
            body1 < body2 * 0.85 and body0 < body1 * 0.85 and  # shrinking bodies
            _upper_shad(o,c,h) > 0.3 * body0):  # growing upper shadow
        hits.append("ADVANCE_BLOCK")

    # Deliberation: two strong bullish, then small
    if (_bull(o2,c2) and _is_large(o2,c2,h2,l2) and
            _bull(o1,c1) and _is_large(o1,c1,h1,l1) and
            _is_small(o,c,h,l) and c >= c1 * 0.995):
        hits.append("DELIBERATION")

    # Two Crows: C2 strong bull, C1 bearish gaps up, C0 bearish closes inside C2 body
    if (_bull(o2,c2) and _is_large(o2,c2,h2,l2) and
            _bear(o1,c1) and o1 > c2 and
            _bear(o,c) and c > c2 and c < o2):
        hits.append("TWO_CROWS")

    # Unique Three River Bottom: bearish, inverted-hammer-like inside, small bullish
    if (_bear(o2,c2) and _is_large(o2,c2,h2,l2) and
            _bear(o1,c1) and l1 < l2 and  # new low
            _is_small(o1,c1,h1,l1) and
            _bull(o,c) and c < c1):
        hits.append("UNIQUE_THREE_RIVER")

    return hits


# ── Complex (4-5 candle) detectors ────────────────────────────────────────────

def _complex(df: pd.DataFrame, i: int) -> list[str]:
    """Detect 4-5 candle patterns ending at index i."""
    if i < 4: return []
    hits = []

    def row(k): return tuple(float(df.iloc[k][x]) for x in ["open","high","low","close"])

    o4,h4,l4,c4 = row(i-4)
    o3,h3,l3,c3 = row(i-3)
    o2,h2,l2,c2 = row(i-2)
    o1,h1,l1,c1 = row(i-1)
    o0,h0,l0,c0 = row(i)

    # Rising Three Methods
    if (_bull(o4,c4) and _is_large(o4,c4,h4,l4) and
            _bear(o3,c3) and _bear(o2,c2) and _bear(o1,c1) and  # 3 small bearish
            all(min(ox,cx) > l4 and max(ox,cx) < h4  # inside first candle
                for ox,cx in [(o3,c3),(o2,c2),(o1,c1)]) and
            _bull(o0,c0) and _is_large(o0,c0,h0,l0) and c0 > c4):
        hits.append("RISING_THREE_METHODS")

    # Falling Three Methods
    if (_bear(o4,c4) and _is_large(o4,c4,h4,l4) and
            _bull(o3,c3) and _bull(o2,c2) and _bull(o1,c1) and
            all(max(ox,cx) < h4 and min(ox,cx) > l4
                for ox,cx in [(o3,c3),(o2,c2),(o1,c1)]) and
            _bear(o0,c0) and _is_large(o0,c0,h0,l0) and c0 < c4):
        hits.append("FALLING_THREE_METHODS")

    # Upside Tasuki Gap (3 candles: bull, gap-up bull, bear fills gap partially)
    if i >= 2:
        op,hp,lp,cp = row(i-2)
        o1b,h1b,l1b,c1b = row(i-1)
        if (_bull(op,cp) and _bull(o1b,c1b) and o1b > cp and  # gap up
                _bear(o0,c0) and c0 > op):  # bear doesn't close the gap
            hits.append("UPSIDE_TASUKI_GAP")

    # Downside Tasuki Gap
    if i >= 2:
        op,hp,lp,cp = row(i-2)
        o1b,h1b,l1b,c1b = row(i-1)
        if (_bear(op,cp) and _bear(o1b,c1b) and o1b < cp and  # gap down
                _bull(o0,c0) and c0 < op):  # bull doesn't close the gap
            hits.append("DOWNSIDE_TASUKI_GAP")

    # Mat Hold (bull, 3 small mixed, then strong bull continuation)
    if (_bull(o4,c4) and _is_large(o4,c4,h4,l4) and
            all(min(ox,cx) > l4 for ox,cx in [(o3,c3),(o2,c2),(o1,c1)]) and
            _bull(o0,c0) and c0 > c4):
        hits.append("MAT_HOLD")

    # Separating Lines
    if i >= 1:
        op,hp,lp,cp = row(i-1)
        if abs(o0 - op) / max(o0, op, 1e-9) < 0.003:
            if _bear(op,cp) and _bull(o0,c0):
                hits.append("SEP_LINES_BULL")
            elif _bull(op,cp) and _bear(o0,c0):
                hits.append("SEP_LINES_BEAR")

    return hits


# ── Chart structure detectors ──────────────────────────────────────────────────

def _structure(df: pd.DataFrame, i: int) -> list[str]:
    """Scan candles up to index i for chart structure patterns."""
    if i < 20: return []
    hits = []
    window = df.iloc[max(0, i-60):i+1]
    c = window["close"].values
    h = window["high"].values
    lo = window["low"].values
    n = len(c)

    # ── Double Bottom / Double Top ─────────────────────────────────────────────
    # Find local minima and maxima (simple: compare to 3 neighbours)
    def local_min_idx():
        idxs = []
        for k in range(2, n-2):
            if lo[k] < lo[k-1] and lo[k] < lo[k-2] and lo[k] < lo[k+1] and lo[k] < lo[k+2]:
                idxs.append(k)
        return idxs

    def local_max_idx():
        idxs = []
        for k in range(2, n-2):
            if h[k] > h[k-1] and h[k] > h[k-2] and h[k] > h[k+1] and h[k] > h[k+2]:
                idxs.append(k)
        return idxs

    mins = local_min_idx()
    maxs = local_max_idx()

    # Double Bottom: two recent minima within 2% of each other, 5+ candles apart
    if len(mins) >= 2:
        m1, m2 = mins[-2], mins[-1]
        if m2 - m1 >= 5 and abs(lo[m1] - lo[m2]) / max(lo[m1], lo[m2], 1e-9) < 0.02:
            # Price should be breaking above the peak between them
            peak_between = h[m1:m2+1].max()
            if c[-1] >= peak_between * 0.995:
                hits.append("DOUBLE_BOTTOM")

    # Double Top: two recent maxima within 2%, with trough between
    if len(maxs) >= 2:
        m1, m2 = maxs[-2], maxs[-1]
        if m2 - m1 >= 5 and abs(h[m1] - h[m2]) / max(h[m1], h[m2], 1e-9) < 0.02:
            trough_between = lo[m1:m2+1].min()
            if c[-1] <= trough_between * 1.005:
                hits.append("DOUBLE_TOP")

    # ── Head & Shoulders ──────────────────────────────────────────────────────
    if len(maxs) >= 3:
        ls, hd, rs = maxs[-3], maxs[-2], maxs[-1]
        if (h[hd] > h[ls] and h[hd] > h[rs] and
                abs(h[ls] - h[rs]) / max(h[ls], h[rs], 1e-9) < 0.04):
            neckline = lo[ls:rs+1].min()
            if c[-1] < neckline * 1.01:
                hits.append("HEAD_AND_SHOULDERS")

    # ── Inverse H&S ───────────────────────────────────────────────────────────
    if len(mins) >= 3:
        ls, hd, rs = mins[-3], mins[-2], mins[-1]
        if (lo[hd] < lo[ls] and lo[hd] < lo[rs] and
                abs(lo[ls] - lo[rs]) / max(lo[ls], lo[rs], 1e-9) < 0.04):
            neckline = h[ls:rs+1].max()
            if c[-1] > neckline * 0.99:
                hits.append("INVERSE_HEAD_AND_SHOULDERS")

    # ── Flags ─────────────────────────────────────────────────────────────────
    if n >= 15:
        # Bullish flag: sharp up move then tight downward channel
        pole_end = max(0, n-12)
        pole_rise = (c[pole_end] - c[max(0, pole_end-6)]) / max(c[max(0, pole_end-6)], 1e-9)
        if pole_rise > 0.04:
            flag_c = c[pole_end:]
            if len(flag_c) >= 4:
                flag_slope = (flag_c[-1] - flag_c[0]) / len(flag_c)
                flag_range = max(flag_c) - min(flag_c)
                if flag_slope < 0 and flag_range < pole_rise * 0.5 * c[pole_end]:
                    hits.append("BULLISH_FLAG")

        pole_drop = (c[max(0, pole_end-6)] - c[pole_end]) / max(c[max(0, pole_end-6)], 1e-9)
        if pole_drop > 0.04:
            flag_c = c[pole_end:]
            if len(flag_c) >= 4:
                flag_slope = (flag_c[-1] - flag_c[0]) / len(flag_c)
                flag_range = max(flag_c) - min(flag_c)
                if flag_slope > 0 and flag_range < pole_drop * 0.5 * c[pole_end]:
                    hits.append("BEARISH_FLAG")

    # ── Triangles ─────────────────────────────────────────────────────────────
    if n >= 15:
        recent_h = h[-15:]
        recent_lo = lo[-15:]
        x = np.arange(15)
        if len(recent_h) == 15 and len(recent_lo) == 15:
            slope_h  = float(np.polyfit(x, recent_h, 1)[0])
            slope_lo = float(np.polyfit(x, recent_lo, 1)[0])
            avg_price = float(np.mean(c[-15:]))

            # Ascending: flat resistance + rising support
            if abs(slope_h) / (avg_price + 1e-9) < 0.001 and slope_lo / (avg_price + 1e-9) > 0.001:
                hits.append("ASCENDING_TRIANGLE")
            # Descending: falling resistance + flat support
            elif slope_h / (avg_price + 1e-9) < -0.001 and abs(slope_lo) / (avg_price + 1e-9) < 0.001:
                hits.append("DESCENDING_TRIANGLE")
            # Symmetrical: converging
            elif slope_h < -0.0002 * avg_price and slope_lo > 0.0002 * avg_price:
                hits.append("SYMMETRICAL_TRIANGLE")

    # ── Wedges ────────────────────────────────────────────────────────────────
    if n >= 15:
        recent_h  = h[-15:]
        recent_lo = lo[-15:]
        x = np.arange(15)
        if len(recent_h) == 15:
            slope_h  = float(np.polyfit(x, recent_h, 1)[0])
            slope_lo = float(np.polyfit(x, recent_lo, 1)[0])
            avg_p = float(np.mean(c[-15:]))

            # Falling Wedge: both slopes negative but converging (lo slope less negative)
            if (slope_h < -0.0002 * avg_p and slope_lo < 0 and
                    slope_lo > slope_h and  # converging
                    slope_lo - slope_h < abs(slope_h) * 0.9):
                hits.append("FALLING_WEDGE")

            # Rising Wedge: both slopes positive but converging (h slope less positive)
            if (slope_lo > 0.0002 * avg_p and slope_h > 0 and
                    slope_h < slope_lo and
                    slope_lo - slope_h < slope_lo * 0.9):
                hits.append("RISING_WEDGE")

    # ── Cup & Handle ──────────────────────────────────────────────────────────
    if n >= 35:
        cup = c[-35:-10]
        handle = c[-10:]
        if len(cup) >= 20 and len(handle) >= 5:
            cup_low  = min(cup)
            cup_rim  = max(cup[0], cup[-1])
            # Cup should be U-shaped (bottom in the middle)
            cup_mid  = min(cup[len(cup)//4 : 3*len(cup)//4])
            depth    = (cup_rim - cup_mid) / max(cup_rim, 1e-9)
            if depth > 0.05:
                handle_retracement = (max(handle) - min(handle)) / max(cup_rim - cup_mid, 1e-9)
                if handle_retracement < 0.5 and c[-1] >= cup_rim * 0.98:
                    hits.append("CUP_AND_HANDLE")

    # ── Rounding Bottom ───────────────────────────────────────────────────────
    if n >= 30:
        seg = c[-30:]
        mid = len(seg) // 2
        left_avg  = float(np.mean(seg[:8]))
        mid_avg   = float(np.mean(seg[mid-4:mid+4]))
        right_avg = float(np.mean(seg[-8:]))
        if mid_avg < left_avg * 0.97 and mid_avg < right_avg * 0.97 and right_avg > left_avg * 0.98:
            hits.append("ROUNDING_BOTTOM")

    return hits


# ── Main engine class ──────────────────────────────────────────────────────────

class CandlestickPatternEngine:
    """
    Detects 62 candlestick and chart patterns on OHLCV data.

    df must have columns: open, high, low, close, volume (lowercase).
    """

    def __init__(self, df: pd.DataFrame):
        # Normalise column names to lowercase
        self.df = df.copy()
        self.df.columns = [c.lower() for c in self.df.columns]
        for col in ["open","high","low","close","volume"]:
            if col not in self.df.columns:
                if col == "volume":
                    self.df["volume"] = 1_000_000.0
                else:
                    raise ValueError(f"Missing column: {col}")
        # Ensure numeric
        for col in ["open","high","low","close","volume"]:
            self.df[col] = pd.to_numeric(self.df[col], errors="coerce").ffill()

    def _date_at(self, i: int) -> str:
        try:
            return str(self.df.index[i].date())
        except Exception:
            return str(i)

    def detect_all(self, lookback: int = 60) -> list[dict]:
        """Scan the last `lookback` candles for all patterns."""
        df = self.df
        n  = len(df)
        start = max(0, n - lookback)
        results = []

        for i in range(start, n):
            candle_index = n - 1 - i  # 0 = most recent
            date_str = self._date_at(i)

            def _row(k):
                r = df.iloc[k]
                return float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])

            o, h, l, c = _row(i)

            # Single candle
            for code in _single(o, h, l, c):
                results.append(_make(code, candle_index, date_str, df, i))

            # Two candle
            if i >= 1:
                o1, h1, l1, c1 = _row(i-1)
                for code in _double(o1,h1,l1,c1, o,h,l,c):
                    results.append(_make(code, candle_index, date_str, df, i))

            # Three candle
            if i >= 2:
                o2, h2, l2, c2 = _row(i-2)
                o1, h1, l1, c1 = _row(i-1)
                for code in _triple(o2,h2,l2,c2, o1,h1,l1,c1, o,h,l,c):
                    results.append(_make(code, candle_index, date_str, df, i))

            # Complex (4-5 candles)
            if i >= 4:
                for code in _complex(df, i):
                    results.append(_make(code, candle_index, date_str, df, i))

        # Chart structure (scan once over full window)
        for code in _structure(df, n-1):
            results.append(_make(code, 0, self._date_at(n-1), df, n-1))

        return results

    def detect_recent(self, n_candles: int = 3) -> list[dict]:
        """Return patterns where candle_index <= n_candles (i.e. last n_candles)."""
        return [p for p in self.detect_all(lookback=max(60, n_candles+10))
                if p["candle_index"] <= n_candles]

    def pattern_summary(self) -> dict:
        """Returns {bullish, bearish, neutral} lists for latest 10 candles."""
        recent = [p for p in self.detect_all(lookback=60) if p["candle_index"] <= 10]
        return {
            "bullish": [p for p in recent if p["bias"] == "BULLISH"],
            "bearish": [p for p in recent if p["bias"] == "BEARISH"],
            "neutral": [p for p in recent if p["bias"] == "NEUTRAL"],
        }


def detect_patterns(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    """Convenience function — instantiate engine and detect all patterns."""
    return CandlestickPatternEngine(df).detect_all(lookback=lookback)
