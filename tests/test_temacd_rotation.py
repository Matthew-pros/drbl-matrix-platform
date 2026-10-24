from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategies.temacd_rotation import (
    TEMACDConfig,
    TEMACD_UNIVERSE,
    _target_weights,
    build_temacd_indicators,
    run_temacd_backtest,
)


def trending_ohlcv(index: pd.DatetimeIndex, scale: float = 1.0, noise: float = 0.006) -> pd.DataFrame:
    rng = np.random.default_rng(42 + int(scale * 100))
    steps = 0.0007 + rng.normal(0, noise, len(index))
    close = 80 * scale * np.exp(np.cumsum(steps))
    open_ = close * (1 + rng.normal(0, noise / 3, len(index)))
    high = np.maximum(open_, close) * 1.012
    low = np.minimum(open_, close) * 0.988
    volume = rng.integers(100_000, 2_000_000, len(index)).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=index)


def test_temacd_indicators_have_expected_columns_and_no_future_dependency():
    dates = pd.bdate_range("2019-01-01", periods=500)
    bars = trending_ohlcv(dates)
    cfg = TEMACDConfig()
    result = build_temacd_indicators(bars, cfg)
    assert {"EMA1", "EMA2", "EMA3", "TEMACD", "TEMACD_Signal", "TEMACD_Hist", "RSI", "ATR_pct", "momentum_score", "trend_ok"} <= set(result.columns)
    assert result["indicator_ready"].sum() > 200
    # The indicator output up to t must be unchanged if only future bars are changed.
    truncated = build_temacd_indicators(bars.iloc[:400], cfg)
    pd.testing.assert_series_equal(result.loc[dates[399], ["TEMACD", "TEMACD_Signal", "ATR_pct"]],
                                   truncated.loc[dates[399], ["TEMACD", "TEMACD_Signal", "ATR_pct"]])


def test_atr_position_sizing_caps_each_name_and_reduces_high_volatility_weight():
    cfg = TEMACDConfig(target_risk=0.01, max_asset_weight=0.35)
    weights = _target_weights([("LOW_VOL", 0.9, 0.01), ("MID_VOL", 0.8, 0.02), ("HIGH_VOL", 0.7, 0.05)], cfg)
    assert all(0 < weight <= 0.35 for weight in weights.values())
    assert weights["HIGH_VOL"] < weights["MID_VOL"]
    assert weights["MID_VOL"] == pytest.approx(0.35)  # individual cap
    assert sum(weights.values()) <= 1.0 + 1e-12


def test_temacd_backtest_uses_next_open_and_compares_spy_benchmark():
    dates = pd.bdate_range("2018-01-01", periods=850)
    data = {asset: trending_ohlcv(dates, scale=1.0 + i * 0.04, noise=0.004 + (i % 3) * 0.003)
            for i, asset in enumerate(TEMACD_UNIVERSE)}
    cfg = TEMACDConfig(top_n=3, rebalance="monthly", initial_equity=50_000, transaction_cost_rate=0.0005)
    result = run_temacd_backtest(data, cfg, start=dates[500].date().isoformat(), end=dates[-1].date().isoformat())
    assert not result.equity.empty
    assert not result.benchmark_equity.empty
    assert result.equity.index.min() >= dates[500]
    assert result.metrics["ending_equity"] > 0
    assert "sortino" in result.metrics
    assert result.metrics["total_transaction_costs"] >= 0
    if not result.trades.empty:
        assert (pd.to_datetime(result.trades["execution_timestamp"]) > pd.to_datetime(result.trades["signal_timestamp"])).all()
        assert (result.trades["commission_usd"] >= 0).all()
    if not result.rebalance_log.empty:
        selected = result.rebalance_log[result.rebalance_log["event"] == "SELECTED"]
        if not selected.empty:
            assert (selected["target_weight"] <= 0.35 + 1e-12).all()
    assert set(TEMACD_UNIVERSE) == set(data)


def test_temacd_config_validation():
    with pytest.raises(ValueError, match="Fast musí být menší"):
        TEMACDConfig(macd_fast=80, macd_slow=30)
    with pytest.raises(ValueError, match="Maximální váha"):
        TEMACDConfig(max_asset_weight=0)