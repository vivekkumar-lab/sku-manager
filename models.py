"""
Database layer for SKU Manager web app.
SQLite via stdlib sqlite3 — no ORM.
"""

import sqlite3, json, os, secrets, hashlib
from datetime import datetime, timedelta

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "sku_manager.db")
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                email       TEXT PRIMARY KEY,
                name        TEXT DEFAULT '',
                role        TEXT DEFAULT 'user',
                created_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS otp_sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT NOT NULL,
                otp_hash    TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                attempts    INTEGER DEFAULT 0,
                used        INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS requests (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id      TEXT UNIQUE,
                email           TEXT,
                requester_name  TEXT,
                request_type    TEXT,
                brand           TEXT,
                details         TEXT,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT,
                updated_at      TEXT,
                generated_skus  TEXT,
                csv_content     TEXT,
                admin_notes     TEXT
            );

            CREATE TABLE IF NOT EXISTS products (
                code        TEXT PRIMARY KEY,
                name        TEXT,
                brand_raw   TEXT,
                enabled     INTEGER,
                item_type   TEXT,
                mrp         TEXT,
                hsn         TEXT,
                sku_category TEXT,
                ean         TEXT
            );

            CREATE TABLE IF NOT EXISTS bundle_components (
                bundle_code     TEXT,
                component_code  TEXT,
                qty             TEXT,
                price           TEXT
            );

            CREATE TABLE IF NOT EXISTS pool_overrides (
                brand_pool  TEXT PRIMARY KEY,
                max_serial  INTEGER
            );
        """)


# ── OTP ───────────────────────────────────────────────────────────────────────

def _hash_otp(otp):
    return hashlib.sha256(otp.encode()).hexdigest()


def create_otp_session(email, otp):
    """Store a new OTP session. Returns session id."""
    h = _hash_otp(otp)
    expires = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    with get_db() as conn:
        # Invalidate previous unused OTPs for this email
        conn.execute("UPDATE otp_sessions SET used=1 WHERE email=? AND used=0", (email,))
        cur = conn.execute(
            "INSERT INTO otp_sessions (email, otp_hash, expires_at) VALUES (?,?,?)",
            (email, h, expires)
        )
        return cur.lastrowid


def verify_otp(email, otp):
    """Verify OTP. Returns True on success, False on failure/expiry. Marks as used on success."""
    h = _hash_otp(otp)
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, attempts, used, expires_at
               FROM otp_sessions
               WHERE email=? AND used=0
               ORDER BY id DESC LIMIT 1""",
            (email,)
        ).fetchone()
        if not row:
            return False
        if row["used"] or row["attempts"] >= 3 or row["expires_at"] < now:
            return False
        conn.execute(
            "UPDATE otp_sessions SET attempts = attempts + 1 WHERE id=?",
            (row["id"],)
        )
        actual = conn.execute(
            "SELECT otp_hash FROM otp_sessions WHERE id=?", (row["id"],)
        ).fetchone()["otp_hash"]
        if actual != h:
            return False
        conn.execute("UPDATE otp_sessions SET used=1 WHERE id=?", (row["id"],))
        return True


# ── Users ─────────────────────────────────────────────────────────────────────

def get_or_create_user(email, name=""):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row:
            return dict(row)
        conn.execute(
            "INSERT INTO users (email, name, role, created_at) VALUES (?,?,?,?)",
            (email, name, "user", datetime.utcnow().isoformat())
        )
        return {"email": email, "name": name, "role": "user"}


def is_admin(email, admin_emails_env):
    admins = [a.strip().lower() for a in admin_emails_env.split(",") if a.strip()]
    return email.lower() in admins


# ── Requests ──────────────────────────────────────────────────────────────────

def _next_request_id():
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM requests").fetchone()
        return f"REQ-{(row['c'] + 1):04d}"


def create_request(email, requester_name, request_type, brand, details_dict):
    rid = _next_request_id()
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO requests
               (request_id, email, requester_name, request_type, brand, details, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, email, requester_name, request_type, brand,
             json.dumps(details_dict), now, now)
        )
    return rid


