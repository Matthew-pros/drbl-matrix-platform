from __future__ import annotations

import itertools
import json
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..data.yfinance_provider import YahooFinanceProvider
from .temacd_rotation import (
    AGGRESSIVE_ASSETS,
    CORE_ASSETS,
    TEMACDAssetParams,
    TEMACDConfig,
    TEMACD_UNIVERSE,
    run_temacd_backtest,
)

PARAMETER_KEYS = (
    "ema_fast", "ema_mid", "ema_slow", "macd_fast", "macd_slow",
    "macd_signal", "rsi_period", "atr_period",
)
DEFAULT_GRID_EMA = ((8, 21, 100), (10, 30, 120), (12, 36, 150), (10, 30, 200))
DEFAULT_GRID_MACD = ((20, 60, 10), (30, 80, 15), (40, 100, 20))


def parse_asset_params_json(payload: str | bytes | dict[str, Any]) -> dict[str, TEMACDAssetParams]:
    """Parse optimizer JSON to per-asset parameter objects; reject malformed/unknown ticker rows."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    document = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(document, dict):
        raise ValueError("Grid-search JSON musí být objekt.")
    raw = document.get("asset_params", document)
    if not isinstance(raw, dict):
        raise ValueError("Položka asset_params musí být objekt mapující ticker na parametry.")

    asset_params: dict[str, TEMACDAssetParams] = {}
    for ticker, values in raw.items():
        if ticker in {"schema_version", "generated_at", "objective", "training_period", "out_of_sample_period", "results"}:
            continue
        if ticker not in TEMACD_UNIVERSE:
            raise ValueError(f"Grid-search JSON obsahuje ticker mimo TEMACD universe: {ticker}.")
        if not isinstance(values, dict):
            raise ValueError(f"Parametry pro {ticker} musí být JSON objekt.")
        missing = set(PARAMETER_KEYS) - set(values)
        if missing:
            raise ValueError(f"{ticker}: chybí parametry {', '.join(sorted(missing))}.")
        try:
            asset_params[ticker] = TEMACDAssetParams(**{key: int(values[key]) for key in PARAMETER_KEYS})
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{ticker}: neplatné TEMACD parametry ({exc}).") from exc
    if not asset_params:
        raise ValueError("Grid-search soubor neobsahuje žádné per-asset parametry.")
    return asset_params


def load_asset_params_file(path: str | Path) -> dict[str, TEMACDAssetParams]:
    return parse_asset_params_json(Path(path).read_text(encoding="utf-8"))


def _safe_float(metrics: dict[str, Any], key: str) -> float:
    try:
        value = float(metrics.get(key, float("nan")))
        return value if np.isfinite(value) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _objective(metrics: dict[str, Any], minimum_transactions: int) -> float:
    """Bounded 50/50 Sharpe-Calmar score; candidates with too few fills are rejected."""
    if int(metrics.get("transactions", 0)) < minimum_transactions:
        return float("-inf")
    sharpe = _safe_float(metrics, "sharpe")
    calmar = _safe_float(metrics, "calmar")
    if not np.isfinite(sharpe) or not np.isfinite(calmar):
        return float("-inf")
    return 0.5 * float(np.clip(sharpe, -3.0, 3.0)) + 0.5 * float(np.clip(calmar, -3.0, 3.0))


def run_temacd_grid_search(
    data: dict[str, pd.DataFrame],
    end: str,
    train_years: int = 5,
    oos_years: int = 2,
    warmup_years: int = 3,
    minimum_transactions: int = 6,
    initial_equity: float = 100_000.0,
    target_risk: float = 0.01,
    max_asset_weight: float = 0.35,
    transaction_cost_rate: float = 0.0005,
    ema_grid: tuple[tuple[int, int, int], ...] = DEFAULT_GRID_EMA,
    macd_grid: tuple[tuple[int, int, int], ...] = DEFAULT_GRID_MACD,
    tickers: tuple[str, ...] = TEMACD_UNIVERSE,
) -> tuple[dict[str, TEMACDAssetParams], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Optimize each ticker on an in-sample window, then report a separate untouched OOS window.

    Every candidate is selected only from in-sample Sharpe/Calmar. The OOS run is for
    reporting and is never used to choose parameters. Inputs must include full OHLCV
    history beginning before train_start by at least warmup_years.
    """
    if train_years < 1 or oos_years < 1 or warmup_years < 1:
        raise ValueError("Train, OOS a warm-up období musí být alespoň jeden rok.")
    if minimum_transactions < 0:
        raise ValueError("Minimum transactions nesmí být záporné.")
    if not ema_grid or not macd_grid:
        raise ValueError("Grid nesmí být prázdný.")
    for fast, mid, slow in ema_grid:
        TEMACDAssetParams(ema_fast=fast, ema_mid=mid, ema_slow=slow)
    for fast, slow, signal in macd_grid:
        TEMACDAssetParams(macd_fast=fast, macd_slow=slow, macd_signal=signal)

    end_ts = pd.Timestamp(end).normalize()
    oos_start = (end_ts - pd.DateOffset(years=oos_years)).normalize()
    train_end = (oos_start - pd.Timedelta(days=1)).normalize()
    train_start = (train_end - pd.DateOffset(years=train_years)).normalize()
    warmup_start = (train_start - pd.DateOffset(years=warmup_years)).normalize()
    candidates = [
        TEMACDAssetParams(
            ema_fast=ema_fast, ema_mid=ema_mid, ema_slow=ema_slow,
            macd_fast=macd_fast, macd_slow=macd_slow, macd_signal=macd_signal,
        )
        for (ema_fast, ema_mid, ema_slow), (macd_fast, macd_slow, macd_signal)
        in itertools.product(ema_grid, macd_grid)
    ]

    all_candidate_rows: list[dict[str, Any]] = []
    oos_rows: list[dict[str, Any]] = []
    best_by_asset: dict[str, TEMACDAssetParams] = {}
    selected_meta: dict[str, Any] = {}

    for ticker in tickers:
        frame = data.get(ticker)
        spy = data.get("SPY")
        if frame is None or frame.empty or spy is None or spy.empty:
            oos_rows.append({
                "ticker": ticker, "status": "SKIPPED_NO_DATA", "reason": "Chybí historie aktiva nebo SPY benchmark.",
                "train_start": train_start.date().isoformat(), "train_end": train_end.date().isoformat(),
                "oos_start": oos_start.date().isoformat(), "oos_end": end_ts.date().isoformat(),
            })
            continue
        if frame.index.max() < train_end or frame.index.min() > train_start + pd.Timedelta(days=90):
            oos_rows.append({
                "ticker": ticker, "status": "SKIPPED_INSUFFICIENT_HISTORY",
                "reason": "Aktivum nepokrývá požadované trénovací okno; nebude se doplňovat syntetická historie.",
                "first_bar": frame.index.min().date().isoformat(), "last_bar": frame.index.max().date().isoformat(),
                "train_start": train_start.date().isoformat(), "train_end": train_end.date().isoformat(),
                "oos_start": oos_start.date().isoformat(), "oos_end": end_ts.date().isoformat(),
            })
            continue

        best_score = float("-inf")
        best_params: TEMACDAssetParams | None = None
        best_train_metrics: dict[str, Any] = {}
        candidate_metrics: dict[str, dict[str, Any]] = {}
        for params in candidates:
            cfg = TEMACDConfig(
                top_n=1, rebalance="monthly", target_risk=target_risk,
                max_asset_weight=max_asset_weight, transaction_cost_rate=transaction_cost_rate,
                initial_equity=initial_equity, asset_params={ticker: params},
            )
            try:
                result = run_temacd_backtest(
                    data, cfg, start=train_start.date().isoformat(),
                    end=train_end.date().isoformat(), universe=(ticker,),
                )
                metrics = result.metrics
                score = _objective(metrics, minimum_transactions)
                metrics_row = {
                    "ticker": ticker, **asdict(params),
                    "in_sample_score": score,
                    "in_sample_cagr": _safe_float(metrics, "cagr"),
                    "in_sample_sharpe": _safe_float(metrics, "sharpe"),
                    "in_sample_sortino": _safe_float(metrics, "sortino"),
                    "in_sample_calmar": _safe_float(metrics, "calmar"),
                    "in_sample_max_drawdown": _safe_float(metrics, "max_drawdown"),
                    "in_sample_profit_factor": _safe_float(metrics, "profit_factor"),
                    "in_sample_transactions": int(metrics.get("transactions", 0)),
                    "in_sample_fees_usd": float(result.total_transaction_costs),
                    "status": "OK" if np.isfinite(score) else "REJECTED_INSUFFICIENT_TRADES_OR_METRICS",
                }
                candidate_metrics[json.dumps(asdict(params), sort_keys=True)] = metrics_row
                all_candidate_rows.append(metrics_row)
                if score > best_score:
                    best_score = score
                    best_params = params
                    best_train_metrics = metrics_row
            except (ValueError, KeyError, TypeError) as exc:
                all_candidate_rows.append({
                    "ticker": ticker, **asdict(params), "in_sample_score": float("-inf"),
                    "status": "ERROR", "error": str(exc),
                })

        fallback = best_params is None or not np.isfinite(best_score)
        if fallback:
            best_params = TEMACDAssetParams()
            best_train_metrics = {"in_sample_score": float("nan"), "in_sample_transactions": 0,
                                  "status": "FALLBACK_TO_DEFAULT_NO_VALID_GRID_CANDIDATE"}
        best_by_asset[ticker] = best_params

        cfg_oos = TEMACDConfig(
            top_n=1, rebalance="monthly", target_risk=target_risk,
            max_asset_weight=max_asset_weight, transaction_cost_rate=transaction_cost_rate,
            initial_equity=initial_equity, asset_params={ticker: best_params},
        )
        try:
            result_oos = run_temacd_backtest(
                data, cfg_oos, start=oos_start.date().isoformat(),
                end=end_ts.date().isoformat(), universe=(ticker,),
            )
            m = result_oos.metrics
            oos_rows.append({
                "ticker": ticker, "status": "FALLBACK_DEFAULT" if fallback else "OK",
                "fallback_to_default": fallback,
                "selected_params": json.dumps(asdict(best_params), sort_keys=True),
                "selected_is_score": best_train_metrics.get("in_sample_score"),
                "is_sharpe": best_train_metrics.get("in_sample_sharpe"),
                "is_calmar": best_train_metrics.get("in_sample_calmar"),
                "oos_start": result_oos.equity.index.min().date().isoformat(),
                "oos_end": result_oos.equity.index.max().date().isoformat(),
                "oos_net_profit_usd": float(m["ending_equity"] - initial_equity),
                "oos_total_return": _safe_float(m, "total_return"),
                "oos_cagr": _safe_float(m, "cagr"),
                "oos_sharpe": _safe_float(m, "sharpe"),
                "oos_sortino": _safe_float(m, "sortino"),
                "oos_calmar": _safe_float(m, "calmar"),
                "oos_max_drawdown": _safe_float(m, "max_drawdown"),
                "oos_profit_factor": _safe_float(m, "profit_factor"),
                "oos_transactions": int(m.get("transactions", 0)),
                "oos_fees_usd": float(result_oos.total_transaction_costs),
                "train_start": train_start.date().isoformat(), "train_end": train_end.date().isoformat(),
            })
        except (ValueError, KeyError, TypeError) as exc:
            oos_rows.append({"ticker": ticker, "status": "OOS_ERROR", "error": str(exc)})

    metadata = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "objective": "In-sample score = 0.5 * clipped Sharpe + 0.5 * clipped Calmar; candidates need minimum transactions. OOS is report-only.",
        "train_start": train_start.date().isoformat(),
        "train_end": train_end.date().isoformat(),
        "out_of_sample_start": oos_start.date().isoformat(),
        "out_of_sample_end": end_ts.date().isoformat(),
        "warmup_start": warmup_start.date().isoformat(),
        "minimum_transactions": minimum_transactions,
        "asset_params": {ticker: asdict(params) for ticker, params in best_by_asset.items()},
        "selection": selected_meta,
    }
    return best_by_asset, pd.DataFrame(all_candidate_rows), pd.DataFrame(oos_rows), metadata


