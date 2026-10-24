from datetime import date
import pytest
from src.calendar import display_prague, provisional_cutoff
from zoneinfo import ZoneInfo
from datetime import datetime

def test_timezone_conversion_across_dst():
    winter=display_prague(datetime(2024,1,15,16,0,tzinfo=ZoneInfo("America/New_York")))
    summer=display_prague(datetime(2024,7,15,16,0,tzinfo=ZoneInfo("America/New_York")))
    assert winter.hour==22
    assert summer.hour==22

def test_provisional_cutoff_requires_calendar(monkeypatch):
    # A real NYSE calendar result should be exactly 15 min before a session close.
    pytest.importorskip("pandas_market_calendars")
    from src.calendar import session_close
    cutoff=provisional_cutoff(date(2024,7,3))
    close=session_close(date(2024,7,3))
    assert close is not None and cutoff is not None
    assert (close-cutoff).total_seconds()==900
