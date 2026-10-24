from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, csv
from pathlib import Path
from datetime import date, datetime, timedelta

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "stocksense.db"
UPLOAD_DIR = APP_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGES = {"png", "jpg", "jpeg", "webp"}
app = Flask(__name__)
app.secret_key = os.environ.get("STOCKSENSE_SECRET_KEY", "change-this-demo-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def add_column(conn, table, column, definition):
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            unit_cost REAL NOT NULL DEFAULT 0,
            daily_sales REAL NOT NULL DEFAULT 0,
            lead_days INTEGER NOT NULL DEFAULT 1,
            safety_stock INTEGER NOT NULL DEFAULT 0,
            expiry_date TEXT DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            sold_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        )""")
        # Safe additive migrations: existing user/product/sales records are retained.
        for col, definition in [
            ("shop_name", "TEXT NOT NULL DEFAULT ''"),
        ]:
            add_column(conn, "users", col, definition)
        for col, definition in [
            ("barcode", "TEXT NOT NULL DEFAULT ''"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("batch_number", "TEXT NOT NULL DEFAULT ''"),
            ("supplier_name", "TEXT NOT NULL DEFAULT ''"),
            ("supplier_price", "REAL NOT NULL DEFAULT 0"),
            ("selling_price", "REAL NOT NULL DEFAULT 0"),
            ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ]:
            add_column(conn, "products", col, definition)
        add_column(conn, "sales", "unit_cost_at_sale", "REAL NOT NULL DEFAULT 0")
        add_column(conn, "sales", "selling_price_at_sale", "REAL NOT NULL DEFAULT 0")
        conn.execute("""CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            avg_delivery_days REAL NOT NULL DEFAULT 0,
            purchase_price REAL NOT NULL DEFAULT 0,
            delayed_deliveries INTEGER NOT NULL DEFAULT 0,
            product_issues INTEGER NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(user_id, name)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            movement_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_user_barcode ON products(user_id, barcode)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_user_date ON sales(user_id, sold_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_product ON sales(product_id)")

def current_user():
    return session.get("user_id")

def expiry_state(value):
    if not value:
        return "No date"
    try:
        days = (date.fromisoformat(value) - date.today()).days
    except ValueError:
        return "Unknown"
    if days < 0:
        return "Expired"
    if days <= 3:
        return "Expiring soon"
    return "In date"

def owned_products(conn, uid):
    return conn.execute("SELECT * FROM products WHERE user_id=? ORDER BY name, expiry_date, id", (uid,)).fetchall()


def seed_excel_products(conn, uid):
    """Import the bundled Excel sheet's product records for this user's account.
    Existing products are preserved; barcodes already present are skipped.
    Imported quantities start at zero so the user can enter actual stock manually.
    """
    data_path = APP_DIR / "data" / "stocksense_products.csv"
    if not data_path.exists():
        return 0
    imported = 0
    with data_path.open("r", newline="", encoding="utf-8-sig") as file:
        for item in csv.DictReader(file):
            barcode = (item.get("barcode") or "").strip()
            name = (item.get("name") or "").strip()
            if not name:
                continue
            if barcode and conn.execute(
                "SELECT 1 FROM products WHERE user_id=? AND barcode=? LIMIT 1",
                (uid, barcode)
            ).fetchone():
                continue
            conn.execute("""INSERT INTO products
                (user_id, name, quantity, unit_cost, daily_sales, lead_days,
                 safety_stock, expiry_date, barcode, category, supplier_price,
                 selling_price, created_at)
                VALUES (?, ?, 0, ?, 0, 1, 0, ?, ?, ?, ?, ?, ?)""",
                (uid, name, float(item.get("unit_cost") or 0),
                 (item.get("expiry_date") or "").strip(), barcode,
                 (item.get("category") or "").strip(),
                 float(item.get("unit_cost") or 0),
                 float(item.get("selling_price") or 0), datetime.now().isoformat(timespec="seconds")))
            imported += 1
    return imported

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE identifier=?", (identifier,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            with db() as conn:
                seed_excel_products(conn, user["id"])
            session["user_id"] = user["id"]
            session["identifier"] = user["identifier"]
            return redirect(url_for("dashboard"))
        flash("Login details are incorrect. Please register first or try again.", "error")
    return render_template("index.html", page="login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        if not identifier or len(password) < 8:
            flash("Enter an email/phone and a password with at least 8 characters.", "error")
        else:
            try:
                with db() as conn:
                    conn.execute("INSERT INTO users(identifier,password_hash) VALUES(?,?)",
                                 (identifier, generate_password_hash(password)))
                flash("Account created. You can now log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email/phone is already registered.", "error")
    return render_template("index.html", page="register")

@app.route("/dashboard")
def dashboard():
    if not current_user():
        return redirect(url_for("login"))
    today = date.today()
    soon = (today + timedelta(days=3)).isoformat()
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id=?", (current_user(),)).fetchone()
        seed_excel_products(conn, current_user())
        products = owned_products(conn, current_user())
        sales_count = conn.execute("SELECT COALESCE(SUM(quantity),0) AS n FROM sales WHERE user_id=?", (current_user(),)).fetchone()["n"]
        expired = conn.execute("SELECT COUNT(*) n FROM products WHERE user_id=? AND expiry_date<>'' AND expiry_date<?", (current_user(), today.isoformat())).fetchone()["n"]
        expiring = conn.execute("SELECT * FROM products WHERE user_id=? AND expiry_date<>'' AND expiry_date>=? AND expiry_date<=? ORDER BY expiry_date", (current_user(), today.isoformat(), soon)).fetchall()
        weekly = conn.execute("""SELECT p.name, SUM(s.quantity) qty, SUM(s.quantity * COALESCE(NULLIF(s.unit_cost_at_sale,0),p.unit_cost)) purchase_value
            FROM sales s JOIN products p ON p.id=s.product_id WHERE s.user_id=? AND s.sold_at>=?
            GROUP BY p.id ORDER BY qty DESC LIMIT 8""", (current_user(), (today-timedelta(days=7)).isoformat())).fetchall()
        monthly = conn.execute("""SELECT p.name, SUM(s.quantity) qty, SUM(s.quantity * COALESCE(NULLIF(s.unit_cost_at_sale,0),p.unit_cost)) purchase_value
            FROM sales s JOIN products p ON p.id=s.product_id WHERE s.user_id=? AND s.sold_at>=?
            GROUP BY p.id ORDER BY qty DESC LIMIT 8""", (current_user(), (today-timedelta(days=30)).isoformat())).fetchall()
        yearly = conn.execute("""SELECT p.name, SUM(s.quantity) qty, SUM(s.quantity * COALESCE(NULLIF(s.unit_cost_at_sale,0),p.unit_cost)) purchase_value
            FROM sales s JOIN products p ON p.id=s.product_id WHERE s.user_id=? AND s.sold_at>=?
            GROUP BY p.id ORDER BY qty DESC LIMIT 8""", (current_user(), (today-timedelta(days=365)).isoformat())).fetchall()
        suppliers = conn.execute("SELECT * FROM suppliers WHERE user_id=? ORDER BY name", (current_user(),)).fetchall()
        revenue = conn.execute("SELECT COALESCE(SUM(quantity * selling_price_at_sale),0) n FROM sales WHERE user_id=?", (current_user(),)).fetchone()["n"]
    supplier_recommendation = None
    if suppliers:
        # Explainable weighted score: price matters, while delays/issues carry extra penalties.
        ranked_suppliers = sorted(suppliers, key=lambda s: float(s["purchase_price"]) +
            float(s["avg_delivery_days"]) * 5 + int(s["delayed_deliveries"]) * 20 + int(s["product_issues"]) * 30)
        supplier_recommendation = ranked_suppliers[0]
    recommendations = []
    for p in products:
        usable = 0 if expiry_state(p["expiry_date"]) == "Expired" else int(p["quantity"])
        target = max(0, round(float(p["daily_sales"]) * int(p["lead_days"]) + int(p["safety_stock"])))
        reorder = max(0, target - usable)
        if reorder > 0:
            recommendations.append({"name": p["name"], "quantity": reorder, "target": target,
                                     "stock": p["quantity"], "cost": round(reorder * p["unit_cost"], 2),
                                     "supplier": p["supplier_name"]})
    recommendations.sort(key=lambda x: (x["stock"] / max(x["target"], 1), -x["cost"]))
    return render_template("index.html", page="dashboard", products=products,
        recommendations=recommendations, sales_count=sales_count, user=user,
        expiring=expiring, expired_count=expired, weekly=weekly, monthly=monthly,
        yearly=yearly, suppliers=suppliers, supplier_recommendation=supplier_recommendation, revenue=revenue, expiry_state=expiry_state, today=today.isoformat())

@app.route("/shop", methods=["POST"])
def update_shop():
    if not current_user():
        return redirect(url_for("login"))
    shop_name = request.form.get("shop_name", "").strip()
    with db() as conn:
        conn.execute("UPDATE users SET shop_name=? WHERE id=?", (shop_name, current_user()))
    flash("Shop name saved.", "success")
    return redirect(url_for("dashboard") + "#shop")

@app.route("/products", methods=["POST"])
def add_product():
    if not current_user():
        return redirect(url_for("login"))
    try:
        name = request.form.get("name", "").strip()
        quantity = int(request.form.get("quantity", 0))
        unit_cost = float(request.form.get("unit_cost", 0))
        daily_sales = float(request.form.get("daily_sales", 0))
        lead_days = int(request.form.get("lead_days", 1))
        safety_stock = int(request.form.get("safety_stock", 0))
        expiry_date = request.form.get("expiry_date", "").strip()
        barcode = request.form.get("barcode", "").strip()
        category = request.form.get("category", "").strip()
        batch_number = request.form.get("batch_number", "").strip()
        supplier_name = request.form.get("supplier_name", "").strip()
        supplier_price = float(request.form.get("supplier_price", unit_cost))
        selling_price = float(request.form.get("selling_price", 0))
        if not name or min(quantity, unit_cost, daily_sales, lead_days, safety_stock, supplier_price, selling_price) < 0:
            raise ValueError
        if expiry_date:
            date.fromisoformat(expiry_date)
        with db() as conn:
            cur = conn.execute("""INSERT INTO products
                (user_id,name,quantity,unit_cost,daily_sales,lead_days,safety_stock,expiry_date,barcode,category,batch_number,supplier_name,supplier_price,selling_price,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (current_user(), name, quantity, unit_cost, daily_sales, lead_days, safety_stock, expiry_date,
                 barcode, category, batch_number, supplier_name, supplier_price, selling_price, date.today().isoformat()))
            product_id = cur.lastrowid
            if quantity:
                conn.execute("INSERT INTO stock_movements(user_id,product_id,movement_type,quantity,created_at,note) VALUES(?,?,?,?,?,?)",
                    (current_user(), product_id, "Opening stock", quantity, datetime.now().isoformat(timespec="seconds"), "New batch/stock entry"))
        flash("Stock batch added. The same product can have multiple batches and expiry dates.", "success")
    except (ValueError, KeyError):
        flash("Please enter valid product details. Quantity and prices cannot be negative.", "error")
    return redirect(url_for("dashboard") + "#scanner")

@app.route("/scan_lookup")
def scan_lookup():
    if not current_user():
        return jsonify({"error": "Please log in first."}), 401
    barcode = request.args.get("barcode", "").strip()
    if not barcode:
        return jsonify({"error": "Enter or scan a barcode."}), 400
    with db() as conn:
        rows = conn.execute("SELECT * FROM products WHERE user_id=? AND barcode=? ORDER BY expiry_date, id", (current_user(), barcode)).fetchall()
    if not rows:
        return jsonify({"found": False, "barcode": barcode, "message": "Barcode not found. Add it as a new product; details are not guessed."})
    return jsonify({"found": True, "barcode": barcode, "batches": [
        {"id": r["id"], "name": r["name"], "quantity": r["quantity"], "expiry_date": r["expiry_date"],
         "batch_number": r["batch_number"], "unit_cost": r["unit_cost"], "selling_price": r["selling_price"],
         "category": r["category"], "supplier_name": r["supplier_name"], "supplier_price": r["supplier_price"],
         "daily_sales": r["daily_sales"], "lead_days": r["lead_days"], "safety_stock": r["safety_stock"],
         "status": expiry_state(r["expiry_date"])} for r in rows
    ]})

@app.route("/barcode-image", methods=["POST"])
def barcode_image():
    if not current_user():
        return redirect(url_for("login"))
    f = request.files.get("barcode_image")
    if not f or not f.filename:
        flash("Choose a barcode image first.", "error")
        return redirect(url_for("dashboard") + "#scanner")
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED_IMAGES:
        flash("Upload a PNG, JPG or WEBP image.", "error")
        return redirect(url_for("dashboard") + "#scanner")
    # Image is made available to browser BarcodeDetector; filename is randomized by timestamp.
    safe_name = f"{current_user()}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.{ext}"
    f.save(UPLOAD_DIR / secure_filename(safe_name))
    flash("Image uploaded. Use “Read barcode from image” on the scanner panel to detect its barcode.", "success")
    return redirect(url_for("dashboard") + "#scanner")

@app.route("/sales", methods=["POST"])
def record_sale():
    if not current_user():
        return redirect(url_for("login"))
    try:
        product_id = int(request.form["product_id"])
        quantity = int(request.form["quantity"])
        if quantity <= 0:
            raise ValueError
        with db() as conn:
            product = conn.execute("SELECT * FROM products WHERE id=? AND user_id=?", (product_id, current_user())).fetchone()
            if not product:
                flash("Product/batch not found.", "error")
            elif product["expiry_date"] and expiry_state(product["expiry_date"]) == "Expired":
                flash("Sale rejected: this batch has expired. Choose a valid batch.", "error")
            elif quantity > product["quantity"]:
                flash("Sale rejected: not enough stock available.", "error")
            else:
                conn.execute("UPDATE products SET quantity=quantity-? WHERE id=? AND user_id=?", (quantity, product_id, current_user()))
                conn.execute("INSERT INTO sales(user_id,product_id,quantity,sold_at,unit_cost_at_sale,selling_price_at_sale) VALUES(?,?,?,?,?,?)",
                    (current_user(), product_id, quantity, date.today().isoformat(), product["unit_cost"], product["selling_price"]))
                conn.execute("INSERT INTO stock_movements(user_id,product_id,movement_type,quantity,created_at,note) VALUES(?,?,?,?,?,?)",
                    (current_user(), product_id, "Sale", -quantity, datetime.now().isoformat(timespec="seconds"), "Sale recorded"))
                flash(f"Sale saved. {quantity} unit(s) sold.", "success")
    except (ValueError, KeyError):
        flash("Enter a valid sale quantity.", "error")
    return redirect(url_for("dashboard") + "#sales")

@app.route("/suppliers", methods=["POST"])
def add_supplier():
    if not current_user():
        return redirect(url_for("login"))
    try:
        name = request.form.get("name", "").strip()
        avg_days = float(request.form.get("avg_delivery_days", 0))
        price = float(request.form.get("purchase_price", 0))
        delays = int(request.form.get("delayed_deliveries", 0))
        issues = int(request.form.get("product_issues", 0))
        notes = request.form.get("notes", "").strip()
        if not name or min(avg_days, price, delays, issues) < 0:
            raise ValueError
        with db() as conn:
            conn.execute("""INSERT INTO suppliers(user_id,name,avg_delivery_days,purchase_price,delayed_deliveries,product_issues,notes)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET avg_delivery_days=excluded.avg_delivery_days,
                purchase_price=excluded.purchase_price,delayed_deliveries=excluded.delayed_deliveries,
                product_issues=excluded.product_issues,notes=excluded.notes""",
                (current_user(), name, avg_days, price, delays, issues, notes))
        flash("Supplier scorecard saved.", "success")
    except (ValueError, KeyError):
        flash("Enter valid supplier details.", "error")
    return redirect(url_for("dashboard") + "#suppliers")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
