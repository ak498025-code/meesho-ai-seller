from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import get_db

sales_bp = Blueprint("sales", __name__)

def init_sales_db():
    with get_db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS sales (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT,
            sku TEXT NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price DOUBLE PRECISION NOT NULL,
            total_amount DOUBLE PRECISION NOT NULL,
            channel TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            sold_at TEXT NOT NULL,
            notes TEXT,
            cost_at_sale DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
            id BIGSERIAL PRIMARY KEY,
            product_id BIGINT NOT NULL,
            sku TEXT NOT NULL,
            movement_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            reference_type TEXT,
            reference_id BIGINT,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        """)

        con.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS cost_at_sale DOUBLE PRECISION")

init_sales_db()

@sales_bp.route("/sales")
def sales_page():
    with get_db() as con:
        rows = con.execute("SELECT * FROM sales ORDER BY id DESC LIMIT 100").fetchall()
        summary = con.execute("SELECT COUNT(*) AS count, COALESCE(SUM(total_amount),0) AS total, COALESCE(SUM(quantity),0) AS units FROM sales").fetchone()
    return render_template("sales.html", sales=rows, summary=summary)

@sales_bp.route("/sales/new", methods=["GET", "POST"])
def new_sale():
    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", ""))
            quantity = int(request.form.get("quantity", "0"))
            unit_price = float(request.form.get("unit_price", "0"))
            channel = request.form.get("channel", "Offline Shop").strip()
            payment_method = request.form.get("payment_method", "Cash").strip()
            notes = request.form.get("notes", "").strip()
            if quantity <= 0:
                raise ValueError("Quantity must be at least 1.")
            if unit_price < 0:
                raise ValueError("Selling price cannot be negative.")
            if channel not in {"Offline Shop", "Meesho", "Amazon", "Flipkart", "Other"}:
                raise ValueError("Choose a valid sales channel.")
            if payment_method not in {"Cash", "UPI", "Card", "Bank Transfer", "Marketplace Settlement", "Other"}:
                raise ValueError("Choose a valid payment method.")
            now = datetime.now().isoformat(timespec="seconds")
            with get_db() as con:
                product = con.execute("SELECT * FROM products WHERE id=? FOR UPDATE", (product_id,)).fetchone()
                if not product:
                    raise ValueError("Selected product was not found.")
                if product["stock"] < quantity:
                    raise ValueError(f"Not enough stock. Available quantity: {product['stock']}.")
                total = round(quantity * unit_price, 2)
                cur = con.execute("""INSERT INTO sales
                    (product_id,sku,product_name,quantity,unit_price,total_amount,channel,payment_method,sold_at,notes,cost_at_sale)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                    (product_id,product["sku"],product["name"],quantity,unit_price,total,channel,payment_method,now,notes,float(product["purchase_cost"] or 0)))
                sale_id = cur.fetchone()["id"]
                con.execute("UPDATE products SET stock=stock-?, updated_at=? WHERE id=?", (quantity,now,product_id))
                con.execute("""INSERT INTO stock_movements
                    (product_id,sku,movement_type,quantity,reference_type,reference_id,notes,created_at)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (product_id,product["sku"],"SALE",-quantity,"SALE",sale_id,notes,now))
            flash(f"Sale recorded. ₹{total:,.2f} collected/recorded and stock updated.", "success")
            return redirect(url_for("sales.sales_page"))
        except ValueError as e:
            flash(str(e), "error")
    with get_db() as con:
        products = con.execute("SELECT id,sku,name,stock,selling_price FROM products ORDER BY name").fetchall()
    return render_template("sale_form.html", products=products)
