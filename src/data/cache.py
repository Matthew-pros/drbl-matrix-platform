from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(os.getenv("DRBL_CACHE_DIR", ".cache/market-data"))


def cache_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def read_cache(key: str) -> pd.DataFrame | None:
    path = CACHE_DIR / f"{key}.parquet"
    try:
        return pd.read_parquet(path) if path.exists() else None
    except (OSError, ValueError, ImportError):
        return None


def write_cache(key: str, data: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        data.to_parquet(CACHE_DIR / f"{key}.parquet")
    except (OSError, ValueError, ImportError):
        # Cache is an optimization, never the authoritative data source.
        pass