def download_and_run_grid_search(
    end: str,
    train_years: int = 5,
    oos_years: int = 2,
    warmup_years: int = 3,
    minimum_transactions: int = 6,
    initial_equity: float = 100_000.0,
    target_risk: float = 0.01,
    max_asset_weight: float = 0.35,
    transaction_cost_rate: float = 0.0005,
    tickers: tuple[str, ...] = TEMACD_UNIVERSE,
) -> tuple[dict[str, TEMACDAssetParams], pd.DataFrame, pd.DataFrame, dict[str, Any], list[str]]:
    end_ts = pd.Timestamp(end).normalize()
    total_years = train_years + oos_years + warmup_years
    start = (end_ts - pd.DateOffset(years=total_years)).strftime("%Y-%m-%d")
    end_exclusive = (end_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    requested = tuple(dict.fromkeys((*tickers, "SPY")))
    provider = YahooFinanceProvider()
    market_data = provider.get_many_daily_bars(requested, start, end_exclusive)
    data = {ticker: item.bars for ticker, item in market_data.items() if item is not None and not item.bars.empty}
    warnings = [
        f"{ticker}: {item.warning or 'historie není dostupná'}"
        for ticker, item in market_data.items() if item is None or item.bars.empty
    ]
    params, candidates, oos, metadata = run_temacd_grid_search(
        data=data, end=end, train_years=train_years, oos_years=oos_years,
        warmup_years=warmup_years, minimum_transactions=minimum_transactions,
        initial_equity=initial_equity, target_risk=target_risk,
        max_asset_weight=max_asset_weight, transaction_cost_rate=transaction_cost_rate,
        tickers=tickers,
    )
    return params, candidates, oos, metadata, warnings
