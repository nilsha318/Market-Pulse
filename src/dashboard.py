"""Local role-based dashboard for the synthetic supermarket sales dataset."""

import argparse
import csv
from datetime import date, timedelta
import hashlib
import hmac
import html
import math
import os
import re
import secrets
import sqlite3
from contextlib import closing
from getpass import getpass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

from src.database import DATABASE_PATH, connect, initialize, is_postgres

PBKDF2_ROUNDS = 260_000
SESSIONS: dict[str, str] = {}


def secure_cookie_attribute() -> str:
    enabled = os.environ.get("MARKET_PULSE_SECURE_COOKIES", "").strip().lower()
    return "; Secure" if enabled in ("1", "true", "yes") else ""


STYLES = """
*{box-sizing:border-box}body{margin:0;background:#f4f7f7;color:#173b38;font:16px/1.5 Segoe UI,Arial,sans-serif}
header{background:#123b38;color:white;padding:20px max(24px,calc((100% - 1120px)/2));display:flex;align-items:center;justify-content:space-between}
header h1{font-size:20px;margin:0}header a{color:#cce8df}main{max-width:1120px;margin:36px auto;padding:0 24px}
.eyebrow{color:#328474;text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700}
h2{font-size:30px;margin:4px 0 22px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin:20px 0 30px}
.card,section,.login{background:white;border:1px solid #dce8e6;border-radius:16px;padding:22px;box-shadow:0 7px 24px #143b3810}
.metric{font-size:30px;font-weight:700;margin:5px 0}.muted{color:#637b78}.layout{display:grid;grid-template-columns:1fr 1fr;gap:20px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #e7efee}th{color:#607875;font-size:12px;text-transform:uppercase}
input,select{width:100%;padding:11px 12px;border:1px solid #cbd9d7;border-radius:8px;margin:5px 0 14px;font:inherit}
button,.button{display:inline-block;background:#176d5e;color:white;border:0;border-radius:8px;padding:11px 16px;font:inherit;font-weight:650;text-decoration:none;cursor:pointer}
.button.secondary{background:#e5f1ef;color:#174d45}.notice{padding:12px;background:#e5f1ef;border-radius:8px;margin:12px 0}.error{background:#fff0ed;color:#923e32}.login{max-width:440px;margin:50px auto}.tag{background:#e5f1ef;border-radius:20px;padding:4px 10px;font-size:12px}
.offer-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:16px;margin:16px 0 28px}.offer{border-top:4px solid #39a184}.offer h3{margin:8px 0}.price{font-size:23px;font-weight:700;color:#176d5e}.old-price{text-decoration:line-through;color:#728582;font-size:14px;margin-left:8px}.offer-tag{display:inline-block;border-radius:20px;background:#e5f1ef;color:#176d5e;padding:4px 9px;font-size:12px}
.brand{letter-spacing:.02em}.nav{display:flex;align-items:center;gap:16px;flex-wrap:wrap}.nav a{text-decoration:none}.hero{padding:30px;border-radius:18px;background:linear-gradient(120deg,#e0f2ec,#f6fbf9);margin-bottom:22px}.hero h2{margin-bottom:6px}.eyebrow{font-size:11px}.tag{white-space:nowrap}.checkout-note{border-left:4px solid #e3aa4e}
@media(max-width:720px){.layout{grid-template-columns:1fr}header{padding:18px 24px}main{margin-top:24px}}
"""


def ensure_schema() -> None:
    with closing(connect()) as connection:
        postgres = is_postgres()
        if postgres:
            connection.execute("""CREATE TABLE IF NOT EXISTS dashboard_users (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                department TEXT,
                job_title TEXT,
                password_salt BYTEA NOT NULL,
                password_hash BYTEA NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            connection.execute("ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS department TEXT")
            connection.execute("ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS job_title TEXT")
            connection.execute("ALTER TABLE dashboard_users DROP CONSTRAINT IF EXISTS dashboard_users_role_check")
            connection.execute("ALTER TABLE dashboard_users ADD CONSTRAINT dashboard_users_role_check "
                               "CHECK (role IN ('admin', 'customer', 'employee'))")
        else:
            # Upgrade the role constraint in place while preserving existing accounts.
            user_table = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='dashboard_users'"
            ).fetchone()
            if user_table and "'employee'" not in user_table[0]:
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("""CREATE TABLE dashboard_users_new (
                    username TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'customer', 'employee')),
                    department TEXT,
                    job_title TEXT,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                connection.execute("""INSERT INTO dashboard_users_new
                    (username, role, password_salt, password_hash, created_at)
                    SELECT username, role, password_salt, password_hash, created_at FROM dashboard_users""")
                connection.execute("DROP TABLE dashboard_users")
                connection.execute("ALTER TABLE dashboard_users_new RENAME TO dashboard_users")
                connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("""CREATE TABLE IF NOT EXISTS dashboard_users (
                username TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK (role IN ('admin', 'customer', 'employee')),
                department TEXT,
                job_title TEXT,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS customer_order_access (
                username TEXT NOT NULL REFERENCES dashboard_users(username) ON DELETE CASCADE,
                order_id TEXT NOT NULL,
                PRIMARY KEY (username, order_id)
            )
        """)
        offers_id = "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        offer_price_type = "NUMERIC(12, 2)" if postgres else "REAL"
        offer_date_type = "DATE" if postgres else "TEXT"
        offer_created_type = "TIMESTAMPTZ" if postgres else "TEXT"
        connection.execute("""CREATE TABLE IF NOT EXISTS offers (
                offer_id """ + offers_id + """,
                product TEXT NOT NULL,
                category TEXT NOT NULL,
                store TEXT NOT NULL,
                regular_price """ + offer_price_type + " NOT NULL, offer_price " + offer_price_type + " NOT NULL, "
                "valid_from " + offer_date_type + " NOT NULL, valid_until " + offer_date_type + " NOT NULL, "
                "description TEXT NOT NULL DEFAULT '', created_at " + offer_created_type + " NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        cart_offer_id_type = "BIGINT" if postgres else "INTEGER"
        connection.execute("""
            CREATE TABLE IF NOT EXISTS cart_items (
                cart_key TEXT NOT NULL,
                offer_id """ + cart_offer_id_type + " NOT NULL REFERENCES offers(offer_id), quantity INTEGER NOT NULL "
                "CHECK (quantity BETWEEN 1 AND 99), PRIMARY KEY (cart_key, offer_id))")
        coupons_id = "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        coupon_percent_type = "NUMERIC(5, 2)" if postgres else "REAL"
        coupon_date_type = "DATE" if postgres else "TEXT"
        coupon_active_type = "BOOLEAN NOT NULL DEFAULT TRUE" if postgres else "INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))"
        coupon_code_collation = "" if postgres else " COLLATE NOCASE"
        connection.execute("""CREATE TABLE IF NOT EXISTS coupons (
            coupon_id """ + coupons_id + """,
            code TEXT NOT NULL UNIQUE""" + coupon_code_collation + ", percent_off " + coupon_percent_type +
            " NOT NULL CHECK (percent_off > 0 AND percent_off <= 100), valid_from " + coupon_date_type +
            " NOT NULL, valid_until " + coupon_date_type + " NOT NULL, active " + coupon_active_type +
            ", created_at " + offer_created_type + " NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        connection.execute("""UPDATE offers SET valid_until = ?, description =
            'Retired sample offer from the previous demo dataset.' WHERE product IN
            ('Alpine Apples 1 kg', 'Wholegrain Pasta 500 g', 'Mountain Cheese 250 g',
             'Dark Roast Coffee 500 g', 'Tomato Passata 700 ml')""",
            ((date.today() - timedelta(days=1)).isoformat(),))
        seed_path = DATABASE_PATH.parent / "offers.csv"
        if seed_path.exists():
            with seed_path.open(newline="", encoding="utf-8-sig") as source:
                seeded = list(csv.DictReader(source))
            for row in seeded:
                exists = connection.execute(
                    "SELECT 1 FROM offers WHERE product = ? AND category = ?", (row["product"], row["category"])
                ).fetchone()
                if not exists:
                    connection.execute(
                        """INSERT INTO offers (product, category, store, regular_price, offer_price,
                                                 valid_from, valid_until, description)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (row["product"], row["category"], row["store"], float(row["regular_price"]),
                         float(row["offer_price"]), row["valid_from"], row["valid_until"], row["description"]),
                    )
        connection.commit()


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or secrets.token_bytes(16)
    return salt, hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)


