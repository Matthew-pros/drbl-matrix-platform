from __future__ import annotations

from ..config import StrategyConfig
from ..models import DataMode, ModelName, PortfolioState, Recommendation, Regime
from .alm import generate_alm_recommendation
from .drbl_matrix import generate_matrix_recommendation
from .risk_overlay import assess_market_regime


def generate_combined_recommendation(
    prices, state: PortfolioState, config: StrategyConfig, source: str = "Yahoo Finance",
    data_mode: DataMode = DataMode.HISTORICAL, gld_leveraged_ticker: str | None = None,
    btc_leveraged_ticker: str | None = None,
) -> Recommendation:
    """Matrix first, with an independent crash-only ALM starter limited to SPY/QQQ."""
    if len(state.positions) > 1:
        return generate_matrix_recommendation(
            prices, state, config, source, data_mode, gld_leveraged_ticker, btc_leveraged_ticker
        )

    assessment = assess_market_regime(prices, config)
    held = next(iter(state.positions.values()), None)
    is_alm_holding = bool(held and held.ticker == state.active_alm_ticker and held.ticker in {"SPY", "QQQ"})

    alm_rec = generate_alm_recommendation(
        prices, state, config, source, data_mode, allow_crisis_tier=True
    )
    if alm_rec.action == "BUY" and alm_rec.ticker in {"SPY", "QQQ"}:
        if held is not None and not is_alm_holding:
            return Recommendation(
                state.model, None, source, data_mode, False, held.ticker, "SELL_ALL", 0.0,
                -held.market_value_usd, 0.0, 0.0,
                "Krizová ALM fáze je oddělena od běžné Matrix pozice. Nejprve uzavři aktivní Matrix pozici; ALM starter se vyhodnotí znovu po zaznamenání výstupu. "
                + assessment.reason,
                Regime.C,
                {"market_regime": assessment.regime, **assessment.metrics},
            )
        return Recommendation(
            state.model, alm_rec.as_of, alm_rec.source, alm_rec.data_mode, alm_rec.provisional,
            alm_rec.ticker, alm_rec.action, alm_rec.target_usd, alm_rec.delta_usd,
            alm_rec.estimated_commission_usd, alm_rec.estimated_slippage_usd,
            "Combined: krizový ALM modul má přednost pouze pro SPY/QQQ. " + alm_rec.reason,
            alm_rec.regime, {**alm_rec.indicators, "market_regime": assessment.regime,
                             "market_regime_reason": assessment.reason, **assessment.metrics}, alm_rec.available,
        )

    if is_alm_holding and config.risk_overlay_enabled and assessment.risk_off:
        return Recommendation(
            state.model, None, source, data_mode, False, held.ticker, "HOLD",
            held.market_value_usd, 0.0, 0.0, 0.0,
            "Combined: krizová ALM tranše je již součástí portfolia; během stejného risk-off režimu ji běžný Matrix vypínač okamžitě neprodává. "
            + assessment.reason,
            Regime.UNKNOWN,
            {"market_regime": assessment.regime, "market_regime_reason": assessment.reason,
             "alm_levels_filled": sorted(state.alm_levels_filled), **assessment.metrics},
        )

    matrix_rec = generate_matrix_recommendation(
        prices, state, config, source, data_mode, gld_leveraged_ticker, btc_leveraged_ticker
    )
    return Recommendation(
        state.model, matrix_rec.as_of, matrix_rec.source, matrix_rec.data_mode, matrix_rec.provisional,
        matrix_rec.ticker, matrix_rec.action, matrix_rec.target_usd, matrix_rec.delta_usd,
        matrix_rec.estimated_commission_usd, matrix_rec.estimated_slippage_usd,
        "Combined: Matrix je výchozí strategie; ALM se aktivuje jen při potvrzeném flash-crash / black-swan spouštěči na SPY/QQQ. "
        + matrix_rec.reason,
        matrix_rec.regime,
        {**matrix_rec.indicators, "combined_crisis_alm_enabled": config.crisis_alm_enabled,
         "market_regime": assessment.regime, "market_regime_reason": assessment.reason, **assessment.metrics},
        matrix_rec.available,
    )
