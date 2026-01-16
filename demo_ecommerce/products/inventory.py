class InventoryService:
    """
    Manages product stock levels.
    """
    def __init__(self):
        self._stock = {"sku_123": 100, "sku_456": 5, "sku_789": 0}

    def check_stock(self, sku: str, quantity: int) -> bool:
        """Verifies if enough stock is available for a requested SKU."""
        return self._stock.get(sku, 0) >= quantity

    def reserve_stock(self, sku: str, quantity: int):
        """Reserves stock for an order."""
        if not self.check_stock(sku, quantity):
            raise Exception("Insufficient stock")
        self._stock[sku] -= quantity

    def release_stock(self, sku: str, quantity: int):
        """Releases reserved stock back to inventory."""
        if sku in self._stock:
            self._stock[sku] += quantity
