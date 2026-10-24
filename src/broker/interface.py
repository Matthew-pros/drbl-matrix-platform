from __future__ import annotations
from abc import ABC, abstractmethod
from ..models import OrderPreview

class BrokerAdapter(ABC):
    @abstractmethod
    def preview_order(self, ticker: str, target_usd: float, current_usd: float, price: float) -> OrderPreview: ...

    @abstractmethod
    def submit_order(self, preview: OrderPreview, confirmed_by_user: bool = False) -> str:
        """Produkční implementace musí mít viditelné potvrzení a samostatný feature flag."""
        ...
