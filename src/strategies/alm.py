from __future__ import annotations

import pandas as pd

from ..config import StrategyConfig
from ..indicators import rolling_drawdown
from ..models import DataMode, ModelName, PortfolioState, Recommendation, Regime
from .risk_overlay import crisis_drawdown_candidate


def generate_alm_recommendation(
    prices: dict[str, pd.DataFrame], state: PortfolioState, config: StrategyConfig,
    source: str = "Yahoo Finance", data_mode: DataMode = DataMode.HISTORICAL,
    allow_crisis_tier: bool = False,
) -> Recommendation:
    """Stupňovaný ALM nákup pouze základních ETF SPY/QQQ.

    Standalone ALM retains the configured 30/50/80% drawdown tiers.
    Combined may request only a distinct starter during a confirmed shock event.
    """
    if len(state.positions) > 1:
        return Recommendation(state.model, None, source, DataMode.STALE, False, None, "REVIEW", 0, 0, 0, 0,
            "ALM očekává nejvýše jednu základní pozici SPY nebo QQQ.", available=False)
    held = next(iter(state.positions.values()), None)
    held_asset = held.ticker if held else None
    if held_asset and held_asset not in {"SPY", "QQQ"}:
        return Recommendation(state.model, None, source, DataMode.STALE, False, None, "REVIEW", 0, 0, 0, 0,
            "ALM může držet pouze základní ETF SPY/QQQ; nejprve uzavři pozici mimo krizový univerzum.", available=False)
    candidates: list[tuple[str, float, float]] = []
    indicators: dict[str, float | None] = {}
    for ticker in ("SPY", "QQQ"):
        if held_asset and ticker != held_asset:
            continue
        frame = prices.get(ticker)
        if frame is None or frame.empty or "Close" not in frame:
            indicators[f"{ticker}_drawdown"] = None
            continue
        close = frame["Close"].dropna()
        if close.empty or close.iloc[-1] <= 0:
            indicators[f"{ticker}_drawdown"] = None
            continue
        dd = float(rolling_drawdown(close).iloc[-1])
        indicators[f"{ticker}_drawdown"] = dd
        indicators[f"{ticker}_close"] = float(close.iloc[-1])
        candidates.append((ticker, dd, float(close.iloc[-1])))

    eligible: list[tuple[str, float, str, float]] = []
    crisis_only = allow_crisis_tier and state.model == ModelName.COMBINED
    if not crisis_only:
        for ticker, dd, _ in candidates:
            for tier_key, threshold, allocation in reversed(config.alm_tiers):
                if dd >= threshold and tier_key not in state.alm_levels_filled:
                    eligible.append((ticker, dd, tier_key, allocation))
                    break
    if crisis_only:
        allowed = {held_asset} if held_asset else None
        crisis_candidate = crisis_drawdown_candidate(prices, config, state.alm_levels_filled, allowed)
        if crisis_candidate is not None:
            ticker, dd = crisis_candidate
            eligible.append((ticker, dd, "crash_event", config.crisis_alm_allocation))
    if not eligible:
        return Recommendation(state.model, None, source, data_mode, False, None, "HOLD", 0, 0, 0, 0,
            "SPY/QQQ nedosáhly další neprovedené ALM tranše, nebo není potvrzen krizový starter.", indicators=indicators)
    ticker, dd, tier_key, allocation = max(eligible, key=lambda item: item[1])
    current = held.market_value_usd if held else 0.0
    max_total_position = state.equity_usd * (1-config.alm_cash_reserve)
    requested_delta = state.equity_usd * allocation
    target = min(current + requested_delta, max_total_position)
    delta = max(0.0, target-current)
    if delta <= 0.01:
        return Recommendation(state.model, None, source, data_mode, False, None, "HOLD", 0, 0, 0, 0,
            "Další tranše by porušila limit hotovostní rezervy; obchod nevytvořen.", indicators=indicators)
    indicators["alm_tier"] = tier_key
    indicators["alm_allocation_pct"] = allocation
    indicators["selected_drawdown"] = dd
    if tier_key == "crash_event":
        reason = (
            f"Krizový ALM starter {ticker}: {allocation:.0%} equity při drawdownu {dd:.1%}; "
            f"spouštěč risk-off a crash potvrzen. Zůstává minimálně {config.alm_cash_reserve:.0%} equity v hotovosti."
        )
    else:
        reason = (
            f"ALM tranše {tier_key} ({allocation:.0%} equity při DD {dd:.1%}); "
            f"zachovat minimálně {config.alm_cash_reserve:.0%} equity v hotovosti."
        )
    return Recommendation(state.model, None, source, data_mode, False, ticker, "BUY", target, delta, 0, 0,
        reason, Regime.UNKNOWN, indicators)
