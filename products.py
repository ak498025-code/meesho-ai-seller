import os
import sqlite3
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(APP_DIR, "seller_data.db"))
products_bp = Blueprint("products", __name__)

def product_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_products_db():
    with product_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                category TEXT,
                purchase_cost REAL NOT NULL DEFAULT 0,
                selling_price REAL NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                reorder_level INTEGER NOT NULL DEFAULT 0,
                supplier TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

init_products_db()

def read_product_form():
    sku = request.form.get("sku", "").strip()
    name = request.form.get("name", "").strip()
    if not sku or not name:
        raise ValueError("SKU and product name are required.")
    try:
        purchase_cost = float(request.form.get("purchase_cost", "0") or 0)
        selling_price = float(request.form.get("selling_price", "0") or 0)
        stock = int(request.form.get("stock", "0") or 0)
        reorder_level = int(request.form.get("reorder_level", "0") or 0)
    except (TypeError, ValueError):
        raise ValueError("Cost, price, stock and reorder level must be valid numbers.")
    if min(purchase_cost, selling_price, stock, reorder_level) < 0:
        raise ValueError("Values cannot be negative.")
    return {
        "sku": sku, "name": name, "category": request.form.get("category", "").strip(),
        "purchase_cost": purchase_cost, "selling_price": selling_price,
        "stock": stock, "reorder_level": reorder_level,
        "supplier": request.form.get("supplier", "").strip()
    }

@products_bp.route("/products")
def products_page():
    q = request.args.get("q", "").strip()
    with product_db() as con:
        if q:
            rows = con.execute(
                "SELECT * FROM products WHERE sku LIKE ? OR name LIKE ? OR category LIKE ? ORDER BY name",
                (f"%{q}%", f"%{q}%", f"%{q}%")
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM products ORDER BY name").fetchall()
    return render_template("products.html", products=rows, query=q)

@products_bp.route("/products/new", methods=["GET", "POST"])
def new_product():
    if request.method == "POST":
        try:
            p = read_product_form()
            now = datetime.now().isoformat(timespec="seconds")
            with product_db() as con:
                con.execute("""INSERT INTO products
                    (sku,name,category,purchase_cost,selling_price,stock,reorder_level,supplier,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (p["sku"],p["name"],p["category"],p["purchase_cost"],p["selling_price"],
                     p["stock"],p["reorder_level"],p["supplier"],now,now))
            flash("Product added successfully.", "success")
            return redirect(url_for("products.products_page"))
        except sqlite3.IntegrityError:
            flash("That SKU already exists. Use a unique SKU.", "error")
        except ValueError as e:
            flash(str(e), "error")
    return render_template("product_form.html", product=None, title="Add product")

@products_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    with product_db() as con:
        existing = con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not existing:
        flash("Product not found.", "error")
        return redirect(url_for("products.products_page"))
    if request.method == "POST":
        try:
            p = read_product_form()
            now = datetime.now().isoformat(timespec="seconds")
            with product_db() as con:
                con.execute("""UPDATE products SET sku=?,name=?,category=?,purchase_cost=?,selling_price=?,
                    stock=?,reorder_level=?,supplier=?,updated_at=? WHERE id=?""",
                    (p["sku"],p["name"],p["category"],p["purchase_cost"],p["selling_price"],
                     p["stock"],p["reorder_level"],p["supplier"],now,product_id))
            flash("Product updated successfully.", "success")
            return redirect(url_for("products.products_page"))
        except sqlite3.IntegrityError:
            flash("That SKU belongs to another product. Use a unique SKU.", "error")
        except ValueError as e:
            flash(str(e), "error")
    return render_template("product_form.html", product=existing, title="Edit product")

@products_bp.route("/products/<int:product_id>/delete", methods=["POST"])
def delete_product(product_id):
    with product_db() as con:
        con.execute("DELETE FROM products WHERE id=?", (product_id,))
    flash("Product deleted.", "success")
    return redirect(url_for("products.products_page"))
