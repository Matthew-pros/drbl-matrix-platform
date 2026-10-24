from __future__ import annotations
import math
import numpy as np
import pandas as pd

def compute_metrics(equity: pd.Series, trades: pd.DataFrame | None = None, periods_per_year: int = 252) -> dict[str, float | int]:
    if equity is None or equity.empty:
        return {"total_return": float("nan"), "annualized_return": float("nan"), "volatility": float("nan"), "sharpe": float("nan"), "max_drawdown": float("nan"), "calmar": float("nan"), "profit_factor": float("nan"), "trades": 0, "turnover": 0.0, "time_in_market": 0.0, "commissions": 0.0, "slippage": 0.0}
    returns = equity.pct_change().dropna()
    total = float(equity.iloc[-1] / equity.iloc[0] - 1) if equity.iloc[0] else float("nan")
    periods = max(len(equity) - 1, 1)
    annual = float((equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / periods) - 1) if equity.iloc[-1] > 0 and equity.iloc[0] > 0 else float("nan")
    volatility = float(returns.std(ddof=1) * math.sqrt(periods_per_year)) if len(returns) > 1 else float("nan")
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(periods_per_year)) if len(returns) > 1 and returns.std(ddof=1) > 0 else float("nan")
    drawdown = equity / equity.cummax() - 1
    max_drawdown = float(abs(drawdown.min()))
    calmar = annual / max_drawdown if max_drawdown > 0 and np.isfinite(annual) else float("nan")
    trades = trades if trades is not None else pd.DataFrame()
    # Trade-log P&L pairs open/close fills; when that cannot be paired reliably, PF is explicitly NA.
    profit_factor = float("nan")
    if not trades.empty and {"ticker", "side", "quantity", "price"}.issubset(trades.columns):
        lots: dict[str, list[tuple[float, float]]] = {}
        realized: list[float] = []
        for row in trades.itertuples(index=False):
            ticker = str(row.ticker); side = str(row.side).upper(); qty = float(row.quantity); price = float(row.price)
            queue = lots.setdefault(ticker, [])
            if side == "BUY":
                queue.append((qty, price))
            elif side == "SELL":
                remaining = qty
                while remaining > 1e-10 and queue:
                    lot_qty, lot_price = queue[0]
                    matched = min(remaining, lot_qty)
                    realized.append((price - lot_price) * matched)
                    remaining -= matched; lot_qty -= matched
                    if lot_qty <= 1e-10: queue.pop(0)
                    else: queue[0] = (lot_qty, lot_price)
        gains = sum(p for p in realized if p > 0)
        losses = -sum(p for p in realized if p < 0)
        if losses > 0: profit_factor = gains / losses
        elif gains > 0: profit_factor = float("inf")
    return {
        "total_return": total, "annualized_return": annual, "volatility": volatility,
        "sharpe": sharpe, "max_drawdown": max_drawdown, "calmar": calmar,
        "profit_factor": profit_factor, "trades": int(len(trades)),
        "turnover": float(trades["notional_usd"].sum() / equity.mean()) if not trades.empty and "notional_usd" in trades else 0.0,
        "time_in_market": float(trades["in_market"].mean()) if not trades.empty and "in_market" in trades else 0.0,
        "commissions": float(trades["commission_usd"].sum()) if not trades.empty and "commission_usd" in trades else 0.0,
        "slippage": float(trades["slippage_usd"].sum()) if not trades.empty and "slippage_usd" in trades else 0.0,
    }

def monthly_returns(equity: pd.Series) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame()
    return equity.resample("ME").last().pct_change().to_frame("return").dropna()
