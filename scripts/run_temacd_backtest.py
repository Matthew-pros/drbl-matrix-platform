#!/usr/bin/env python3
"""Download Yahoo Finance daily bars and run the TEMACD rotation backtest.

Example:
  python scripts/run_temacd_backtest.py --start 2018-01-01 --end 2026-10-01

Outputs are written to outputs/temacd by default. Yahoo's daily data availability,
corporate-action treatment and rate limits are external dependencies; this script
never sends orders to a broker.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.yfinance_provider import YahooFinanceProvider
from src.strategies.temacd_rotation import TEMACDConfig, TEMACD_UNIVERSE, run_temacd_backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TEMACD volatility-sized sector/beta rotation backtest")
    parser.add_argument("--start", default=(date.today() - timedelta(days=365 * 5)).isoformat(), help="First evaluation date YYYY-MM-DD")
    parser.add_argument("--end", default=date.today().isoformat(), help="Last evaluation date YYYY-MM-DD")
    parser.add_argument("--warmup-years", type=int, default=2, help="Extra years of prices before --start")
    parser.add_argument("--initial-equity", type=float, default=100_000.0)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--rebalance", choices=("weekly", "monthly"), default="monthly")
    parser.add_argument("--target-risk-pct", type=float, default=1.0, help="Target risk unit as percent of equity per position")
    parser.add_argument("--max-weight-pct", type=float, default=35.0, help="Max single-asset weight percent")
    parser.add_argument("--transaction-cost-bps", type=float, default=5.0, help="Cost per buy/sell side in basis points; 5 bps = 0.05%%")
    parser.add_argument("--ema-fast", type=int, default=10)
    parser.add_argument("--ema-mid", type=int, default=30)
    parser.add_argument("--ema-slow", type=int, default=120)
    parser.add_argument("--macd-fast", type=int, default=30)
    parser.add_argument("--macd-slow", type=int, default=80)
    parser.add_argument("--macd-signal", type=int, default=15)
    parser.add_argument("--atr-period", type=int, default=20)
    parser.add_argument("--rsi-period", type=int, default=14)
    parser.add_argument("--output-dir", default="outputs/temacd")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.warmup_years < 1:
        raise SystemExit("--warmup-years must be >= 1")
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    if end < start:
        raise SystemExit("--end must be on or after --start")
    warmup_start = (start - pd.DateOffset(years=args.warmup_years)).strftime("%Y-%m-%d")
    end_exclusive = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    provider = YahooFinanceProvider()
    market_data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    print(f"Loading daily Yahoo Finance bars from {warmup_start} through {end_exclusive} (exclusive end)…")
    for ticker in TEMACD_UNIVERSE:
        try:
            result = provider.get_daily_bars(ticker, warmup_start, end_exclusive)
            market_data[ticker] = result.bars
            print(f"  {ticker:8} {len(result.bars):5} bars, last={result.last_timestamp}")
        except Exception as exc:  # one asset failing should not hide other symbol histories
            errors.append(f"{ticker}: {exc}")
            print(f"  {ticker:8} SKIPPED: {exc}")

    config = TEMACDConfig(
        ema_fast=args.ema_fast, ema_mid=args.ema_mid, ema_slow=args.ema_slow,
        macd_fast=args.macd_fast, macd_slow=args.macd_slow, macd_signal=args.macd_signal,
        atr_period=args.atr_period, rsi_period=args.rsi_period, top_n=args.top_n,
        rebalance=args.rebalance, target_risk=args.target_risk_pct / 100.0,
        max_asset_weight=args.max_weight_pct / 100.0,
        transaction_cost_rate=args.transaction_cost_bps / 10_000.0,
        initial_equity=args.initial_equity,
    )
    result = run_temacd_backtest(market_data, config, args.start, args.end)
    output_dir = (ROOT / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "config": {
            "start": args.start, "end": args.end, "warmup_start": warmup_start,
            "universe": list(TEMACD_UNIVERSE), "top_n": args.top_n, "rebalance": args.rebalance,
            "target_risk_pct": args.target_risk_pct, "max_weight_pct": args.max_weight_pct,
            "transaction_cost_bps_per_side": args.transaction_cost_bps,
            "initial_equity": args.initial_equity,
            "ema": [args.ema_fast, args.ema_mid, args.ema_slow],
            "temacd": [args.macd_fast, args.macd_slow, args.macd_signal],
            "atr_period": args.atr_period, "rsi_period": args.rsi_period,
        },
        "temacd": result.metrics,
        "spy_buy_hold": result.benchmark_metrics,
        "data_warnings": errors,
        "backtest_warnings": result.warnings,
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    result.trades.to_csv(output_dir / "trades.csv", index=False)
    result.rebalance_log.to_csv(output_dir / "rebalance_log.csv", index=False)
    result.weights.to_csv(output_dir / "weights.csv", index=False)
    pd.concat([result.equity, result.benchmark_equity], axis=1).to_csv(output_dir / "equity.csv", index_label="Date")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=result.equity.index, y=result.equity.values, mode="lines", name="TEMACD volatility sizing"))
    fig.add_trace(go.Scatter(x=result.benchmark_equity.index, y=result.benchmark_equity.values, mode="lines", name="SPY Buy & Hold"))
    fig.update_layout(title="TEMACD Rotation vs SPY Buy & Hold", xaxis_title="Date", yaxis_title="Equity (USD)", template="plotly_white")
    fig.write_html(output_dir / "equity_vs_spy.html", include_plotlyjs="cdn")

    table = pd.DataFrame([
        {"Strategy": "TEMACD Rotation", **result.metrics},
        {"Strategy": "SPY Buy & Hold", **result.benchmark_metrics},
    ]).set_index("Strategy")
    print("\nHistorical metrics (not a return forecast):")
    print(table.to_string(float_format=lambda value: f"{value:,.4f}"))
    print(f"\nStrategy transaction costs: ${result.total_transaction_costs:,.2f}")
    print(f"Outputs: {output_dir}")
    if errors or result.warnings:
        print(f"Warnings: {len(errors) + len(result.warnings)}; see metrics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())