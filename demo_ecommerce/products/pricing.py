class PricingService:
    """
    Calculates product prices including dynamic discounts and tax.
    """
    def __init__(self):
        self._base_prices = {"sku_123": 10.0, "sku_456": 50.0, "sku_789": 100.0}

    def get_price(self, sku: str, user_tier: str = "standard") -> float:
        """Calculates the price for a specific user tier."""
        base = self._base_prices.get(sku, 0.0)
        
        if user_tier == "vip":
            return base * 0.90
        elif user_tier == "wholesale":
            return base * 0.75
        
        return base

    def calculate_tax(self, amount: float, region: str) -> float:
        """Calculates tax based on region."""
        if region == "EU":
            return amount * 0.22
        elif region == "US":
            return amount * 0.08
        return 0.0
