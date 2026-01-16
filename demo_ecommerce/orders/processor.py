from datetime import datetime
from ..products.inventory import InventoryService
from ..products.pricing import PricingService

class OrderProcessor:
    """
    Orchestrates the order creation workflow.
    """
    def __init__(self):
        self.inventory = InventoryService()
        self.pricing = PricingService()
        self.orders = {}

    def create_order(self, user_id: str, sku: str, quantity: int, region: str) -> dict:
        """
        Creates an order if stock is available.
        Calculates total price including tax.
        """
        if not self.inventory.check_stock(sku, quantity):
            raise Exception("Out of stock")

        unit_price = self.pricing.get_price(sku)
        total_base = unit_price * quantity
        tax = self.pricing.calculate_tax(total_base, region)
        total = total_base + tax
        
        order_id = f"ord_{int(datetime.now().timestamp())}"
        
        # Reserve stock
        self.inventory.reserve_stock(sku, quantity)
        
        order = {
            "id": order_id,
            "user": user_id,
            "items": [{"sku": sku, "qty": quantity, "price": unit_price}],
            "total": total,
            "status": "created"
        }
        self.orders[order_id] = order
        return order
