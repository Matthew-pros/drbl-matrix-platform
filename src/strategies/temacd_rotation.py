"""TEMACD volatility-sized multi-asset rotation backtest.

Signal timing is deliberately conservative: indicators are computed from Close(t),
orders are simulated at Open(t+1), and per-side transaction costs are charged on
executed notional. This is a historical research module, not an order-routing engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import sqrt
from typing import Literal

import numpy as np
import pandas as pd

from ..indicators import atr_wilder, normalize_ohlcv, rolling_drawdown, true_range

CORE_ASSETS: tuple[str, ...] = (
    "SPY", "QQQ", "XLK", "XLY", "XLI", "XLV", "XLF", "XLE", "XLP", "XLU",
)
AGGRESSIVE_ASSETS: tuple[str, ...] = (
    "TQQQ", "SOXL", "SMH", "BTC-USD", "ETH-USD", "SOL-USD",
)
TEMACD_UNIVERSE: tuple[str, ...] = CORE_ASSETS + AGGRESSIVE_ASSETS


@dataclass(frozen=True)
class TEMACDAssetParams:
    """Per-asset indicator parameters selected by the walk-forward grid-search tool."""

    ema_fast: int = 10
    ema_mid: int = 30
    ema_slow: int = 120
    macd_fast: int = 30
    macd_slow: int = 80
    macd_signal: int = 15
    rsi_period: int = 14
    atr_period: int = 20

    def __post_init__(self) -> None:
        periods = (self.ema_fast, self.ema_mid, self.ema_slow, self.macd_fast,
                   self.macd_slow, self.macd_signal, self.rsi_period, self.atr_period)
        if any(period < 2 for period in periods):
            raise ValueError("Per-asset indikátorové periody musí být alespoň 2.")
        if not self.ema_fast < self.ema_mid < self.ema_slow:
            raise ValueError("EMA periody musí být vzestupné: EMA fast < mid < slow.")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("MACD Fast musí být menší než MACD Slow.")


@dataclass(frozen=True)
class TEMACDConfig:
    """Rotation and risk configuration; defaults are explicit and reproducible."""

    ema_fast: int = 10
    ema_mid: int = 30
    ema_slow: int = 120
    macd_fast: int = 30
    macd_slow: int = 80
    macd_signal: int = 15
    rsi_period: int = 14
    atr_period: int = 20
    top_n: int = 3
    rebalance: Literal["weekly", "monthly"] = "monthly"
    target_risk: float = 0.01
    max_asset_weight: float = 0.35
    transaction_cost_rate: float = 0.0005
    initial_equity: float = 100_000.0
    # Optional per-asset parameters from the walk-forward grid-search runner.
    asset_params: dict[str, TEMACDAssetParams] = field(default_factory=dict)
    # Combined-only group caps. Standalone Core/Aggressive portfolios are not limited by these.
    combined_aggressive_group_cap: float = 0.50
    combined_crypto_group_cap: float = 0.25
    combined_leveraged_group_cap: float = 0.20
    # Transparent market-regime overlay; VIX is optional but its absence must be logged.
    risk_overlay_enabled: bool = True
    exit_on_risk_off: bool = True
    risk_off_vix_threshold: float = 30.0
    risk_elevated_vix_threshold: float = 25.0
    risk_vix_spike_minimum: float = 28.0
    risk_vix_spike_threshold: float = 0.35
    risk_crash_daily_return: float = -0.04
    risk_crash_range_multiple: float = 3.0
    risk_crash_cooldown_sessions: int = 5
    transition_risk_multiplier: float = 0.50
    disable_leverage_in_transition: bool = True
    risk_recovery_confirmation_days: int = 2

    def __post_init__(self) -> None:
        periods = (
            self.ema_fast, self.ema_mid, self.ema_slow, self.macd_fast,
            self.macd_slow, self.macd_signal, self.rsi_period, self.atr_period,
        )
        if any(period < 2 for period in periods):
            raise ValueError("Všechna období indikátorů musí být alespoň 2.")
        if not self.ema_fast < self.ema_mid < self.ema_slow:
            raise ValueError("EMA periody musí být vzestupné: EMA fast < mid < slow.")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("MACD Fast musí být menší než MACD Slow.")
        if self.top_n < 1 or self.top_n > len(TEMACD_UNIVERSE):
            raise ValueError(f"Top N musí být v rozsahu 1–{len(TEMACD_UNIVERSE)}.")
        if self.rebalance not in {"weekly", "monthly"}:
            raise ValueError("Rebalanční interval musí být weekly nebo monthly.")
        if not 0 < self.target_risk <= 0.10:
            raise ValueError("Cílový risk na pozici musí být v intervalu (0, 10 %].")
        if not 0 < self.max_asset_weight <= 1:
            raise ValueError("Maximální váha musí být v intervalu (0, 100 %].")
        for name, value in (
            ("aggressive group cap", self.combined_aggressive_group_cap),
            ("crypto group cap", self.combined_crypto_group_cap),
            ("leveraged group cap", self.combined_leveraged_group_cap),
        ):
            if not 0 < value <= 1:
                raise ValueError(f"Combined {name} musí být v intervalu (0, 100 %].")
        if not 0 <= self.transaction_cost_rate < 0.1:
            raise ValueError("Transakční poplatek musí být v intervalu [0, 10 %).")
        if self.initial_equity <= 0:
            raise ValueError("Počáteční equity musí být kladná.")
        if min(self.risk_off_vix_threshold, self.risk_elevated_vix_threshold, self.risk_vix_spike_minimum) <= 0:
            raise ValueError("Hranice VIX musí být kladné.")
        if self.risk_vix_spike_threshold < 0:
            raise ValueError("Prahová změna VIX nesmí být záporná.")
        if not -1 < self.risk_crash_daily_return < 0:
            raise ValueError("Crash denní výnos musí ležet v intervalu (-100 %, 0 %).")
        if self.risk_crash_range_multiple <= 0:
            raise ValueError("Násobek denního rozpětí musí být kladný.")
        if self.risk_crash_cooldown_sessions < 1:
            raise ValueError("Crash cooldown musí být alespoň jedna obchodní seance.")
        if not 0 < self.transition_risk_multiplier <= 1:
            raise ValueError("Transition risk multiplier musí být v intervalu (0, 1].")
        if self.risk_recovery_confirmation_days < 1:
            raise ValueError("Recovery confirmation musí být alespoň jedna seance.")
        unknown_assets = set(self.asset_params) - set(TEMACD_UNIVERSE)
        if unknown_assets:
            raise ValueError(f"Per-asset parametry obsahují neznámé tickery: {', '.join(sorted(unknown_assets))}.")
        if any(not isinstance(value, TEMACDAssetParams) for value in self.asset_params.values()):
            raise TypeError("asset_params musí mapovat tickery na TEMACDAssetParams.")

    def for_asset(self, ticker: str) -> TEMACDConfig:
        """Return a config with the selected ticker's parameters, if available."""
        params = self.asset_params.get(ticker)
        if params is None:
            return self
        return replace(
            self,
            ema_fast=params.ema_fast,
            ema_mid=params.ema_mid,
            ema_slow=params.ema_slow,
            macd_fast=params.macd_fast,
            macd_slow=params.macd_slow,
            macd_signal=params.macd_signal,
            rsi_period=params.rsi_period,
            atr_period=params.atr_period,
            asset_params={},
        )

