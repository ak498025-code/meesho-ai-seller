import os, csv, io, json, hashlib, sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import pandas as pd
from products import products_bp

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(APP_DIR, "seller_data.db"))
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls"}
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-before-deploying")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.register_blueprint(products_bp)

REPORT_ALIASES = {
    "orders": ["order id", "order_id", "sub order no", "sub order id", "sub_order_num", "order number"],
    "returns": ["return id", "return_id", "sub order no", "sub order id", "order id"],
    "settlements": ["settlement id", "payment id", "transaction id", "sub order no", "order id"],
    "ads": ["campaign", "campaign name", "ad spend", "advertisement cost", "spend"],
    "inventory": ["sku", "supplier sku", "product sku", "catalogue id", "product name"]
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL, report_type TEXT NOT NULL,
            rows_seen INTEGER NOT NULL DEFAULT 0, rows_added INTEGER NOT NULL DEFAULT 0,
            rows_skipped INTEGER NOT NULL DEFAULT 0, file_hash TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, external_key TEXT UNIQUE,
            order_id TEXT, sub_order_id TEXT, sku TEXT, product_name TEXT,
            quantity REAL, order_status TEXT, order_date TEXT, sale_amount REAL,
            raw_json TEXT, import_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS returns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, external_key TEXT UNIQUE,
            order_id TEXT, sub_order_id TEXT, sku TEXT, return_status TEXT,
            return_reason TEXT, quantity REAL, return_date TEXT, raw_json TEXT,
            import_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, external_key TEXT UNIQUE,
            transaction_id TEXT, order_id TEXT, sub_order_id TEXT,
            transaction_type TEXT, amount REAL, transaction_date TEXT,
            raw_json TEXT, import_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, external_key TEXT UNIQUE,
            campaign_name TEXT, campaign_id TEXT, spend REAL, impressions REAL,
            clicks REAL, attributed_sales REAL, report_date TEXT, raw_json TEXT,
            import_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT, external_key TEXT UNIQUE,
            sku TEXT, product_name TEXT, available_stock REAL, price REAL,
            raw_json TEXT, import_id INTEGER
        );
        """)
init_db()

def norm(s):
    return " ".join(str(s).strip().lower().replace("_", " ").replace("-", " ").split())

def first(row, *names):
    lookup = {norm(k): v for k, v in row.items()}
    for name in names:
        val = lookup.get(norm(name))
        if val is not None and str(val).strip() not in ("", "nan", "None"):
            return val
    return None

def as_num(v):
    if v is None: return None
    try:
        s = str(v).replace(",", "").replace("₹", "").replace("Rs.", "").strip()
        if s in ("", "-", "nan", "None"): return None
        return float(s)
    except Exception:
        return None

def detect_report(columns):
    c = {norm(x) for x in columns}
    if c.intersection({"campaign", "campaign name", "ad spend", "advertisement cost", "spend"}):
        return "ads"
    if c.intersection({"return id", "return status", "return reason", "return date"}):
        return "returns"
    if c.intersection({"settlement id", "payment id", "transaction id", "transaction type", "settlement amount"}):
        return "settlements"
    if c.intersection({"available stock", "inventory", "stock", "supplier sku"}):
        return "inventory"
    if c.intersection({"order id", "sub order no", "sub order id", "order number"}):
        return "orders"
    return "unknown"

def read_report(file_storage):
    name = secure_filename(file_storage.filename or "upload")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    raw = file_storage.read()
    digest = hashlib.sha256(raw).hexdigest()
    if ext == "csv":
        try:
            df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1")
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(io.BytesIO(raw), dtype=str)
    else:
        raise ValueError("Please upload a CSV or Excel file.")
    df = df.fillna("")
    return name, digest, df

def stable_key(report_type, row, index):
    key_fields = {
        "orders": ["sub order no", "sub order id", "order id", "order number"],
        "returns": ["return id", "sub order no", "sub order id", "order id"],
        "settlements": ["transaction id", "payment id", "settlement id", "sub order no", "order id"],
        "ads": ["campaign id", "campaign name", "date", "report date"],
        "inventory": ["sku", "supplier sku", "product sku", "catalogue id"]
    }[report_type]
    values = [str(first(row, f) or "").strip() for f in key_fields]
    meaningful = [v for v in values if v]
    if not meaningful:
        meaningful = [str(index)]
    return hashlib.sha256((report_type + "|" + "|".join(meaningful)).encode()).hexdigest()

def insert_row(con, typ, row, import_id, idx):
    key = stable_key(typ, row, idx)
    raw = json.dumps({str(k): str(v) for k, v in row.items()}, ensure_ascii=False)
    if typ == "orders":
        con.execute("""INSERT OR IGNORE INTO orders
        (external_key,order_id,sub_order_id,sku,product_name,quantity,order_status,order_date,sale_amount,raw_json,import_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
            key, first(row,"order id","order number"), first(row,"sub order no","sub order id"),
            first(row,"sku","supplier sku","product sku"), first(row,"product name","product"),
            as_num(first(row,"quantity","qty")), first(row,"order status","status"),
            first(row,"order date","created date"), as_num(first(row,"supplier listed price","product price","sale amount","total amount")), raw, import_id))
    elif typ == "returns":
        con.execute("""INSERT OR IGNORE INTO returns
        (external_key,order_id,sub_order_id,sku,return_status,return_reason,quantity,return_date,raw_json,import_id)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", (
            key, first(row,"order id"), first(row,"sub order no","sub order id"),
            first(row,"sku","supplier sku"), first(row,"return status","status"),
            first(row,"return reason","reason"), as_num(first(row,"quantity","qty")),
            first(row,"return date","created date"), raw, import_id))
    elif typ == "settlements":
        con.execute("""INSERT OR IGNORE INTO settlements
        (external_key,transaction_id,order_id,sub_order_id,transaction_type,amount,transaction_date,raw_json,import_id)
        VALUES (?,?,?,?,?,?,?,?,?)""", (
            key, first(row,"transaction id","payment id","settlement id"), first(row,"order id"),
            first(row,"sub order no","sub order id"), first(row,"transaction type","type","description"),
            as_num(first(row,"amount","settlement amount","transaction amount","credit","debit")),
            first(row,"transaction date","date","payment date"), raw, import_id))
    elif typ == "ads":
        con.execute("""INSERT OR IGNORE INTO ads
        (external_key,campaign_name,campaign_id,spend,impressions,clicks,attributed_sales,report_date,raw_json,import_id)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", (
            key, first(row,"campaign name","campaign"), first(row,"campaign id"),
            as_num(first(row,"ad spend","advertisement cost","spend","cost")),
            as_num(first(row,"impressions")), as_num(first(row,"clicks")),
            as_num(first(row,"attributed sales","sales","revenue")), first(row,"date","report date"), raw, import_id))
    elif typ == "inventory":
        con.execute("""INSERT OR IGNORE INTO inventory
        (external_key,sku,product_name,available_stock,price,raw_json,import_id)
        VALUES (?,?,?,?,?,?,?)""", (
            key, first(row,"sku","supplier sku","product sku"), first(row,"product name","product"),
            as_num(first(row,"available stock","stock","inventory","quantity")),
            as_num(first(row,"price","selling price")), raw, import_id))
    return con.execute("SELECT changes()").fetchone()[0] == 1

