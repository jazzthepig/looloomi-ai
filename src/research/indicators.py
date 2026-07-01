"""
Technical indicators — Wilder ADX, EMAs, ATR, RSI, channels.

Vectorised implementations that match the freqtrade / ta-lib output closely enough
for parity with the baseline. Extracted from `data_bridge.py` so it can be imported
by `universe.py` without creating a circular import (data_bridge → universe →
data_bridge).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def precompute_indicators(
    df_4h: pd.DataFrame,
    adx_period: int = 14,
    ema_fast: int = 9,
    ema_slow: int = 21,
    atr_period: int = 14,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    """Attach the full indicator suite to a 4h DataFrame (vectorised, like freqtrade).

    ADX uses Welles Wilder smoothing (matches talib.ADX output).
    MACD is the standard 12/26/9 EMA difference + signal line.
    Volume MA is a 20-bar SMA.

    Returns df with added columns:
      adx_14, plus_di_14, minus_di_14,
      ema_9, ema_20, ema_21, ema_50,
      atr, atr_pct,
      rsi,
      macd, macd_signal, macd_hist,
      volume_ma, vol_contraction,
      roll_min_20, roll_max_20.
    """
    df = df_4h.copy()
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    v = df["volume"].values if "volume" in df.columns else np.zeros(len(df))

    # True Range
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))

    # +DM / -DM (Welles Wilder definition)
    prev_h = np.concatenate([[h[0]], h[:-1]])
    prev_l = np.concatenate([[l[0]], l[:-1]])
    up_move = h - prev_h
    down_move = prev_l - l
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder smoothing of TR, +DM, -DM
    def wilder_smooth(arr, period):
        out = np.full_like(arr, np.nan, dtype=float)
        if period >= len(arr):
            return out
        out[period - 1] = arr[:period].sum()
        for i in range(period, len(arr)):
            out[i] = out[i - 1] - (out[i - 1] / period) + arr[i]
        return out

    sm_tr = wilder_smooth(tr, adx_period)
    sm_pdm = wilder_smooth(plus_dm, adx_period)
    sm_ndm = wilder_smooth(minus_dm, adx_period)

    # +DI / -DI (guard divide-by-zero)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = np.where(sm_tr > 0, 100.0 * sm_pdm / sm_tr, 0.0)
        minus_di = np.where(sm_tr > 0, 100.0 * sm_ndm / sm_tr, 0.0)
        dx_sum = plus_di + minus_di
        dx = np.where(dx_sum > 0, 100.0 * np.abs(plus_di - minus_di) / dx_sum, 0.0)
    adx = wilder_smooth(dx, adx_period)

    # ATR via Wilder smoothing (standard)
    atr = sm_tr / adx_period

    df["adx_14"] = adx
    df["plus_di_14"] = plus_di
    df["minus_di_14"] = minus_di
    df["ema_9"] = pd.Series(c).ewm(span=ema_fast, adjust=False).mean().values
    df["ema_21"] = pd.Series(c).ewm(span=ema_slow, adjust=False).mean().values
    df["ema_50"] = pd.Series(c).ewm(span=50, adjust=False).mean().values
    df["ema_20"] = pd.Series(c).ewm(span=20, adjust=False).mean().values
    df["atr"] = atr
    df["atr_pct"] = atr / np.where(c > 0, c, np.nan)

    # RSI (Wilder)
    delta = np.concatenate([[0], np.diff(c)])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    sm_gain = wilder_smooth(gain, rsi_period)
    sm_loss = wilder_smooth(loss, rsi_period)
    rs = np.where(sm_loss > 0, sm_gain / sm_loss, np.nan)
    rsi = np.where(
        sm_loss == 0,
        100.0,
        np.where(sm_gain == 0, 0.0, 100.0 - 100.0 / (1.0 + rs)),
    )
    df["rsi"] = rsi

    # MACD (12/26/9 EMA diff + signal line). Vectorised.
    ema_fast_series = pd.Series(c).ewm(span=macd_fast, adjust=False).mean()
    ema_slow_series = pd.Series(c).ewm(span=macd_slow, adjust=False).mean()
    macd_line = ema_fast_series - ema_slow_series
    signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
    df["macd"] = macd_line.values
    df["macd_signal"] = signal_line.values
    df["macd_hist"] = (macd_line - signal_line).values

    # Volume MA + contraction flag (matches freqtrade volume_ma + vol_contraction)
    vol_series = pd.Series(v)
    df["volume_ma"] = vol_series.rolling(20).mean().values
    df["vol_contraction"] = (vol_series < df["volume_ma"] * 0.5).values

    # Robust channel indicators
    df["roll_min_20"] = pd.Series(df["low"]).rolling(20).min().values
    df["roll_max_20"] = pd.Series(df["high"]).rolling(20).max().values
    return df