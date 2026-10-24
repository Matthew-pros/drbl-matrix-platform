from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

APP_NAME = "DRBL Matrix Platform"
PORTFOLIO_CURRENCY = "USD"
UI_TIMEZONE = ZoneInfo("Europe/Prague")
EXCHANGE_TIMEZONE = ZoneInfo("America/New_York")

# Klíče jsou interní názvy aktiv; ticker pro stažení dat může být odlišný.
BASE_TICKERS: dict[str, str] = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "GLD": "GLD",
    "IBIT": "IBIT",
    "BTCUSD": "BTC-USD",
}
LEVERAGED_TICKERS: dict[str, str | None] = {
    "SPY": "UPRO",
    "QQQ": "TQQQ",
    "GLD": None,       # povinné explicitní nastavení uživatelem
    "IBIT": None,      # Bitcoin ETF se v této matici nepákuje
    "BTCUSD": None,    # 3x BTC instrument není univerzální symbol; nikdy jej neodhaduj
}
DEFAULT_FACTORS: dict[str, str] = {
    "SPY": "TURTLE_SOUP",
    "QQQ": "TURTLE_SOUP",
    "GLD": "LRS",
    "IBIT": "LRS",
    "BTCUSD": "LRS",
}
AVAILABLE_FACTORS = ("TURTLE_SOUP", "KELTNER", "LRS", "SMA200", "EMA200", "VWAP200")

@dataclass(frozen=True)
class CostConfig:
    profile: str = "IBKR Pro Tiered – modelový odhad"
    commission_per_share: float = 0.0035
    minimum_per_order: float = 0.35
    additional_fee_per_share: float = 0.0
    slippage_bps_per_side: float = 10.0
    fractional_shares: bool = True
    cash_interest_annual: float = 0.0

    def __post_init__(self) -> None:
        if min(self.commission_per_share, self.minimum_per_order, self.additional_fee_per_share, self.slippage_bps_per_side) < 0:
            raise ValueError("Náklady nemohou být záporné.")
        if self.cash_interest_annual < 0:
            raise ValueError("Úrok hotovosti nemůže být záporný.")

@dataclass(frozen=True)
class StrategyConfig:
    initial_equity: float = 100_000.0
    # ALM: postupné tranše pro samostatný iniciační model. Combined přepíná po prvním potvrzeném fillu.
    alm_cash_reserve: float = 0.15
    alm_tiers: tuple[tuple[str, float, float], ...] = (("dd_30", 0.30, 0.15), ("dd_50", 0.50, 0.20), ("dd_80", 0.80, 0.50))
    matrix_target_fraction: float = 0.85
    rotation_hysteresis: float = 0.08
    # Denní režimový filtr používá výslovné pravidla, ne tvrzenou implementaci RAAM/FAA.
    risk_overlay_enabled: bool = True
    risk_off_vix_threshold: float = 35.0
    risk_elevated_vix_threshold: float = 25.0
    risk_vix_spike_minimum: float = 28.0
    risk_vix_spike_threshold: float = 0.35
    risk_crash_daily_return: float = -0.04
    risk_crash_range_multiple: float = 3.0
    crisis_alm_enabled: bool = True
    crisis_alm_drawdown: float = 0.15
    crisis_alm_allocation: float = 0.10
    adx_period: int = 14
    adx_leverage_threshold: float = 25.0
    rvol_short: int = 20
    rvol_long: int = 200
    rvol_leverage_threshold: float = 1.4
    atr_period: int = 20
    atr_percentile_window: int = 252
    atr_percentile: float = 0.90
    ts_entry_lookback: int = 40
    ts_exit_lookback: int = 20
    ts_confirmation_days: int = 5
    keltner_ema_period: int = 50
    keltner_atr_period: int = 20
    keltner_atr_multiple: float = 2.0
    regression_period: int = 100
    regression_band_multiple: float = 2.0
    sma_period: int = 200
    ema_period: int = 200
    vwap_period: int = 200
    base_tickers: dict[str, str] = field(default_factory=lambda: dict(BASE_TICKERS))
    leveraged_tickers: dict[str, str | None] = field(default_factory=lambda: dict(LEVERAGED_TICKERS))
    factor_by_asset: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FACTORS))
    gld_leveraged_ticker: str | None = None
    btc_leveraged_ticker: str | None = None

    def __post_init__(self) -> None:
        if self.initial_equity <= 0:
            raise ValueError("Počáteční equity musí být kladná.")
        if not 0 <= self.alm_cash_reserve < 1:
            raise ValueError("Hotovostní rezerva musí být v intervalu [0, 1).")
        if not 0 < self.matrix_target_fraction <= 1:
            raise ValueError("Cílová alokace musí být v intervalu (0, 1].")
        if not 0 <= self.rotation_hysteresis < 1:
            raise ValueError("Hystereze rotace musí být v intervalu [0, 1).")
        if self.risk_off_vix_threshold <= 0 or self.risk_elevated_vix_threshold <= 0:
            raise ValueError("Hranice VIX musí být kladné.")
        if self.risk_vix_spike_minimum <= 0 or self.risk_vix_spike_threshold < 0:
            raise ValueError("Parametry růstu VIX nejsou validní.")
        if not -1 < self.risk_crash_daily_return < 0:
            raise ValueError("Denní crash threshold musí být v intervalu (-1, 0).")
        if self.risk_crash_range_multiple <= 0:
            raise ValueError("Násobek denního rozpětí musí být kladný.")
        if not 0 < self.crisis_alm_drawdown < 1:
            raise ValueError("Krizový drawdown musí být v intervalu (0, 1).")
        if not 0 < self.crisis_alm_allocation <= 1 - self.alm_cash_reserve:
            raise ValueError("Krizová ALM tranše musí být kladná a respektovat hotovostní rezervu.")
        if self.atr_percentile_window < self.atr_period:
            raise ValueError("ATR percentile window musí být alespoň ATR perioda.")
        unknown = set(self.factor_by_asset.values()) - set(AVAILABLE_FACTORS)
        if unknown:
            raise ValueError(f"Neznámé trendové faktory: {', '.join(sorted(unknown))}.")
