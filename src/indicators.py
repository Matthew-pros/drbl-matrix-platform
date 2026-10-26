"""Matematicky explicitní indikátory; všechny rolling reference vylučují aktuální bar tam, kde se testuje breakout."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

REQUIRED_OHLCV = ("Open", "High", "Low", "Close", "Volume")

def normalize_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    if data is None or data.empty:
        raise ValueError("Poskytovatel vrátil prázdná data.")
    df = data.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0] if c[0] in REQUIRED_OHLCV else c[-1]) for c in df.columns]
    df.columns = [str(c).strip().title() for c in df.columns]
    missing = set(REQUIRED_OHLCV) - set(df.columns)
    if missing:
        raise ValueError(f"Chybí sloupce OHLCV: {', '.join(sorted(missing))}.")
    idx = pd.to_datetime(df.index, errors="coerce")
    valid = ~idx.isna()
    df = df.loc[valid].copy(); idx = idx[valid]
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for col in REQUIRED_OHLCV:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    positive = (df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
    coherent = (df["High"] >= df[["Open", "Close", "Low"]].max(axis=1)) & (df["Low"] <= df[["Open", "Close", "High"]].min(axis=1))
    df = df.loc[positive & coherent]
    df.loc[df["Volume"] < 0, "Volume"] = np.nan
    return df

def rolling_drawdown(close: pd.Series) -> pd.Series:
    peak = close.cummax()
    return (peak - close) / peak

def momentum_12_1(close: pd.Series) -> pd.Series:
    # Jeden rok přibližně 252 barů; posledních 22 barů se záměrně vynechá.
    return (close.shift(22) - close.shift(252)) / close.shift(252)

def annualized_volatility(close: pd.Series, window: int = 60) -> pd.Series:
    returns = close.pct_change(fill_method=None)
    return returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(252)

def momentum_score(close: pd.Series) -> pd.Series:
    momentum = momentum_12_1(close)
    volatility = annualized_volatility(close, 60)
    score = momentum / volatility
    return score.where(volatility.notna() & (volatility > 0))

def true_range(data: pd.DataFrame) -> pd.Series:
    prev = data["Close"].shift(1)
    return pd.concat([(data["High"]-data["Low"]), (data["High"]-prev).abs(), (data["Low"]-prev).abs()], axis=1).max(axis=1)

def atr_wilder(data: pd.DataFrame, period: int = 20) -> pd.Series:
    """ATR with an explicit SMA seed followed by Wilder smoothing."""
    tr = true_range(data).astype(float)
    out = pd.Series(np.nan, index=data.index, dtype=float, name=f"ATR{period}")
    if len(data) <= period:
        return out
    out.iloc[period] = tr.iloc[1:period+1].mean()
    for i in range(period+1, len(data)):
        out.iloc[i] = (out.iloc[i-1] * (period-1) + tr.iloc[i]) / period
    return out

def atr_percent(data: pd.DataFrame, period: int = 20) -> pd.Series:
    return atr_wilder(data, period) / data["Close"]

def atr_percentile_cap(data: pd.DataFrame, period: int = 20, window: int = 252, percentile: float = 0.90) -> pd.Series:
    # Threshold uses only previous bars, avoiding contamination by today's volatility.
    return atr_percent(data, period).rolling(window, min_periods=window).quantile(percentile).shift(1)

def rvol(volume: pd.Series, short: int = 20, long: int = 200) -> pd.Series:
    numerator = volume.rolling(short, min_periods=short).mean()
    denominator = volume.rolling(long, min_periods=long).mean()
    return (numerator / denominator).where(denominator > 0)

def adx_wilder(data: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = data["High"].astype(float), data["Low"].astype(float), data["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    up, down = high.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=data.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=data.index)
    tr.iloc[0] = plus_dm.iloc[0] = minus_dm.iloc[0] = np.nan
    tr_s = pd.Series(np.nan, index=data.index, dtype=float)
    plus_s, minus_s = tr_s.copy(), tr_s.copy()
    if len(data) <= period:
        return pd.Series(np.nan, index=data.index, name="ADX")
    tr_s.iloc[period] = tr.iloc[1:period+1].sum(min_count=period)
    plus_s.iloc[period] = plus_dm.iloc[1:period+1].sum(min_count=period)
    minus_s.iloc[period] = minus_dm.iloc[1:period+1].sum(min_count=period)
    for i in range(period+1, len(data)):
        tr_s.iloc[i] = tr_s.iloc[i-1] - tr_s.iloc[i-1]/period + tr.iloc[i]
        plus_s.iloc[i] = plus_s.iloc[i-1] - plus_s.iloc[i-1]/period + plus_dm.iloc[i]
        minus_s.iloc[i] = minus_s.iloc[i-1] - minus_s.iloc[i-1]/period + minus_dm.iloc[i]
    plus_di = 100 * plus_s / tr_s.replace(0, np.nan)
    minus_di = 100 * minus_s / tr_s.replace(0, np.nan)
    denominator = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di-minus_di).abs() / denominator
    adx = pd.Series(np.nan, index=data.index, dtype=float, name="ADX")
    first = 2*period-1
    if len(data) > first:
        adx.iloc[first] = dx.iloc[period:first+1].mean()
        for i in range(first+1, len(data)):
            adx.iloc[i] = (adx.iloc[i-1]*(period-1) + dx.iloc[i])/period
    return adx

def turtle_soup_factors(data: pd.DataFrame, entry_lookback: int = 40, exit_lookback: int = 20, confirmation_days: int = 5) -> pd.DataFrame:
    """TS/DB hybrid from the spec: 40-bar breakout after a 5-bar pause; exit on 20-bar low."""
    df = data.copy()
    high_level = df["High"].shift(1).rolling(entry_lookback, min_periods=entry_lookback).max()
    exit_level = df["Low"].shift(1).rolling(exit_lookback, min_periods=exit_lookback).min()
    prior_high = df["High"].shift(1)
    prior_reference = df["High"].shift(2).rolling(entry_lookback, min_periods=entry_lookback).max()
    prior_new_high = prior_high >= prior_reference
    no_recent_new_high = prior_new_high.rolling(confirmation_days, min_periods=confirmation_days).sum().eq(0)
    entry = (df["Close"] >= high_level) & no_recent_new_high
    exit_signal = df["Close"] <= exit_level
    return pd.DataFrame({"entry_level": high_level, "exit_level": exit_level, "entry": entry.fillna(False), "exit": exit_signal.fillna(False)}, index=df.index)

def breakout_factors(data: pd.DataFrame, entry_lookback: int = 40, exit_lookback: int = 20) -> pd.DataFrame:
    # Retain the simpler 40/20 Donchian breakout as a separate selectable baseline.
    df = data.copy()
    entry_level = df["High"].shift(1).rolling(entry_lookback, min_periods=entry_lookback).max()
    exit_level = df["Low"].shift(1).rolling(exit_lookback, min_periods=exit_lookback).min()
    return pd.DataFrame({"entry_level": entry_level, "exit_level": exit_level, "entry": (df["Close"] >= entry_level).fillna(False), "exit": (df["Close"] <= exit_level).fillna(False)}, index=df.index)

def keltner_factors(data: pd.DataFrame, ema_period: int = 50, atr_period: int = 20, atr_multiple: float = 2.0) -> pd.DataFrame:
    df = data.copy()
    middle = df["Close"].ewm(span=ema_period, adjust=False, min_periods=ema_period).mean()
    atr = atr_wilder(df, atr_period)
    upper = middle + atr_multiple * atr
    return pd.DataFrame({"middle": middle, "upper": upper, "atr": atr, "entry": (df["Close"] > upper).fillna(False), "exit": (df["Close"] < middle).fillna(False)}, index=df.index)

def regression_factors(close: pd.Series, period: int = 100, band_multiple: float = 2.0) -> pd.DataFrame:
    slope = pd.Series(np.nan, index=close.index, dtype=float)
    mean = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std(ddof=0)
    upper = mean + band_multiple*std
    for i in range(period-1, len(close)):
        values = close.iloc[i-period+1:i+1].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            continue
        slope.iloc[i] = np.polyfit(np.arange(period, dtype=float), values, 1)[0]
    return pd.DataFrame({"slope": slope, "upper_band": upper, "entry": ((slope > 0) & (close > upper)).fillna(False), "exit": (slope < 0).fillna(False)}, index=close.index)

def sma200_factors(data: pd.DataFrame, period: int = 200) -> pd.DataFrame:
    average = data["Close"].rolling(period, min_periods=period).mean()
    return pd.DataFrame({"middle": average, "entry": (data["Close"] > average).fillna(False), "exit": (data["Close"] < average).fillna(False)}, index=data.index)

def ema200_factors(data: pd.DataFrame, period: int = 200) -> pd.DataFrame:
    average = data["Close"].ewm(span=period, adjust=False, min_periods=period).mean()
    return pd.DataFrame({"middle": average, "entry": (data["Close"] > average).fillna(False), "exit": (data["Close"] < average).fillna(False)}, index=data.index)

def vwap200_factors(data: pd.DataFrame, period: int = 200) -> pd.DataFrame:
    typical = (data["High"] + data["Low"] + data["Close"])/3
    vol = data["Volume"].where(data["Volume"] >= 0)
    denominator = vol.rolling(period, min_periods=period).sum().replace(0, np.nan)
    vwap = (typical*vol).rolling(period, min_periods=period).sum()/denominator
    return pd.DataFrame({"middle": vwap, "entry": (data["Close"] > vwap).fillna(False), "exit": (data["Close"] < vwap).fillna(False)}, index=data.index)

def selected_factor(data: pd.DataFrame, factor: str, config) -> pd.DataFrame:
    factor = factor.upper()
    if factor == "BREAKOUT_40_20":
        result = breakout_factors(data, config.ts_entry_lookback, config.ts_exit_lookback)
    elif factor == "TURTLE_SOUP":
        result = turtle_soup_factors(data, config.ts_entry_lookback, config.ts_exit_lookback, config.ts_confirmation_days)
    elif factor == "KELTNER":
        result = keltner_factors(data, config.keltner_ema_period, config.keltner_atr_period, config.keltner_atr_multiple)
    elif factor == "LRS":
        result = regression_factors(data["Close"], config.regression_period, config.regression_band_multiple)
    elif factor == "SMA200":
        result = sma200_factors(data, config.sma_period)
    elif factor == "EMA200":
        result = ema200_factors(data, config.ema_period)
    elif factor == "VWAP200":
        result = vwap200_factors(data, config.vwap_period)
    else:
        raise ValueError(f"Neznámý trendový faktor: {factor}.")
    indicator_columns = [column for column in result.columns if column not in {"entry", "exit"}]
    if indicator_columns:
        ready = result[indicator_columns].notna().all(axis=1)
        result.loc[~ready, ["entry", "exit"]] = False
    return result
