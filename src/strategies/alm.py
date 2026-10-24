from __future__ import annotations
import pandas as pd
from ..config import StrategyConfig
from ..indicators import rolling_drawdown
from ..models import DataMode, ModelName, PortfolioState, Recommendation, Regime

def generate_alm_recommendation(
    prices: dict[str, pd.DataFrame], state: PortfolioState, config: StrategyConfig,
    source: str = "Yahoo Finance", data_mode: DataMode = DataMode.HISTORICAL,
) -> Recommendation:
    """ALM pracuje pouze se SPY/QQQ. V samostatném ALM modelu je možné postupovat po tranších.
    Combined po prvním potvrzeném fillu přepne na DRBL a další ALM tranše už nevydává.
    """
    if state.model == ModelName.COMBINED and state.alm_completed and state.alm_fill_confirmed:
        return Recommendation(state.model, None, source, data_mode, False, None, "HOLD", 0, 0, 0, 0,
            "Combined již přešel do provozní DRBL fáze.")
    if len(state.positions) > 1:
        return Recommendation(state.model, None, source, DataMode.STALE, False, None, "REVIEW", 0, 0, 0, 0,
            "ALM očekává nejvýše jednu základní pozici SPY nebo QQQ.", available=False)
    held = next(iter(state.positions.values()), None)
    held_asset = held.ticker if held else None
    if held_asset and held_asset not in {"SPY", "QQQ"}:
        return Recommendation(state.model, None, source, DataMode.STALE, False, None, "REVIEW", 0, 0, 0, 0,
            "ALM může držet pouze základní ETF SPY/QQQ.", available=False)
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
    eligible = []
    for ticker, dd, _ in candidates:
        for tier_key, threshold, allocation in reversed(config.alm_tiers):
            if dd >= threshold and tier_key not in state.alm_levels_filled:
                eligible.append((ticker, dd, tier_key, allocation))
                break
    if not eligible:
        return Recommendation(state.model, None, source, data_mode, False, None, "HOLD", 0, 0, 0, 0,
            "SPY/QQQ nedosáhly další neprovedené ALM tranše, nebo byly všechny tranše vyčerpány.", indicators=indicators)
    # Pokud portfolio ještě nic nedrží, vyber aktivum s hlubším drawdownem. Pak pokračuj jen na drženém aktivu.
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
    return Recommendation(state.model, None, source, data_mode, False, ticker, "BUY", target, delta, 0, 0,
        f"ALM tranše {tier_key} ({allocation:.0%} equity při DD {dd:.1%}); zachovat minimálně {config.alm_cash_reserve:.0%} equity v hotovosti.",
        Regime.UNKNOWN, indicators)
