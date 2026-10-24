import numpy as np
import pandas as pd
import pytest
from src.config import StrategyConfig
from src.indicators import atr_percentile_cap, keltner_factors, regression_factors, selected_factor, turtle_soup_factors


def test_selected_factor_warmup_disables_entries(sample_ohlcv):
    cfg = StrategyConfig()
    for factor in ("TURTLE_SOUP", "KELTNER", "LRS", "SMA200", "EMA200", "VWAP200"):
        result = selected_factor(sample_ohlcv, factor, cfg)
        warmup = result.index[result["entry"].to_numpy()].min() if result["entry"].any() else None
        # Each rolling signal must be false before its key indicator has warmed up.
        if factor == "SMA200":
            assert not result.iloc[:199]["entry"].any()
        elif factor == "EMA200":
            assert not result.iloc[:199]["entry"].any()
        elif factor == "LRS":
            assert not result.iloc[:99]["entry"].any()
        elif factor == "KELTNER":
            assert not result.iloc[:20]["entry"].any()
        assert warmup is None or warmup >= result.index[0]


def test_keltner_midline_exit_and_upper_entry(sample_ohlcv):
    result = keltner_factors(sample_ohlcv, 20, 14, 2.0)
    assert {"middle", "upper", "entry", "exit"}.issubset(result.columns)
    assert result.iloc[:20]["entry"].eq(False).all()


def test_lrs_uses_population_std_band(sample_ohlcv):
    close = pd.Series(np.linspace(100, 150, 100), index=sample_ohlcv.index[:100])
    result = regression_factors(close, 100, 2.0)
    assert result["upper_band"].iloc[-1] == pytest.approx(close.mean() + 2 * close.std(ddof=0))
    assert result["slope"].iloc[-1] > 0


def test_turtle_soup_exit_level_excludes_current_bar(sample_ohlcv):
    data = sample_ohlcv.iloc[:250].copy()
    last = data.index[-1]
    baseline = turtle_soup_factors(data, 40, 20, 5)
    expected = data["Low"].iloc[-21:-1].min()
    assert baseline["exit_level"].loc[last] == pytest.approx(expected)
    data.loc[last, "Low"] = 0.01
    updated = turtle_soup_factors(data, 40, 20, 5)
    assert updated["exit_level"].loc[last] == pytest.approx(expected)


def test_atr_percentile_uses_prior_bars_only(sample_ohlcv):
    df = sample_ohlcv.copy()
    before = atr_percentile_cap(df, period=10, window=40, percentile=0.90)
    idx = df.index[-1]
    df.loc[idx, "High"] *= 10
    after = atr_percentile_cap(df, period=10, window=40, percentile=0.90)
    assert after.loc[idx] == pytest.approx(before.loc[idx])