def page(title: str, body: str, user: dict | None = None) -> str:
    nav = "<a href='/guest'>Overview</a><a href='/offers'>Offer Zone</a><a href='/cart'>Cart</a>"
    if user:
        dashboard_path = user_dashboard_path(user)
        role = user["role"]
        links = f"<a href='{dashboard_path}'>Dashboard</a>"
        if role in ("customer", "admin"):
            links += "<a href='/offers'>Offer Zone</a>"
        if role == "customer":
            links += "<a href='/cart'>Cart</a><a href='/checkout'>Checkout</a>"
        links += "<a href='/account'>Account</a>"
        nav = (f"<span class='nav'>{links}<span>{html.escape(user['username'])} &nbsp; <b class='tag'>{html.escape((user.get('department') or role).title())}</b></span>"
               "<form method='post' action='/logout' style='display:inline;margin:0'>"
               f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'><button class='button secondary'>Log out</button></form>")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)} · Market Pulse</title><style>{STYLES}</style></head><body>"
            f"<header><h1 class='brand'>Market Pulse</h1><nav class='nav'>{nav}</nav></header>"
            f"<main>{body}</main></body></html>")


def money(value: float) -> str:
    return f"{value:,.2f}"


def user_dashboard_path(user: dict) -> str:
    if user["role"] == "admin":
        return "/admin"
    if user["role"] == "customer":
        return "/customer"
    if user.get("department") == "Finance" and user.get("job_title") == "Accountant":
        return "/finance"
    return "/employee"


def get_sales(username: str | None = None) -> list[dict]:
    query = """
        SELECT invoice_id, branch, city, customer_type, gender, product_line,
               unit_price, quantity, sales, date, time, payment, gross_income, rating
        FROM (
            SELECT invoice_id, branch, city, customer_type, gender, product_line,
                   unit_price, quantity, sales, date, time, payment, gross_income, rating,
                   ROW_NUMBER() OVER (PARTITION BY invoice_id ORDER BY source_row) AS position
            FROM sales
        ) WHERE position = 1
    """
    params: tuple = ()
    if username is not None:
        query = "SELECT * FROM (" + query.rstrip().removesuffix(";") + ") AS unique_orders " \
                "WHERE invoice_id IN (SELECT order_id FROM customer_order_access WHERE username = ?)"
        params = (username,)
    with closing(connect()) as connection:
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def get_offers(active_only: bool = True, branches: set[str] | None = None) -> list[dict]:
    query = "SELECT * FROM offers"
    params: tuple = ()
    clauses = []
    if active_only:
        clauses.extend(("valid_from <= ?", "valid_until >= ?"))
        today = date.today().isoformat()
        params += (today, today)
    if branches is not None:
        choices = sorted(branches | {"All branches"})
        clauses.append("store IN (" + ", ".join("?" for _ in choices) + ")")
        params += tuple(choices)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY valid_until, product"
    with closing(connect()) as connection:
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def get_cart_items(cart_key: str) -> list[dict]:
    with closing(connect()) as connection:
        return [dict(row) for row in connection.execute(
            """SELECT o.offer_id, o.product, o.category, o.store, o.offer_price,
                      o.valid_from, o.valid_until, c.quantity
               FROM cart_items c JOIN offers o ON o.offer_id = c.offer_id
               WHERE c.cart_key = ? ORDER BY o.product""", (cart_key,)
        ).fetchall()]


def coupon_discount(code: str, subtotal: float) -> tuple[float, float] | None:
    if not code:
        return (0.0, 0.0)
    today = date.today().isoformat()
    with closing(connect()) as connection:
        coupon = connection.execute(
            """SELECT percent_off FROM coupons WHERE upper(code) = upper(?)
               AND active = TRUE AND valid_from <= ? AND valid_until >= ?""",
            (code.strip(), today, today),
        ).fetchone()
    if not coupon:
        return None
    percent = float(coupon["percent_off"])
    return percent, round(subtotal * percent / 100, 2)


def render_offers(offers: list[dict], csrf: str, empty_message: str = "No active offers right now.",
                  can_add_to_cart: bool = True) -> str:
    if not offers:
        return f"<p class='muted'>{html.escape(empty_message)}</p>"
    cards = []
    for offer in offers:
        saving = max(0, offer["regular_price"] - offer["offer_price"])
        active = offer["valid_from"] <= date.today().isoformat() <= offer["valid_until"]
        cart_action = ""
        if active and can_add_to_cart:
            cart_action = (
                "<form method='post' action='/cart/add'>"
                f"<input type='hidden' name='csrf' value='{html.escape(csrf)}'>"
                f"<input type='hidden' name='offer_id' value='{offer['offer_id']}'>"
                "<label>Qty <input name='quantity' type='number' min='1' max='99' value='1' required></label>"
                "<button>Add to cart</button></form>"
            )
        elif active:
            cart_action = "<p class='muted'>Available in the customer Offer Zone.</p>"
        else:
            cart_action = "<p class='muted'>Offer expired or not yet active.</p>"
        cards.append(
            "<article class='card offer'>"
            f"<span class='offer-tag'>{html.escape(offer['category'])}</span>"
            f"<h3>{html.escape(offer['product'])}</h3>"
            f"<div class='price'>{money(offer['offer_price'])} <small style='font-size:12px'>dataset units</small>"
            f"<span class='old-price'>{money(offer['regular_price'])}</span></div>"
            f"<p>{html.escape(offer['description'])}</p>"
            f"<p class='muted'>Save {money(saving)} dataset units · Branch: {html.escape(offer['store'])}</p>"
            f"<small class='muted'>Valid {html.escape(offer['valid_from'])} to {html.escape(offer['valid_until'])}</small>"
            f"{cart_action}"
            "</article>"
        )
    return "<div class='offer-grid'>" + "".join(cards) + "</div>"