@dataclass
class TEMACDBacktestResult:
    equity: pd.Series
    benchmark_equity: pd.Series
    metrics: dict[str, float | int]
    benchmark_metrics: dict[str, float | int]
    trades: pd.DataFrame
    rebalance_log: pd.DataFrame
    weights: pd.DataFrame
    indicators: dict[str, pd.DataFrame] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    total_transaction_costs: float = 0.0
    regime_log: pd.DataFrame = field(default_factory=pd.DataFrame)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _tema(series: pd.Series, period: int) -> pd.Series:
    """Triple Exponential Moving Average: 3*EMA1 - 3*EMA2 + EMA3."""
    ema1 = series.ewm(span=period, adjust=False, min_periods=period).mean()
    ema2 = ema1.ewm(span=period, adjust=False, min_periods=period).mean()
    ema3 = ema2.ewm(span=period, adjust=False, min_periods=period).mean()
    return 3.0 * ema1 - 3.0 * ema2 + ema3


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + rs)
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    return result.rename("RSI")


def build_temacd_indicators(
    data: pd.DataFrame, config: TEMACDConfig | None = None, asset: str | None = None,
) -> pd.DataFrame:
    """Compute trend filter, TEMA-MACD, RSI and ATR without using future bars.

    When an asset is supplied, use its grid-searched parameters if configured;
    otherwise fall back to the explicit global defaults.
    """
    global_cfg = config or TEMACDConfig()
    cfg = global_cfg.for_asset(asset) if asset else global_cfg
    frame = normalize_ohlcv(data)
    close = frame["Close"].astype(float)
    out = frame.copy()
    out["EMA1"] = _ema(close, cfg.ema_fast)
    out["EMA2"] = _ema(close, cfg.ema_mid)
    out["EMA3"] = _ema(close, cfg.ema_slow)
    out["TEMA_MACD_Fast"] = _tema(close, cfg.macd_fast)
    out["TEMA_MACD_Slow"] = _tema(close, cfg.macd_slow)
    out["TEMACD"] = out["TEMA_MACD_Fast"] - out["TEMA_MACD_Slow"]
    out["TEMACD_Signal"] = _ema(out["TEMACD"], cfg.macd_signal)
    out["TEMACD_Hist"] = out["TEMACD"] - out["TEMACD_Signal"]
    out["RSI"] = _rsi(close, cfg.rsi_period)
    out["ATR"] = atr_wilder(frame, cfg.atr_period)
    out["ATR_pct"] = out["ATR"] / close
    # A bullish state persists while MACD is above its signal. The event flag
    # marks a new cross from non-positive to positive histogram.
    out["bullish"] = (out["TEMACD_Hist"] > 0).fillna(False)
    out["bullish_cross"] = (
        (out["TEMACD_Hist"] > 0) & (out["TEMACD_Hist"].shift(1) <= 0)
    ).fillna(False)
    out["bearish_cross"] = (
        (out["TEMACD_Hist"] <= 0) & (out["TEMACD_Hist"].shift(1) > 0)
    ).fillna(False)
    # The specification calls EMA3 the long-term eligibility filter.
    out["trend_ok"] = (close > out["EMA3"]).fillna(False)
    rsi_component = (out["RSI"] / 100.0).clip(0.0, 1.0)
    hist_pct = (out["TEMACD_Hist"] / close) * 100.0
    hist_component = (1.0 + np.tanh(hist_pct)) / 2.0
    out["momentum_score"] = 0.5 * rsi_component + 0.5 * hist_component
    required = ["EMA3", "TEMACD", "TEMACD_Signal", "RSI", "ATR_pct", "momentum_score"]
    out["indicator_ready"] = out[required].notna().all(axis=1)
    return out


