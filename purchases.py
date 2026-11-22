from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import get_db

purchases_bp = Blueprint("purchases", __name__)

def init_purchases_db():
    with get_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id BIGSERIAL PRIMARY KEY,
                product_id BIGINT NOT NULL,
                sku TEXT NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_cost DOUBLE PRECISION NOT NULL,
                total_amount DOUBLE PRECISION NOT NULL,
                supplier TEXT,
                invoice_number TEXT,
                purchased_at TEXT NOT NULL,
                notes TEXT
            )
        """)

init_purchases_db()

@purchases_bp.route("/purchases")
def purchases_page():
    with get_db() as con:
        rows = con.execute("SELECT * FROM purchases ORDER BY id DESC LIMIT 100").fetchall()
        summary = con.execute("""
            SELECT COUNT(*) AS count, COALESCE(SUM(quantity),0) AS units,
                   COALESCE(SUM(total_amount),0) AS total
            FROM purchases
        """).fetchone()
    return render_template("purchases.html", purchases=rows, summary=summary)

@purchases_bp.route("/purchases/new", methods=["GET", "POST"])
def new_purchase():
    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", ""))
            quantity = int(request.form.get("quantity", "0"))
            unit_cost = float(request.form.get("unit_cost", "0"))
            supplier = request.form.get("supplier", "").strip()
            invoice_number = request.form.get("invoice_number", "").strip()
            notes = request.form.get("notes", "").strip()
            if quantity <= 0:
                raise ValueError("Purchase quantity must be at least 1.")
            if unit_cost < 0:
                raise ValueError("Purchase cost cannot be negative.")
            now = datetime.now().isoformat(timespec="seconds")
            with get_db() as con:
                product = con.execute("SELECT * FROM products WHERE id=? FOR UPDATE", (product_id,)).fetchone()
                if not product:
                    raise ValueError("Selected product was not found.")
                old_stock = int(product["stock"])
                new_stock = old_stock + quantity
                total = round(quantity * unit_cost, 2)
                # Keep purchase cost as the weighted average of existing stock and this purchase.
                old_value = old_stock * float(product["purchase_cost"] or 0)
                average_cost = round((old_value + total) / new_stock, 2) if new_stock else unit_cost
                cur = con.execute("""
                    INSERT INTO purchases
                    (product_id,sku,product_name,quantity,unit_cost,total_amount,supplier,invoice_number,purchased_at,notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id
                """, (product_id, product["sku"], product["name"], quantity, unit_cost, total,
                      supplier or product["supplier"], invoice_number, now, notes))
                purchase_id = cur.fetchone()["id"]
                con.execute("""
                    UPDATE products SET stock=?, purchase_cost=?, supplier=CASE WHEN ?='' THEN supplier ELSE ? END,
                    updated_at=? WHERE id=?
                """, (new_stock, average_cost, supplier, supplier, now, product_id))
                con.execute("""
                    INSERT INTO stock_movements
                    (product_id,sku,movement_type,quantity,reference_type,reference_id,notes,created_at)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (product_id, product["sku"], "PURCHASE", quantity, "PURCHASE", purchase_id, notes, now))
            flash(f"Purchase recorded. {quantity} units added; new stock is {new_stock}.", "success")
            return redirect(url_for("purchases.purchases_page"))
        except (ValueError, TypeError) as e:
            flash(str(e) or "Please enter valid purchase details.", "error")
    with get_db() as con:
        products = con.execute("SELECT id,sku,name,stock,purchase_cost,supplier FROM products ORDER BY name").fetchall()
    return render_template("purchase_form.html", products=products)
