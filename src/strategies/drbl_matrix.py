from __future__ import annotations
import pandas as pd
from ..calendar import month_rotation_date
from ..config import StrategyConfig
from ..models import DataMode, ModelName, PortfolioState, Recommendation, Regime
from ..indicators import (
    adx_wilder, atr_percent, atr_percentile_cap, momentum_score, rvol,
    selected_factor,
)

ASSETS = ("SPY", "QQQ", "GLD", "IBIT", "BTCUSD")

def monthly_rotation_score(prices: dict[str, pd.DataFrame]) -> dict[str, float]:
    """12–1 momentum dělené 60denní anualizovanou sample volatilitou; nevalidní skóre se vynechá."""
    scores: dict[str, float] = {}
    for asset in ASSETS:
        frame = prices.get(asset)
        if frame is None or frame.empty or "Close" not in frame:
            continue
        score = momentum_score(frame["Close"]).iloc[-1]
        if pd.notna(score):
            scores[asset] = float(score)
    return scores

def choose_rotation(scores: dict[str, float], incumbent: str | None, hysteresis: float = 0.08) -> str | None:
    valid = {key: value for key, value in scores.items() if pd.notna(value)}
    if not valid:
        return None
    challenger = max(valid, key=lambda key: valid[key])
    if incumbent is None or incumbent not in valid:
        return challenger
    threshold = valid[incumbent] + abs(valid[incumbent]) * hysteresis
    return challenger if challenger != incumbent and valid[challenger] > threshold else incumbent

def _finite(value) -> float | None:
    try:
        number = float(value)
        return number if pd.notna(number) else None
    except (TypeError, ValueError):
        return None

def _ticker_asset(ticker: str, config: StrategyConfig) -> str | None:
    for asset in ASSETS:
        candidates = {config.base_tickers.get(asset)}
        candidates.add(config.leveraged_tickers.get(asset))
        if asset == "GLD": candidates.add(config.gld_leveraged_ticker)
        if asset == "BTCUSD": candidates.add(config.btc_leveraged_ticker)
        if ticker in candidates:
            return asset
    return None

def _held_asset(state: PortfolioState, config: StrategyConfig) -> str | None:
    if len(state.positions) != 1:
        return None
    return _ticker_asset(next(iter(state.positions.values())).ticker, config)

def _factor_for(asset: str, config: StrategyConfig) -> str:
    return config.factor_by_asset.get(asset, "TURTLE_SOUP")

def _latest(frame: pd.DataFrame | None, asset: str, config: StrategyConfig) -> dict:
    if frame is None or frame.empty:
        return {"available": False, "reason": "Data nejsou dostupná."}
    factor = _factor_for(asset, config)
    factors = selected_factor(frame, factor, config)
    last = factors.iloc[-1]
    entry, exit_signal = bool(last["entry"]), bool(last["exit"])
    adx = _finite(adx_wilder(frame, config.adx_period).iloc[-1])
    relative_volume = _finite(rvol(frame["Volume"], config.rvol_short, config.rvol_long).iloc[-1])
    atrp = _finite(atr_percent(frame, config.atr_period).iloc[-1])
    atr_cap = _finite(atr_percentile_cap(frame, config.atr_period, config.atr_percentile_window, config.atr_percentile).iloc[-1])
    trend_filter_ready = adx is not None and relative_volume is not None
    volatility_filter_ready = atrp is not None and atr_cap is not None
    leverage_allowed = bool(
        trend_filter_ready and volatility_filter_ready
        and adx > config.adx_leverage_threshold
        and relative_volume > config.rvol_leverage_threshold
        and atrp <= atr_cap
    )
    regime = Regime.C if exit_signal else (Regime.A if entry and leverage_allowed else Regime.B if entry else Regime.UNKNOWN)
    details = {key: _finite(last[key]) for key in factors.columns if key not in {"entry", "exit"}}
    details.update({
        "factor": factor, "close": float(frame["Close"].iloc[-1]), "entry": entry, "exit": exit_signal,
        "adx14": adx, "rvol": relative_volume, "atr20_pct": atrp,
        "atr_pct_90th_percentile_prior": atr_cap,
        "trend_filter_ready": trend_filter_ready, "volatility_filter_ready": volatility_filter_ready,
        "leverage_allowed": leverage_allowed, "regime": regime.value, "available": True,
    })
    return details