def _metrics(equity: pd.Series) -> dict[str, float | int]:
    clean = equity.astype(float).dropna()
    if len(clean) < 2 or clean.iloc[0] <= 0:
        return {"total_return": float("nan"), "cagr": float("nan"), "annualized_volatility": float("nan"),
                "sharpe": float("nan"), "sortino": float("nan"), "max_drawdown": float("nan"), "ending_equity": float(clean.iloc[-1]) if len(clean) else float("nan")}
    returns = clean.pct_change(fill_method=None).dropna()
    total_return = float(clean.iloc[-1] / clean.iloc[0] - 1.0)
    years = max((clean.index[-1] - clean.index[0]).days / 365.25, 1.0 / 252.0)
    cagr = float((clean.iloc[-1] / clean.iloc[0]) ** (1.0 / years) - 1.0) if clean.iloc[-1] > 0 else float("nan")
    volatility = float(returns.std(ddof=1) * sqrt(252)) if len(returns) > 1 else float("nan")
    daily_std = returns.std(ddof=1)
    sharpe = float(returns.mean() / daily_std * sqrt(252)) if len(returns) > 1 and daily_std > 0 else float("nan")
    downside = np.minimum(returns.to_numpy(dtype=float), 0.0)
    downside_dev = float(np.sqrt(np.mean(np.square(downside)))) if len(downside) else 0.0
    sortino = float(returns.mean() / downside_dev * sqrt(252)) if downside_dev > 0 else float("nan")
    dd = clean / clean.cummax() - 1.0
    return {"total_return": total_return, "cagr": cagr, "annualized_volatility": volatility,
            "sharpe": sharpe, "sortino": sortino, "max_drawdown": float(abs(dd.min())),
            "ending_equity": float(clean.iloc[-1])}




def _closed_trade_pnls_fifo(trades: pd.DataFrame) -> list[float]:
    """Realized lot-level P&L matched FIFO with both entry and exit fees included."""
    from collections import defaultdict, deque

    if trades.empty:
        return []
    lots: dict[str, deque[list[float]]] = defaultdict(deque)
    closed_pnl: list[float] = []
    for row in trades.sort_values("execution_timestamp", kind="stable").itertuples(index=False):
        ticker, side = str(row.ticker), str(row.side).upper()
        quantity = float(row.quantity)
        notional = float(row.notional_usd)
        fee = float(row.commission_usd)
        if quantity <= 0:
            continue
        if side == "BUY":
            lots[ticker].append([quantity, (notional + fee) / quantity])
        elif side == "SELL":
            remaining = quantity
            unit_proceeds = (notional - fee) / quantity
            while remaining > 1e-10 and lots[ticker]:
                lot_quantity, unit_cost = lots[ticker][0]
                matched = min(remaining, lot_quantity)
                closed_pnl.append((unit_proceeds - unit_cost) * matched)
                remaining -= matched
                lot_quantity -= matched
                if lot_quantity <= 1e-10:
                    lots[ticker].popleft()
                else:
                    lots[ticker][0][0] = lot_quantity
    return closed_pnl


def profit_factor_fifo(trades: pd.DataFrame) -> float:
    """Realized gross profit / gross loss after fees; open lots do not count as closed trades."""
    closed_pnl = _closed_trade_pnls_fifo(trades)
    gross_profit = sum(value for value in closed_pnl if value > 0)
    gross_loss = -sum(value for value in closed_pnl if value < 0)
    if gross_loss > 0:
        return float(gross_profit / gross_loss)
    if gross_profit > 0:
        return float("inf")
    return float("nan")


def _period_key(day: pd.Timestamp, rebalance: str) -> tuple[int, ...]:
    if rebalance == "weekly":
        iso = day.isocalendar()
        return (int(iso.year), int(iso.week))
    return (day.year, day.month)


def _target_weights(
    eligible: list[tuple[str, float, float]],
    config: TEMACDConfig,
    apply_combined_group_caps: bool = False,
) -> dict[str, float]:
    """Inverse-ATR weights, per-asset cap, optional Combined group caps and 100% gross cap."""
    if not eligible:
        return {}
    raw: dict[str, float] = {}
    for asset, _score, atr_pct in eligible:
        if not np.isfinite(atr_pct) or atr_pct <= 0:
            continue
        raw[asset] = min(config.max_asset_weight, config.target_risk / atr_pct)

    def cap_group(tickers: tuple[str, ...], group_cap: float) -> None:
        group_total = sum(raw.get(ticker, 0.0) for ticker in tickers)
        if group_total > group_cap and group_total > 0:
            scale = group_cap / group_total
            for ticker in tickers:
                if ticker in raw:
                    raw[ticker] *= scale

    if apply_combined_group_caps:
        # Apply the narrower group caps first so the total aggressive cap cannot
        # re-expand crypto or leveraged exposures above their configured limits.
        cap_group(("BTC-USD", "ETH-USD", "SOL-USD"), config.combined_crypto_group_cap)
        cap_group(("TQQQ", "SOXL"), config.combined_leveraged_group_cap)
        cap_group(AGGRESSIVE_ASSETS, config.combined_aggressive_group_cap)

    gross = sum(raw.values())
    if gross > 1.0:
        raw = {asset: weight / gross for asset, weight in raw.items()}
    return raw


