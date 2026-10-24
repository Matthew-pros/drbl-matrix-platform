from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..config import StrategyConfig
from ..indicators import rolling_drawdown, true_range


@dataclass(frozen=True)
class MarketRegimeAssessment:
    regime: str
    risk_off: bool
    reason: str
    metrics: dict[str, Any]


def assess_market_regime(prices: dict[str, pd.DataFrame], config: StrategyConfig) -> MarketRegimeAssessment:
    """Transparent daily-bar regime filter; no external model is implied.

    Reads SPY/QQQ trend and daily range plus VIX level/momentum. Only uses bars
    present in prices; callers should provide the history available as-of signal date.
    """
    spy = prices.get("SPY")
    qqq = prices.get("QQQ")
    vix = prices.get("VIX")
    if vix is None or vix.empty:
        vix = prices.get("^VIX")

    metrics: dict[str, Any] = {}
    reasons: list[str] = []
    vix_level: float | None = None
    vix_change_5d: float | None = None

    if vix is not None and not vix.empty and "Close" in vix:
        vix_close = vix["Close"].dropna()
        if not vix_close.empty:
            vix_level = float(vix_close.iloc[-1])
            if len(vix_close) >= 6 and float(vix_close.iloc[-6]) > 0:
                vix_change_5d = float(vix_close.iloc[-1] / vix_close.iloc[-6] - 1.0)
    metrics["vix_level"] = vix_level
    metrics["vix_change_5d_pct"] = vix_change_5d

    trend_below_200: dict[str, bool | None] = {}
    broken_20d_low = False
    crash_event = False
    for ticker, frame in (("SPY", spy), ("QQQ", qqq)):
        below_200: bool | None = None
        if frame is not None and not frame.empty and "Close" in frame:
            close = frame["Close"].dropna()
            if not close.empty:
                last_close = float(close.iloc[-1])
                metrics[f"{ticker.lower()}_close"] = last_close
                drawdown = float(rolling_drawdown(close).iloc[-1])
                metrics[f"{ticker.lower()}_drawdown_pct"] = drawdown
                if drawdown >= 0.30:
                    reasons.append(f"{ticker}: hluboký drawdown {drawdown:.1%} od dostupného maxima")
                sma200 = close.rolling(200, min_periods=200).mean().iloc[-1]
                if pd.notna(sma200):
                    below_200 = last_close < float(sma200)
                    metrics[f"{ticker.lower()}_sma200"] = float(sma200)
                if len(close) >= 21:
                    prior_low = float(frame["Low"].iloc[-21:-1].min()) if "Low" in frame else float(close.iloc[-21:-1].min())
                    broken_20d_low = broken_20d_low or last_close < prior_low
                if len(frame) >= 22 and {"High", "Low", "Close"}.issubset(frame.columns):
                    tr = true_range(frame)
                    prior_range = tr.rolling(20, min_periods=20).mean().shift(1).iloc[-1]
                    today_range = tr.iloc[-1]
                    prev_close = close.iloc[-2] if len(close) >= 2 else float("nan")
                    daily_return = last_close / float(prev_close) - 1.0 if pd.notna(prev_close) and prev_close else 0.0
                    metrics[f"{ticker.lower()}_daily_return_pct"] = daily_return
                    if pd.notna(prior_range) and float(prior_range) > 0:
                        range_multiple = float(today_range) / float(prior_range)
                        metrics[f"{ticker.lower()}_range_multiple"] = range_multiple
                        if daily_return <= config.risk_crash_daily_return and range_multiple >= config.risk_crash_range_multiple:
                            crash_event = True
                            reasons.append(
                                f"{ticker}: jednodenní pokles {daily_return:.1%} a rozsah {range_multiple:.1f}× předchozího průměru"
                            )
        trend_below_200[ticker] = below_200
    metrics["spy_below_sma200"] = trend_below_200.get("SPY")
    metrics["qqq_below_sma200"] = trend_below_200.get("QQQ")
    metrics["broken_20d_low"] = broken_20d_low
    metrics["crash_event"] = crash_event

    if vix_level is not None and vix_level >= config.risk_off_vix_threshold:
        reasons.append(f"VIX {vix_level:.1f} ≥ {config.risk_off_vix_threshold:.1f}")
    if (
        vix_level is not None
        and vix_level >= config.risk_vix_spike_minimum
        and vix_change_5d is not None
        and vix_change_5d >= config.risk_vix_spike_threshold
    ):
        reasons.append(f"VIX za 5 seancí vzrostl o {vix_change_5d:.1%}")
    if (
        vix_level is not None
        and vix_level >= config.risk_elevated_vix_threshold
        and trend_below_200.get("SPY") is True
        and trend_below_200.get("QQQ") is True
    ):
        reasons.append("SPY i QQQ jsou pod SMA200 při zvýšeném VIX")
    if vix_level is not None and vix_level >= config.risk_elevated_vix_threshold and broken_20d_low:
        reasons.append("SPY/QQQ prolomily předchozí 20denní minimum při zvýšeném VIX")

    if reasons:
        return MarketRegimeAssessment("RISK_OFF", True, "; ".join(dict.fromkeys(reasons)), metrics)

    spy_above = trend_below_200.get("SPY") is False
    qqq_above = trend_below_200.get("QQQ") is False
    if spy_above and qqq_above and vix_level is not None and vix_level < 20:
        return MarketRegimeAssessment("RISK_ON", False, "SPY i QQQ jsou nad SMA200 a VIX je pod 20.", metrics)

    reason = "Přechodový režim; není aktivní risk-off spouštěč."
    if vix_level is None:
        reason += " VIX není dostupný, klasifikace proto používá jen cenové krizové spouštěče."
    return MarketRegimeAssessment("TRANSITION", False, reason, metrics)


def crisis_drawdown_candidate(
    prices: dict[str, pd.DataFrame], config: StrategyConfig, filled_levels: set[str],
    allowed_tickers: set[str] | None = None,
) -> tuple[str, float] | None:
    """Returns (SPY/QQQ, drawdown) when risk-off plus configured crisis DD is met."""
    if not config.crisis_alm_enabled:
        return None
    assessment = assess_market_regime(prices, config)
    if not assessment.risk_off:
        return None
    if assessment.metrics.get("crash_event") is not True:
        return None
    eligible: list[tuple[str, float]] = []
    for ticker in ("SPY", "QQQ"):
        if allowed_tickers is not None and ticker not in allowed_tickers:
            continue
        frame = prices.get(ticker)
        if frame is None or frame.empty or "Close" not in frame:
            continue
        dd_series = rolling_drawdown(frame["Close"].dropna())
        if dd_series.empty:
            continue
        dd = float(dd_series.iloc[-1])
        if dd >= config.crisis_alm_drawdown and "crash_event" not in filled_levels:
            eligible.append((ticker, dd))
    return max(eligible, key=lambda item: item[1]) if eligible else None
