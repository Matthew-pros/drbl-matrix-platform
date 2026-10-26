from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from .base import DataProvider, MarketData
from .cache import cache_key, read_cache, write_cache
from ..indicators import normalize_ohlcv
from ..models import DataMode


class YahooFinanceProvider(DataProvider):
    """Historická OHLCV data přes yfinance; nejsou garantovaným živým feedem.

    get_many_daily_bars batches requests to avoid sequential per-ticker startup delays.
    Failed tickers return an empty MarketData row with a visible warning; successful
    tickers are retained so one unavailable listing does not invalidate all downloaded data.
    """

    def __init__(self, retries: int = 2, timeout_seconds: float = 12.0) -> None:
        self.retries = max(1, retries)
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    @staticmethod
    def _ticker_frame(raw: pd.DataFrame, ticker: str, requested_count: int) -> pd.DataFrame:
        if raw is None or raw.empty:
            raise ValueError("Yahoo Finance vrátilo prázdnou odpověď.")
        if isinstance(raw.columns, pd.MultiIndex):
            for level in range(raw.columns.nlevels):
                if ticker in raw.columns.get_level_values(level):
                    frame = raw.xs(ticker, axis=1, level=level, drop_level=True)
                    if isinstance(frame.columns, pd.MultiIndex):
                        # When the same label appears in more than one level, reduce
                        # to the field names without guessing from column positions.
                        if frame.columns.nlevels == 1:
                            frame.columns = frame.columns.get_level_values(0)
                        else:
                            first_level = frame.columns.get_level_values(0)
                            if len(set(first_level)) == len(first_level):
                                frame.columns = first_level
                    return frame
            raise ValueError(f"Yahoo Finance nevrátil sloupce pro ticker {ticker}.")
        if requested_count != 1:
            raise ValueError("Yahoo Finance vrátilo jednovrstvé sloupce pro více tickerů.")
        return raw.copy()

    @staticmethod
    def _empty_result(ticker: str, warning: str) -> MarketData:
        return MarketData(
            ticker, pd.DataFrame(), "Yahoo Finance", datetime.now(timezone.utc),
            None, DataMode.STALE, warning,
        )

    def get_many_daily_bars(self, tickers: Iterable[str], start: str, end: str) -> dict[str, MarketData]:
        """Fetch/cache multiple daily series with bounded timeout and partial-failure handling."""
        symbols = list(dict.fromkeys(str(ticker).strip() for ticker in tickers if str(ticker).strip()))
        if not symbols:
            return {}
        output: dict[str, MarketData] = {}
        pending: list[str] = []

        for ticker in symbols:
            key = cache_key(ticker, start, end, "daily-auto-adjust-true-v3")
            cached = read_cache(key)
            if cached is not None and not cached.empty:
                try:
                    bars = normalize_ohlcv(cached)
                    output[ticker] = MarketData(
                        ticker, bars, "Yahoo Finance (cache)", datetime.now(timezone.utc),
                        bars.index[-1].to_pydatetime(), DataMode.HISTORICAL,
                        "Historická data z lokální cache; nejsou live.",
                    )
                    continue
                except (ValueError, TypeError):
                    # An invalid old cache should be replaced by a fresh request.
                    pass
            pending.append(ticker)

        if not pending:
            return output
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("Balíček yfinance není instalován.") from exc

        errors: dict[str, str] = {}
        for attempt in range(self.retries):
            if not pending:
                break
            request_tickers = pending.copy()
            try:
                raw = yf.download(
                    request_tickers,
                    start=start,
                    end=end,
                    interval="1d",
                    auto_adjust=True,
                    actions=True,
                    progress=False,
                    threads=min(4, len(request_tickers)),
                    group_by="column",
                    timeout=self.timeout_seconds,
                    multi_level_index=True,
                )
                if raw is None or raw.empty:
                    raise RuntimeError("Yahoo Finance vrátilo prázdnou odpověď.")
                for ticker in request_tickers:
                    try:
                        frame = self._ticker_frame(raw, ticker, len(request_tickers))
                        bars = normalize_ohlcv(frame)
                        if bars.empty:
                            raise ValueError("Po normalizaci nezůstaly žádné platné OHLCV bary.")
                        for extra in ("Dividends", "Stock Splits"):
                            if extra in frame.columns:
                                bars[extra] = pd.to_numeric(frame.loc[bars.index, extra], errors="coerce")
                        key = cache_key(ticker, start, end, "daily-auto-adjust-true-v3")
                        write_cache(key, bars)
                        output[ticker] = MarketData(
                            ticker,
                            bars,
                            "Yahoo Finance",
                            datetime.now(timezone.utc),
                            bars.index[-1].to_pydatetime(),
                            DataMode.HISTORICAL,
                            "Denní historická data; OHLC upravené přes auto_adjust=True. "
                            "Dostupnost a úplnost historie poskytovatele nejsou garantovány.",
                        )
                        errors.pop(ticker, None)
                    except (ValueError, TypeError, KeyError, IndexError) as exc:
                        errors[ticker] = str(exc)
            except Exception as exc:
                for ticker in request_tickers:
                    errors[ticker] = str(exc)

            pending = [ticker for ticker in symbols if ticker not in output]
            if pending and attempt + 1 < self.retries:
                time.sleep(min(0.5 * (2**attempt), 2.0))

        for ticker in pending:
            output[ticker] = self._empty_result(
                ticker,
                f"Nepodařilo se načíst {ticker} po {self.retries} pokusech: {errors.get(ticker, 'neznámá chyba')}",
            )
        return output

    def get_daily_bars(self, ticker: str, start: str, end: str) -> MarketData:
        result = self.get_many_daily_bars([ticker], start, end)[ticker]
        if result.bars.empty:
            raise RuntimeError(result.warning or f"Načtení {ticker} selhalo.")
        return result