def _market_regime_history(
    normalized: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    config: TEMACDConfig,
) -> pd.DataFrame:
    """Vectorized, point-in-time market regimes built only from current and prior daily bars."""
    spy = normalized["SPY"]
    spy_close_full = spy["Close"].astype(float)
    spy_close = spy_close_full.reindex(dates)
    spy_sma200 = spy_close_full.rolling(200, min_periods=200).mean().reindex(dates)
    spy_below = (spy_close < spy_sma200).fillna(False)
    spy_valid_trend = spy_sma200.notna() & spy_close.notna()
    spy_drawdown = rolling_drawdown(spy_close_full).reindex(dates)
    spy_break_low = (
        spy_close_full < spy["Low"].rolling(20, min_periods=20).min().shift(1)
    ).reindex(dates).fillna(False)
    spy_tr = true_range(spy)
    spy_range_multiple = (
        spy_tr / spy_tr.rolling(20, min_periods=20).mean().shift(1).replace(0.0, np.nan)
    ).reindex(dates)
    spy_daily_return = spy_close_full.pct_change(fill_method=None).reindex(dates)
    spy_crash = (
        (spy_daily_return <= config.risk_crash_daily_return)
        & (spy_range_multiple >= config.risk_crash_range_multiple)
    ).fillna(False)

    qqq = normalized.get("QQQ")
    if qqq is not None and not qqq.empty:
        qqq_close_full = qqq["Close"].astype(float)
        qqq_close = qqq_close_full.reindex(dates)
        qqq_sma200 = qqq_close_full.rolling(200, min_periods=200).mean().reindex(dates)
        qqq_below = (qqq_close < qqq_sma200).fillna(False)
        qqq_valid_trend = qqq_sma200.notna() & qqq_close.notna()
        qqq_drawdown = rolling_drawdown(qqq_close_full).reindex(dates)
        qqq_break_low = (
            qqq_close_full < qqq["Low"].rolling(20, min_periods=20).min().shift(1)
        ).reindex(dates).fillna(False)
        qqq_tr = true_range(qqq)
        qqq_range_multiple = (
            qqq_tr / qqq_tr.rolling(20, min_periods=20).mean().shift(1).replace(0.0, np.nan)
        ).reindex(dates)
        qqq_daily_return = qqq_close_full.pct_change(fill_method=None).reindex(dates)
        qqq_crash = (
            (qqq_daily_return <= config.risk_crash_daily_return)
            & (qqq_range_multiple >= config.risk_crash_range_multiple)
        ).fillna(False)
    else:
        qqq_below = pd.Series(False, index=dates)
        qqq_valid_trend = pd.Series(False, index=dates)
        qqq_drawdown = pd.Series(np.nan, index=dates)
        qqq_break_low = pd.Series(False, index=dates)
        qqq_crash = pd.Series(False, index=dates)

    vix = normalized.get("VIX")
    if vix is not None and not vix.empty:
        vix_close_full = vix["Close"].astype(float)
        # Reindex to SPY sessions before the five-session change calculation.
        vix_close = vix_close_full.reindex(dates).ffill()
        vix_change_5d = vix_close.pct_change(5, fill_method=None)
        vix_available = vix_close.notna()
    else:
        vix_close = pd.Series(np.nan, index=dates, dtype=float)
        vix_change_5d = pd.Series(np.nan, index=dates, dtype=float)
        vix_available = pd.Series(False, index=dates)

    crash_today = (spy_crash | qqq_crash).reindex(dates).fillna(False).astype(bool)
    crash_recent = (
        crash_today.astype(int)
        .rolling(config.risk_crash_cooldown_sessions, min_periods=1)
        .max()
        .astype(bool)
    )
    deep_drawdown = ((spy_drawdown >= 0.30) | (qqq_drawdown >= 0.30)).fillna(False)
    high_vix = (vix_close >= config.risk_off_vix_threshold).fillna(False)
    vix_spike = (
        (vix_close >= config.risk_vix_spike_minimum)
        & (vix_change_5d >= config.risk_vix_spike_threshold)
    ).fillna(False)
    trend_stress = (
        (vix_close >= config.risk_elevated_vix_threshold)
        & spy_below
        & qqq_below
    ).fillna(False)
    low_break_stress = (
        (vix_close >= config.risk_elevated_vix_threshold)
        & (spy_break_low | qqq_break_low)
    ).fillna(False)
    risk_off = (deep_drawdown | crash_recent | high_vix | vix_spike | trend_stress | low_break_stress).astype(bool)

    # If VIX is missing, degrade transparently to a SPY/QQQ trend-only risk-on test.
    both_trends_valid = spy_valid_trend & qqq_valid_trend
    both_above = (~spy_below) & (~qqq_below)
    low_or_missing_vix = (vix_close < 20.0) | (~vix_available)
    risk_on = (~risk_off) & both_trends_valid & both_above & low_or_missing_vix
    transition = ~(risk_off | risk_on)

    reasons: list[str] = []
    for day in dates:
        why: list[str] = []
        if bool(deep_drawdown.loc[day]):
            why.append("SPY/QQQ drawdown ≥30 %")
        if bool(crash_recent.loc[day]):
            why.append(f"flash-crash trigger active within {config.risk_crash_cooldown_sessions} SPY sessions")
        if bool(high_vix.loc[day]):
            why.append(f"VIX ≥ {config.risk_off_vix_threshold:g}")
        if bool(vix_spike.loc[day]):
            why.append(f"VIX 5-session rise ≥ {config.risk_vix_spike_threshold:.0%}")
        if bool(trend_stress.loc[day]):
            why.append("SPY and QQQ below SMA200 with elevated VIX")
        if bool(low_break_stress.loc[day]):
            why.append("20-session low break with elevated VIX")
        if bool(risk_off.loc[day]):
            reasons.append("; ".join(why) or "risk-off trigger")
        elif bool(risk_on.loc[day]) and not bool(vix_available.loc[day]):
            reasons.append("SPY/QQQ above SMA200; VIX unavailable, degraded trend-only mode")
        elif bool(risk_on.loc[day]):
            reasons.append("SPY/QQQ above SMA200 and VIX below 20")
        elif not bool(vix_available.loc[day]):
            reasons.append("TRANSITION: VIX unavailable; trend/crash-only assessment")
        else:
            reasons.append("TRANSITION: mixed trend/volatility signals")

    regimes = np.where(risk_off, "RISK_OFF", np.where(risk_on, "RISK_ON", "TRANSITION"))
    return pd.DataFrame({
        "raw_market_regime": regimes,
        "raw_risk_off": risk_off,
        "raw_risk_on": risk_on,
        "reason": reasons,
        "vix_level": vix_close,
        "vix_change_5d": vix_change_5d,
        "spy_below_sma200": spy_below,
        "qqq_below_sma200": qqq_below,
        "spy_drawdown": spy_drawdown,
        "qqq_drawdown": qqq_drawdown,
        "crash_event_today": crash_today,
        "crash_event_recent": crash_recent,
    }, index=dates)


