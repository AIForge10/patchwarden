"""A tiny throwaway buggy file for the day-one test (not the real demo app)."""
 
 
def parse_payment_response(response):
    """Return the charge id from a payment gateway response."""
    return response["data"]["charge_id"]
 
 
def checkout(order_id, response):
    charge_id = parse_payment_response(response)
    return {"order_id": order_id, "status": "completed", "charge_id": charge_id}