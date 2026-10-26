from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import StrategyConfig
from src.models import ModelName, PortfolioState, Position, Regime
from src.strategies.combined import generate_combined_recommendation
from src.strategies.drbl_matrix import generate_matrix_recommendation
from src.strategies.risk_overlay import assess_market_regime


def _ohlcv(close: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame(index=close.index)
    frame["Close"] = close.astype(float)
    frame["Open"] = close.shift(1).fillna(close.iloc[0])
    frame["High"] = frame[["Open", "Close"]].max(axis=1) * 1.005
    frame["Low"] = frame[["Open", "Close"]].min(axis=1) * 0.995
    frame["Volume"] = 1_000_000.0
    return frame


def test_high_vix_activates_risk_off(sample_ohlcv):
    data = {"SPY": sample_ohlcv.copy(), "QQQ": sample_ohlcv.copy(),
            "VIX": _ohlcv(pd.Series(42.0, index=sample_ohlcv.index))}
    assessment = assess_market_regime(data, StrategyConfig())
    assert assessment.risk_off is True
    assert assessment.regime == "RISK_OFF"
    assert "VIX" in assessment.reason


def test_matrix_risk_off_stays_in_cash_and_exits_position(sample_ohlcv):
    data = {"SPY": sample_ohlcv.copy(), "QQQ": sample_ohlcv.copy(),
            "VIX": _ohlcv(pd.Series(40.0, index=sample_ohlcv.index))}
    cfg = StrategyConfig()
    flat = PortfolioState(ModelName.DRBL_MATRIX, 100_000, selected_asset="SPY")
    flat_rec = generate_matrix_recommendation(data, flat, cfg)
    assert flat_rec.action == "HOLD_CASH"
    assert flat_rec.regime == Regime.C
    invested = PortfolioState(ModelName.DRBL_MATRIX, 15_000,
        positions={"SPY": Position("SPY", 85_000)}, selected_asset="SPY")
    exit_rec = generate_matrix_recommendation(data, invested, cfg)
    assert exit_rec.action == "SELL_ALL"
    assert exit_rec.target_usd == 0
    assert "Risk-off" in exit_rec.reason


def test_combined_uses_crisis_alm_starter_only_on_spy_or_qqq(sample_ohlcv):
    index = sample_ohlcv.index
    close = pd.Series(np.linspace(100, 150, len(index)), index=index)
    close.iloc[-1] = 120.0
    spy = _ohlcv(close)
    spy.iloc[-1, spy.columns.get_loc("Open")] = 149.0
    spy.iloc[-1, spy.columns.get_loc("High")] = 151.0
    spy.iloc[-1, spy.columns.get_loc("Low")] = 118.0
    data = {"SPY": spy, "QQQ": spy.copy(),
            "VIX": _ohlcv(pd.Series(42.0, index=index))}
    state = PortfolioState(ModelName.COMBINED, 100_000, selected_asset="GLD")
    rec = generate_combined_recommendation(data, state, StrategyConfig())
    assert rec.action == "BUY"
    assert rec.ticker in {"SPY", "QQQ"}
    assert rec.indicators.get("alm_tier") == "crash_event"


def test_combined_defaults_to_matrix_when_no_crisis(sample_ohlcv):
    data = {"SPY": sample_ohlcv.copy(), "QQQ": sample_ohlcv.copy(),
            "GLD": sample_ohlcv.copy(), "IBIT": sample_ohlcv.copy(),
            "BTCUSD": sample_ohlcv.copy(),
            "VIX": _ohlcv(pd.Series(16.0, index=sample_ohlcv.index))}
    state = PortfolioState(ModelName.COMBINED, 100_000, selected_asset="SPY")
    rec = generate_combined_recommendation(data, state, StrategyConfig())
    assert "Matrix je výchozí strategie" in rec.reason
    assert rec.indicators.get("combined_crisis_alm_enabled") is True


def test_combined_closes_matrix_position_before_crisis_alm_starter(sample_ohlcv):
    index = sample_ohlcv.index
    close = pd.Series(np.linspace(100, 150, len(index)), index=index)
    close.iloc[-1] = 120.0
    spy = _ohlcv(close)
    spy.iloc[-1, spy.columns.get_loc("Open")] = 149.0
    spy.iloc[-1, spy.columns.get_loc("High")] = 151.0
    spy.iloc[-1, spy.columns.get_loc("Low")] = 118.0
    data = {"SPY": spy, "QQQ": spy.copy(),
            "VIX": _ohlcv(pd.Series(42.0, index=index))}
    for ticker in ("SPY", "TQQQ"):
        state = PortfolioState(ModelName.COMBINED, 15_000,
            positions={ticker: Position(ticker, 85_000)}, selected_asset="SPY")
        rec = generate_combined_recommendation(data, state, StrategyConfig())
        assert rec.action == "SELL_ALL"
        assert rec.target_usd == 0


def test_combined_does_not_immediately_sell_recorded_crisis_alm_holding(sample_ohlcv):
    index = sample_ohlcv.index
    close = pd.Series(np.linspace(100, 150, len(index)), index=index)
    close.iloc[-1] = 120.0
    spy = _ohlcv(close)
    spy.iloc[-1, spy.columns.get_loc("Open")] = 149.0
    spy.iloc[-1, spy.columns.get_loc("High")] = 151.0
    spy.iloc[-1, spy.columns.get_loc("Low")] = 118.0
    data = {"SPY": spy, "QQQ": spy.copy(),
            "VIX": _ohlcv(pd.Series(42.0, index=index))}
    state = PortfolioState(ModelName.COMBINED, 80_000,
        positions={"SPY": Position("SPY", 20_000)},
        alm_levels_filled={"crash_event"}, active_alm_ticker="SPY")
    rec = generate_combined_recommendation(data, state, StrategyConfig())
    assert rec.action == "HOLD"
    assert rec.ticker == "SPY"
    assert "krizová ALM tranše" in rec.reason


def test_combined_does_not_trigger_crisis_alm_on_slow_drawdown_without_crash_bar(sample_ohlcv):
    index = sample_ohlcv.index
    close = pd.Series(np.linspace(100, 150, len(index)), index=index)
    close.iloc[-10:] = np.linspace(126.0, 120.0, 10)
    spy = _ohlcv(close)
    spy.iloc[-1, spy.columns.get_loc("Open")] = 120.5
    spy.iloc[-1, spy.columns.get_loc("High")] = 121.0
    spy.iloc[-1, spy.columns.get_loc("Low")] = 119.5
    data = {
        "SPY": spy,
        "QQQ": spy.copy(),
        "VIX": _ohlcv(pd.Series(42.0, index=index)),
    }
    state = PortfolioState(ModelName.COMBINED, 100_000, selected_asset="SPY")
    rec = generate_combined_recommendation(data, state, StrategyConfig())
    assert rec.action == "HOLD_CASH"
    assert rec.indicators.get("alm_tier") is None


def test_risk_off_closes_one_position_even_when_multiple_holdings_need_review(sample_ohlcv):
    data = {
        "SPY": sample_ohlcv.copy(),
        "QQQ": sample_ohlcv.copy(),
        "VIX": _ohlcv(pd.Series(42.0, index=sample_ohlcv.index)),
    }
    state = PortfolioState(
        ModelName.DRBL_MATRIX, 10_000,
        positions={
            "SPY": Position("SPY", 45_000),
            "QQQ": Position("QQQ", 45_000),
        },
    )
    rec = generate_matrix_recommendation(data, state, StrategyConfig())
    assert rec.action == "SELL_ALL"
    assert rec.ticker in {"SPY", "QQQ"}
    assert rec.target_usd == 0


def _recent_crash_data(index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    close = pd.Series(np.linspace(100.0, 150.0, len(index)), index=index)
    close.iloc[-3] = 150.0
    close.iloc[-2] = 120.0   # flash-crash bar
    close.iloc[-1] = 119.5   # the trigger is no longer on today's bar
    spy = _ohlcv(close)
    vix = _ohlcv(pd.Series(42.0, index=index))
    return {"SPY": spy, "QQQ": spy.copy(), "VIX": vix}


def test_crash_trigger_stays_valid_for_configured_cooldown(sample_ohlcv):
    data = _recent_crash_data(sample_ohlcv.index)
    assessment = assess_market_regime(data, StrategyConfig(risk_crash_cooldown_sessions=5))
    assert assessment.metrics["crash_event"] is False
    assert assessment.metrics["crash_event_recent"] is True
    assert assessment.risk_off is True


def test_combined_closes_matrix_then_enters_crisis_alm_within_cooldown(sample_ohlcv):
    data = _recent_crash_data(sample_ohlcv.index)
    cfg = StrategyConfig(risk_crash_cooldown_sessions=5)
    matrix_state = PortfolioState(
        ModelName.COMBINED, 15_000,
        positions={"TQQQ": Position("TQQQ", 85_000)},
        selected_asset="QQQ",
    )
    first = generate_combined_recommendation(data, matrix_state, cfg)
    assert first.action == "SELL_ALL"
    assert first.ticker == "TQQQ"
    assert first.indicators.get("pending_crisis_alm_ticker") in {"SPY", "QQQ"}

    # Simulate the Matrix position being flattened at the next available execution.
    flat_state = PortfolioState(ModelName.COMBINED, 100_000, selected_asset="QQQ")
    second = generate_combined_recommendation(data, flat_state, cfg)
    assert second.action == "BUY"
    assert second.ticker in {"SPY", "QQQ"}
    assert second.indicators.get("alm_tier") == "crash_event"


def test_active_crisis_alm_exits_once_risk_off_has_cleared(sample_ohlcv):
    data = {
        "SPY": sample_ohlcv.copy(),
        "QQQ": sample_ohlcv.copy(),
        "VIX": _ohlcv(pd.Series(16.0, index=sample_ohlcv.index)),
    }
    state = PortfolioState(
        ModelName.COMBINED, 80_000,
        positions={"SPY": Position("SPY", 20_000)},
        alm_levels_filled={"crash_event"}, active_alm_ticker="SPY",
    )
    rec = generate_combined_recommendation(data, state, StrategyConfig())
    assert rec.action == "SELL_ALL"
    assert rec.ticker == "SPY"
    assert rec.target_usd == 0
    assert "běžná Matrix rotace se obnoví" in rec.reason


def test_disabling_risk_overlay_also_disables_crisis_starter(sample_ohlcv):
    index = sample_ohlcv.index
    close = pd.Series(np.linspace(100.0, 150.0, len(index)), index=index)
    close.iloc[-1] = 120.0
    spy = _ohlcv(close)
    spy.iloc[-1, spy.columns.get_loc("Open")] = 149.0
    spy.iloc[-1, spy.columns.get_loc("High")] = 151.0
    spy.iloc[-1, spy.columns.get_loc("Low")] = 118.0
    data = {
        "SPY": spy, "QQQ": spy.copy(),
        "VIX": _ohlcv(pd.Series(42.0, index=index)),
    }
    cfg = StrategyConfig(risk_overlay_enabled=False)
    state = PortfolioState(ModelName.COMBINED, 100_000, selected_asset="SPY")
    rec = generate_combined_recommendation(data, state, cfg)
    assert rec.indicators.get("alm_tier") is None
