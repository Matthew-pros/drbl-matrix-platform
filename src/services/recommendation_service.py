from __future__ import annotations
from dataclasses import replace
from datetime import UTC, datetime
import pandas as pd
from ..config import CostConfig, StrategyConfig
from ..costs import estimate_costs
from ..models import DataMode, ModelName, PortfolioState, Recommendation
from ..strategies.alm import generate_alm_recommendation
from ..strategies.combined import generate_combined_recommendation
from ..strategies.drbl_matrix import generate_matrix_recommendation

def recommend(
    model: ModelName, prices: dict[str, pd.DataFrame], state: PortfolioState,
    strategy: StrategyConfig, costs: CostConfig, source: str = "Yahoo Finance",
    data_mode: DataMode = DataMode.HISTORICAL, latest_timestamp=None,
    gld_leveraged_ticker: str | None = None, btc_leveraged_ticker: str | None = None,
    max_age_hours: float = 36,
) -> Recommendation:
    if latest_timestamp is None:
        latest_timestamp = max((pd.Timestamp(frame.index[-1]).to_pydatetime() for frame in prices.values() if frame is not None and not frame.empty), default=None)
    mode = data_mode
    if latest_timestamp is None:
        mode = DataMode.STALE
    elif mode in {DataMode.LIVE, DataMode.DELAYED}:
        stamp = latest_timestamp if latest_timestamp.tzinfo else latest_timestamp.replace(tzinfo=UTC)
        age_hours = (datetime.now(UTC) - stamp.astimezone(UTC)).total_seconds() / 3600
        if age_hours > max_age_hours:
            mode = DataMode.STALE
    if model == ModelName.ALM:
        rec = generate_alm_recommendation(prices, state, strategy, source, mode)
    elif model == ModelName.DRBL_MATRIX:
        rec = generate_matrix_recommendation(prices, state, strategy, source, mode, gld_leveraged_ticker, btc_leveraged_ticker)
    else:
        rec = generate_combined_recommendation(prices, state, strategy, source, mode, gld_leveraged_ticker, btc_leveraged_ticker)
    rec = replace(rec, as_of=latest_timestamp, data_mode=mode)
    if not rec.available or not rec.ticker or rec.action in {"HOLD", "HOLD_CASH", "REVIEW", "UNAVAILABLE", "CONFIGURATION_REQUIRED", "ROTATION_REQUIRED", "ROTATE_POSITION", "SELL_ALL"}:
        return rec
    frame = prices.get(rec.ticker)
    if frame is None or frame.empty:
        # A base asset's configured history may be aliased under its logical asset key.
        asset = next((key for key, value in strategy.base_tickers.items() if value == rec.ticker), None)
        frame = prices.get(asset) if asset else None
        if frame is None or frame.empty:
            frame = prices.get("GLD_3X") if rec.ticker == gld_leveraged_ticker else None
        if frame is None or frame.empty:
            frame = prices.get("BTCUSD_3X") if rec.ticker == btc_leveraged_ticker else None
    if frame is None or frame.empty or pd.isna(frame.Close.iloc[-1]) or float(frame.Close.iloc[-1]) <= 0:
        return replace(rec, available=False, reason=rec.reason + " Nelze vypočítat náklady: chybí cena přesného tickeru.")
    current = state.positions.get(rec.ticker)
    current_usd = current.market_value_usd if current else 0.0
    delta = rec.target_usd - current_usd
    if abs(delta) < 0.01:
        return replace(rec, delta_usd=0.0, action="HOLD")
    price = float(frame.Close.iloc[-1])
    qty = abs(delta) / price
    if not costs.fractional_shares:
        qty = float(int(qty))
    estimate = estimate_costs(qty, price, "buy" if delta > 0 else "sell", costs)
    return replace(rec, delta_usd=delta, estimated_commission_usd=estimate.commission_usd,
                   estimated_slippage_usd=estimate.slippage_usd,
                   reason=rec.reason + f" Odhad nákladů při ceně {price:.2f} USD; jde o model, nikoli skutečnou brokerovu provizi.")
