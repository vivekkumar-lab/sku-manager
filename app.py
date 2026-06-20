"""
SKU Manager Web Application
Flask + SQLite + OTP email auth

Environment variables (set in .env):
  SECRET_KEY        — Flask session secret (generate with: python -c "import secrets; print(secrets.token_hex(32))")
  ADMIN_EMAILS      — Comma-separated admin email list
  ALLOWED_DOMAINS   — Comma-separated domains (default: mcaffeine.com)
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS  — Email config
  DB_PATH           — SQLite database path (default: ./sku_manager.db)
"""

import os, json
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, send_file, flash, abort)
from functools import wraps
from io import BytesIO

from dotenv import load_dotenv
load_dotenv()

import models as db
import email_service as mail
from sku_logic import (
    BRANDS, TYPE_DEFS, BRAND_UC,
    generate_product_skus, generate_combo_skus,
    build_simple_rows, build_combo_rows, rows_to_csv_string,
    parse_catalog,
)

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")

ALLOWED_DOMAINS = [d.strip().lower() for d in
                   os.environ.get("ALLOWED_DOMAINS", "mcaffeine.com").split(",") if d.strip()]
ADMIN_EMAILS    = os.environ.get("ADMIN_EMAILS", "")

db.init_db()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def current_user():
    return session.get("user")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()
        if not user or not db.is_admin(user["email"], ADMIN_EMAILS):
            abort(403)
        return f(*args, **kwargs)
    return decorated


