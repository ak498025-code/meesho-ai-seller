from flask import Blueprint, render_template
from database import get_db

analytics_bp = Blueprint("analytics", __name__)

def init_analytics_db():
    with get_db() as con:
        con.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS cost_at_sale DOUBLE PRECISION")
        # Existing sales predate cost snapshots. Backfill from the current average product cost;
        # these historical figures are estimates and are labelled as such in the report.
        con.execute("""
            UPDATE sales s
            SET cost_at_sale = COALESCE(p.purchase_cost, 0)
            FROM products p
            WHERE s.cost_at_sale IS NULL AND s.product_id = p.id
        """)

init_analytics_db()

@analytics_bp.route("/analytics")
def analytics_page():
    with get_db() as con:
        summary = con.execute("""
            SELECT COUNT(*) AS orders,
                   COALESCE(SUM(quantity),0) AS units,
                   COALESCE(SUM(total_amount),0) AS revenue,
                   COALESCE(SUM(quantity * COALESCE(cost_at_sale,0)),0) AS cogs,
                   COALESCE(SUM(total_amount - quantity * COALESCE(cost_at_sale,0)),0) AS gross_profit,
                   COUNT(*) FILTER (WHERE cost_at_sale IS NULL) AS missing_cost_rows
            FROM sales
        """).fetchone()
        daily = con.execute("""
            SELECT sold_at::date AS day, SUM(total_amount) AS revenue,
                   SUM(quantity * COALESCE(cost_at_sale,0)) AS cogs,
                   SUM(total_amount - quantity * COALESCE(cost_at_sale,0)) AS gross_profit
            FROM sales
            WHERE sold_at::date >= CURRENT_DATE - INTERVAL '29 days'
            GROUP BY sold_at::date ORDER BY day
        """).fetchall()
        monthly = con.execute("""
            SELECT TO_CHAR(sold_at::date, 'YYYY-MM') AS month,
                   SUM(total_amount) AS revenue,
                   SUM(total_amount - quantity * COALESCE(cost_at_sale,0)) AS gross_profit
            FROM sales GROUP BY TO_CHAR(sold_at::date, 'YYYY-MM')
            ORDER BY month DESC LIMIT 12
        """).fetchall()
        by_channel = con.execute("""
            SELECT channel, COUNT(*) AS orders, SUM(quantity) AS units,
                   SUM(total_amount) AS revenue,
                   SUM(total_amount - quantity * COALESCE(cost_at_sale,0)) AS gross_profit
            FROM sales GROUP BY channel ORDER BY revenue DESC
        """).fetchall()
        by_product = con.execute("""
            SELECT sku, product_name, SUM(quantity) AS units,
                   SUM(total_amount) AS revenue,
                   SUM(quantity * COALESCE(cost_at_sale,0)) AS cogs,
                   SUM(total_amount - quantity * COALESCE(cost_at_sale,0)) AS gross_profit
            FROM sales GROUP BY sku, product_name ORDER BY gross_profit DESC LIMIT 20
        """).fetchall()
        low_stock = con.execute("""
            SELECT sku, name, stock, reorder_level
            FROM products WHERE stock <= reorder_level ORDER BY stock ASC, name LIMIT 20
        """).fetchall()
        total_purchase = con.execute("SELECT COALESCE(SUM(total_amount),0) AS value, COALESCE(SUM(quantity),0) AS units FROM purchases").fetchone()
        inventory = con.execute("SELECT COALESCE(SUM(stock * purchase_cost),0) AS value, COALESCE(SUM(stock),0) AS units FROM products").fetchone()

    return render_template(
        "analytics.html", summary=summary, daily=daily, monthly=monthly,
        by_channel=by_channel, by_product=by_product, low_stock=low_stock,
        total_purchase=total_purchase, inventory=inventory
    )