def _recommendation(state, source, data_mode, ticker, action, target, delta, reason, regime, indicators, available=True):
    return Recommendation(state.model, None, source, data_mode, False, ticker, action, float(target), float(delta), 0.0, 0.0, reason, regime, indicators, available)

def generate_matrix_recommendation(
    prices: dict[str, pd.DataFrame], state: PortfolioState, config: StrategyConfig,
    source: str = "Yahoo Finance", data_mode: DataMode = DataMode.HISTORICAL,
    gld_leveraged_ticker: str | None = None, btc_leveraged_ticker: str | None = None,
) -> Recommendation:
    """Denní DRBL rozhodnutí pro aktuálního rotačního lídra; rotaci sama nespouští."""
    gl = gld_leveraged_ticker if gld_leveraged_ticker is not None else config.gld_leveraged_ticker
    btc_lev = btc_leveraged_ticker if btc_leveraged_ticker is not None else config.btc_leveraged_ticker
    # Attach runtime user mappings to a shallow local view of config maps; never invent a levered symbol.
    base_tickers = dict(config.base_tickers)
    levered_tickers = dict(config.leveraged_tickers)
    if gl: levered_tickers["GLD"] = gl
    if btc_lev: levered_tickers["BTCUSD"] = btc_lev
    indicators = {asset: _latest(prices.get(asset), asset, config) for asset in ASSETS}
    if len(state.positions) > 1:
        return _recommendation(state, source, DataMode.STALE, None, "REVIEW", 0, 0,
            "Portfolio obsahuje více než jednu spravovanou pozici; před novým obchodem je nutná ruční kontrola.", Regime.UNKNOWN, indicators, False)

    held = next(iter(state.positions.values()), None)
    held_asset = _ticker_asset(held.ticker, config) if held else None
    selected = state.selected_asset or held_asset
    if selected is None:
        return _recommendation(state, source, data_mode, None, "ROTATION_REQUIRED", 0, 0,
            "Není zvolen rotační lídr. Proveď plánovanou měsíční rotaci; denní signál lídra nevybírá.", Regime.UNKNOWN, indicators, False)
    info = indicators.get(selected, {})
    if not info.get("available"):
        return _recommendation(state, source, DataMode.STALE, None, "UNAVAILABLE", 0, 0,
            f"Chybí validní historie pro {selected} / faktor {_factor_for(selected, config)}.", Regime.UNKNOWN, indicators, False)

    # If rotation has selected a different base asset, close old exposure first. A new entry may occur next session.
    if held and held_asset != selected:
        return _recommendation(state, source, data_mode, held.ticker, "ROTATE_POSITION", 0, -held.market_value_usd,
            f"Měsíční rotace {held_asset} → {selected}; nejprve uzavřít původní pozici. Pokud nový faktor nemá entry, zůstaneme v hotovosti.", Regime.C, indicators)

    regime = Regime(info["regime"])
    reason = (
        f"Aktivum {selected}; faktor={info['factor']}; entry={info['entry']}; exit={info['exit']}; "
        f"ADX14={info['adx14']}; RVOL={info['rvol']}; ATR20%={info['atr20_pct']}; "
        f"předchozí ATR p90={info['atr_pct_90th_percentile_prior']}."
    )
    if info["exit"]:
        if held:
            return _recommendation(state, source, data_mode, held.ticker, "SELL_ALL", 0, -held.market_value_usd,
                "Režim C: cílová pozice všech spravovaných tickerů je nula; držet hotovost. " + reason, Regime.C, indicators)
        return _recommendation(state, source, data_mode, None, "HOLD_CASH", 0, 0,
            "Režim C: bez otevřené pozice, zůstat v hotovosti. " + reason, Regime.C, indicators)

    if not info["entry"]:
        if held:
            return _recommendation(state, source, data_mode, held.ticker, "HOLD", held.market_value_usd, 0,
                "Entry není aktivní a exit není aktivní; zachovat stávající pozici. " + reason, Regime.UNKNOWN, indicators)
        return _recommendation(state, source, data_mode, None, "HOLD_CASH", 0, 0,
            "Entry není aktivní; kapitál zůstává v hotovosti. " + reason, Regime.UNKNOWN, indicators)

    # Režim A je zakázán pro IBIT; BTCUSD má 3x režim pouze pokud uživatel výslovně nakonfiguroval broker-validní symbol.
    if selected == "IBIT":
        target_ticker = base_tickers[selected]
        regime = Regime.B
    elif selected == "BTCUSD" and not btc_lev:
        target_ticker = base_tickers[selected]
        regime = Regime.B
    elif regime == Regime.A:
        target_ticker = levered_tickers.get(selected)
        if selected == "GLD" and not gl:
            return _recommendation(state, source, data_mode, None, "CONFIGURATION_REQUIRED", 0, 0,
                "Režim A vyžaduje explicitně nakonfigurovaný broker-validní pákový ticker GLD; objednávka nebyla vytvořena.", Regime.A, indicators, False)
        if selected == "BTCUSD" and not btc_lev:
            target_ticker = base_tickers[selected]
            regime = Regime.B
        if not target_ticker:
            return _recommendation(state, source, data_mode, None, "CONFIGURATION_REQUIRED", 0, 0,
                f"Pro režim A u {selected} není nakonfigurovaný pákový ticker. Objednávka nebyla vytvořena.", Regime.A, indicators, False)
    else:
        target_ticker = base_tickers[selected]
        regime = Regime.B

    # BTC/IBIT and other 1x/no-leverage cases obey the same 85% target in regime B.
    target_usd = state.equity_usd * config.matrix_target_fraction
    current_usd = held.market_value_usd if held and held.ticker == target_ticker else 0.0
    if held and held.ticker != target_ticker:
        return _recommendation(state, source, data_mode, held.ticker, "ROTATE_POSITION", 0, -held.market_value_usd,
            f"Změna expozice {held.ticker} → {target_ticker}; nejprve uzavřít starý ticker. " + reason, regime, indicators)
    delta = target_usd - current_usd
    action = "HOLD" if abs(delta) < 0.01 else "BUY_OR_REBALANCE"
    return _recommendation(state, source, data_mode, target_ticker, action, target_usd, delta,
        f"Režim {regime.value}; cílová pozice {config.matrix_target_fraction:.0%} equity; zbytek zůstává hotovost. " + reason,
        regime, indicators)

def process_monthly_rotation(
    prices: dict[str, pd.DataFrame], state: PortfolioState, config: StrategyConfig, rotation_date: str,
) -> tuple[str | None, bool, dict[str, float]]:
    """Rotace nejdříve 28. dne/poslední seance před 28.; při chybějících skórech měsíc neuzavře."""
    scores = monthly_rotation_score(prices)
    if not scores:
        return state.selected_asset, False, scores
    stamp = pd.Timestamp(rotation_date)
    scheduled = month_rotation_date(stamp.year, stamp.month)
    if scheduled is None or stamp.date() < scheduled:
        return state.selected_asset, False, scores
    month = stamp.strftime("%Y-%m")
    if state.last_rotation_month == month:
        return state.selected_asset, False, scores
    previous = state.selected_asset
    selected = choose_rotation(scores, previous, config.rotation_hysteresis)
    if selected is None:
        return previous, False, scores
    state.selected_asset = selected
    state.last_rotation_month = month
    return selected, selected != previous, scores
