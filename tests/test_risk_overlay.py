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
