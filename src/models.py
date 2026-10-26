from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

class ModelName(str, Enum):
    ALM = "ALM"
    DRBL_MATRIX = "DRBL Matrix"
    COMBINED = "Combined"

class Regime(str, Enum):
    A = "A"  # 3x, pouze pokud jsou všechny potvrzovací filtry dostupné a splněné
    B = "B"  # konzervativní 1x podklad
    C = "C"  # hotovost
    UNKNOWN = "NEDOSTUPNÝ"

class DataMode(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    HISTORICAL = "HISTORICAL"
    STALE = "STALE"

@dataclass
class Position:
    ticker: str
    market_value_usd: float
    quantity: float = 0.0
    average_price: float | None = None

@dataclass
class PortfolioState:
    model: ModelName
    cash_usd: float
    positions: dict[str, Position] = field(default_factory=dict)
    alm_completed: bool = False
    alm_fill_confirmed: bool = False
    selected_asset: str | None = None
    current_regime: Regime = Regime.UNKNOWN
    last_rotation_month: str | None = None
    alm_levels_filled: set[str] = field(default_factory=set)
    # Distinguishes a live crisis ALM sleeve from an ordinary Matrix position.
    active_alm_ticker: str | None = None

    @property
    def equity_usd(self) -> float:
        return self.cash_usd + sum(p.market_value_usd for p in self.positions.values())

@dataclass(frozen=True)
class Recommendation:
    model: ModelName
    as_of: datetime | None
    source: str
    data_mode: DataMode
    provisional: bool
    ticker: str | None
    action: str
    target_usd: float
    delta_usd: float
    estimated_commission_usd: float
    estimated_slippage_usd: float
    reason: str
    regime: Regime = Regime.UNKNOWN
    indicators: dict[str, Any] = field(default_factory=dict)
    available: bool = True

@dataclass(frozen=True)
class OrderPreview:
    ticker: str
    side: str
    target_usd: float
    delta_usd: float
    estimated_price: float
    estimated_quantity: float
    residual_cash_usd: float
    commission_usd: float
    slippage_usd: float
    currency: str = "USD"
    exchange: str = "SMART"
    status: str = "PREVIEW_ONLY"
    other_fees_usd: float = 0.0
