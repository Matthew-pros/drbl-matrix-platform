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
    """Matrix is the default strategy; crisis ALM is a separate SPY/QQQ-only sleeve.

    A crash signal remains eligible for a bounded number of sessions. If a Matrix
    holding exists, Combined first asks to close it, then reevaluates the persisted
    recent-crash window before opening the crisis starter at the next feasible Open.
    """
    assessment = assess_market_regime(prices, config)

    # When multiple shadow positions exist, Matrix/risk-off handles them one by one.
    # Risk-off must have priority over a generic "review required" response.
    if len(state.positions) > 1:
        return generate_matrix_recommendation(
            prices, state, config, source, data_mode, gld_leveraged_ticker, btc_leveraged_ticker
        )

    held = next(iter(state.positions.values()), None)
    is_alm_holding = bool(
        held and held.ticker == state.active_alm_ticker and held.ticker in {"SPY", "QQQ"}
    )

    # Never send a crisis sleeve back through the normal Matrix leader selector.
    # Hold while risk-off remains active; close it once the protective regime clears.
    if is_alm_holding:
        if config.risk_overlay_enabled and assessment.risk_off:
            return Recommendation(
                state.model, None, source, data_mode, False, held.ticker, "HOLD",
                held.market_value_usd, 0.0, 0.0, 0.0,
                "Combined: držet oddělenou krizovou ALM tranši SPY/QQQ, dokud trvá risk-off ochranné okno. "
                + assessment.reason,
                Regime.C,
                {"market_regime": assessment.regime, "market_regime_reason": assessment.reason,
                 "active_alm_ticker": state.active_alm_ticker,
                 "alm_levels_filled": sorted(state.alm_levels_filled), **assessment.metrics},
            )
        return Recommendation(
            state.model, None, source, data_mode, False, held.ticker, "SELL_ALL",
            0.0, -held.market_value_usd, 0.0, 0.0,
            "Combined: krizový risk-off režim skončil nebo byla ochranná vrstva vypnuta. "
            "Uzavři oddělenou ALM tranši; běžná Matrix rotace se obnoví při následujícím vyhodnocení.",
            Regime.B,
            {"market_regime": assessment.regime, "market_regime_reason": assessment.reason,
             "active_alm_ticker": state.active_alm_ticker, **assessment.metrics},
        )

    alm_rec = generate_alm_recommendation(
        prices, state, config, source, data_mode, allow_crisis_tier=True
    )
    if alm_rec.action == "BUY" and alm_rec.ticker in {"SPY", "QQQ"}:
        if held is not None:
            # The trigger remains valid through risk_crash_cooldown_sessions, so a
            # one-day crash can first flatten Matrix and then enter ALM next session.
            return Recommendation(
                state.model, None, source, data_mode, False, held.ticker, "SELL_ALL", 0.0,
                -held.market_value_usd, 0.0, 0.0,
                "Krizová ALM fáze je oddělena od běžné Matrix pozice. Nejprve uzavři aktivní Matrix pozici; "
                "starter SPY/QQQ se znovu vyhodnotí v omezeném ochranném okně. "
                + assessment.reason,
                Regime.C,
                {**alm_rec.indicators, "pending_crisis_alm_ticker": alm_rec.ticker,
                 "market_regime": assessment.regime, "market_regime_reason": assessment.reason,
                 **assessment.metrics},
            )
        return Recommendation(
            state.model, alm_rec.as_of, alm_rec.source, alm_rec.data_mode, alm_rec.provisional,
            alm_rec.ticker, alm_rec.action, alm_rec.target_usd, alm_rec.delta_usd,
            alm_rec.estimated_commission_usd, alm_rec.estimated_slippage_usd,
            "Combined: krizový ALM modul má přednost pouze pro SPY/QQQ. " + alm_rec.reason,
            alm_rec.regime,
            {**alm_rec.indicators, "market_regime": assessment.regime,
             "market_regime_reason": assessment.reason, **assessment.metrics},
            alm_rec.available,
        )

    matrix_rec = generate_matrix_recommendation(
        prices, state, config, source, data_mode, gld_leveraged_ticker, btc_leveraged_ticker
    )
    return Recommendation(
        state.model, matrix_rec.as_of, matrix_rec.source, matrix_rec.data_mode, matrix_rec.provisional,
        matrix_rec.ticker, matrix_rec.action, matrix_rec.target_usd, matrix_rec.delta_usd,
        matrix_rec.estimated_commission_usd, matrix_rec.estimated_slippage_usd,
        "Combined: Matrix je výchozí strategie; ALM se aktivuje jen při potvrzeném crash triggeru "
        "na SPY/QQQ a risk-off režimu. " + matrix_rec.reason,
        matrix_rec.regime,
        {**matrix_rec.indicators, "combined_crisis_alm_enabled": config.crisis_alm_enabled,
         "market_regime": assessment.regime, "market_regime_reason": assessment.reason, **assessment.metrics},
        matrix_rec.available,
    )
