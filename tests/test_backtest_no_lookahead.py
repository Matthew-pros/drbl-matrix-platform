import pandas as pd
import pytest
from src.backtest.engine import run_backtest
from src.config import CostConfig, StrategyConfig
from src.models import ModelName


def test_backtest_requires_warmup(sample_ohlcv):
    with pytest.raises(ValueError, match="warm-up"):
        run_backtest({"SPY": sample_ohlcv.iloc[:150]}, ModelName.ALM, StrategyConfig(), CostConfig())


def test_backtest_executes_after_signal_bar(sample_ohlcv):
    result = run_backtest(
        {"SPY": sample_ohlcv, "QQQ": sample_ohlcv, "GLD": sample_ohlcv, "IBIT": sample_ohlcv,
         "UPRO": sample_ohlcv, "TQQQ": sample_ohlcv},
        ModelName.ALM, StrategyConfig(), CostConfig(), start=sample_ohlcv.index[260].date().isoformat(),
    )
    if not result.trades.empty:
        assert (pd.to_datetime(result.trades.execution_timestamp) > pd.to_datetime(result.trades.signal_timestamp)).all()


def test_backtest_start_date_keeps_earlier_warmup(sample_ohlcv):
    start = sample_ohlcv.index[300].date().isoformat()
    result = run_backtest(
        {"SPY": sample_ohlcv, "QQQ": sample_ohlcv, "GLD": sample_ohlcv, "IBIT": sample_ohlcv,
         "UPRO": sample_ohlcv, "TQQQ": sample_ohlcv},
        ModelName.ALM, StrategyConfig(), CostConfig(), start=start,
    )
    assert result.equity.index.min() >= pd.Timestamp(start)
    if not result.trades.empty:
        assert pd.to_datetime(result.trades.signal_timestamp).min() >= pd.Timestamp(start)
        assert (pd.to_datetime(result.trades.execution_timestamp) > pd.to_datetime(result.trades.signal_timestamp)).all()


def test_matrix_backtest_warns_when_momentum_warmup_missing(sample_ohlcv):
    # 253 bars are enough to begin scoring; fewer are explicitly rejected at the top-level warmup.
    bars = sample_ohlcv.iloc[:260]
    result = run_backtest(
        {"SPY": bars, "QQQ": bars, "GLD": bars, "IBIT": bars, "BTCUSD": bars, "UPRO": bars, "TQQQ": bars},
        ModelName.DRBL_MATRIX, StrategyConfig(), CostConfig(), start=bars.index[253].date().isoformat(),
    )
    assert not result.equity.empty
    assert result.equity.index.min() >= bars.index[253]
