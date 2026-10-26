from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(os.getenv("DRBL_CACHE_DIR", ".cache/market-data"))


def cache_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def read_cache(key: str, max_age_seconds: float = 6 * 60 * 60) -> pd.DataFrame | None:
    """Read only a recent cache entry; old market data is refetched instead of being silently reused."""
    path = CACHE_DIR / f"{key}.parquet"
    try:
        if not path.exists():
            return None
        if max_age_seconds >= 0 and time.time() - path.stat().st_mtime > max_age_seconds:
            return None
        return pd.read_parquet(path)
    except (OSError, ValueError, ImportError):
        return None


def write_cache(key: str, data: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data.to_parquet(CACHE_DIR / f"{key}.parquet")
    except (OSError, ValueError, ImportError):
        # Cache is an optimization, never the authoritative data source.
        pass
