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
    assert calls[0]["ticker"] == ["SPY"]
    assert calls[0]["timeout"] == 7
    assert calls[0]["auto_adjust"] is True
    assert calls[0]["actions"] is True
    assert calls[0]["threads"] is False


def test_yahoo_provider_batches_multiple_tickers_in_one_download(monkeypatch) -> None:
    index = pd.bdate_range("2025-01-02", periods=3)
    tickers = ["SPY", "QQQ"]
    fields = ["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]
    columns = pd.MultiIndex.from_product([fields, tickers])
    values = []
    for _day in range(len(index)):
        row = []
        for field in fields:
            for symbol in tickers:
                if field == "Open":
                    row.append(100.0 if symbol == "SPY" else 200.0)
                elif field == "High":
                    row.append(101.0 if symbol == "SPY" else 201.0)
                elif field == "Low":
                    row.append(99.0 if symbol == "SPY" else 199.0)
                elif field == "Close":
                    row.append(100.5 if symbol == "SPY" else 200.5)
                elif field == "Volume":
                    row.append(1_000_000.0)
                else:
                    row.append(0.0)
        values.append(row)
    raw = pd.DataFrame(values, index=index, columns=columns)
    calls: list[dict] = []

    def fake_download(tickers_arg, **kwargs):
        calls.append({"tickers": tickers_arg, **kwargs})
        return raw.copy()

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    monkeypatch.setattr(yfinance_provider, "read_cache", lambda _key: None)
    monkeypatch.setattr(yfinance_provider, "write_cache", lambda _key, _frame: None)

    data = YahooFinanceProvider(timeout_seconds=9).get_many_daily_bars(
        ["SPY", "QQQ"], "2025-01-01", "2025-02-01"
    )
    assert len(calls) == 1
    assert calls[0]["timeout"] == 9
    assert set(data) == {"SPY", "QQQ"}
    assert len(data["SPY"].bars) == 3
    assert len(data["QQQ"].bars) == 3
    assert data["SPY"].bars["Close"].iloc[-1] < data["QQQ"].bars["Close"].iloc[-1]