def summary(sales_rows: list[dict]) -> dict:
    total_sales = sum(float(row["sales"]) for row in sales_rows)
    gross_income = sum(float(row["gross_income"]) for row in sales_rows)
    quantity = sum(int(row["quantity"]) for row in sales_rows)
    ratings = [float(row["rating"]) for row in sales_rows if row.get("rating")]
    return {
        "invoices": len({row["invoice_id"] for row in sales_rows if row.get("invoice_id")}),
        "sales": total_sales,
        "gross_income": gross_income,
        "quantity": quantity,
        "rating": sum(ratings) / len(ratings) if ratings else 0,
    }


def render_sales(sales_rows: list[dict]) -> str:
    if not sales_rows:
        return "<p class='muted'>No invoices are linked to this account yet.</p>"
    rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row.get(key) or '—'))}</td>"
                          for key in ("invoice_id", "date", "branch", "city", "product_line", "quantity", "sales", "rating")) + "</tr>"
        for row in sales_rows
    )
    return ("<div style='overflow:auto'><table><thead><tr><th>Invoice</th><th>Date</th><th>Branch</th><th>City</th>"
            f"<th>Product line</th><th>Qty</th><th>Sales</th><th>Rating</th></tr></thead><tbody>{rows}</tbody></table></div>")


def render_product_breakdown(sales_rows: list[dict]) -> str:
    grouped: dict[str, dict] = {}
    for row in sales_rows:
        item = grouped.setdefault(row["product_line"], {"sales": 0.0, "quantity": 0, "invoices": 0})
        item["sales"] += float(row["sales"])
        item["quantity"] += int(row["quantity"])
        item["invoices"] += 1
    if not grouped:
        return "<p class='muted'>No product-line data for this account.</p>"
    rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{values['invoices']}</td><td>{values['quantity']}</td><td>{money(values['sales'])}</td></tr>"
        for name, values in sorted(grouped.items(), key=lambda pair: pair[1]["sales"], reverse=True)
    )
    return ("<div style='overflow:auto'><table><thead><tr><th>Product line</th><th>Invoices</th><th>Units</th>"
            f"<th>Sales (dataset units)</th></tr></thead><tbody>{rows}</tbody></table></div>")


