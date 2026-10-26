from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import pytest

from src.strategies.temacd_grid_search import parse_asset_params_json
from src.strategies.temacd_rotation import (
    TEMACDAssetParams,
    TEMACDConfig,
    build_temacd_indicators,
)


def test_grid_search_json_maps_per_asset_params() -> None:
    qqq = TEMACDAssetParams(
        ema_fast=8, ema_mid=21, ema_slow=100,
        macd_fast=20, macd_slow=60, macd_signal=10,
    )
    payload = {
        "schema_version": 1,
        "asset_params": {"QQQ": asdict(qqq)},
        "training_period": {"start": "2018-01-01", "end": "2023-12-31"},
    }
    mapping = parse_asset_params_json(payload)
    assert mapping == {"QQQ": qqq}
    cfg = TEMACDConfig(asset_params=mapping)
    assert cfg.for_asset("QQQ").ema_slow == 100
    assert cfg.for_asset("QQQ").macd_slow == 60
    assert cfg.for_asset("SPY").ema_slow == 120
    # Resolving per-asset params must not mutate the shared config.
    assert cfg.asset_params["QQQ"] == qqq


def test_grid_search_json_rejects_unknown_tickers_and_invalid_periods() -> None:
    params = asdict(TEMACDAssetParams())
    with pytest.raises(ValueError, match="mimo TEMACD universe"):
        parse_asset_params_json({"asset_params": {"NOT_A_TICKER": params}})
    invalid = {**params, "ema_fast": 50, "ema_mid": 20}
    with pytest.raises(ValueError, match="EMA periody"):
        parse_asset_params_json({"asset_params": {"QQQ": invalid}})


def test_indicator_builder_uses_asset_override(sample_ohlcv: pd.DataFrame) -> None:
    override = TEMACDAssetParams(ema_fast=8, ema_mid=21, ema_slow=100,
                                 macd_fast=20, macd_slow=60, macd_signal=10)
    cfg = TEMACDConfig(asset_params={"QQQ": override})
    actual = build_temacd_indicators(sample_ohlcv, cfg, asset="QQQ")
    expected = build_temacd_indicators(sample_ohlcv, cfg.for_asset("QQQ"))
    defaults = build_temacd_indicators(sample_ohlcv, cfg)
    pd.testing.assert_series_equal(actual["EMA3"], expected["EMA3"])
    assert not actual["EMA3"].equals(defaults["EMA3"])
