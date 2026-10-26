from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from src.data import yfinance_provider
from src.data.yfinance_provider import YahooFinanceProvider


def test_yahoo_provider_uses_bounded_explicit_adjusted_download(monkeypatch) -> None:
    index = pd.bdate_range("2025-01-02", periods=4)
    raw = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0],
            "High": [101.0, 102.0, 103.0, 104.0],
            "Low": [99.0, 100.0, 101.0, 102.0],
            "Close": [100.5, 101.5, 102.5, 103.5],
            "Volume": [1_000_000.0] * 4,
            "Dividends": [0.0] * 4,
            "Stock Splits": [0.0] * 4,
        },
        index=index,
    )
    calls: list[dict] = []

    def fake_download(ticker, **kwargs):
        calls.append({"ticker": ticker, **kwargs})
        return raw.copy()

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    monkeypatch.setattr(yfinance_provider, "read_cache", lambda _key: None)
    monkeypatch.setattr(yfinance_provider, "write_cache", lambda _key, _frame: None)

    result = YahooFinanceProvider(retries=2, timeout_seconds=7).get_daily_bars(
        "SPY", "2025-01-01", "2025-02-01"
    )

    assert len(result.bars) == 4
    assert calls[0]["ticker"] == "SPY"
    assert calls[0]["timeout"] == 7
    assert calls[0]["auto_adjust"] is True
    assert calls[0]["actions"] is True
    assert calls[0]["threads"] is False
