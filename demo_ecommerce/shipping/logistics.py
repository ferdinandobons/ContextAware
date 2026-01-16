class ShippingLogistics:
    """
    Calculates shipping costs and estimated delivery times.
    """
    def calculate_shipping(self, region: str, weight: float) -> float:
        """Calculates shipping cost based on weight and destination."""
        base_rate = 5.0
        if region == "international":
            base_rate = 20.0
        
        return base_rate + (weight * 0.5)

    def schedule_delivery(self, order_id: str):
        """Generates a tracking number and schedules pickup."""
        return f"TRACK_{order_id}_EXP"
