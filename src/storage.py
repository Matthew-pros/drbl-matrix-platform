from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/drbl.sqlite3")

def save_backtest(model: str, parameters: dict[str, Any], metrics: dict[str, Any], trades_json: str) -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.execute("CREATE TABLE IF NOT EXISTS backtests (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, model TEXT NOT NULL, parameters_json TEXT NOT NULL, metrics_json TEXT NOT NULL, trades_json TEXT NOT NULL)")
        cur = con.execute("INSERT INTO backtests(created_at, model, parameters_json, metrics_json, trades_json) VALUES(?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), model, json.dumps(parameters, default=str), json.dumps(metrics, default=str), trades_json))
        return int(cur.lastrowid)

def list_backtests(limit: int = 50) -> list[dict]:
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE IF NOT EXISTS backtests (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, model TEXT NOT NULL, parameters_json TEXT NOT NULL, metrics_json TEXT NOT NULL, trades_json TEXT NOT NULL)")
        return [dict(row) for row in con.execute("SELECT id, created_at, model, parameters_json, metrics_json FROM backtests ORDER BY id DESC LIMIT ?", (limit,))]
