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
        recorded_profit = con.execute("""
            SELECT COUNT(*) AS sale_entries,
                   COALESCE(SUM(total_amount),0) AS revenue,
                   COALESCE(SUM(quantity * COALESCE(cost_at_sale,0)),0) AS cogs,
                   COALESCE(SUM(total_amount - quantity * COALESCE(cost_at_sale,0)),0) AS gross_profit
            FROM sales
        """).fetchone()
        expense_summary = con.execute("""
            SELECT COALESCE(SUM(amount),0) AS total,
                   COALESCE(SUM(amount) FILTER (WHERE channel='Shared'),0) AS shared,
                   COUNT(*) AS entries
            FROM expenses
        """).fetchone()
        expense_by_channel = con.execute("""
            SELECT channel, COALESCE(SUM(amount),0) AS total, COUNT(*) AS entries
            FROM expenses GROUP BY channel ORDER BY total DESC
        """).fetchall()
        recorded_net_profit = float(recorded_profit["gross_profit"] or 0) - float(expense_summary["total"] or 0)
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
        marketplace_summary = con.execute("""
            SELECT o.marketplace, COUNT(*) AS report_rows,
                   COALESCE(SUM(o.quantity),0) AS units,
                   COALESCE(SUM(o.sale_amount),0) AS revenue,
                   COALESCE(SUM(o.quantity * p.purchase_cost),0) AS matched_cogs,
                   COALESCE(SUM(o.sale_amount - o.quantity * p.purchase_cost),0) AS estimated_gross_profit,
                   COUNT(*) FILTER (WHERE o.sku IS NULL OR p.id IS NULL) AS unmatched_cost_rows,
                   COUNT(*) FILTER (WHERE o.sale_amount IS NULL) AS missing_amount_rows
            FROM orders o
            LEFT JOIN products p ON LOWER(TRIM(o.sku)) = LOWER(TRIM(p.sku))
            GROUP BY o.marketplace ORDER BY revenue DESC NULLS LAST, o.marketplace
        """).fetchall()
        marketplace_products = con.execute("""
            SELECT o.marketplace, COALESCE(o.sku,'—') AS sku,
                   COALESCE(MAX(o.product_name), MAX(p.name), 'Unmapped product') AS product_name,
                   COALESCE(SUM(o.quantity),0) AS units,
                   COALESCE(SUM(o.sale_amount),0) AS revenue,
                   COALESCE(SUM(o.quantity * p.purchase_cost),0) AS matched_cogs,
                   COALESCE(SUM(o.sale_amount - o.quantity * p.purchase_cost),0) AS estimated_gross_profit
            FROM orders o
            LEFT JOIN products p ON LOWER(TRIM(o.sku)) = LOWER(TRIM(p.sku))
            GROUP BY o.marketplace, o.sku
            ORDER BY revenue DESC NULLS LAST LIMIT 30
        """).fetchall()
        settlement_summary = con.execute("""
            SELECT marketplace, COUNT(*) AS transaction_rows,
                   COALESCE(SUM(amount),0) AS net_movement,
                   COUNT(*) FILTER (WHERE amount IS NULL) AS missing_amount_rows
            FROM settlements
            WHERE marketplace <> 'Meesho'
               OR NOT (jsonb_exists(raw_json::jsonb, 'Sub Order No'))
               OR NULLIF(raw_json::jsonb ->> 'Sub Order No','') IS NOT NULL
            GROUP BY marketplace ORDER BY marketplace
        """).fetchall()
        settlement_types = con.execute("""
            SELECT marketplace,
                   CASE WHEN marketplace='Meesho' AND jsonb_exists(raw_json::jsonb, 'Live Order Status')
                        THEN COALESCE(NULLIF(raw_json::jsonb ->> 'Live Order Status',''),'Unclassified')
                        ELSE COALESCE(transaction_type,'Unclassified') END AS transaction_type,
                   COUNT(*) AS rows, COALESCE(SUM(amount),0) AS amount
            FROM settlements
            WHERE marketplace <> 'Meesho'
               OR NOT (jsonb_exists(raw_json::jsonb, 'Sub Order No'))
               OR NULLIF(raw_json::jsonb ->> 'Sub Order No','') IS NOT NULL
            GROUP BY marketplace, transaction_type, raw_json::jsonb ->> 'Live Order Status'
            ORDER BY marketplace, amount DESC
        """).fetchall()
        meesho_details = con.execute("""
            SELECT
              COUNT(*) AS order_rows,
              COUNT(*) FILTER (WHERE raw_json::jsonb ->> 'Live Order Status'='Delivered') AS delivered_orders,
              COUNT(*) FILTER (WHERE raw_json::jsonb ->> 'Live Order Status'='RTO') AS rto_orders,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Total Sale Amount (Incl. Shipping & GST)','')::numeric),0) AS sale_amount,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Total Sale Return Amount (Incl. Shipping & GST)','')::numeric),0) AS sale_return_amount,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Shipping Charge (Incl. GST)','')::numeric),0) AS shipping_charge,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Return Shipping Charge (Incl. GST)','')::numeric),0) AS return_shipping_charge,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Fixed Fee (Incl. GST)','')::numeric),0) AS fixed_fee,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Warehousing fee (inc Gst)','')::numeric),0) AS warehousing_fee,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Meesho Commission (Incl. GST)','')::numeric),0) AS commission,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Meesho gold platform fee (Incl. GST)','')::numeric),0) AS gold_platform_fee,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Meesho mall platform fee (Incl. GST)','')::numeric),0) AS mall_platform_fee,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'TCS','')::numeric),0) AS tcs,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'TDS','')::numeric),0) AS tds,
              COALESCE(SUM(NULLIF(raw_json::jsonb ->> 'Final Settlement Amount','')::numeric),0) AS final_settlement
            FROM settlements
            WHERE marketplace='Meesho'
              AND NULLIF(raw_json::jsonb ->> 'Sub Order No','') IS NOT NULL
        """).fetchone()
        meesho_orders = con.execute("""
            SELECT raw_json::jsonb ->> 'Sub Order No' AS sub_order_no,
                   raw_json::jsonb ->> 'Product Name' AS product_name,
                   raw_json::jsonb ->> 'Live Order Status' AS order_status,
                   COALESCE(NULLIF(raw_json::jsonb ->> 'Total Sale Amount (Incl. Shipping & GST)','')::numeric,0) AS sale_amount,
                   COALESCE(NULLIF(raw_json::jsonb ->> 'Total Sale Return Amount (Incl. Shipping & GST)','')::numeric,0) AS sale_return,
                   COALESCE(NULLIF(raw_json::jsonb ->> 'Shipping Charge (Incl. GST)','')::numeric,0) AS shipping_charge,
                   COALESCE(NULLIF(raw_json::jsonb ->> 'Return Shipping Charge (Incl. GST)','')::numeric,0) AS return_shipping,
                   COALESCE(NULLIF(raw_json::jsonb ->> 'TCS','')::numeric,0) AS tcs,
                   COALESCE(NULLIF(raw_json::jsonb ->> 'TDS','')::numeric,0) AS tds,
                   COALESCE(NULLIF(raw_json::jsonb ->> 'Final Settlement Amount','')::numeric,0) AS final_settlement
            FROM settlements
            WHERE marketplace='Meesho'
              AND NULLIF(raw_json::jsonb ->> 'Sub Order No','') IS NOT NULL
            ORDER BY transaction_date, sub_order_no
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
        marketplace_summary=marketplace_summary, marketplace_products=marketplace_products,
        settlement_summary=settlement_summary, settlement_types=settlement_types,
        meesho_details=meesho_details, meesho_orders=meesho_orders,
        total_purchase=total_purchase, inventory=inventory,
        recorded_profit=recorded_profit, expense_summary=expense_summary,
        expense_by_channel=expense_by_channel, recorded_net_profit=recorded_net_profit
    )
