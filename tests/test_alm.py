import numpy as np
import pandas as pd
import pytest
from src.config import StrategyConfig
from src.models import ModelName, PortfolioState, Position
from src.strategies.alm import generate_alm_recommendation


def frame_from_close(close):
    index = pd.bdate_range("2000-01-03", periods=len(close))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1_000_000.0}, index=index)


def test_alm_deepest_drawdown_selects_deeper_asset_and_tranche():
    spy = frame_from_close(np.r_[np.linspace(100, 200, 100), np.linspace(190, 80, 30)])
    qqq = frame_from_close(np.r_[np.linspace(100, 200, 100), np.linspace(190, 90, 30)])
    state = PortfolioState(ModelName.ALM, 100_000)
    rec = generate_alm_recommendation({"SPY": spy, "QQQ": qqq}, state, StrategyConfig(initial_equity=100_000))
    assert rec.ticker == "SPY"
    assert rec.target_usd == pytest.approx(20_000)
    assert rec.delta_usd == pytest.approx(20_000)
    assert rec.indicators["alm_tier"] == "dd_50"


def test_alm_next_tier_on_existing_base_position(sample_ohlcv):
    state = PortfolioState(
        ModelName.ALM, 70_000,
        positions={"SPY": Position("SPY", 30_000, 300)},
        alm_levels_filled={"dd_30"},
    )
    # Price path is low enough vs its available ATH for the next tier in this fixture.
    deep = sample_ohlcv.copy()
    deep["Close"] = np.linspace(200, 80, len(deep))
    deep["Open"] = deep["Close"]
    deep["High"] = deep["Close"] * 1.01
    deep["Low"] = deep["Close"] * 0.99
    rec = generate_alm_recommendation({"SPY": deep}, state, StrategyConfig(initial_equity=100_000))
    assert rec.ticker == "SPY"
    assert rec.indicators["alm_tier"] in {"dd_50", "dd_80"}
    assert rec.target_usd <= state.equity_usd * 0.85 + 1e-6


def test_alm_never_uses_btc_or_other_position(sample_ohlcv):
    state = PortfolioState(ModelName.ALM, 100_000, positions={"BTC-USD": Position("BTC-USD", 100_000, 1)})
    rec = generate_alm_recommendation({"SPY": sample_ohlcv, "QQQ": sample_ohlcv}, state, StrategyConfig())
    assert not rec.available
    assert rec.action == "REVIEW"
