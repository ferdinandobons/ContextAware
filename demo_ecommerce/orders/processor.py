from datetime import datetime
from products.inventory import InventoryService
from products.pricing import PricingService

class OrderProcessor:
    """Orchestrates the order creation workflow."""
    
    def __init__(self):
        self.inventory = InventoryService()
        self.pricing = PricingService()
        
    def create_order(self, user_id: str, items: list) -> dict:
        """
        Creates an order for the user.
        Steps:
        1. Check stock
        2. Calculate price
        3. Reserve stock
        4. Create order record
        """
        # FRESHNESS TEST: This comment should appear in retrieval!
        if not self.inventory.check_stock(items):
            raise ValueError("Out of stock")
            
        total = self.pricing.calculate_total(items, user_id)
        order_id = f"ORD-{datetime.now().timestamp()}"
        
        self.inventory.reserve(items)
        
        return {
            "id": order_id,
            "user_id": user_id,
            "total": total,
            "items": items,
            "status": "CREATED"
        }
