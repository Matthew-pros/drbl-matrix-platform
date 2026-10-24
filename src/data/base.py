from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from ..models import DataMode


@dataclass(frozen=True)
class MarketData:
    ticker: str
    bars: pd.DataFrame
    source: str
    retrieved_at: datetime
    last_timestamp: datetime | None
    mode: DataMode
    warning: str | None = None


class DataProvider(ABC):
    @abstractmethod
    def get_daily_bars(self, ticker: str, start: str, end: str) -> MarketData:
        """Return daily OHLCV bars for [start, end)."""
        raise NotImplementedError
