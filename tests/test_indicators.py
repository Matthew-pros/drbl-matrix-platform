import numpy as np
import pandas as pd
import pytest
from src.indicators import adx_wilder, breakout_factors, momentum_12_1, annualized_volatility, regression_factors, rvol, normalize_ohlcv

def test_momentum_12_1_uses_t_minus_22_and_252():
    s = pd.Series(np.arange(1., 300.))
    out = momentum_12_1(s)
    assert out.iloc[252] == pytest.approx((231-1)/1)

def test_volatility_sample_std():
    s = pd.Series(np.arange(1., 80.))
    ret = s.pct_change(fill_method=None)
    expected = ret.iloc[-60:].std(ddof=1)*np.sqrt(252)
    assert annualized_volatility(s,60).iloc[-1] == pytest.approx(expected)

def test_breakout_excludes_current_bar(sample_ohlcv):
    df = sample_ohlcv.iloc[:45].copy()
    df.loc[df.index[-1], "High"] = 1e6
    result = breakout_factors(df, 40, 20)
    assert result["entry_level"].iloc[-1] < 1e6
    assert result["entry_level"].iloc[-1] == pytest.approx(df["High"].iloc[-41:-1].max())

def test_adx_wilder_warmup_and_bounds(sample_ohlcv):
    out = adx_wilder(sample_ohlcv,14)
    assert out.iloc[:27].isna().all()
    assert out.iloc[27:].notna().any()
    assert out.dropna().between(0,100).all()

def test_rvol_needs_full_warmup(sample_ohlcv):
    out = rvol(sample_ohlcv["Volume"],20,200)
    assert out.iloc[:199].isna().all()
    assert out.iloc[199:].notna().all()

def test_regression_factors_warmup(sample_ohlcv):
    out = regression_factors(sample_ohlcv["Close"],100)
    assert out.iloc[:99]["slope"].isna().all()
    assert out.iloc[99:]["slope"].notna().all()

def test_normalize_duplicates_invalid_price_and_columns():
    idx=pd.to_datetime(["2024-01-02","2024-01-02","2024-01-03"])
    df=pd.DataFrame({"Open":[10,11,0],"High":[12,13,2],"Low":[9,10,0],"Close":[11,12,1],"Volume":[10,20,30]},index=idx)
    out=normalize_ohlcv(df)
    assert len(out)==1
    assert out["Close"].iloc[0]==12
