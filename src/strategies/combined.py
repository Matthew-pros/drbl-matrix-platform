from __future__ import annotations
from ..config import StrategyConfig
from ..models import DataMode, ModelName, PortfolioState, Recommendation
from .alm import generate_alm_recommendation
from .drbl_matrix import generate_matrix_recommendation

def generate_combined_recommendation(
    prices, state: PortfolioState, config: StrategyConfig, source: str = "Yahoo Finance",
    data_mode: DataMode = DataMode.HISTORICAL, gld_leveraged_ticker: str | None = None,
    btc_leveraged_ticker: str | None = None,
) -> Recommendation:
    if not state.alm_completed or not state.alm_fill_confirmed:
        rec = generate_alm_recommendation(prices, state, config, source, data_mode)
        prefix = "Combined: čeká na brokerem potvrzený fill iniciační ALM tranše. "
        return Recommendation(ModelName.COMBINED, rec.as_of, rec.source, rec.data_mode, rec.provisional,
            rec.ticker, rec.action, rec.target_usd, rec.delta_usd, rec.estimated_commission_usd,
            rec.estimated_slippage_usd, prefix + rec.reason, rec.regime, rec.indicators, rec.available)
    rec = generate_matrix_recommendation(prices, state, config, source, data_mode,
        gld_leveraged_ticker, btc_leveraged_ticker)
    return Recommendation(ModelName.COMBINED, rec.as_of, rec.source, rec.data_mode, rec.provisional,
        rec.ticker, rec.action, rec.target_usd, rec.delta_usd, rec.estimated_commission_usd,
        rec.estimated_slippage_usd, "Combined: provozní DRBL fáze po potvrzeném fillu. " + rec.reason,
        rec.regime, rec.indicators, rec.available)
