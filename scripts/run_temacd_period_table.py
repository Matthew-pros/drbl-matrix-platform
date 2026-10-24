#!/usr/bin/env python3
"""Vypočítá skutečné historické metriky TEMACD pro horizonty 1/3/5/10/20/30 let.

Skript nikdy nedoplňuje neznámé výsledky odhadem. Neúplná historie se označí jako
N/A a zaznamená do coverage CSV. Všechny výnosy vycházejí z historických dat Yahoo
Finance a simulovaných obchodů po transakčních nákladech.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.yfinance_provider import YahooFinanceProvider
from src.strategies.temacd_rotation import (
    AGGRESSIVE_ASSETS, CORE_ASSETS, TEMACD_UNIVERSE, TEMACDConfig, run_temacd_backtest,
)

HORIZONS = (1, 3, 5, 10, 20, 30)
VARIANTS = {
    "Sector Rotation": CORE_ASSETS,
    "Aggressive Rotation": AGGRESSIVE_ASSETS,
    "Combined Rotation": TEMACD_UNIVERSE,
}


def _profit_factor_fifo(trades: pd.DataFrame) -> float:
    """Realized profit factor after both entry and exit commissions, matched FIFO."""
    if trades.empty:
        return float("nan")
    lots: dict[str, deque[list[float]]] = defaultdict(deque)
    closed_pnl: list[float] = []
    for row in trades.sort_values("execution_timestamp", kind="stable").itertuples(index=False):
        ticker, side = str(row.ticker), str(row.side).upper()
        qty, notional, fee = float(row.quantity), float(row.notional_usd), float(row.commission_usd)
        if qty <= 0:
            continue
        if side == "BUY":
            lots[ticker].append([qty, (notional + fee) / qty])
        elif side == "SELL":
            remaining = qty
            unit_proceeds = (notional - fee) / qty
            while remaining > 1e-10 and lots[ticker]:
                lot_qty, unit_cost = lots[ticker][0]
                matched = min(remaining, lot_qty)
                closed_pnl.append((unit_proceeds - unit_cost) * matched)
                remaining -= matched
                lot_qty -= matched
                if lot_qty <= 1e-10:
                    lots[ticker].popleft()
                else:
                    lots[ticker][0][0] = lot_qty
    gross_profit = sum(x for x in closed_pnl if x > 0)
    gross_loss = -sum(x for x in closed_pnl if x < 0)
    return gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else float("nan"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TEMACD quant metriky za 1, 3, 5, 10, 20 a 30 let")
    parser.add_argument("--end", default=date.today().isoformat(), help="Konec období (YYYY-MM-DD, včetně)")
    parser.add_argument("--warmup-years", type=int, default=3, help="Warm-up období před nejstarším horizontem")
    parser.add_argument("--initial-equity", type=float, default=100_000)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--rebalance", choices=("weekly", "monthly"), default="monthly")
    parser.add_argument("--target-risk-pct", type=float, default=1.0)
    parser.add_argument("--max-weight-pct", type=float, default=35.0)
    parser.add_argument("--transaction-cost-bps", type=float, default=5.0, help="Náklad za každou stranu obchodu")
    parser.add_argument("--output-dir", default="outputs/temacd_periods")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.initial_equity <= 0 or args.transaction_cost_bps < 0:
        raise SystemExit("Počáteční kapitál musí být kladný a náklady nesmí být záporné.")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    end = pd.Timestamp(args.end).normalize()
    if args.warmup_years < 1:
        raise SystemExit("--warmup-years musí být alespoň 1")
    earliest = end - pd.DateOffset(years=max(HORIZONS))
    # Warm-up is before the earliest evaluation start so EMA/ATR indicators are initialized.
    fetch_start = (earliest - pd.DateOffset(years=args.warmup_years)).strftime("%Y-%m-%d")
    fetch_end = (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    provider = YahooFinanceProvider()
    tickers = list(dict.fromkeys((*TEMACD_UNIVERSE, "SPY")))
    data: dict[str, pd.DataFrame] = {}
    coverage: list[dict[str, object]] = []

    for ticker in tickers:
        try:
            item = provider.get_daily_bars(ticker, fetch_start, fetch_end)
            data[ticker] = item.bars
            coverage.append({
                "ticker": ticker, "first_bar": item.bars.index.min().date().isoformat(),
                "last_bar": item.bars.index.max().date().isoformat(), "bars": len(item.bars),
                "source": item.source, "status": "OK", "warning": item.warning or "",
            })
        except Exception as exc:
            coverage.append({"ticker": ticker, "first_bar": "", "last_bar": "", "bars": 0,
                             "source": "Yahoo Finance", "status": "ERROR", "warning": str(exc)})

    rows: list[dict[str, object]] = []
    coverage_by_ticker = {str(row["ticker"]): row for row in coverage}
    cost_rate = args.transaction_cost_bps / 10_000.0

    for horizon in HORIZONS:
        start = (end - pd.DateOffset(years=horizon)).normalize()
        benchmark_added = False
        for variant, universe in VARIANTS.items():
            missing = [ticker for ticker in universe if ticker not in data]
            available = [ticker for ticker in universe if ticker in data]
            late_history: list[str] = []
            for ticker in available:
                first_bar = coverage_by_ticker.get(ticker, {}).get("first_bar")
                if first_bar:
                    first_day = pd.Timestamp(str(first_bar)).normalize()
                    if first_day > start + pd.Timedelta(days=35):
                        late_history.append(f"{ticker}:{first_day.date().isoformat()}")
            spy_row = coverage_by_ticker.get("SPY", {})
            spy_start = pd.Timestamp(str(spy_row.get("first_bar"))) if spy_row.get("first_bar") else None
            if "SPY" not in data or spy_start is None or spy_start > start + pd.Timedelta(days=35):
                rows.append({"portfolio": variant, "horizon_years": horizon, "start": start.date().isoformat(),
                             "end": end.date().isoformat(), "net_profit_usd": None, "net_profit_pct": None,
                             "max_drawdown_pct": None, "cagr_pct": None, "sharpe": None, "sortino": None,
                             "profit_factor": None, "trades": None, "fees_usd": None,
                             "coverage": "N/A: SPY history does not cover full requested period",
                             "available_assets": len(available), "missing_assets": ",".join(missing),
                             "late_history_assets": ",".join(late_history)})
                continue
            if not available:
                rows.append({"portfolio": variant, "horizon_years": horizon, "start": start.date().isoformat(),
                             "end": end.date().isoformat(), "net_profit_usd": None, "net_profit_pct": None,
                             "max_drawdown_pct": None, "cagr_pct": None, "sharpe": None, "sortino": None,
                             "profit_factor": None, "trades": None, "fees_usd": None,
                             "coverage": "N/A: no eligible assets have data",
                             "available_assets": 0, "missing_assets": ",".join(missing)})
                continue
            cfg = TEMACDConfig(
                top_n=min(args.top_n, len(TEMACD_UNIVERSE)), rebalance=args.rebalance,
                target_risk=args.target_risk_pct / 100, max_asset_weight=args.max_weight_pct / 100,
                transaction_cost_rate=cost_rate, initial_equity=args.initial_equity,
            )
            try:
                result = run_temacd_backtest(data, cfg, start=start.date().isoformat(),
                                             end=end.date().isoformat(), universe=universe)
                m = result.metrics
                rows.append({
                    "portfolio": variant, "horizon_years": horizon,
                    "start": result.equity.index.min().date().isoformat(),
                    "end": result.equity.index.max().date().isoformat(),
                    "net_profit_usd": float(m["ending_equity"] - args.initial_equity),
                    "net_profit_pct": float(m["total_return"] * 100),
                    "max_drawdown_pct": -float(m["max_drawdown"] * 100),
                    "cagr_pct": float(m["cagr"] * 100),
                    "sharpe": float(m["sharpe"]), "sortino": float(m["sortino"]),
                    "profit_factor": _profit_factor_fifo(result.trades),
                    "trades": len(result.trades), "fees_usd": float(result.total_transaction_costs),
                    "coverage": (
                        ("PARTIAL; missing=" + ",".join(missing) if missing else "OK")
                        + ("; late_history=" + ",".join(late_history) if late_history else "")
                    ),
                    "available_assets": len(available), "missing_assets": ",".join(missing),
                    "late_history_assets": ",".join(late_history),
                })
                if not benchmark_added:
                    bm = result.benchmark_metrics
                    rows.append({
                        "portfolio": "SPY Buy & Hold", "horizon_years": horizon,
                        "start": result.benchmark_equity.index.min().date().isoformat(),
                        "end": result.benchmark_equity.index.max().date().isoformat(),
                        "net_profit_usd": float(bm["ending_equity"] - args.initial_equity),
                        "net_profit_pct": float(bm["total_return"] * 100),
                        "max_drawdown_pct": -float(bm["max_drawdown"] * 100),
                        "cagr_pct": float(bm["cagr"] * 100),
                        "sharpe": float(bm["sharpe"]), "sortino": float(bm["sortino"]),
                        "profit_factor": float("nan"), "trades": 1,
                        "fees_usd": float(args.initial_equity * cost_rate / (1.0 + cost_rate)),
                        "coverage": "SPY benchmark", "available_assets": 1, "missing_assets": "",
                    })
                    benchmark_added = True
                variant_slug = variant.lower().replace(" ", "_")
                result.equity.rename("TEMACD").to_csv(output / f"equity_{variant_slug}_{horizon}y.csv")
                result.benchmark_equity.rename("SPY_BuyHold").to_csv(output / f"spy_{horizon}y.csv")
                result.trades.to_csv(output / f"trades_{variant_slug}_{horizon}y.csv", index=False)
                result.rebalance_log.to_csv(output / f"rebalance_{variant_slug}_{horizon}y.csv", index=False)
                result.weights.to_csv(output / f"weights_{variant_slug}_{horizon}y.csv", index=False)
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=result.equity.index, y=result.equity.values, mode="lines", name=variant))
                fig.add_trace(go.Scatter(x=result.benchmark_equity.index, y=result.benchmark_equity.values, mode="lines", name="SPY Buy & Hold"))
                fig.update_layout(title=f"{variant} vs SPY — {horizon}Y", xaxis_title="Datum", yaxis_title="Equity (USD)", template="plotly_white")
                fig.write_html(output / f"equity_vs_spy_{variant_slug}_{horizon}y.html", include_plotlyjs="cdn")
            except Exception as exc:
                rows.append({"portfolio": variant, "horizon_years": horizon, "start": start.date().isoformat(),
                             "end": end.date().isoformat(), "net_profit_usd": None, "net_profit_pct": None,
                             "max_drawdown_pct": None, "cagr_pct": None, "sharpe": None, "sortino": None,
                             "profit_factor": None, "trades": None, "fees_usd": None,
                             "coverage": f"N/A: {type(exc).__name__}: {exc}",
                             "available_assets": len(available), "missing_assets": ",".join(missing)})

    results = pd.DataFrame(rows)
    results.to_csv(output / "period_metrics.csv", index=False)
    pd.DataFrame(coverage).to_csv(output / "data_coverage.csv", index=False)
    display_columns = ["portfolio", "horizon_years", "net_profit_usd", "net_profit_pct",
                       "max_drawdown_pct", "cagr_pct", "sharpe", "sortino", "profit_factor",
                       "trades", "fees_usd", "coverage"]
    display = results[display_columns].copy()

    def cell(value: object) -> str:
        if pd.isna(value):
            return "N/A"
        if isinstance(value, (int, float)):
            return f"{value:,.3f}"
        return str(value).replace("|", "\\|").replace("\\n", " ")

    header = "| " + " | ".join(display.columns) + " |"
    separator = "| " + " | ".join("---" for _ in display.columns) + " |"
    body = [
        "| " + " | ".join(cell(value) for value in row) + " |"
        for row in display.itertuples(index=False, name=None)
    ]
    markdown = "\n".join([header, separator, *body])
    (output / "period_metrics.md").write_text(
        "# TEMACD — historické quant metriky\n\n"
        f"Stav k {end.date().isoformat()}, počáteční equity USD {args.initial_equity:,.2f}; "
        f"náklady {args.transaction_cost_bps:g} bps za každou stranu.\n\n"
        "CAGR/Sharpe/Sortino/MaxDD jsou vypočítány z denní equity; Profit Factor je FIFO "
        "realizovaný P&L po započtení vstupních i výstupních nákladů. N/A není nula; "
        "zkontrolujte coverage. Výsledky jsou historická simulace, ne příslib budoucí výkonnosti.\n\n"
        + markdown + "\n",
        encoding="utf-8",
    )
    print(markdown)
    print(f"\nVýstupy uloženy do: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
