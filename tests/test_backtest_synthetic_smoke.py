import numpy as np
import pandas as pd
from src.backtest.engine import run_backtest
from src.config import CostConfig, StrategyConfig
from src.models import ModelName


def test_all_models_run_on_synthetic_history():
    index = pd.bdate_range("2018-01-02", periods=520)
    rng = np.random.default_rng(74)
    data = {}
    for ticker, drift in {"SPY": 0.0003, "QQQ": 0.0004, "GLD": 0.00015, "IBIT": 0.0008, "BTCUSD": 0.001, "UPRO": 0.0007, "TQQQ": 0.001}.items():
        close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.012, len(index))))
        open_ = close * (1 + rng.normal(0, 0.001, len(index)))
        data[ticker] = pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) * 1.01, "Low": np.minimum(open_, close) * 0.99, "Close": close, "Volume": rng.integers(800_000, 1_500_000, len(index))}, index=index)
    for model in ModelName:
        result = run_backtest(data, model, StrategyConfig(), CostConfig(), start=index[500].date().isoformat())
        assert not result.equity.empty
        assert result.equity.index.min() >= index[500]
        assert (pd.to_datetime(result.trades.execution_timestamp) > pd.to_datetime(result.trades.signal_timestamp)).all() if not result.trades.empty else True