def is_allowed_email(email):
    domain = email.strip().lower().split("@")[-1]
    return domain in ALLOWED_DOMAINS


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if current_user():
        user = current_user()
        if db.is_admin(user["email"], ADMIN_EMAILS):
            return redirect(url_for("admin"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login")
def login():
    if current_user():
        return redirect(url_for("index"))
    step = request.args.get("step", "email")
    email = request.args.get("email", "")
    error = request.args.get("error", "")
    return render_template("login.html", step=step, email=email, error=error)


@app.route("/login/send-otp", methods=["POST"])
def send_otp():
    email = request.form.get("email", "").strip().lower()
    if not email or "@" not in email:
        return redirect(url_for("login", error="Enter a valid email address."))
    if not is_allowed_email(email):
        domain = ", ".join(f"@{d}" for d in ALLOWED_DOMAINS)
        return redirect(url_for("login", error=f"Only {domain} emails are allowed."))

    otp = mail.generate_otp()
    ok, err = mail.send_otp(email, otp)
    if not ok:
        return redirect(url_for("login", error=f"Could not send email: {err}"))

    db.create_otp_session(email, otp)
    return redirect(url_for("login", step="verify", email=email))


@app.route("/login/verify", methods=["POST"])
def verify_otp():
    email = request.form.get("email", "").strip().lower()
    otp   = request.form.get("otp", "").strip()

    if not db.verify_otp(email, otp):
        return redirect(url_for("login", step="verify", email=email,
                                error="Invalid or expired code. Try again."))

    user = db.get_or_create_user(email)
    session["user"] = user
    session.permanent = True

    if db.is_admin(email, ADMIN_EMAILS):
        return redirect(url_for("admin"))
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── User dashboard ────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    reqs = db.get_requests(email=user["email"])
    catalog_count = db.get_catalog_count()
    return render_template("dashboard.html", user=user, requests=reqs,
                           brands=BRANDS, type_defs=TYPE_DEFS,
                           catalog_count=catalog_count,
                           is_admin=db.is_admin(user["email"], ADMIN_EMAILS))


# ── Request submission ────────────────────────────────────────────────────────

@app.route("/request/submit", methods=["POST"])
@login_required
def submit_request():
    user = current_user()
    req_type = request.form.get("request_type")
    brand    = request.form.get("brand", "").upper()

    if req_type == "new_combo":
        comps_json = request.form.get("components_json", "[]")
        try:
            components = json.loads(comps_json)
        except Exception:
            return jsonify({"error": "Invalid components data."}), 400

        comp_codes = [c["code"] for c in components]
        if len(comp_codes) < 2:
            return jsonify({"error": "A combo needs at least 2 products."}), 400

        # Duplicate check
        existing = db.find_combo_by_components(comp_codes)
        if existing:
            return jsonify({"error": f"This combo already exists: {', '.join(existing)}"}), 409

        details = {
            "combo_type": request.form.get("combo_type", "COMB"),
            "name":       request.form.get("combo_name", ""),
            "components": components,
            "mrp":        request.form.get("mrp", ""),
            "hsn":        request.form.get("hsn", ""),
            "notes":      request.form.get("notes", ""),
        }
        rid = db.create_request(user["email"], user.get("name", user["email"]),
                                "new_combo", brand, details)

    elif req_type == "new_sku":
        details = {
            "types":    request.form.getlist("types"),
            "filling":  request.form.get("filling", ""),
            "name":     request.form.get("product_name", ""),
            "mrp":      request.form.get("mrp", ""),
            "hsn":      request.form.get("hsn", ""),
            "ean":      request.form.get("ean", ""),
            "variant":  request.form.get("is_variant", "") == "yes",
            "existing_serial": request.form.get("existing_serial", ""),
            "notes":    request.form.get("notes", ""),
        }
        rid = db.create_request(user["email"], user.get("name", user["email"]),
                                "new_sku", brand, details)

    elif req_type == "new_pm":
        details = {
            "pm_type":      request.form.get("pm_type", ""),
            "description":  request.form.get("description", ""),
            "notes":        request.form.get("notes", ""),
        }
        rid = db.create_request(user["email"], user.get("name", user["email"]),
                                "new_pm", brand, details)
    else:
        return jsonify({"error": "Unknown request type."}), 400

    return jsonify({"success": True, "request_id": rid})


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/products")
@login_required
def api_products():
    q       = request.args.get("q", "")
    brand   = request.args.get("brand", "")
    active  = request.args.get("active", "1") == "1"
    results = db.search_products(q, brand, active_only=active)
    return jsonify(results)


@app.route("/api/check-combo")
@login_required
def api_check_combo():
    codes_raw = request.args.get("codes", "")
    codes = [c.strip() for c in codes_raw.split(",") if c.strip()]
    if len(codes) < 2:
        return jsonify({"exists": False})
    existing = db.find_combo_by_components(codes)
    if existing:
        return jsonify({"exists": True, "bundles": existing})
    return jsonify({"exists": False})


@app.route("/api/registry")
@login_required
def api_registry():
    pools = db.get_pools_from_db()
    registry = []
    for brand, brand_pools in pools.items():
        for pool, serial in sorted(brand_pools.items()):
            registry.append({
                "brand": brand, "pool": pool,
                "current": serial, "next": serial + 1
            })
    return jsonify(registry)


# ── Admin panel ───────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin():
    user = current_user()
    status_filter = request.args.get("status", "pending")
    if status_filter == "all":
        reqs = db.get_requests()
    else:
        reqs = db.get_requests(status=status_filter)

    counts = {
        "pending":  len(db.get_requests(status="pending")),
        "approved": len(db.get_requests(status="approved")),
        "rejected": len(db.get_requests(status="rejected")),
        "all":      len(db.get_requests()),
    }
    catalog_count = db.get_catalog_count()
    return render_template("admin.html", user=user, requests=reqs,
                           brands=BRANDS, type_defs=TYPE_DEFS,
                           status_filter=status_filter, counts=counts,
                           catalog_count=catalog_count,
                           is_admin=True)


@app.route("/admin/upload-csv", methods=["POST"])
@admin_required
def upload_csv():
    f = request.files.get("csv_file")
    if not f:
        return jsonify({"error": "No file uploaded."}), 400
    try:
        content = f.read().decode("utf-8-sig")
        catalog, bundles, _, _ = parse_catalog(content)
        db.save_catalog(catalog, bundles)
        return jsonify({"success": True, "products": len(catalog), "bundles": len(bundles)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/generate/<request_id>", methods=["POST"])
@admin_required
def generate_sku(request_id):
    req = db.get_request(request_id)
    if not req:
        return jsonify({"error": "Request not found."}), 404
    if req["status"] == "approved":
        return jsonify({"error": "Already approved."}), 400

    details = json.loads(req["details"])
    brand   = req["brand"]
    pools   = db.get_pools_from_db()
    overrides = {}  # overrides are already merged into pools by get_pools_from_db

    try:
        if req["request_type"] == "new_combo":
            combo_type  = details.get("combo_type", "COMB")
            components  = details.get("components", [])
            comp_tuples = [(c["code"], c.get("qty", 1), c.get("price", "")) for c in components]
            count       = len(components)
            serial, base, simple = generate_combo_skus(pools, overrides, brand, combo_type, count)
            db.reserve_serial(brand, TYPE_DEFS[combo_type]["pool"], serial)

            rows = build_combo_rows(
                base, simple, details.get("name", ""), brand, comp_tuples,
                details.get("mrp", ""), details.get("hsn", "")
            )
            csv_content = rows_to_csv_string(rows)
            skus = [base, simple]

        elif req["request_type"] == "new_sku":
            types    = details.get("types", ["MUBX"])
            filling  = details.get("filling", "")
            existing = details.get("existing_serial") or None
            serial, skus = generate_product_skus(pools, overrides, brand, types, filling, existing)
            if not existing:
                db.reserve_serial(brand, TYPE_DEFS[types[0]]["pool"], serial)

            rows = build_simple_rows(skus[0], details.get("name", ""), brand,
                                     details.get("mrp", ""), details.get("hsn", ""),
                                     details.get("ean", ""))
            if len(skus) > 1:
                for s in skus[1:]:
                    rows += build_simple_rows(s, details.get("name", ""), brand,
                                              details.get("mrp", ""), details.get("hsn", ""),
                                              details.get("ean", ""))
            csv_content = rows_to_csv_string(rows)

        elif req["request_type"] == "new_pm":
            pm_type = details.get("pm_type", "BOXT")
            serial, [sku] = generate_product_skus(pools, overrides, brand, [pm_type], None)
            db.reserve_serial(brand, TYPE_DEFS[pm_type]["pool"], serial)
            rows = build_simple_rows(sku, details.get("description", ""), brand)
            csv_content = rows_to_csv_string(rows)
            skus = [sku]
        else:
            return jsonify({"error": "Unknown request type."}), 400

        db.update_request(request_id,
                          status="approved",
                          generated_skus=json.dumps(skus),
                          csv_content=csv_content)
        return jsonify({"success": True, "skus": skus, "serial": serial})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/reject/<request_id>", methods=["POST"])
@admin_required
def reject_request(request_id):
    notes = request.json.get("notes", "") if request.is_json else request.form.get("notes", "")
    db.update_request(request_id, status="rejected", admin_notes=notes)
    return jsonify({"success": True})


@app.route("/admin/download/<request_id>")
@admin_required
def download_csv(request_id):
    req = db.get_request(request_id)
    if not req or not req.get("csv_content"):
        abort(404)
    buf = BytesIO(req["csv_content"].encode("utf-8"))
    skus = json.loads(req["generated_skus"] or "[]")
    filename = f"UC_{skus[0] if skus else request_id}.csv"
    return send_file(buf, mimetype="text/csv",
                     as_attachment=True, download_name=filename)


# ── Misc ──────────────────────────────────────────────────────────────────────

@app.template_filter("pretty_date")
def pretty_date(iso):
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d %b %Y, %H:%M")
    except Exception:
        return iso


@app.template_filter("from_json")
def from_json(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
