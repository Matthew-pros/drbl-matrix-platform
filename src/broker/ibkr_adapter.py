from __future__ import annotations
import os
from ..config import CostConfig
from ..costs import preview_quantity
from ..models import OrderPreview
from .interface import BrokerAdapter

class IBKROrderAdapter(BrokerAdapter):
    def __init__(self, cost_config: CostConfig, fractional_allowed: bool = True, exchange: str = "SMART") -> None:
        self.cost_config = cost_config
        self.fractional_allowed = fractional_allowed
        self.exchange = exchange

    def preview_order(self, ticker: str, target_usd: float, current_usd: float, price: float) -> OrderPreview:
        if not ticker or price <= 0 or target_usd < 0 or current_usd < 0:
            raise ValueError("Neplatný ticker, cena nebo pozice.")
        cfg = self.cost_config
        if cfg.fractional_shares != self.fractional_allowed:
            from dataclasses import replace
            cfg = replace(cfg, fractional_shares=self.fractional_allowed)
        side, qty, delta, costs = preview_quantity(target_usd, current_usd, price, cfg)
        return OrderPreview(ticker, side, target_usd, delta, price, qty, max(0.0, -delta - costs.commission_usd), costs.commission_usd, costs.slippage_usd, exchange=self.exchange)

    def submit_order(self, preview: OrderPreview, confirmed_by_user: bool = False) -> str:
        enabled = os.getenv("ENABLE_ORDER_SUBMISSION", "false").lower() == "true"
        if not enabled:
            return "BLOCKED: ENABLE_ORDER_SUBMISSION=false; odeslání příkazů není povoleno."
        if not confirmed_by_user:
            return "BLOCKED: vyžaduje viditelné uživatelské potvrzení."
        # V této verzi je odesílání úmyslně vypnuté; implementován je pouze order preview/read-only.
        return "NOT_IMPLEMENTED: tato verze nepodporuje odeslání příkazu; použijte pouze náhled."
