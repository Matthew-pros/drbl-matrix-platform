from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from .base import DataProvider, MarketData
from .cache import cache_key, read_cache, write_cache
from ..indicators import normalize_ohlcv
from ..models import DataMode


class YahooFinanceProvider(DataProvider):
    """Historická denní OHLCV data přes yfinance; nejsou garantovaným živým feedem."""

    def __init__(self, retries: int = 3) -> None:
        self.retries = max(1, retries)

    def get_daily_bars(self, ticker: str, start: str, end: str) -> MarketData:
        key = cache_key(ticker, start, end, "daily-auto-adjust-true-v3")
        cached = read_cache(key)
        if cached is not None and not cached.empty:
            bars = normalize_ohlcv(cached)
            return MarketData(
                ticker, bars, "Yahoo Finance (cache)", datetime.now(timezone.utc),
                bars.index[-1].to_pydatetime(), DataMode.HISTORICAL,
                "Historická data z lokální cache; nejsou live.",
            )

        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("Balíček yfinance není instalován.") from exc

        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                raw = yf.download(
                    ticker, start=start, end=end, interval="1d",
                    auto_adjust=True, actions=True, progress=False,
                    threads=False, group_by="column",
                )
                if raw is None or raw.empty:
                    raise RuntimeError(f"Yahoo Finance vrátilo prázdnou historii pro {ticker}.")
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = [str(col[0]) for col in raw.columns]
                bars = normalize_ohlcv(raw)
                for extra in ("Dividends", "Stock Splits"):
                    if extra in raw.columns:
                        bars[extra] = pd.to_numeric(raw.loc[bars.index, extra], errors="coerce")
                write_cache(key, bars)
                return MarketData(
                    ticker, bars, "Yahoo Finance", datetime.now(timezone.utc),
                    bars.index[-1].to_pydatetime(), DataMode.HISTORICAL,
                    "Denní historická data; OHLC upravené přes auto_adjust=True. "
                    "Úplnost, časová dostupnost a přesnost poskytovatele nejsou garantovány.",
                )
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(min(0.25 * 2**attempt, 2.0))
        raise RuntimeError(f"Načtení {ticker} selhalo po {self.retries} pokusech: {last_error}")
