from __future__ import annotations
import pandas as pd
TRADE_COLUMNS = ["signal_timestamp", "execution_timestamp", "ticker", "side", "quantity", "price", "target_usd", "delta_usd", "commission_usd", "slippage_usd", "other_fees_usd", "status", "reason", "notional_usd", "in_market"]
def trade_log_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)