def render_finance_breakdown(sales_rows: list[dict]) -> str:
    grouped: dict[str, dict] = {}
    for row in sales_rows:
        item = grouped.setdefault(row["product_line"], {"gross_income": 0.0, "sales": 0.0})
        item["gross_income"] += float(row["gross_income"])
        item["sales"] += float(row["sales"])
    rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{money(values['sales'])}</td>"
        f"<td>{money(values['gross_income'])}</td></tr>"
        for name, values in sorted(grouped.items(), key=lambda pair: pair[1]["gross_income"], reverse=True)
    )
    return ("<div style='overflow:auto'><table><thead><tr><th>Product line</th>"
            "<th>Sales (dataset units)</th><th>Gross income (dataset units)</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


def render_branch_breakdown(sales_rows: list[dict]) -> str:
    grouped: dict[str, dict] = {}
    for row in sales_rows:
        branch = row.get("branch") or "Unknown"
        item = grouped.setdefault(branch, {"sales": 0.0, "quantity": 0, "invoices": set()})
        item["sales"] += float(row["sales"])
        item["quantity"] += int(row["quantity"])
        if row.get("invoice_id"):
            item["invoices"].add(row["invoice_id"])
    rows = "".join(
        f"<tr><td>{html.escape(branch)}</td><td>{len(values['invoices'])}</td>"
        f"<td>{values['quantity']}</td><td>{money(values['sales'])}</td></tr>"
        for branch, values in sorted(grouped.items(), key=lambda pair: pair[1]["sales"], reverse=True)
    )
    if not rows:
        return "<p class='muted'>No branch data is available.</p>"
    return ("<div style='overflow:auto'><table><thead><tr><th>Branch</th><th>Invoices</th>"
            "<th>Units</th><th>Sales (dataset units)</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "MarketPulse/1.0"

    def do_GET(self):
        if self.path == "/account":
            user = self.current_user()
            if not user:
                self.redirect("/login")
            else:
                self.respond_account(user)
        elif self.path == "/guest":
            self.respond_guest()
        elif self.path in ("/", "/dashboard"):
            user = self.current_user()
            if not user:
                self.redirect("/login")
            else:
                self.redirect(user_dashboard_path(user))
        elif self.path == "/login":
            self.respond_login()
        elif self.path == "/offers":
            user = self.current_user()
            if user and user["role"] not in ("admin", "customer"):
                self.send_error(403)
            else:
                self.respond_offer_zone(user)
        elif self.path == "/cart":
            user = self.current_user()
            if user and user["role"] != "customer":
                self.send_error(403)
            else:
                self.respond_cart(user)
        elif self.path == "/checkout":
            self.require_role("customer", self.respond_checkout)
        elif self.path == "/admin":
            self.require_role("admin", self.respond_admin)
        elif self.path == "/customer":
            self.require_role("customer", self.respond_customer)
        elif self.path == "/finance":
            self.require_employee_department("Finance", "Accountant", self.respond_finance)
        elif self.path == "/employee":
            self.require_role("employee", self.respond_employee)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/login":
            self.login()
        elif self.path == "/logout":
            self.logout()
        elif self.path == "/account/update":
            user = self.current_user()
            if not user:
                self.redirect("/login")
            else:
                self.update_account(user)
        elif self.path == "/admin/users":
            self.require_role("admin", self.create_customer)
        elif self.path == "/admin/employees":
            self.require_role("admin", self.create_employee)
        elif self.path == "/admin/links":
            self.require_role("admin", self.update_customer_invoices)
        elif self.path == "/admin/offers":
            self.require_role("admin", self.create_offer)
        elif self.path == "/admin/coupons":
            self.require_role("admin", self.create_coupon)
        elif self.path == "/checkout/apply":
            self.require_role("customer", self.apply_coupon)
        elif self.path in ("/cart/add", "/cart/update"):
            self.cart_action()
        else:
            self.send_error(404)

    def current_user(self) -> dict | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("session")
        username = SESSIONS.get(morsel.value) if morsel else None
        if not username:
            return None
        with closing(connect()) as connection:
            row = connection.execute(
                "SELECT username, role, department, job_title FROM dashboard_users WHERE username = ?", (username,)
            ).fetchone()
        if not row:
            return None
        user = dict(row)
        user["csrf"] = self.csrf_token(morsel.value)
        return user

    @staticmethod
    def csrf_token(session_id: str) -> str:
        return hmac.new(session_id.encode(), b"market-pulse-csrf", hashlib.sha256).hexdigest()

    def cart_identity(self, user: dict | None) -> tuple[str, str, str | None]:
        if user:
            return "user:" + user["username"], user["csrf"], None
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("guest_cart")
        token = morsel.value if morsel else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{30,80}", token):
            token = secrets.token_urlsafe(32)
            set_cookie = (f"guest_cart={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000"
                          + secure_cookie_attribute())
        else:
            set_cookie = None
        return "guest:" + token, token, set_cookie

    def body(self) -> dict[str, str]:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 65536)
            raw = self.rfile.read(length).decode("utf-8")
            return {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}
        except (ValueError, UnicodeDecodeError):
            return {}

    def send_html(self, content: str, status: int = 200, extra_headers: dict | None = None):
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'")
        self.send_header("Referrer-Policy", "no-referrer")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, location: str, headers: dict | None = None):
        self.send_response(303)
        self.send_header("Location", location)
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def message(self, text: str, error: bool = False):
        return f"<div class='notice{' error' if error else ''}'>{html.escape(text)}</div>"

    def respond_account(self, user: dict, notice: str = "", error: bool = False):
        body = ("<div class='login'><p class='eyebrow'>Account settings</p><h2>Change account details</h2>"
                "<p class='muted'>Update your username and password. Your account role and linked data stay attached.</p>"
                + (self.message(notice, error) if notice else "") +
                "<form method='post' action='/account/update'>"
                f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'>"
                f"<label>New username<input name='username' value='{html.escape(user['username'], quote=True)}' required minlength='3' maxlength='40' pattern='[A-Za-z0-9_.-]+' autocomplete='username'></label>"
                "<label>Current password<input name='current_password' type='password' required autocomplete='current-password'></label>"
                "<label>New password<input name='new_password' type='password' required minlength='10' maxlength='256' autocomplete='new-password'></label>"
                "<label>Confirm new password<input name='confirm_password' type='password' required minlength='10' maxlength='256' autocomplete='new-password'></label>"
                "<button>Save account changes</button></form></div>")
        self.send_html(page("Account settings", body, user))

    def update_account(self, user: dict):
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), user["csrf"]):
            self.send_error(403)
            return
        username = form.get("username", "").strip()
        current_password = form.get("current_password", "")
        new_password = form.get("new_password", "")
        confirm_password = form.get("confirm_password", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
            self.respond_account(user, "Use 3–40 letters, numbers, dots, dashes, or underscores for the username.", True)
            return
        if len(new_password) < 10 or len(new_password) > 256:
            self.respond_account(user, "Choose a new password between 10 and 256 characters.", True)
            return
        if new_password != confirm_password:
            self.respond_account(user, "The new password and confirmation do not match.", True)
            return

        with closing(connect()) as connection:
            account = connection.execute(
                "SELECT password_salt, password_hash, role, department, job_title, created_at "
                "FROM dashboard_users WHERE username = ?", (user["username"],)
            ).fetchone()
        if not account:
            self.send_error(401)
            return
        candidate = hashlib.pbkdf2_hmac("sha256", current_password.encode("utf-8"),
                                        account["password_salt"], PBKDF2_ROUNDS)
        if not hmac.compare_digest(candidate, account["password_hash"]):
            self.respond_account(user, "Current password was incorrect.", True)
            return

        session_cookie = SimpleCookie(self.headers.get("Cookie", ""))
        session_morsel = session_cookie.get("session")
        session_id = session_morsel.value if session_morsel else ""
        if not session_id or SESSIONS.get(session_id) != user["username"]:
            self.redirect("/login")
            return
        salt, password_hash = hash_password(new_password)
        try:
            with closing(connect()) as connection, connection:
                if username != user["username"]:
                    connection.execute(
                        "INSERT INTO dashboard_users (username, role, department, job_title, password_salt, password_hash, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (username, account["role"], account["department"], account["job_title"],
                         salt, password_hash, account["created_at"]),
                    )
                    connection.execute("UPDATE customer_order_access SET username = ? WHERE username = ?",
                                       (username, user["username"]))
                    connection.execute("DELETE FROM dashboard_users WHERE username = ?", (user["username"],))
                else:
                    connection.execute(
                        "UPDATE dashboard_users SET password_salt = ?, password_hash = ? WHERE username = ?",
                        (salt, password_hash, username),
                    )
        except sqlite3.IntegrityError:
            self.respond_account(user, "That username is already in use.", True)
            return

        old_username = user["username"]
        for active_session, active_username in list(SESSIONS.items()):
            if active_username == old_username and active_session != session_id:
                SESSIONS.pop(active_session, None)
        SESSIONS[session_id] = username
        updated_user = {**user, "username": username}
        self.respond_account(updated_user, "Username and password updated.")

    def require_role(self, role: str, callback):
        user = self.current_user()
        if not user:
            self.redirect("/login")
        elif user["role"] != role:
            self.redirect("/dashboard")
        else:
            callback(user)

    def require_employee_department(self, department: str, job_title: str, callback):
        user = self.current_user()
        if not user:
            self.redirect("/login")
        elif (user["role"] != "employee" or user.get("department") != department
              or user.get("job_title") != job_title):
            self.send_error(403, "This dashboard is restricted to Finance accountants.")
        else:
            callback(user)

    def respond_employee(self, user: dict):
        department = user.get("department") or ""
        rows = get_sales()
        content = ("<div class='hero'><p class='eyebrow'>Employee workspace</p>"
                   f"<h2>{html.escape(department or 'Department')} overview</h2>"
                   f"<p class='muted'>Signed in as {html.escape(user.get('job_title') or 'Employee')}.</p></div>"
                   "<p class='muted'>Read-only department view of the historical sample. Amounts are dataset units.</p>"
                   + self.cards(summary(rows)))
        if department == "Sales":
            content += ("<section><h3>Sales by product line</h3>" + render_product_breakdown(rows)
                        + "</section><section><h3>Branch sales</h3>" + render_branch_breakdown(rows) + "</section>")
        elif department == "Marketing":
            content += ("<section><h3>Published offers</h3><p class='muted'>Current promotional examples "
                        "managed by an administrator.</p>" + render_offers(get_offers(), user["csrf"],
                        "No active offers are published.", can_add_to_cart=False) + "</section>")
        elif department == "Operations":
            content += ("<section><h3>Branch activity</h3><p class='muted'>Invoice and quantity totals by branch.</p>"
                        + render_branch_breakdown(rows) + "</section>")
        else:
            content += "<section><h3>Department view</h3><p class='muted'>No department-specific panel is configured.</p></section>"
        content += ("<section><h3>Access</h3><p class='muted'>This employee view is read-only. Finance details "
                    "are available only to employees assigned to Finance with the Accountant job title.</p></section>")
        self.send_html(page("Employee dashboard", content, user))

    def respond_finance(self, user: dict):
        rows = get_sales()
        stats = summary(rows)
        content = ("<p class='eyebrow'>Restricted · Finance</p><h2>Finance dashboard</h2>"
                   f"<p class='muted'>Accountant access · {html.escape(user['username'])}</p>"
                   + self.cards(stats) + "<section><h3>Finance summary by product line</h3>"
                   + render_finance_breakdown(rows) + "</section>")
        self.send_html(page("Finance dashboard", content, user))

    def respond_login(self, notice: str = ""):
        body = ("<div class='login'><p class='eyebrow'>Secure sign in</p><h2>Welcome back</h2>"
                "<p class='muted'>Sign in to see your role-specific sales dashboard.</p>" + notice +
                "<form method='post' action='/login'><label>Username<input name='username' required autocomplete='username'></label>"
                "<label>Password<input name='password' type='password' required autocomplete='current-password'></label>"
                "<button>Sign in</button></form><p class='muted'>Just looking? <a href='/guest'>Continue as guest</a></p></div>")
        self.send_html(page("Sign in", body))

    def login(self):
        form = self.body()
        username = form.get("username", "").strip()
        with closing(connect()) as connection:
            row = connection.execute(
                "SELECT username, role, department, job_title, password_salt, password_hash FROM dashboard_users WHERE username = ?",
                (username,),
            ).fetchone()
        password = form.get("password", "")
        valid = False
        if row and len(password) <= 256:
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), row["password_salt"], PBKDF2_ROUNDS)
            valid = hmac.compare_digest(candidate, row["password_hash"])
        if not valid:
            self.respond_login(self.message("Username or password was incorrect.", True))
            return
        session_id = secrets.token_urlsafe(32)
        SESSIONS[session_id] = username
        self.redirect("/dashboard", {"Set-Cookie": f"session={session_id}; HttpOnly; SameSite=Lax; Path=/"
                                       + secure_cookie_attribute()})

    def logout(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("session")
        session_id = morsel.value if morsel else ""
        if session_id in SESSIONS:
            expected = self.csrf_token(session_id)
            if not hmac.compare_digest(self.body().get("csrf", ""), expected):
                self.send_error(403)
                return
            SESSIONS.pop(session_id, None)
        self.redirect("/login", {"Set-Cookie": "session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
                                  + secure_cookie_attribute()})

    def respond_guest(self):
        _, csrf, set_cookie = self.cart_identity(None)
        sales_rows = get_sales()
        stats = summary(sales_rows)
        content = ("<div class='hero'><p class='eyebrow'>Public overview · Guest</p><h2>Supermarket sales</h2>"
                   "<p class='muted'>Explore the sample's sales performance and current offers.</p></div>"
                   "<p class='muted'>Read-only overview of the historical 2019 supermarket sample.</p>" + self.cards(stats) +
                   "<section><h3>Sales by product line</h3>" + render_product_breakdown(sales_rows) + "</section>"
                   "<section><h3>About this view</h3><p>Guest accounts only see aggregate figures. Sign in for account-specific details.</p>"
                   "<a class='button' href='/login'>Sign in</a></section>"
                   f"<section style='margin-top:20px'><h3>Offer Zone</h3>{render_offers(get_offers(), csrf)}</section>")
        headers = {"Set-Cookie": set_cookie} if set_cookie else None
        self.send_html(page("Guest overview", content), extra_headers=headers)

    @staticmethod
    def cards(stats: dict) -> str:
        cards = [("Distinct invoices", f"{stats['invoices']:,}"),
                 ("Sales (dataset units)", money(stats["sales"])),
                 ("Gross income (dataset units)", money(stats["gross_income"])),
                 ("Quantity sold", f"{stats['quantity']:,}"),
                 ("Average rating", f"{stats['rating']:.2f} / 10")]
        return "<div class='grid'>" + "".join(
            f"<article class='card'><span class='muted'>{label}</span><div class='metric'>{value}</div></article>"
            for label, value in cards
        ) + "</div>"

    def respond_customer(self, user: dict, notice: str = ""):
        sales_rows = get_sales(user["username"])
        branches = {row["branch"] for row in sales_rows if row.get("branch")}
        content = (f"<div class='hero'><p class='eyebrow'>Customer account</p><h2>Welcome, {html.escape(user['username'])}</h2>"
                   "<p class='muted'>Your linked activity, offers, and shopping cart.</p></div>"
                   "<p class='muted'>Your account's linked invoices and summary.</p>" + notice + self.cards(summary(sales_rows)) +
                   "<section><h3>Your sales by product line</h3>" + render_product_breakdown(sales_rows) + "</section>"
                   f"<section style='margin-top:20px'><h3>Your invoices</h3>{render_sales(sales_rows)}</section>"
                   f"<section style='margin-top:20px'><h3>Offer Zone</h3>{render_offers(get_offers(branches=branches), user['csrf'])}</section>"
                   "<p><a class='button' href='/cart'>View cart and checkout</a></p>")
        self.send_html(page("Customer dashboard", content, user))

    def respond_admin(self, user: dict, notice: str = ""):
        sales_rows = get_sales()
        stats = summary(sales_rows)
        with closing(connect()) as connection:
            users = connection.execute(
                "SELECT username, role, department, job_title, created_at FROM dashboard_users ORDER BY role, department, username"
            ).fetchall()
            links_by_user = {row[0]: [link[0] for link in connection.execute(
                "SELECT order_id FROM customer_order_access WHERE username = ? ORDER BY order_id", (row[0],)
            )] for row in users}
        user_rows = []
        for account in users:
            name = account["username"]
            links = ", ".join(links_by_user[name])
            link_form = ("<form method='post' action='/admin/links' style='display:flex;gap:6px'>"
                         f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'>"
                         f"<input type='hidden' name='username' value='{html.escape(name)}'>"
                         f"<input name='invoice_ids' value='{html.escape(links)}' placeholder='Invoice IDs, comma separated' style='min-width:220px;margin:0'>"
                         "<button class='button secondary'>Save links</button></form>" if account["role"] == "customer" else "—")
            user_rows.append(
                f"<tr><td>{html.escape(name)}</td><td>{html.escape(account['role'])}</td>"
                f"<td>{html.escape(account['department'] or '—')}</td><td>{html.escape(account['job_title'] or '—')}</td>"
                f"<td>{html.escape(account['created_at'])}</td><td>{link_form}</td></tr>"
            )
        form = ("<form method='post' action='/admin/users'>"
                f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'>"
                "<label>Customer username<input name='username' required minlength='3' maxlength='40' pattern='[A-Za-z0-9_.-]+'></label>"
                "<label>Temporary password<input name='password' type='password' required minlength='10' maxlength='256'></label>"
                "<label>Invoice IDs to link <span class='muted'>(comma separated)</span><input name='invoice_ids' placeholder='750-67-8428, 226-31-3081'></label>"
                "<button>Create customer account</button></form>")
        offer_form = ("<form method='post' action='/admin/offers'>"
                      f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'>"
                      "<label>Offer title<input name='product' required maxlength='100'></label>"
                      "<label>Product line<select name='category' required>"
                      "<option>Electronic accessories</option><option>Fashion accessories</option>"
                      "<option>Food and beverages</option><option>Health and beauty</option>"
                      "<option>Home and lifestyle</option><option>Sports and travel</option></select></label>"
                      "<label>Branch<select name='store' required><option>All branches</option>"
                      "<option>Alex</option><option>Cairo</option><option>Giza</option></select></label>"
                      "<label>Regular price (dataset units)<input name='regular_price' type='number' min='0.01' step='0.01' required></label>"
                      "<label>Offer price (dataset units)<input name='offer_price' type='number' min='0' step='0.01' required></label>"
                      "<label>Valid from<input name='valid_from' type='date' required></label>"
                      "<label>Valid until<input name='valid_until' type='date' required></label>"
                      "<label>Description<input name='description' maxlength='240'></label>"
                      "<button>Publish offer</button></form>")
        all_offers = get_offers(active_only=False)
        with closing(connect()) as connection:
            coupons = connection.execute(
                "SELECT code, percent_off, valid_from, valid_until, active FROM coupons ORDER BY code"
            ).fetchall()
        coupon_rows = "".join(
            f"<tr><td>{html.escape(row['code'])}</td><td>{row['percent_off']:g}%</td>"
            f"<td>{html.escape(row['valid_from'])} to {html.escape(row['valid_until'])}</td>"
            f"<td>{'Active' if row['active'] else 'Inactive'}</td></tr>" for row in coupons
        ) or "<tr><td colspan='4' class='muted'>No coupons yet.</td></tr>"
        coupon_form = ("<form method='post' action='/admin/coupons'>"
                       f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'>"
                       "<label>Coupon code<input name='code' required maxlength='24' pattern='[A-Za-z0-9_-]+'></label>"
                       "<label>Discount (%)<input name='percent_off' type='number' min='1' max='100' step='1' required></label>"
                       "<label>Valid from<input name='valid_from' type='date' required></label>"
                       "<label>Valid until<input name='valid_until' type='date' required></label>"
                       "<button>Create coupon</button></form>")
        content = ("<div class='hero'><p class='eyebrow'>Administration</p><h2>Store dashboard</h2>"
                   "<p class='muted'>Sales performance, accounts, offers, and campaign coupons.</p></div>"
                   "<p class='muted'>Full sales data, product-line summaries, accounts, and offers.</p>" + notice + self.cards(stats) +
                   "<section><h3>Sales by product line</h3>" + render_product_breakdown(sales_rows) + "</section>"
                   "<div class='layout' style='margin-top:20px'><section><h3>Create a customer</h3><p class='muted'>Accounts see only linked Invoice IDs.</p>" + form +
                   "</section><section><h3>Create an employee</h3><p class='muted'>Finance data is restricted to employees assigned the Finance department and Accountant job title.</p>"
                   "<form method='post' action='/admin/employees'>"
                   f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'>"
                   "<label>Employee username<input name='username' required minlength='3' maxlength='40' pattern='[A-Za-z0-9_.-]+'></label>"
                   "<label>Temporary password<input name='password' type='password' required minlength='10' maxlength='256'></label>"
                   "<label>Department<select name='department'><option>Finance</option><option>Sales</option><option>Marketing</option><option>Operations</option></select></label>"
                   "<label>Job title<input name='job_title' required maxlength='60' placeholder='Accountant'></label>"
                   "<button>Create employee account</button></form></section></div>"
                   "<section style='margin-top:20px'><h3>Accounts and invoice access</h3><div style='overflow:auto'><table><thead><tr><th>Username</th><th>Role</th><th>Department</th><th>Job title</th><th>Created</th><th>Linked invoice IDs</th></tr></thead>"
                   f"<tbody>{''.join(user_rows)}</tbody></table></div></section></div>"
                   "<div class='layout' style='margin-top:20px'><section><h3>Add product offer</h3>" + offer_form +
                   "</section><section><h3>Offer Zone · all offers</h3>" + render_offers(all_offers, user["csrf"], "No offers have been added.", can_add_to_cart=False) + "</section></div>"
                   f"<section style='margin-top:20px'><h3>All transactions · {len(sales_rows)} unique invoices</h3>{render_sales(sales_rows)}</section>")
        content += ("<div class='layout' style='margin-top:20px'><section><h3>Create a coupon</h3>"
                    "<p class='muted'>Percentage discounts for customer checkout previews.</p>" + coupon_form +
                    "</section><section><h3>Coupons</h3><div style='overflow:auto'><table>"
                    "<thead><tr><th>Code</th><th>Discount</th><th>Dates</th><th>Status</th></tr></thead>"
                    f"<tbody>{coupon_rows}</tbody></table></div></section></div>")
        self.send_html(page("Admin dashboard", content, user))

    def create_customer(self, user: dict):
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), user["csrf"]):
            self.send_error(403)
            return
        username = form.get("username", "").strip()
        password = form.get("password", "")
        raw_ids = [value.strip() for value in form.get("invoice_ids", "").split(",") if value.strip()]
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
            self.respond_admin(user, self.message("Use 3–40 letters, numbers, dots, dashes, or underscores for the username.", True))
            return
        if len(password) < 10 or len(password) > 256:
            self.respond_admin(user, self.message("Choose a password between 10 and 256 characters.", True))
            return
        with closing(connect()) as connection:
            known_ids = {row[0] for row in connection.execute("SELECT DISTINCT invoice_id FROM sales WHERE invoice_id IS NOT NULL")}
            unknown = sorted(set(raw_ids) - known_ids)
            if unknown:
                self.respond_admin(user, self.message("Unknown Invoice IDs: " + ", ".join(unknown), True))
                return
            salt, password_hash = hash_password(password)
            try:
                connection.execute(
                    "INSERT INTO dashboard_users(username, role, password_salt, password_hash) VALUES (?, 'customer', ?, ?)",
                    (username, salt, password_hash),
                )
                connection.executemany(
                    "INSERT INTO customer_order_access(username, order_id) VALUES (?, ?)",
                    [(username, order_id) for order_id in sorted(set(raw_ids))],
                )
                connection.commit()
            except sqlite3.IntegrityError:
                self.respond_admin(user, self.message("That username already exists.", True))
                return
        self.respond_admin(user, self.message(f"Customer account {username} was created."))

    def create_employee(self, user: dict):
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), user["csrf"]):
            self.send_error(403)
            return
        username = form.get("username", "").strip()
        password = form.get("password", "")
        department = form.get("department", "")
        job_title = form.get("job_title", "").strip()
        allowed = {"Finance", "Sales", "Marketing", "Operations"}
        if (not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username) or len(password) < 10
                or len(password) > 256 or department not in allowed or not job_title or len(job_title) > 60):
            self.respond_admin(user, self.message("Enter a valid employee username, password, department, and job title.", True))
            return
        salt, password_hash = hash_password(password)
        with closing(connect()) as connection:
            try:
                connection.execute("""INSERT INTO dashboard_users
                    (username, role, department, job_title, password_salt, password_hash)
                    VALUES (?, 'employee', ?, ?, ?, ?)""",
                    (username, department, job_title, salt, password_hash))
                connection.commit()
            except sqlite3.IntegrityError:
                self.respond_admin(user, self.message("That username already exists.", True))
                return
        self.respond_admin(user, self.message(f"Employee account {username} was created."))

    def update_customer_invoices(self, user: dict):
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), user["csrf"]):
            self.send_error(403)
            return
        username = form.get("username", "")
        invoice_ids = sorted(set(value.strip() for value in form.get("invoice_ids", "").split(",") if value.strip()))
        with closing(connect()) as connection:
            account = connection.execute(
                "SELECT role FROM dashboard_users WHERE username = ?", (username,)
            ).fetchone()
            if not account or account["role"] != "customer":
                self.respond_admin(user, self.message("Customer account not found.", True))
                return
            known_ids = {row[0] for row in connection.execute(
                "SELECT DISTINCT invoice_id FROM sales WHERE invoice_id IS NOT NULL"
            )}
            unknown = sorted(set(invoice_ids) - known_ids)
            if unknown:
                self.respond_admin(user, self.message("Unknown Invoice IDs: " + ", ".join(unknown), True))
                return
            connection.execute("DELETE FROM customer_order_access WHERE username = ?", (username,))
            connection.executemany(
                "INSERT INTO customer_order_access(username, order_id) VALUES (?, ?)",
                [(username, invoice_id) for invoice_id in invoice_ids],
            )
            connection.commit()
        self.respond_admin(user, self.message(f"Invoice access updated for {username}."))

    def create_offer(self, user: dict):
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), user["csrf"]):
            self.send_error(403)
            return
        product = form.get("product", "").strip()
        category = form.get("category", "").strip()
        store = form.get("store", "").strip()
        description = form.get("description", "").strip()
        try:
            regular_price = float(form.get("regular_price", ""))
            offer_price = float(form.get("offer_price", ""))
            valid_from = date.fromisoformat(form.get("valid_from", ""))
            valid_until = date.fromisoformat(form.get("valid_until", ""))
            if not all((product, category, store)) or len(product) > 100 or len(category) > 60 or len(store) > 60 or len(description) > 240:
                raise ValueError
            if (not math.isfinite(regular_price) or not math.isfinite(offer_price)
                    or regular_price <= 0 or offer_price < 0
                    or offer_price >= regular_price or valid_until < valid_from):
                raise ValueError
        except (ValueError, OverflowError):
            self.respond_admin(user, self.message("Enter valid product details, dates, and prices; the offer price must be lower than the regular price.", True))
            return
        with closing(connect()) as connection:
            connection.execute(
                """INSERT INTO offers (product, category, store, regular_price, offer_price,
                                       valid_from, valid_until, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (product, category, store, regular_price, offer_price,
                 valid_from.isoformat(), valid_until.isoformat(), description),
            )
            connection.commit()
        self.respond_admin(user, self.message(f"Offer for {product} was published."))

    def create_coupon(self, user: dict):
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), user["csrf"]):
            self.send_error(403)
            return
        code = form.get("code", "").strip().upper()
        try:
            percent = float(form.get("percent_off", ""))
            valid_from = date.fromisoformat(form.get("valid_from", ""))
            valid_until = date.fromisoformat(form.get("valid_until", ""))
            if (not re.fullmatch(r"[A-Z0-9_-]{3,24}", code) or not math.isfinite(percent)
                    or percent <= 0 or percent > 100 or valid_until < valid_from):
                raise ValueError
        except (ValueError, OverflowError):
            self.respond_admin(user, self.message("Enter a valid coupon code, discount from 0 to 100%, and date range.", True))
            return
        with closing(connect()) as connection:
            try:
                connection.execute(
                    "INSERT INTO coupons(code, percent_off, valid_from, valid_until) VALUES (?, ?, ?, ?)",
                    (code, percent, valid_from.isoformat(), valid_until.isoformat()),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                self.respond_admin(user, self.message("That coupon code already exists.", True))
                return
        self.respond_admin(user, self.message(f"Coupon {code} was created."))

    def apply_coupon(self, user: dict):
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), user["csrf"]):
            self.send_error(403)
            return
        code = form.get("code", "").strip()
        items = get_cart_items("user:" + user["username"])
        subtotal = sum(item["offer_price"] * item["quantity"] for item in items
                       if item["valid_from"] <= date.today().isoformat() <= item["valid_until"])
        if not code:
            self.respond_checkout(user, notice="Enter a coupon code to apply it.", error=True)
        elif coupon_discount(code, subtotal) is None:
            self.respond_checkout(user, notice="That coupon is invalid, expired, or inactive.", error=True)
        else:
            self.respond_checkout(user, code=code, notice="Coupon applied.")

    def cart_action(self):
        user = self.current_user()
        if user and user["role"] != "customer":
            self.send_error(403)
            return
        cart_key, expected_csrf, set_cookie = self.cart_identity(user)
        form = self.body()
        if not hmac.compare_digest(form.get("csrf", ""), expected_csrf):
            self.send_error(403)
            return
        try:
            offer_id = int(form.get("offer_id", ""))
            if self.path == "/cart/add":
                quantity = int(form.get("quantity", "1"))
                if quantity < 1 or quantity > 99:
                    raise ValueError
                today = date.today().isoformat()
                with closing(connect()) as connection:
                    offer = connection.execute(
                        "SELECT offer_id FROM offers WHERE offer_id = ? AND valid_from <= ? AND valid_until >= ?",
                        (offer_id, today, today),
                    ).fetchone()
                    if not offer:
                        raise ValueError
                    cap_quantity = "LEAST" if is_postgres() else "MIN"
                    connection.execute(
                        f"""INSERT INTO cart_items(cart_key, offer_id, quantity) VALUES (?, ?, ?)
                           ON CONFLICT(cart_key, offer_id) DO UPDATE
                           SET quantity = {cap_quantity}(cart_items.quantity + excluded.quantity, 99)""",
                        (cart_key, offer_id, quantity),
                    )
                    connection.commit()
            else:
                action = form.get("action", "update")
                with closing(connect()) as connection:
                    if action == "remove":
                        connection.execute("DELETE FROM cart_items WHERE cart_key = ? AND offer_id = ?", (cart_key, offer_id))
                    else:
                        quantity = int(form.get("quantity", ""))
                        if quantity < 1 or quantity > 99:
                            raise ValueError
                        connection.execute(
                            "UPDATE cart_items SET quantity = ? WHERE cart_key = ? AND offer_id = ?",
                            (quantity, cart_key, offer_id),
                        )
                    connection.commit()
        except (ValueError, OverflowError):
            self.respond_cart(user, "Please choose a valid quantity and an active offer.", error=True)
            return
        headers = {"Set-Cookie": set_cookie} if set_cookie else None
        self.respond_cart(user, "Cart updated.", extra_headers=headers)

    def respond_cart(self, user: dict | None, notice: str = "", error: bool = False,
                     extra_headers: dict | None = None):
        cart_key, csrf, set_cookie = self.cart_identity(user)
        items = get_cart_items(cart_key)
        today = date.today().isoformat()
        subtotal = 0.0
        lines = []
        for item in items:
            active = item["valid_from"] <= today <= item["valid_until"]
            line_total = item["offer_price"] * item["quantity"] if active else 0
            subtotal += line_total
            state = "Active" if active else "Expired — remove this item"
            lines.append(
                "<tr>"
                f"<td>{html.escape(item['product'])}<br><small class='muted'>{html.escape(item['category'])} · {html.escape(item['store'])}</small></td>"
                f"<td>{money(item['offer_price'])}</td><td>{html.escape(state)}</td>"
                "<td><form method='post' action='/cart/update' style='display:flex;gap:6px;align-items:center'>"
                f"<input type='hidden' name='csrf' value='{html.escape(csrf)}'>"
                f"<input type='hidden' name='offer_id' value='{item['offer_id']}'>"
                f"<input name='quantity' type='number' min='1' max='99' value='{item['quantity']}' style='width:80px;margin:0'>"
                "<button name='action' value='update'>Update</button>"
                "<button class='button secondary' name='action' value='remove'>Remove</button></form></td>"
                f"<td>{money(line_total) if active else '—'}</td></tr>"
            )
        if lines:
            table = ("<div style='overflow:auto'><table><thead><tr><th>Product</th><th>Unit price (dataset units)</th><th>Offer status</th>"
                     f"<th>Quantity</th><th>Line total</th></tr></thead><tbody>{''.join(lines)}</tbody></table></div>")
            table += f"<p style='text-align:right;font-size:20px'><b>Active offers subtotal: {money(subtotal)} dataset units</b></p>"
        else:
            table = "<p class='muted'>Your cart is empty. Browse the Offer Zone to add products.</p>"
        next_step = ("<a class='button' href='/checkout'>Continue to checkout</a> " if user else
                     "<a class='button secondary' href='/login'>Sign in as a customer to check out</a> ")
        body = ("<div class='hero'><p class='eyebrow'>Your selections</p><h2>Shopping cart</h2>"
                "<p class='muted'>Review quantities and active offer prices.</p></div>" +
                (self.message(notice, error) if notice else "") + table +
                "<a class='button secondary' href='/offers'>Continue shopping</a> " + next_step)
        headers = dict(extra_headers or {})
        if set_cookie:
            headers["Set-Cookie"] = set_cookie
        self.send_html(page("Cart", body, user), extra_headers=headers or None)

    def respond_checkout(self, user: dict, code: str = "", notice: str = "", error: bool = False):
        cart_key = "user:" + user["username"]
        items = get_cart_items(cart_key)
        today = date.today().isoformat()
        subtotal = sum(item["offer_price"] * item["quantity"] for item in items
                       if item["valid_from"] <= today <= item["valid_until"])
        applied = coupon_discount(code, subtotal) if code else (0.0, 0.0)
        if applied is None:
            code = ""
            applied = (0.0, 0.0)
        percent, discount = applied
        total = max(0, subtotal - discount)
        summary_rows = "".join(
            f"<tr><td>{html.escape(item['product'])}</td><td>{item['quantity']}</td>"
            f"<td>{money(item['offer_price'] * item['quantity'])}</td></tr>"
            for item in items if item["valid_from"] <= today <= item["valid_until"]
        ) or "<tr><td colspan='3' class='muted'>Your cart has no active offers.</td></tr>"
        coupon_form = ("<form method='post' action='/checkout/apply'>"
                       f"<input type='hidden' name='csrf' value='{html.escape(user['csrf'])}'>"
                       f"<label>Coupon code<input name='code' value='{html.escape(code)}' maxlength='24'></label>"
                       "<button>Apply coupon</button></form>")
        content = ("<div class='hero'><p class='eyebrow'>Customer checkout</p><h2>Order preview</h2>"
                   "<p class='muted'>This demo calculates a total but does not take payment or place an order.</p></div>"
                   + (self.message(notice, error) if notice else "") +
                   "<div class='layout'><section><h3>Order summary</h3><div style='overflow:auto'><table>"
                   "<thead><tr><th>Item</th><th>Qty</th><th>Line total</th></tr></thead>"
                   f"<tbody>{summary_rows}</tbody></table></div>"
                   f"<p>Subtotal <b>{money(subtotal)} dataset units</b></p>"
                   f"<p>Coupon discount ({percent:g}%) <b>−{money(discount)} dataset units</b></p>"
                   f"<p style='font-size:20px'>Preview total <b>{money(total)} dataset units</b></p>"
                   "<p class='muted'>No currency is specified by the source data.</p></section>"
                   "<section><h3>Coupon</h3>" + coupon_form +
                   "<h3>Payment method preview</h3><label>Choose a method<select disabled>"
                   "<option>Cash</option><option>Credit card</option><option>E-wallet</option></select></label>"
                   "<p class='notice checkout-note'>Payment processing is not connected. No payment details are requested or stored.</p>"
                   "<a class='button secondary' href='/cart'>Back to cart</a></section></div>")
        self.send_html(page("Checkout preview", content, user))

    def respond_offer_zone(self, user: dict | None):
        _, csrf, set_cookie = self.cart_identity(user)
        offers = get_offers()
        body = ("<p class='eyebrow'>Deals for the shop</p><h2>Offer Zone</h2>"
                "<p class='muted'>Browse current offers on different products.</p>" +
                render_offers(offers, csrf, can_add_to_cart=not user or user["role"] == "customer") + ("<a class='button secondary' href='/dashboard'>Back to dashboard</a>" if user else "<a class='button secondary' href='/guest'>Guest overview</a>"))
        headers = {"Set-Cookie": set_cookie} if set_cookie else None
        self.send_html(page("Offer Zone", body, user), extra_headers=headers)

    def log_message(self, format, *args):
        # Keep request paths and submitted credentials out of the console log.
        return


def create_admin() -> None:
    ensure_schema()
    username = input("Admin username (3–40 letters, numbers, dot, dash, underscore): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise SystemExit("Invalid username format.")
    password = getpass("Admin password (at least 10 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation or len(password) < 10 or len(password) > 256:
        raise SystemExit("Passwords must match and be 10–256 characters.")
    salt, password_hash = hash_password(password)
    with closing(connect()) as connection:
        try:
            connection.execute(
                "INSERT INTO dashboard_users(username, role, password_salt, password_hash) VALUES (?, 'admin', ?, ?)",
                (username, salt, password_hash),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            raise SystemExit("That username already exists.")
    print(f"Admin account '{username}' created in {DATABASE_PATH}.")


def create_initial_admin_from_environment() -> None:
    username = os.environ.get("MARKET_PULSE_INITIAL_ADMIN_USERNAME", "").strip()
    password = os.environ.get("MARKET_PULSE_INITIAL_ADMIN_PASSWORD", "")
    if not username and not password:
        return
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
        raise SystemExit("MARKET_PULSE_INITIAL_ADMIN_USERNAME must be 3–40 letters, numbers, dots, dashes, or underscores.")
    if len(password) < 10 or len(password) > 256:
        raise SystemExit("MARKET_PULSE_INITIAL_ADMIN_PASSWORD must be 10–256 characters.")
    with closing(connect()) as connection, connection:
        admin_exists = connection.execute(
            "SELECT 1 FROM dashboard_users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
        if admin_exists:
            return
        salt, password_hash = hash_password(password)
        connection.execute(
            "INSERT INTO dashboard_users(username, role, password_salt, password_hash) "
            "VALUES (?, 'admin', ?, ?)",
            (username, salt, password_hash),
        )
    print(f"Created initial admin account '{username}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-admin", action="store_true", help="Interactively create the first/admin account")
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    parser.add_argument("--host", default=default_host, help="Bind address (default: local machine only)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    initialize()
    ensure_schema()
    if args.create_admin:
        create_admin()
        return
    create_initial_admin_from_environment()
    server = HTTPServer((args.host, args.port), DashboardHandler)
    print(f"Dashboard available at http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
