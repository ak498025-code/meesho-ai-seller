from flask import Blueprint, render_template, request
from database import get_db

unified_orders_bp = Blueprint("unified_orders", __name__)
MARKETPLACES = ["Meesho", "Amazon", "Flipkart", "Offline Shop", "Other"]

@unified_orders_bp.route("/unified-orders")
def unified_orders_page():
    marketplace = request.args.get("marketplace", "").strip()
    if marketplace not in MARKETPLACES:
        marketplace = ""
    with get_db() as con:
        if marketplace in ("Meesho", "Amazon", "Flipkart"):
            imported = con.execute("""SELECT id, marketplace, order_id, sub_order_id, sku, product_name, quantity, order_status, order_date, sale_amount FROM orders WHERE marketplace=? ORDER BY id DESC LIMIT 500""", (marketplace,)).fetchall()
        elif not marketplace:
            imported = con.execute("""SELECT id, marketplace, order_id, sub_order_id, sku, product_name, quantity, order_status, order_date, sale_amount FROM orders ORDER BY id DESC LIMIT 500""").fetchall()
        else:
            imported = []
        if marketplace:
            managed = con.execute("""SELECT id, channel, order_ref, sku, product_name, quantity, selling_price, status, created_at FROM managed_orders WHERE channel=? ORDER BY id DESC LIMIT 500""", (marketplace,)).fetchall()
        else:
            managed = con.execute("""SELECT id, channel, order_ref, sku, product_name, quantity, selling_price, status, created_at FROM managed_orders ORDER BY id DESC LIMIT 500""").fetchall()

    rows = []
    for o in imported:
        rows.append({"source":"Imported report", "marketplace":o["marketplace"] or "Meesho",
            "order_id":o["sub_order_id"] or o["order_id"] or "—", "parent_id":o["order_id"] or "—",
            "sku":o["sku"] or "—", "product":o["product_name"] or "—", "quantity":o["quantity"],
            "status":o["order_status"] or "Not provided", "date":o["order_date"] or "—", "amount":o["sale_amount"]})
    for o in managed:
        rows.append({"source":"Managed order", "marketplace":o["channel"], "order_id":o["order_ref"],
            "parent_id":"—", "sku":o["sku"], "product":o["product_name"], "quantity":o["quantity"],
            "status":o["status"], "date":o["created_at"],
            "amount":float(o["selling_price"] or 0) * int(o["quantity"] or 0)})
    rows.sort(key=lambda r: str(r["date"]), reverse=True)
    rows = rows[:500]
    imported_count = sum(1 for r in rows if r["source"] == "Imported report")
    managed_count = len(rows) - imported_count
    visible_amount = sum(r["amount"] for r in rows if r["amount"] is not None)
    return render_template("unified_orders.html", orders=rows, marketplaces=MARKETPLACES,
        selected_marketplace=marketplace, total=len(rows), imported_count=imported_count,
        managed_count=managed_count, visible_amount=visible_amount)