def get_requests(status=None, email=None):
    with get_db() as conn:
        if status and email:
            rows = conn.execute(
                "SELECT * FROM requests WHERE status=? AND email=? ORDER BY id DESC",
                (status, email)
            ).fetchall()
        elif status:
            rows = conn.execute(
                "SELECT * FROM requests WHERE status=? ORDER BY id DESC", (status,)
            ).fetchall()
        elif email:
            rows = conn.execute(
                "SELECT * FROM requests WHERE email=? ORDER BY id DESC", (email,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM requests ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_request(request_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM requests WHERE request_id=?", (request_id,)
        ).fetchone()
    return dict(row) if row else None


def update_request(request_id, **kwargs):
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    cols = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [request_id]
    with get_db() as conn:
        conn.execute(f"UPDATE requests SET {cols} WHERE request_id=?", vals)


# ── Product catalog ───────────────────────────────────────────────────────────

def save_catalog(catalog, bundles):
    """Replace entire product catalog in DB."""
    with get_db() as conn:
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM bundle_components")
        for code, item in catalog.items():
            conn.execute(
                """INSERT OR REPLACE INTO products
                   (code, name, brand_raw, enabled, item_type, mrp, hsn, sku_category, ean)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (code, item["name"], item.get("brand_raw", ""),
                 1 if item["enabled"] else 0,
                 item.get("type", ""), item.get("mrp", ""),
                 item.get("hsn", ""), item.get("sku_category", ""),
                 item.get("ean", ""))
            )
        for bundle_code, comps in bundles.items():
            for comp_code, qty, price in comps:
                conn.execute(
                    "INSERT INTO bundle_components (bundle_code, component_code, qty, price) VALUES (?,?,?,?)",
                    (bundle_code, comp_code, qty, price)
                )


def search_products(query="", brand="", active_only=True, limit=30):
    q = f"%{query.strip().lower()}%"
    conditions = []
    params = []
    if active_only:
        conditions.append("enabled=1")
    if brand:
        conditions.append("code LIKE ?")
        params.append(brand.upper() + "%")
    if query.strip():
        conditions.append("(LOWER(code) LIKE ? OR LOWER(name) LIKE ?)")
        params += [q, q]
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT * FROM products {where} ORDER BY code LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_product(code):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM products WHERE code=?", (code,)).fetchone()
    return dict(row) if row else None


def get_bundles_for_product(comp_code):
    """Return all bundle codes that contain this component."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT bundle_code FROM bundle_components WHERE component_code=?",
            (comp_code,)
        ).fetchall()
    return [r["bundle_code"] for r in rows]


def find_combo_by_components(component_codes):
    """Find any existing bundle that contains exactly this set of components."""
    if not component_codes:
        return []
    codes_upper = [c.upper() for c in component_codes]
    target = frozenset(codes_upper)
    with get_db() as conn:
        bundles = conn.execute(
            "SELECT DISTINCT bundle_code FROM bundle_components"
        ).fetchall()
        matches = []
        for b in bundles:
            bc = b["bundle_code"]
            comps = conn.execute(
                "SELECT component_code FROM bundle_components WHERE bundle_code=?", (bc,)
            ).fetchall()
            bundle_set = frozenset(r["component_code"].upper() for r in comps)
            if bundle_set == target:
                matches.append(bc)
    return matches


# ── Serial pools ──────────────────────────────────────────────────────────────

def get_pools_from_db():
    """Compute pools from the products table, then apply overrides."""
    from sku_logic import BRANDS, TYPE_DEFS, TYPE_ALL_CODES, extract_serial
    from collections import defaultdict
    pools = {b: defaultdict(int) for b in BRANDS}
    with get_db() as conn:
        codes = [r["code"] for r in conn.execute("SELECT code FROM products").fetchall()]
        overrides = {r["brand_pool"]: r["max_serial"]
                     for r in conn.execute("SELECT * FROM pool_overrides").fetchall()}
    for code in codes:
        for brand in BRANDS:
            if not code.upper().startswith(brand.upper()):
                continue
            for tc, defn in TYPE_DEFS.items():
                s = extract_serial(code, brand, TYPE_ALL_CODES[tc])
                if s:
                    pools[brand][defn["pool"]] = max(pools[brand][defn["pool"]], s)
    for key, val in overrides.items():
        brand, pool = key.split(".", 1)
        if brand in pools:
            pools[brand][pool] = max(pools[brand][pool], val)
    return {b: dict(p) for b, p in pools.items()}


def reserve_serial(brand, pool, serial):
    key = f"{brand}.{pool}"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO pool_overrides (brand_pool, max_serial) VALUES (?,?)
               ON CONFLICT(brand_pool) DO UPDATE SET max_serial=MAX(max_serial, excluded.max_serial)""",
            (key, serial)
        )


def get_catalog_count():
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM products").fetchone()
    return row["c"]
