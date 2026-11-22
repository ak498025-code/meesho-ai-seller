from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import get_db

expenses_bp = Blueprint("expenses", __name__)

def init_expenses_db():
    with get_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id BIGSERIAL PRIMARY KEY,
                expense_date TEXT NOT NULL,
                channel TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                amount DOUBLE PRECISION NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

init_expenses_db()

@expenses_bp.route("/expenses")
def expenses_page():
    with get_db() as con:
        rows = con.execute("SELECT * FROM expenses ORDER BY expense_date DESC, id DESC LIMIT 200").fetchall()
        summary = con.execute("""
            SELECT COUNT(*) AS count, COALESCE(SUM(amount),0) AS total
            FROM expenses
        """).fetchone()
        by_category = con.execute("""
            SELECT category, COALESCE(SUM(amount),0) AS total
            FROM expenses GROUP BY category ORDER BY total DESC
        """).fetchall()
    return render_template("expenses.html", expenses=rows, summary=summary, by_category=by_category)

@expenses_bp.route("/expenses/new", methods=["GET", "POST"])
def new_expense():
    categories = ["Advertising", "Packaging", "Shipping", "Marketplace Fees", "Rent", "Utilities", "Staff", "Other"]
    channels = ["Meesho", "Amazon", "Flipkart", "Offline Shop", "Shared"]
    if request.method == "POST":
        try:
            expense_date = request.form.get("expense_date", "").strip()
            channel = request.form.get("channel", "").strip()
            category = request.form.get("category", "").strip()
            description = request.form.get("description", "").strip()
            amount = float(request.form.get("amount", "0"))
            if not expense_date:
                raise ValueError("Please select the expense date.")
            if channel not in channels:
                raise ValueError("Please select a valid channel.")
            if category not in categories:
                raise ValueError("Please select a valid expense category.")
            if amount <= 0:
                raise ValueError("Expense amount must be greater than zero.")
            now = datetime.now().isoformat(timespec="seconds")
            with get_db() as con:
                con.execute("""
                    INSERT INTO expenses (expense_date,channel,category,description,amount,created_at)
                    VALUES (?,?,?,?,?,?)
                """, (expense_date, channel, category, description, round(amount, 2), now))
            flash("Expense recorded successfully.", "success")
            return redirect(url_for("expenses.expenses_page"))
        except (ValueError, TypeError) as e:
            flash(str(e) or "Please enter valid expense details.", "error")
    return render_template(
        "expense_form.html",
        categories=categories,
        channels=channels,
        today=datetime.now().date().isoformat()
    )