def _apply_regime_hysteresis(
    raw_history: pd.DataFrame,
    config: TEMACDConfig,
) -> pd.DataFrame:
    """Apply a causal RISK_OFF latch and multi-session RISK_ON recovery confirmation."""
    history = raw_history.copy()
    regimes: list[str] = []
    latched_rows: list[bool] = []
    multipliers: list[float] = []
    recovery_rows: list[int] = []
    reasons: list[str] = []
    latched = False
    recovery_count = 0

    for day, row in history.iterrows():
        raw_regime = str(row["raw_market_regime"])
        raw_risk_off = bool(row["raw_risk_off"])
        reason = str(row["reason"])

        if not config.risk_overlay_enabled:
            latched = False
            recovery_count = 0
            effective = "OVERLAY_OFF"
            risk_off_active = False
            risk_multiplier = 1.0
            reason = "Risk overlay disabled by configuration."
        else:
            if raw_risk_off:
                latched = True
                recovery_count = 0
            elif latched:
                if raw_regime == "RISK_ON":
                    recovery_count += 1
                else:
                    recovery_count = 0
                if recovery_count >= config.risk_recovery_confirmation_days:
                    latched = False
                    recovery_count = 0
                    reason += (
                        f"; recovery confirmed after {config.risk_recovery_confirmation_days} consecutive RISK_ON closes"
                    )
                else:
                    reason += (
                        f"; risk-off latch awaiting {config.risk_recovery_confirmation_days} consecutive RISK_ON closes "
                        f"({recovery_count}/{config.risk_recovery_confirmation_days})"
                    )
            risk_off_active = latched
            effective = "RISK_OFF" if risk_off_active else raw_regime
            risk_multiplier = (
                0.0 if risk_off_active
                else config.transition_risk_multiplier if effective == "TRANSITION"
                else 1.0
            )

        regimes.append(effective)
        latched_rows.append(risk_off_active)
        multipliers.append(risk_multiplier)
        recovery_rows.append(recovery_count)
        reasons.append(reason)

    history["market_regime"] = regimes
    history["risk_off_active"] = latched_rows
    history["risk_multiplier"] = multipliers
    history["recovery_confirmation_count"] = recovery_rows
    history["effective_reason"] = reasons
    return history


