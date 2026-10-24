from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
from ..config import BASE_TICKERS, LEVERAGED_TICKERS, CostConfig, StrategyConfig
from ..data.yfinance_provider import YahooFinanceProvider
from ..backtest.engine import BacktestResult, run_backtest
from ..models import ModelName

def default_data_symbols(config: StrategyConfig | None = None, include_leverage: bool = True) -> dict[str, str]:
    cfg = config or StrategyConfig()
    symbols = dict(cfg.base_tickers)
    if include_leverage:
        for asset, ticker in cfg.leveraged_tickers.items():
            if ticker:
                symbols[ticker] = ticker
        if cfg.gld_leveraged_ticker:
            symbols[cfg.gld_leveraged_ticker] = cfg.gld_leveraged_ticker
        if cfg.btc_leveraged_ticker:
            symbols[cfg.btc_leveraged_ticker] = cfg.btc_leveraged_ticker
    # Keep IBIT and BTC-USD separate logical assets, not synonymous instruments.
    return symbols

def get_prices(start: str, end: str | None = None, provider=None, config: StrategyConfig | None = None) -> dict[str, pd.DataFrame]:
    p = provider or YahooFinanceProvider()
    cfg = config or StrategyConfig()
    end_value = end or (date.today() + timedelta(days=1)).isoformat()
    result: dict[str, pd.DataFrame] = {}
    for key, ticker in default_data_symbols(cfg).items():
        try:
            result[key] = p.get_daily_bars(ticker, start, end_value).bars
        except Exception:
            # Missing instruments are reported by the UI; do not fabricate bars.
            continue
    return result

def run_model_backtest(data: dict[str, pd.DataFrame], model: ModelName, config: StrategyConfig, costs: CostConfig,
                       start: str | None = None, end: str | None = None,
                       gld_leveraged_ticker: str | None = None, btc_leveraged_ticker: str | None = None) -> BacktestResult:
    return run_backtest(data, model, config, costs, start, end, gld_leveraged_ticker, btc_leveraged_ticker)

def compare_models(data: dict[str, pd.DataFrame], config: StrategyConfig, costs: CostConfig,
                   start: str | None = None, end: str | None = None,
                   gld_leveraged_ticker: str | None = None, btc_leveraged_ticker: str | None = None) -> dict[str, BacktestResult]:
    return {m.value: run_model_backtest(data, m, config, costs, start, end, gld_leveraged_ticker, btc_leveraged_ticker) for m in ModelName}
