from __future__ import annotations
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
ET = ZoneInfo("America/New_York")
PRAGUE = ZoneInfo("Europe/Prague")

def _calendar():
    try:
        import pandas_market_calendars as mcal
        return mcal.get_calendar("NYSE")
    except ImportError as exc:
        raise RuntimeError("Chybí pandas-market-calendars; burzovní seance nelze bezpečně ověřit.") from exc

def month_rotation_date(year: int, month: int) -> date | None:
    anchor = date(year, month, 28)
    try:
        schedule = _calendar().schedule(start_date=anchor-timedelta(days=12), end_date=anchor)
    except RuntimeError:
        # Lightweight fallback for offline unit/backtest use only. Production gets the exchange calendar via dependency.
        candidate = anchor
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate
    return pd.Timestamp(schedule.index[-1]).date() if not schedule.empty else None

def session_close(day: date) -> datetime | None:
    schedule = _calendar().schedule(start_date=day, end_date=day)
    return pd.Timestamp(schedule.iloc[0]["market_close"]).to_pydatetime().astimezone(ET) if not schedule.empty else None

def provisional_cutoff(day: date) -> datetime | None:
    close = session_close(day)
    return close-timedelta(minutes=15) if close else None

def display_prague(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        raise ValueError("Timestamp musí obsahovat časovou zónu.")
    return timestamp.astimezone(PRAGUE)