def run_temacd_backtest(
    data: dict[str, pd.DataFrame],
    config: TEMACDConfig | None = None,
    start: str | None = None,
    end: str | None = None,
    universe: tuple[str, ...] = TEMACD_UNIVERSE,
) -> TEMACDBacktestResult:
    """Run the strategy on SPY sessions; Close(t) signals execute at Open(t+1).

    ``data`` must map Yahoo/IBKR tickers to daily OHLCV frames. BTC/ETH/SOL rows
    can be present every day; the common evaluation calendar is SPY's sessions.
    """
    cfg = config or TEMACDConfig()
    normalized: dict[str, pd.DataFrame] = {}
    indicators: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
    # SPY is benchmark/session calendar; QQQ is an additional market-trend input.
    assets_to_prepare = tuple(dict.fromkeys((*universe, "SPY", "QQQ")))
    for asset in assets_to_prepare:
        frame = data.get(asset)
        if frame is None or frame.empty:
            warnings.append(f"{asset}: data nejsou dostupná; aktivum je z rotace vynecháno.")
            continue
        try:
            normalized[asset] = normalize_ohlcv(frame)
            indicators[asset] = build_temacd_indicators(normalized[asset], cfg, asset=asset)
        except (ValueError, TypeError) as exc:
            warnings.append(f"{asset}: data/indikátory nelze použít ({exc}).")
    raw_vix = data.get("VIX")
    if raw_vix is None or raw_vix.empty:
        raw_vix = data.get("^VIX")
    if raw_vix is not None and not raw_vix.empty:
        try:
            normalized["VIX"] = normalize_ohlcv(raw_vix)
        except (ValueError, TypeError) as exc:
            warnings.append(f"VIX: historickou řadu nelze použít; režim bude degradovaný ({exc}).")
    elif cfg.risk_overlay_enabled:
        warnings.append("VIX není dostupný; risk overlay přechází do degradovaného trend/crash-only režimu.")

    if "SPY" not in normalized:
        raise ValueError("Pro backtest a benchmark je povinné OHLCV SPY.")
    spy_dates = pd.DatetimeIndex(normalized["SPY"].index).sort_values()
    start_ts = pd.Timestamp(start) if start else spy_dates[0]
    end_ts = pd.Timestamp(end) if end else spy_dates[-1]
    dates = spy_dates[(spy_dates >= start_ts) & (spy_dates <= end_ts)]
    if len(dates) < 2:
        raise ValueError("Vybrané období musí obsahovat alespoň dvě SPY obchodní seance.")
    # Build regime state across the full available warm-up history so a risk-off
    # latch that began before the evaluation window is not silently forgotten.
    regime_dates = pd.DatetimeIndex(spy_dates[spy_dates <= end_ts])
    raw_regime_history = _market_regime_history(normalized, regime_dates, cfg)
    regime_history = _apply_regime_hysteresis(raw_regime_history, cfg)

    cash = float(cfg.initial_equity)
    holdings: dict[str, float] = {}  # asset -> shares
    last_marks: dict[str, float] = {}
    pending: tuple[pd.Timestamp, float, dict[str, float], str] | None = None
    equity_rows: list[tuple[pd.Timestamp, float]] = []
    benchmark_rows: list[tuple[pd.Timestamp, float]] = []
    trade_rows: list[dict] = []
    rebalance_rows: list[dict] = []
    weight_rows: list[dict] = []
    regime_rows: list[dict] = []
    benchmark_qty = 0.0
    benchmark_cash = float(cfg.initial_equity)
    benchmark_initialized = False
    last_rebalance_key: tuple[int, ...] | None = None

    def bar_on(asset: str, day: pd.Timestamp) -> pd.Series | None:
        frame = normalized.get(asset)
        if frame is None or day not in frame.index:
            return None
        return frame.loc[day]

    def mark_equity(day: pd.Timestamp, use_open: bool = False) -> float:
        nonlocal last_marks
        total = cash
        for asset, quantity in holdings.items():
            bar = bar_on(asset, day)
            field = "Open" if use_open else "Close"
            if bar is not None and pd.notna(bar[field]) and float(bar[field]) > 0:
                last_marks[asset] = float(bar[field])
            total += quantity * last_marks.get(asset, 0.0)
        return float(total)

    for idx, day in enumerate(dates):
        # Execute yesterday's Close signal at today's Open, in sell-first order.
        if pending is not None and pending[0] < day:
            signal_day, signal_equity, target_weights, reason = pending
            open_prices: dict[str, float] = {}
            trade_assets = set(holdings) | set(target_weights)
            for asset in trade_assets:
                bar = bar_on(asset, day)
                if bar is not None and pd.notna(bar["Open"]) and float(bar["Open"]) > 0:
                    open_prices[asset] = float(bar["Open"])
            # Mark current holdings at open where a bar exists.
            current_values = {asset: qty * open_prices.get(asset, last_marks.get(asset, 0.0))
                              for asset, qty in holdings.items()}
            target_values = {asset: signal_equity * weight for asset, weight in target_weights.items()}
            asset_order = sorted(trade_assets, key=lambda a: 0 if target_values.get(a, 0.0) < current_values.get(a, 0.0) else 1)
            # Sells first, then buys, so rotations do not spend proceeds before they exist.
            for asset in asset_order:
                open_price = open_prices.get(asset)
                if open_price is None:
                    if target_values.get(asset, 0.0) != current_values.get(asset, 0.0):
                        warnings.append(f"{day.date()}: {asset} nemá Open pro simulovanou exekuci; příkaz {reason!r} se přeskočil.")
                    continue
                current_qty = holdings.get(asset, 0.0)
                target_qty = target_values.get(asset, 0.0) / open_price
                delta_qty = target_qty - current_qty
                notional = abs(delta_qty) * open_price
                if notional < 1.0:
                    continue
                side = "BUY" if delta_qty > 0 else "SELL"
                if side == "BUY":
                    affordable = cash / (open_price * (1.0 + cfg.transaction_cost_rate)) if open_price > 0 else 0.0
                    delta_qty = min(delta_qty, affordable)
                    notional = delta_qty * open_price
                if delta_qty == 0:
                    continue
                fee = notional * cfg.transaction_cost_rate
                if side == "BUY":
                    cash -= notional + fee
                    holdings[asset] = current_qty + delta_qty
                else:
                    sell_qty = min(current_qty, abs(delta_qty))
                    notional = sell_qty * open_price
                    fee = notional * cfg.transaction_cost_rate
                    cash += notional - fee
                    remaining = current_qty - sell_qty
                    if remaining <= 1e-10:
                        holdings.pop(asset, None)
                    else:
                        holdings[asset] = remaining
                trade_rows.append({
                    "signal_timestamp": signal_day, "execution_timestamp": day, "ticker": asset,
                    "side": side, "quantity": abs(delta_qty), "price": open_price,
                    "notional_usd": notional, "commission_usd": fee, "transaction_cost_rate": cfg.transaction_cost_rate,
                    "reason": reason, "status": "SIMULATED_FILLED",
                })
                last_marks[asset] = open_price
            pending = None

        # Benchmark SPY buys at the first evaluation Open, then holds.
        spy_bar = bar_on("SPY", day)
        if spy_bar is not None:
            spy_open = float(spy_bar["Open"])
            if not benchmark_initialized:
                benchmark_notional = benchmark_cash / (1.0 + cfg.transaction_cost_rate)
                benchmark_qty = benchmark_notional / spy_open
                benchmark_cash -= benchmark_notional + benchmark_notional * cfg.transaction_cost_rate
                benchmark_initialized = True
            benchmark_close = float(spy_bar["Close"])
            benchmark_equity = benchmark_cash + benchmark_qty * benchmark_close
            benchmark_rows.append((day, benchmark_equity))

        # Mark equity using Close prices after Open fills.
        close_equity = mark_equity(day, use_open=False)
        equity_rows.append((day, close_equity))

        market_state = regime_history.loc[day]
        market_regime = str(market_state["market_regime"])
        risk_off_active = bool(market_state["risk_off_active"])
        risk_multiplier = float(market_state["risk_multiplier"])
        market_regime_reason = str(market_state["effective_reason"])
        regime_rows.append({
            "timestamp": day,
            "raw_market_regime": str(market_state["raw_market_regime"]),
            "market_regime": market_regime,
            "raw_risk_off": bool(market_state["raw_risk_off"]),
            "risk_off_active": risk_off_active,
            "risk_multiplier": risk_multiplier,
            "vix_level": market_state["vix_level"],
            "vix_change_5d": market_state["vix_change_5d"],
            "spy_below_sma200": bool(market_state["spy_below_sma200"]),
            "qqq_below_sma200": bool(market_state["qqq_below_sma200"]),
            "spy_drawdown": market_state["spy_drawdown"],
            "qqq_drawdown": market_state["qqq_drawdown"],
            "crash_event_today": bool(market_state["crash_event_today"]),
            "crash_event_recent": bool(market_state["crash_event_recent"]),
            "recovery_confirmation_count": int(market_state["recovery_confirmation_count"]),
            "reason": market_regime_reason,
        })

        # Avoid creating orders that cannot execute before the selected end date.
        if idx >= len(dates) - 1:
            break

        # Exit layer combines the normal TEMACD/EMA3 exit with the higher-priority
        # regime overlay. Every requested liquidation executes at the next Open.
        exits: list[str] = []
        if risk_off_active and cfg.exit_on_risk_off:
            exits = list(holdings)
        else:
            for asset in holdings:
                frame_i = indicators.get(asset)
                if frame_i is None or day not in frame_i.index:
                    continue
                row = frame_i.loc[day]
                if bool(row.get("bearish_cross", False)) or not bool(row.get("trend_ok", False)):
                    exits.append(asset)
                elif market_regime == "TRANSITION" and cfg.disable_leverage_in_transition and asset in {"TQQQ", "SOXL"}:
                    exits.append(asset)

        if exits:
            current_weights: dict[str, float] = {}
            current_equity = max(close_equity, 1e-9)
            for asset, quantity in holdings.items():
                if asset not in exits:
                    mark = last_marks.get(asset, 0.0)
                    current_weights[asset] = max(0.0, quantity * mark / current_equity)
            if risk_off_active and cfg.exit_on_risk_off:
                reason = "RISK_OFF liquidation scheduled for next Open; " + market_regime_reason
                exit_event = "RISK_OFF_EXIT"
            else:
                reason = (
                    "daily exit: bearish TEMACD / Close below EMA3 / leverage disabled in TRANSITION for "
                    + ", ".join(sorted(exits))
                )
                exit_event = "EXIT"
            pending = (day, close_equity, current_weights, reason)
            for asset in exits:
                row = indicators.get(asset, pd.DataFrame()).loc[day] if asset in indicators and day in indicators[asset].index else None
                rebalance_rows.append({
                    "signal_timestamp": day, "event": exit_event, "ticker": asset,
                    "close": float(row["Close"]) if row is not None else last_marks.get(asset, float("nan")),
                    "ATR_pct": float(row["ATR_pct"]) if row is not None else float("nan"),
                    "target_weight": 0.0,
                    "momentum_score": float(row["momentum_score"]) if row is not None else float("nan"),
                    "market_regime": market_regime, "risk_multiplier": risk_multiplier,
                    "reason": reason,
                })

        # Scheduled weekly/monthly rotation. The decision only uses today's Close.
        next_day = dates[idx + 1]
        today_key = _period_key(day, cfg.rebalance)
        next_key = _period_key(next_day, cfg.rebalance)
        is_scheduled_rebalance = today_key != next_key
        if is_scheduled_rebalance and today_key != last_rebalance_key:
            eligible: list[tuple[str, float, float]] = []
            held_assets = set(holdings)
            # A fresh bullish cross is an entry gate over the current rebalance
            # window. Existing holdings may remain eligible while the bullish state
            # and EMA3 trend filter persist; otherwise a positive MACD state that
            # crossed months ago could be mistaken for a fresh entry signal.
            cross_window = 5 if cfg.rebalance == "weekly" else 22
            recent_cross: dict[str, bool] = {}
            for asset in universe:
                frame_i = indicators.get(asset)
                if frame_i is None or day not in frame_i.index:
                    continue
                row = frame_i.loc[day]
                ready = bool(row.get("indicator_ready", False))
                bullish = bool(row.get("bullish", False))
                trend_ok = bool(row.get("trend_ok", False))
                crosses = frame_i.loc[:day, "bullish_cross"].tail(cross_window)
                bullish_cross_recent = bool(crosses.any())
                recent_cross[asset] = bullish_cross_recent
                cross_or_held = bullish_cross_recent or asset in held_assets
                atr_pct = float(row["ATR_pct"]) if pd.notna(row.get("ATR_pct")) else float("nan")
                score = float(row["momentum_score"]) if pd.notna(row.get("momentum_score")) else float("nan")
                if ready and bullish and trend_ok and cross_or_held and np.isfinite(atr_pct) and atr_pct > 0 and np.isfinite(score):
                    eligible.append((asset, score, atr_pct))
            eligible.sort(key=lambda item: item[1], reverse=True)
            selected = eligible[:cfg.top_n]
            combined_mode = bool(set(universe) & set(CORE_ASSETS)) and bool(set(universe) & set(AGGRESSIVE_ASSETS))
            target_weights = _target_weights(selected, cfg, apply_combined_group_caps=combined_mode)
            reason = (
                f"{cfg.rebalance} rotation; Top {cfg.top_n}; EMA3 trend filter + bullish TEMACD; "
                f"fresh cross in last {cross_window} bars unless already held; "
                f"Combined group caps={'ON' if combined_mode else 'OFF'}; "
                f"selected={','.join(target_weights) or 'CASH'}"
            )
            # Scheduled rotation supersedes the daily-exit target from the same Close.
            pending = (day, close_equity, target_weights, reason)
            last_rebalance_key = today_key
            for asset in universe:
                row_i = indicators.get(asset)
                if row_i is None or day not in row_i.index:
                    continue
                row = row_i.loc[day]
                if not bool(row.get("indicator_ready", False)):
                    continue
                score = float(row["momentum_score"])
                atr_pct = float(row["ATR_pct"])
                weight = target_weights.get(asset, 0.0)
                event = "SELECTED" if asset in target_weights else ("ELIGIBLE_NOT_TOP_N" if any(x[0] == asset for x in eligible) else "NOT_ELIGIBLE")
                bullish_cross_recent = recent_cross.get(asset, False)
                rebalance_rows.append({
                    "signal_timestamp": day, "event": event, "ticker": asset,
                    "close": float(row["Close"]), "ATR_pct": atr_pct,
                    "target_weight": weight, "momentum_score": score,
                    "RSI": float(row["RSI"]), "TEMACD_Hist": float(row["TEMACD_Hist"]),
                    "trend_ok": bool(row["trend_ok"]), "bullish": bool(row["bullish"]),
                    "bullish_cross": bool(row["bullish_cross"]), "bullish_cross_recent": bullish_cross_recent,
                    "reason": reason,
                })
                weight_rows.append({"signal_timestamp": day, "ticker": asset, "ATR_pct": atr_pct,
                                    "target_weight": weight, "momentum_score": score,
                                    "selected": asset in target_weights,
                                    "bullish_cross_recent": bullish_cross_recent,
                                    "combined_group_caps_applied": combined_mode})

    equity = pd.Series(dict(equity_rows), dtype=float).sort_index().rename("TEMACD Strategy")
    benchmark = pd.Series(dict(benchmark_rows), dtype=float).sort_index().rename("SPY Buy & Hold")
    if equity.empty or benchmark.empty:
        raise ValueError("Výsledná equity křivka je prázdná; zkontrolujte období a SPY data.")
    trades = pd.DataFrame(trade_rows)
    rebalance_log = pd.DataFrame(rebalance_rows)
    weights = pd.DataFrame(weight_rows)
    metrics = _metrics(equity)
    benchmark_metrics = _metrics(benchmark)
    dd_abs = float(metrics.get("max_drawdown", float("nan")))
    cagr_value = float(metrics.get("cagr", float("nan")))
    metrics["calmar"] = cagr_value / dd_abs if np.isfinite(cagr_value) and np.isfinite(dd_abs) and dd_abs > 0 else float("nan")
    metrics["profit_factor"] = profit_factor_fifo(trades)
    closed_pnls = _closed_trade_pnls_fifo(trades)
    metrics["win_rate"] = (
        float(sum(value > 0 for value in closed_pnls) / len(closed_pnls))
        if closed_pnls else float("nan")
    )
    metrics["transactions"] = int(len(trades))
    metrics["total_transaction_costs"] = float(trades["commission_usd"].sum()) if not trades.empty else 0.0
    if not trades.empty:
        metrics["average_transaction_cost_rate"] = float(trades["transaction_cost_rate"].mean())
    else:
        metrics["average_transaction_cost_rate"] = cfg.transaction_cost_rate
    benchmark_metrics["transactions"] = int(benchmark_initialized)
    return TEMACDBacktestResult(equity, benchmark, metrics, benchmark_metrics, trades, rebalance_log,
                                weights, indicators, warnings, float(metrics["total_transaction_costs"]))