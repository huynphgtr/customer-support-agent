import json

def handler(event, context):
    order_id = event.get("order_id", "")
    amount = event.get("amount", 0)
    reason = event.get("reason", "")

    if not order_id or not amount or not reason:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing required fields: order_id, amount, reason"})
        }

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "approved",
            "order_id": order_id,
            "refund_amount": amount,
            "reason": reason,
            "message": f"Refund of ${amount} for order {order_id} has been processed successfully.",
            "transaction_id": f"TXN-{order_id.replace('ORD-', '')}R"
        })
    }
