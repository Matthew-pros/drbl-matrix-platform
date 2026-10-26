#!/usr/bin/env python3
"""Walk-forward grid search for per-asset TEMACD indicator parameters.

Parameters are selected only on the in-sample window; a later out-of-sample window
is reported separately and never contributes to selection. The JSON output can be
loaded by the Streamlit TEMACD page or by either historical backtest runner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.strategies.temacd_grid_search import download_and_run_grid_search
from src.strategies.temacd_rotation import TEMACD_UNIVERSE


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward per-asset TEMACD grid search with a separate out-of-sample window."
    )
    parser.add_argument("--end", required=True, help="Poslední datum OOS okna, YYYY-MM-DD")
    parser.add_argument("--train-years", type=int, default=5)
    parser.add_argument("--oos-years", type=int, default=2)
    parser.add_argument("--warmup-years", type=int, default=3)
    parser.add_argument("--minimum-transactions", type=int, default=6)
    parser.add_argument("--initial-equity", type=float, default=100_000.0)
    parser.add_argument("--target-risk-pct", type=float, default=1.0)
    parser.add_argument("--max-weight-pct", type=float, default=35.0)
    parser.add_argument("--transaction-cost-bps", type=float, default=5.0)
    parser.add_argument("--tickers", nargs="+", choices=TEMACD_UNIVERSE, default=list(TEMACD_UNIVERSE))
    parser.add_argument("--output-dir", default="outputs/temacd_grid")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if min(args.train_years, args.oos_years, args.warmup_years) < 1:
        raise SystemExit("Train, OOS a warm-up období musí být alespoň jeden rok.")
    if args.initial_equity <= 0 or args.transaction_cost_bps < 0:
        raise SystemExit("Počáteční kapitál musí být kladný a transakční náklady nezáporné.")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    params, candidates, oos, metadata, warnings = download_and_run_grid_search(
        end=args.end,
        train_years=args.train_years,
        oos_years=args.oos_years,
        warmup_years=args.warmup_years,
        minimum_transactions=args.minimum_transactions,
        initial_equity=args.initial_equity,
        target_risk=args.target_risk_pct / 100.0,
        max_asset_weight=args.max_weight_pct / 100.0,
        transaction_cost_rate=args.transaction_cost_bps / 10_000.0,
        tickers=tuple(args.tickers),
    )

    (output / "asset_params.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    candidates.to_csv(output / "grid_candidates.csv", index=False)
    oos.to_csv(output / "out_of_sample_metrics.csv", index=False)
    (output / "download_warnings.txt").write_text("\n".join(warnings) + ("\n" if warnings else ""), encoding="utf-8")

    print(f"In-sample period: {metadata['train_start']} .. {metadata['train_end']}")
    print(f"Out-of-sample period: {metadata['out_of_sample_start']} .. {metadata['out_of_sample_end']}")
    print(oos.to_string(index=False))
    print(f"\nVybrané per-asset parametry: {output / 'asset_params.json'}")
    print(f"Všichni kandidáti: {output / 'grid_candidates.csv'}")
    print(f"OOS výsledky: {output / 'out_of_sample_metrics.csv'}")
    print("OOS metriky jsou pouze reporting; výběr parametrů se provádí výhradně z in-sample období.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
