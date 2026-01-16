class PaymentGateway:
    """
    Simulates interaction with external payment providers.
    """
    def process_payment(self, order_id: str, amount: float, method: str) -> bool:
        """
        Processes a payment for a specific order.
        """
        print(f"Processing payment of ${amount} for Order {order_id} via {method}")
        
        if method == "credit_card":
             # Simulate random success
            return True
        elif method == "paypal":
            return True
            
        return False
