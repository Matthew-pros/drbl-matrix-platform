from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd

from .base import DataProvider, MarketData
from ..indicators import normalize_ohlcv
from ..models import DataMode


class IBKRProvider(DataProvider):
    """Read-only historická data z TWS/IB Gateway; nepředpokládá live feed ani routing."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        self.port = int(port if port is not None else (os.getenv("IBKR_PORT") or "4002"))
        self.client_id = int(client_id if client_id is not None else (os.getenv("IBKR_CLIENT_ID") or "71"))
        self.timeout = timeout

    def get_daily_bars(self, ticker: str, start: str, end: str) -> MarketData:
        try:
            from ib_async import Contract, IB, Index, Stock, util
        except ImportError as exc:
            raise RuntimeError("IBKR provider vyžaduje ib_async a běžící IB Gateway/TWS.") from exc

        ib = IB()
        symbol = ticker.upper()
        is_vix = symbol in {"VIX", "^VIX"}
        is_crypto = symbol in {"BTC-USD", "ETH-USD", "SOL-USD"}
        try:
            ib.connect(self.host, self.port, clientId=self.client_id, readonly=True, timeout=self.timeout)
            if is_vix:
                contract = Index("VIX", "CBOE", "USD")
            elif is_crypto:
                crypto_symbol = symbol.split("-", maxsplit=1)[0]
                exchange = os.getenv("IBKR_CRYPTO_EXCHANGE", "PAXOS").upper()
                contract = Contract(symbol=crypto_symbol, secType="CRYPTO", exchange=exchange, currency="USD")
            else:
                contract = Stock(symbol, "SMART", "USD")

            qualified = ib.qualifyContracts(contract)
            if not qualified:
                raise RuntimeError(f"IBKR nemohl kvalifikovat {ticker}; zkontrolujte instrument, burzu a oprávnění.")

            start_ts = pd.Timestamp(start)
            end_ts = pd.Timestamp(end) - pd.Timedelta(days=1)  # end je v aplikaci exclusive
            years = max(1, min(30, int(((end_ts - start_ts).days + 364) // 365)))
            end_datetime = end_ts.strftime("%Y%m%d") + " 23:59:59 America/New_York"
            what_to_show = "AGGTRADES" if is_crypto else ("TRADES" if is_vix else "ADJUSTED_LAST")
            bars = ib.reqHistoricalData(
                qualified[0], endDateTime=end_datetime, durationStr=f"{years} Y",
                barSizeSetting="1 day", whatToShow=what_to_show,
                useRTH=not is_crypto, formatDate=1, keepUpToDate=False,
            )
            if not bars:
                raise RuntimeError(f"IBKR nevrátil historii {ticker}; zkontrolujte permissions a dostupnost historie.")
            frame = util.df(bars).rename(columns={
                "date": "Date", "open": "Open", "high": "High",
                "low": "Low", "close": "Close", "volume": "Volume",
            })
            frame = frame.set_index("Date")
            frame = normalize_ohlcv(frame)
            frame = frame.loc[(frame.index >= start_ts) & (frame.index < pd.Timestamp(end))]
            if frame.empty:
                raise RuntimeError(f"IBKR nevrátil použitelné bary {ticker} ve zvoleném období.")
            return MarketData(
                ticker, frame, f"IBKR historical ({what_to_show})", datetime.now(timezone.utc),
                frame.index[-1].to_pydatetime(), DataMode.HISTORICAL,
                "Historická data nejsou live/delayed stream. Rozsah historie závisí na IBKR, kontraktu a oprávněních. "
                "Akcie/ETF používají ADJUSTED_LAST; krypto AGGTRADES; VIX TRADES.",
            )
        except Exception as exc:
            raise RuntimeError(f"IBKR data selhala pro {ticker}: {exc}") from exc
        finally:
            if ib.isConnected():
                ib.disconnect()