@app.route("/")
def dashboard():
    with db() as con:
        stats = {}
        for table, label in [("orders","orders"),("returns","returns"),("settlements","settlements"),("ads","ad reports"),("inventory","inventory rows")]:
            stats[label] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        imports = con.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 8").fetchall()
        recent = con.execute("SELECT order_id,sub_order_id,sku,quantity,order_status,order_date,sale_amount FROM orders ORDER BY id DESC LIMIT 8").fetchall()
    return render_template("dashboard.html", stats=stats, imports=imports, recent=recent)

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("report")
    if not f or not f.filename:
        flash("Choose a CSV or Excel report first.", "error")
        return redirect(url_for("dashboard"))
    try:
        filename, digest, df = read_report(f)
        if df.empty:
            raise ValueError("The uploaded report has no data rows.")
        selected = request.form.get("report_type", "auto")
        typ = detect_report(df.columns) if selected == "auto" else selected
        if typ not in {"orders","returns","settlements","ads","inventory"}:
            raise ValueError("Could not identify this report. Select its report type manually.")
        with db() as con:
            exists = con.execute("SELECT id FROM imports WHERE file_hash=?", (digest,)).fetchone()
            if exists:
                flash("This exact file was already imported. Duplicate upload skipped.", "warning")
                return redirect(url_for("dashboard"))
            cur = con.execute("INSERT INTO imports(filename,report_type,rows_seen,rows_added,rows_skipped,file_hash,imported_at) VALUES(?,?,?,?,?,?,?)",
                (filename,typ,len(df),0,0,digest,datetime.now().isoformat(timespec="seconds")))
            import_id = cur.lastrowid
            added = 0
            for idx, series in df.iterrows():
                row = series.to_dict()
                if insert_row(con, typ, row, import_id, idx):
                    added += 1
            skipped = len(df) - added
            con.execute("UPDATE imports SET rows_added=?,rows_skipped=? WHERE id=?", (added,skipped,import_id))
        flash(f"Imported {added} new {typ} rows. {skipped} duplicate rows skipped.", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("dashboard"))

@app.route("/imports")
def imports_page():
    with db() as con:
        rows = con.execute("SELECT * FROM imports ORDER BY id DESC").fetchall()
    return render_template("imports.html", imports=rows)

@app.route("/health")
def health():
    return jsonify({"status":"ok","service":"Meesho AI Seller Control Center","database":"connected"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
