from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import get_db

orders_bp = Blueprint("order_manager", __name__)

STATUSES = ["New", "Packed", "Shipped", "Delivered", "Cancelled", "Returned"]
CHANNELS = ["Meesho", "Amazon", "Flipkart", "Offline Shop", "Other"]

def init_orders_db():
    with get_db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS managed_orders (
            id BIGSERIAL PRIMARY KEY,
            order_ref TEXT NOT NULL UNIQUE,
            channel TEXT NOT NULL,
            product_id BIGINT NOT NULL,
            sku TEXT NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            selling_price DOUBLE PRECISION NOT NULL,
            cost_at_order DOUBLE PRECISION NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'New',
            return_reason TEXT,
            stock_deducted BOOLEAN NOT NULL DEFAULT TRUE,
            stock_restored BOOLEAN NOT NULL DEFAULT FALSE,
            return_to_stock BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_managed_orders_created ON managed_orders(created_at DESC)")
init_orders_db()

@orders_bp.route("/orders")
def orders_page():
    status = request.args.get("status", "").strip()
    with get_db() as con:
        if status in STATUSES:
            rows = con.execute("SELECT * FROM managed_orders WHERE status=? ORDER BY id DESC LIMIT 300", (status,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM managed_orders ORDER BY id DESC LIMIT 300").fetchall()
        summary = con.execute("""SELECT COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status='New') AS new_count,
            COUNT(*) FILTER (WHERE status='Shipped') AS shipped_count,
            COUNT(*) FILTER (WHERE status='Delivered') AS delivered_count,
            COUNT(*) FILTER (WHERE status IN ('Cancelled','Returned')) AS issue_count
            FROM managed_orders""").fetchone()
    return render_template("orders.html", orders=rows, summary=summary, statuses=STATUSES, selected_status=status)

@orders_bp.route("/orders/new", methods=["GET", "POST"])
def new_order():
    if request.method == "POST":
        try:
            order_ref = request.form.get("order_ref", "").strip()
            channel = request.form.get("channel", "")
            product_id = int(request.form.get("product_id", "0"))
            quantity = int(request.form.get("quantity", "0"))
            selling_price = float(request.form.get("selling_price", "0"))
            notes = request.form.get("notes", "").strip()
            if not order_ref: raise ValueError("Order ID is required.")
            if channel not in CHANNELS: raise ValueError("Choose a valid sales channel.")
            if quantity < 1 or selling_price < 0: raise ValueError("Quantity must be at least 1 and price cannot be negative.")
            now = datetime.now().isoformat(timespec="seconds")
            with get_db() as con:
                product = con.execute("SELECT * FROM products WHERE id=? FOR UPDATE", (product_id,)).fetchone()
                if not product: raise ValueError("Select a valid product.")
                if int(product["stock"]) < quantity:
                    raise ValueError(f"Insufficient stock. Available: {product['stock']}.")
                con.execute("""INSERT INTO managed_orders
                    (order_ref,channel,product_id,sku,product_name,quantity,selling_price,cost_at_order,status,
                     stock_deducted,stock_restored,notes,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?, 'New', TRUE, FALSE, ?,?,?)""",
                    (order_ref,channel,product_id,product["sku"],product["name"],quantity,selling_price,
                     float(product["purchase_cost"] or 0),notes,now,now))
                con.execute("UPDATE products SET stock=stock-?,updated_at=? WHERE id=?", (quantity,now,product_id))
                con.execute("""INSERT INTO stock_movements
                    (product_id,sku,movement_type,quantity,reference_type,reference_id,notes,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (product_id,product["sku"],"ORDER",-quantity,"MANAGED_ORDER",None,"Order "+order_ref,now))
            flash("Order created and stock reserved successfully.", "success")
            return redirect(url_for("order_manager.orders_page"))
        except ValueError as e:
            flash(str(e), "error")
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                flash("This order ID already exists. Use a unique order ID.", "error")
            else:
                raise
    with get_db() as con:
        products = con.execute("SELECT id,sku,name,stock,purchase_cost,selling_price FROM products ORDER BY name").fetchall()
    return render_template("order_form.html", products=products, channels=CHANNELS)

@orders_bp.route("/orders/<int:order_id>/update", methods=["POST"])
def update_order(order_id):
    status = request.form.get("status", "")
    reason = request.form.get("return_reason", "").strip()
    return_to_stock = request.form.get("return_to_stock") == "yes"
    if status not in STATUSES:
        flash("Invalid order status.", "error")
        return redirect(url_for("order_manager.orders_page"))
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as con:
        order = con.execute("SELECT * FROM managed_orders WHERE id=? FOR UPDATE", (order_id,)).fetchone()
        if not order:
            flash("Order not found.", "error")
            return redirect(url_for("order_manager.orders_page"))
        if order["stock_restored"]:
            flash("This order's stock was already restored. No duplicate stock adjustment was made.", "warning")
            return redirect(url_for("order_manager.orders_page"))
        if status in ("Cancelled", "Returned") and order["stock_deducted"]:
            should_restore = status == "Cancelled" or (status == "Returned" and return_to_stock)
            if should_restore:
                con.execute("UPDATE products SET stock=stock+?,updated_at=? WHERE id=?", (order["quantity"],now,order["product_id"]))
                con.execute("""INSERT INTO stock_movements
                    (product_id,sku,movement_type,quantity,reference_type,reference_id,notes,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (order["product_id"],order["sku"],"ORDER_REVERSAL",order["quantity"],"MANAGED_ORDER",order_id,
                     "Stock restored for "+status+" order "+order["order_ref"],now))
                con.execute("UPDATE managed_orders SET stock_restored=TRUE,return_to_stock=? WHERE id=?", (should_restore,order_id))
        con.execute("""UPDATE managed_orders SET status=?,return_reason=?,return_to_stock=?,updated_at=? WHERE id=?""",
                    (status,reason,return_to_stock,now,order_id))
    flash("Order status updated.", "success")
    return redirect(url_for("order_manager.orders_page"))
