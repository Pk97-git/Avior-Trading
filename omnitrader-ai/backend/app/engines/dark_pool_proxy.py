"""
engines/dark_pool_proxy.py
===========================
Institutional activity detection — dark pool proxy signals.

We can't access actual dark pool prints (requires Bloomberg Terminal).
Instead we detect institutional FOOTPRINTS:

1. Volume surge: volume > 3x 20-day average → institutions can't hide size
2. Price-volume divergence: price flat ±0.5% but volume > 2x avg → accumulation/distribution
3. Unusual close-to-open gaps: significant gaps suggest pre-market institutional moves
4. Block trade proxy: single-day volume > 5% of avg daily volume is a block trade equivalent

Signal types:
  ACCUMULATION: High volume + flat/rising price → institutions buying quietly
  DISTRIBUTION: High volume + flat/falling price → institutions selling quietly
  BREAKOUT_CONFIRMATION: High volume + strong price move = institutional breakout
  INSTITUTIONAL_INTEREST: Moderate unusual volume, no clear direction yet
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

VOLUME_SURGE_THRESHOLD  = 2.5   # volume / avg_volume > this = surge
ACCUMULATION_PRICE_BAND = 0.015 # ±1.5% price move = "flat"
BREAKOUT_PRICE_MOVE     = 0.025 # >2.5% price move = breakout


def detect_institutional_activity(
    df: pd.DataFrame,   # OHLCV dataframe, columns: Open, High, Low, Close, Volume
    lookback_volume: int = 20,
    scan_days: int = 10,
) -> list[dict]:
    """
    Scan recent candles for institutional activity footprints.
    Returns list of detected events, newest first.
    """
    if df is None or len(df) < lookback_volume + 5:
        return []

    # Normalize columns
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            return []
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["close", "volume"])
    df = df.sort_index()

    # Rolling volume average
    df["avg_volume"] = df["volume"].rolling(window=lookback_volume).mean()
    df["vol_ratio"]  = df["volume"] / df["avg_volume"].replace(0, np.nan)

    # Price change
    df["price_chg_pct"] = df["close"].pct_change()
    df["gap_pct"]       = (df["open"] - df["close"].shift(1)) / df["close"].shift(1)

    events = []
    scan_window = df.iloc[-scan_days:]

    for date, row in scan_window.iterrows():
        if pd.isna(row.get("vol_ratio")) or pd.isna(row.get("price_chg_pct")):
            continue

        vol_ratio  = float(row["vol_ratio"])
        price_chg  = float(row["price_chg_pct"])
        gap_pct    = float(row.get("gap_pct", 0) or 0)
        close      = float(row["close"])
        volume     = float(row["volume"])
        avg_vol    = float(row["avg_volume"])

        if vol_ratio < 1.5:
            continue  # Not unusual enough

        # Classify
        signal_type = None
        strength    = 1
        description = ""

        if vol_ratio >= VOLUME_SURGE_THRESHOLD:
            if abs(price_chg) <= ACCUMULATION_PRICE_BAND:
                # High volume, price barely moved — classic accumulation or distribution
                if price_chg >= 0:
                    signal_type = "ACCUMULATION"
                    description = f"Volume {vol_ratio:.1f}x average with flat price (+{price_chg*100:.2f}%) — possible quiet institutional buying"
                else:
                    signal_type = "DISTRIBUTION"
                    description = f"Volume {vol_ratio:.1f}x average with flat price ({price_chg*100:.2f}%) — possible quiet institutional selling"
                strength = 4 if vol_ratio >= 4 else 3

            elif abs(price_chg) >= BREAKOUT_PRICE_MOVE:
                signal_type = "BREAKOUT_CONFIRMATION"
                direction = "up" if price_chg > 0 else "down"
                description = f"Volume {vol_ratio:.1f}x average with {price_chg*100:+.2f}% price move — institutional-grade breakout {direction}"
                strength = 5 if vol_ratio >= 5 else 4

            else:
                signal_type = "INSTITUTIONAL_INTEREST"
                description = f"Volume {vol_ratio:.1f}x average — elevated institutional interest, direction unclear"
                strength = 3

        elif vol_ratio >= 1.5:
            signal_type = "ELEVATED_VOLUME"
            description = f"Volume {vol_ratio:.1f}x average — above-normal activity, worth monitoring"
            strength = 2

        if signal_type:
            events.append({
                "date":        str(date)[:10],
                "signal_type": signal_type,
                "description": description,
                "strength":    strength,
                "vol_ratio":   round(vol_ratio, 2),
                "price_chg_pct": round(price_chg * 100, 3),
                "gap_pct":     round(gap_pct * 100, 3),
                "close":       round(close, 2),
                "volume":      int(volume),
                "avg_volume":  int(avg_vol),
                "is_bullish":  signal_type in ("ACCUMULATION", "BREAKOUT_CONFIRMATION") and price_chg >= 0,
                "is_bearish":  signal_type in ("DISTRIBUTION",) or (signal_type == "BREAKOUT_CONFIRMATION" and price_chg < 0),
            })

    events.sort(key=lambda x: x["date"], reverse=True)
    return events
