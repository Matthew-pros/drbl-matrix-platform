from __future__ import annotations

import math

import pandas as pd

from scripts.run_temacd_period_table import _profit_factor_fifo


def test_profit_factor_fifo_includes_entry_and_exit_costs() -> None:
    trades = pd.DataFrame([
        {"execution_timestamp": "2024-01-02", "ticker": "TQQQ", "side": "BUY", "quantity": 10,
         "notional_usd": 1000, "commission_usd": 0.50},
        {"execution_timestamp": "2024-01-03", "ticker": "TQQQ", "side": "SELL", "quantity": 10,
         "notional_usd": 1100, "commission_usd": 0.55},
        {"execution_timestamp": "2024-01-04", "ticker": "SPY", "side": "BUY", "quantity": 10,
         "notional_usd": 1000, "commission_usd": 0.50},
        {"execution_timestamp": "2024-01-05", "ticker": "SPY", "side": "SELL", "quantity": 10,
         "notional_usd": 900, "commission_usd": 0.45},
    ])
    result = _profit_factor_fifo(trades)
    expected_profit = 1100 - 0.55 - (1000 + 0.50)
    expected_loss = (1000 + 0.50) - (900 - 0.45)
    assert math.isclose(result, expected_profit / expected_loss, rel_tol=1e-12)


def test_profit_factor_without_closed_trades_is_nan() -> None:
    trades = pd.DataFrame(columns=[
        "execution_timestamp", "ticker", "side", "quantity", "notional_usd", "commission_usd"
    ])
    assert math.isnan(_profit_factor_fifo(trades))
