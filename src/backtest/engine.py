from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from ..calendar import month_rotation_date
from ..config import CostConfig, StrategyConfig
from ..costs import estimate_costs
from ..indicators import normalize_ohlcv
from ..models import DataMode, ModelName, PortfolioState, Position
from ..strategies.alm import generate_alm_recommendation
from ..strategies.combined import generate_combined_recommendation
from ..strategies.drbl_matrix import ASSETS, generate_matrix_recommendation, process_monthly_rotation
from .metrics import compute_metrics, monthly_returns
from .trade_log import trade_log_frame

@dataclass
class BacktestResult:
    model: str
    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict
    warnings: list[str]
    costs: dict
    monthly_returns: pd.DataFrame
    drawdown: pd.Series

def run_backtest(
    data: dict[str, pd.DataFrame], model: ModelName, config: StrategyConfig,
    costs: CostConfig, start: str | None = None, end: str | None = None,
    gld_leveraged_ticker: str | None = None, btc_leveraged_ticker: str | None = None,
) -> BacktestResult:
    """Signál po Close(t) -> simulovaný fill na Open(t+1). Žádný bar budoucnosti se nedostane do signálu."""
    normalized = {key: normalize_ohlcv(frame) for key, frame in data.items() if frame is not None and not frame.empty}
    if not normalized:
        raise ValueError("Backtest nelze spustit: nejsou dostupná OHLCV data.")
    asset_dates = normalized.get("SPY")
    if asset_dates is None:
        raise ValueError("Benchmarkový kalendář SPY chybí v datové sadě.")
    full_dates = pd.DatetimeIndex(sorted(set().union(*(set(frame.index) for frame in normalized.values()))))
    if len(full_dates) < 254:
        raise ValueError("Nedostatečný warm-up: vyžadováno nejméně 253 historických barů.")
    start_ts = pd.Timestamp(start) if start else full_dates[0]
    end_ts = pd.Timestamp(end) if end else full_dates[-1]
    dates = full_dates[full_dates <= end_ts]
    eval_dates = dates[dates >= start_ts]
    if len(eval_dates) < 2:
        raise ValueError("Vybrané období obsahuje méně než dva obchodní bary.")
    if dates[0] > start_ts and int((full_dates < start_ts).sum()) < 252:
        raise ValueError("Před začátkem období není dost historie pro indikátory; načtěte delší historii.")

    cash = float(config.initial_equity)
    holdings: dict[str, dict[str, float]] = {}
    selected_asset: str | None = None
    last_rotation_month: str | None = None
    alm_levels_filled: set[str] = set()
    alm_first_fill_confirmed = False
    equity_rows: list[tuple[pd.Timestamp, float]] = []
    log: list[dict] = []
    warnings: list[str] = []

    for index, signal_date in enumerate(dates[:-1]):
        next_date = dates[index + 1]
        # Current close is used for signal and marking only; fill is always at next_date Open.
        signal_closes = {
            ticker: float(frame.loc[signal_date, "Close"])
            for ticker, frame in normalized.items() if signal_date in frame.index
        }
        for ticker, holding in holdings.items():
            if ticker in signal_closes:
                holding["last_price"] = signal_closes[ticker]
        if costs.cash_interest_annual > 0:
            cash *= (1.0 + costs.cash_interest_annual) ** (1.0 / 252.0)
        equity_at_close = cash + sum(h["quantity"] * h["last_price"] for h in holdings.values())
        if signal_date >= start_ts:
            equity_rows.append((signal_date, equity_at_close))

        # For DRBL, initialize the leader at the first valid scheduled session, then rotate only on the planned monthly event.
        if model in {ModelName.DRBL_MATRIX, ModelName.COMBINED} and signal_date <= end_ts:
            scheduled = month_rotation_date(signal_date.year, signal_date.month)
            month = signal_date.strftime("%Y-%m")
            rotation_enabled = model == ModelName.DRBL_MATRIX or (alm_first_fill_confirmed and bool(holdings))
            # Initial leader is selected at the first date where all lookback scores exist;
            # subsequent changes only occur on the exchange-calendar scheduled date.
            initial_scores_ready = selected_asset is None and int((dates <= signal_date).sum()) >= 253
            should_rotate = (initial_scores_ready and last_rotation_month is None) or (scheduled is not None and signal_date.date() >= scheduled and last_rotation_month != month)
            if rotation_enabled and should_rotate:
                state_for_rotation = PortfolioState(model, cash, _positions(holdings, signal_closes), selected_asset=selected_asset, last_rotation_month=last_rotation_month)
                history = {key: frame.loc[:signal_date] for key, frame in normalized.items() if key in ASSETS}
                # Avoid selecting a different asset again on every day before the first scheduled event.
                new_asset, changed, scores = process_monthly_rotation(history, state_for_rotation, config, signal_date.date().isoformat())
                selected_asset = state_for_rotation.selected_asset
                last_rotation_month = state_for_rotation.last_rotation_month
                if not scores:
                    warnings.append(f"{signal_date.date()}: měsíční rotace odložena, momentum skóre nejsou dostupná.")
                elif changed:
                    warnings.append(f"{signal_date.date()}: rotace {new_asset} (skóre {scores.get(new_asset, float('nan')):.3f}).")

        # Do not generate or execute trades before requested evaluation start. Rotation state is still warmed above.
        if signal_date < start_ts or next_date > end_ts:
            continue
        history = {ticker: frame.loc[:signal_date] for ticker, frame in normalized.items() if (frame.index <= signal_date).any()}
        marks = {ticker: float(frame.loc[signal_date, "Close"]) for ticker, frame in normalized.items() if signal_date in frame.index}
        state = PortfolioState(
            model, cash, _positions(holdings, marks),
            alm_completed=alm_first_fill_confirmed, alm_fill_confirmed=alm_first_fill_confirmed,
            selected_asset=selected_asset, last_rotation_month=last_rotation_month,
            alm_levels_filled=set(alm_levels_filled),
        )
        try:
            if model == ModelName.ALM:
                rec = generate_alm_recommendation(history, state, config)
            elif model == ModelName.DRBL_MATRIX:
                rec = generate_matrix_recommendation(history, state, config, source="Backtest", data_mode=DataMode.HISTORICAL,
                    gld_leveraged_ticker=gld_leveraged_ticker, btc_leveraged_ticker=btc_leveraged_ticker)
            else:
                rec = generate_combined_recommendation(history, state, config, source="Backtest", data_mode=DataMode.HISTORICAL,
                    gld_leveraged_ticker=gld_leveraged_ticker, btc_leveraged_ticker=btc_leveraged_ticker)
        except Exception as exc:
            warnings.append(f"{signal_date}: výpočet signálu přeskočen ({exc})")
            continue
        if not rec.available:
            warnings.append(f"{signal_date}: {rec.reason}")
            continue

        # Target map defaults to keeping all existing holdings, unless explicit exit/rotation is requested.
        current_targets = {ticker: holding["quantity"] * marks.get(ticker, holding["last_price"]) for ticker, holding in holdings.items()}
        if rec.action in {"HOLD", "UNAVAILABLE", "REVIEW", "CONFIGURATION_REQUIRED", "ROTATION_REQUIRED"}:
            targets = current_targets
        elif rec.action == "HOLD_CASH":
            targets = {ticker: 0.0 for ticker in holdings}
        elif rec.action in {"SELL_ALL", "ROTATE_POSITION"}:
            targets = {ticker: 0.0 for ticker in holdings}
        elif rec.ticker and rec.action in {"BUY", "BUY_OR_REBALANCE"}:
            targets = {ticker: 0.0 for ticker in holdings}
            targets[rec.ticker] = max(0.0, rec.target_usd)
        else:
            targets = current_targets

        # Multiple existing assets should be closed if target matrix requires cash/rotation.
        for ticker in sorted(set(holdings) | set(targets)):
            target = float(targets.get(ticker, 0.0))
            current_qty = holdings.get(ticker, {}).get("quantity", 0.0)
            mark_price = marks.get(ticker, holdings.get(ticker, {}).get("last_price", 0.0))
            current_value = current_qty * mark_price
            delta = target - current_value
            if abs(delta) < 1.0:
                continue
            next_frame = normalized.get(ticker)
            if next_frame is None or next_date not in next_frame.index:
                warnings.append(f"{signal_date}: chybí Open pro exekuci {ticker} dne {next_date.date()}.")
                continue
            open_price = float(next_frame.loc[next_date, "Open"])
            if open_price <= 0:
                warnings.append(f"{signal_date}: neplatný Open pro {ticker}; obchod přeskočen.")
                continue
            side = "BUY" if delta > 0 else "SELL"
            qty = abs(delta) / open_price
            if not costs.fractional_shares:
                qty = float(int(qty))
            if qty <= 0:
                continue
            estimate = estimate_costs(qty, open_price, side.lower(), costs)
            fill_price = estimate.fill_price
            commission, other = estimate.commission_usd, estimate.other_fees_usd
            notional = qty * fill_price
            if side == "BUY":
                # Reserve at least 15% of equity for Matrix/Combined; ALM uses the same reserve cap.
                equity_before = cash + sum(h["quantity"] * h["last_price"] for h in holdings.values())
                desired_reserve = max(0.0, equity_before * config.alm_cash_reserve)
                max_spend = max(0.0, cash - desired_reserve)
                spend = notional + commission + other
                if spend > max_spend and spend > 0:
                    qty *= max_spend / spend
                    if not costs.fractional_shares:
                        qty = float(int(qty))
                    if qty <= 0:
                        continue
                    estimate = estimate_costs(qty, open_price, "buy", costs)
                    fill_price, commission, other = estimate.fill_price, estimate.commission_usd, estimate.other_fees_usd
                    notional = qty * fill_price
                    spend = notional + commission + other
                if spend > cash + 1e-6:
                    continue
                cash -= spend
                holdings.setdefault(ticker, {"quantity": 0.0, "last_price": fill_price})["quantity"] += qty
                pending_tier = rec.indicators.get("alm_tier") if isinstance(rec.indicators, dict) else None
                if pending_tier and model == ModelName.ALM:
                    alm_levels_filled.add(str(pending_tier))
                if model == ModelName.COMBINED and not alm_first_fill_confirmed:
                    alm_first_fill_confirmed = True
                    selected_asset = ticker if ticker in ASSETS else selected_asset
            else:
                qty = min(qty, current_qty)
                if qty <= 0:
                    continue
                estimate = estimate_costs(qty, open_price, "sell", costs)
                fill_price, commission, other = estimate.fill_price, estimate.commission_usd, estimate.other_fees_usd
                notional = qty * fill_price
                cash += notional - commission - other
                holdings[ticker]["quantity"] -= qty
                if holdings[ticker]["quantity"] <= 1e-8:
                    holdings.pop(ticker, None)
            holdings.setdefault(ticker, {"quantity": 0.0, "last_price": fill_price})["last_price"] = fill_price
            log.append({
                "signal_timestamp": signal_date, "execution_timestamp": next_date, "ticker": ticker,
                "side": side, "quantity": qty, "price": fill_price, "target_usd": target,
                "delta_usd": delta, "commission_usd": commission, "slippage_usd": estimate.slippage_usd,
                "other_fees_usd": other, "status": "SIMULATED_FILLED", "reason": rec.reason,
                "notional_usd": notional, "in_market": bool(holdings),
            })

    # Mark the final Close for reporting; do not fabricate an execution on it.
    final_date = dates[-1]
    final_marks = {ticker: float(frame.loc[final_date, "Close"]) for ticker, frame in normalized.items() if final_date in frame.index}
    for ticker, holding in holdings.items():
        if ticker in final_marks:
            holding["last_price"] = final_marks[ticker]
    final_equity = cash + sum(h["quantity"] * h["last_price"] for h in holdings.values())
    if final_date >= start_ts and (not equity_rows or equity_rows[-1][0] != final_date):
        equity_rows.append((final_date, final_equity))
    equity_series = pd.Series(dict(equity_rows), dtype=float).sort_index()
    if equity_series.empty:
        last_date = eval_dates[0]
        equity_series = pd.Series([config.initial_equity], index=pd.DatetimeIndex([last_date]), name=model.value)
    trades = trade_log_frame(log)
    metrics = compute_metrics(equity_series, trades)
    cost_summary = {
        "commissions": float(trades["commission_usd"].sum()) if not trades.empty else 0.0,
        "slippage": float(trades["slippage_usd"].sum()) if not trades.empty else 0.0,
        "other_fees": float(trades["other_fees_usd"].sum()) if not trades.empty else 0.0,
    }
    drawdown = equity_series / equity_series.cummax() - 1 if not equity_series.empty else pd.Series(dtype=float)
    return BacktestResult(model.value, equity_series, trades, metrics, list(dict.fromkeys(warnings)), cost_summary, monthly_returns(equity_series), drawdown)

def _positions(holdings: dict[str, dict[str, float]], prices: dict[str, float]) -> dict[str, Position]:
    result: dict[str, Position] = {}
    for ticker, holding in holdings.items():
        price = float(prices.get(ticker, holding.get("last_price", 0.0)))
        result[ticker] = Position(ticker, holding["quantity"] * price, holding["quantity"], price)
    return result
