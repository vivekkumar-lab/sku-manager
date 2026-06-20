"""
SKU Management System — Business Logic (no GUI, no I/O)
All constants, serial extraction, SKU generation, and Unicommerce export.
"""

import csv, re, io
from collections import defaultdict

BRANDS = {"HYP": "Hyphen", "MCF": "mCaffeine", "DND": "Drip N Dip"}
BRAND_UC = {"HYP": "HYPHEN", "MCF": "mCaffeine", "DND": "Drip N Dip"}

TYPE_DEFS = {
    "MUBX": dict(name="Main Unit (Box)",    pool="MAIN", has_f=True,  s_pair=False, filling="volume"),
    "MUWB": dict(name="Main Unit (No Box)", pool="MAIN", has_f=True,  s_pair=False, filling="volume"),
    "COMB": dict(name="Combo",              pool="COMB", has_f=True,  s_pair=True,  filling="count"),
    "GKIT": dict(name="Giftkit",            pool="GKIT", has_f=True,  s_pair=True,  filling="count"),
    "MNPK": dict(name="Miniature Pack",     pool="MNPK", has_f=True,  s_pair=True,  filling="count"),
    "TOBX": dict(name="ToolBox",            pool="TOBX", has_f=True,  s_pair=False, filling="count"),
    "TOOL": dict(name="Tools",              pool="TOOL", has_f=False, s_pair=False, filling=None),
    "KTBX": dict(name="Kitbox",             pool="KTBX", has_f=False, s_pair=False, filling=None),
    "BOXT": dict(name="Box (D2C)",          pool="BOXT", has_f=False, s_pair=False, filling=None),
    "CRTN": dict(name="Master Carton",      pool="CRTN", has_f=False, s_pair=False, filling=None),
    "SHPR": dict(name="Shipper",            pool="SHPR", has_f=False, s_pair=False, filling=None),
    "TAPE": dict(name="Tape",               pool="TAPE", has_f=False, s_pair=False, filling=None),
    "STKR": dict(name="Sticker",            pool="STKR", has_f=False, s_pair=False, filling=None),
    "WRAP": dict(name="Bubble Wrap",        pool="WRAP", has_f=False, s_pair=False, filling=None),
    "BOTL": dict(name="Card / Bottle",      pool="BOTL", has_f=False, s_pair=False, filling=None),
    "PBAG": dict(name="Paper Bag",          pool="PBAG", has_f=False, s_pair=False, filling=None),
    "SHRK": dict(name="Shrink",             pool="SHRK", has_f=False, s_pair=False, filling=None),
}

LEGACY_MAP = {"TBOX": "BOXT", "MCRN": "CRTN", "CARD": "BOTL", "TLBX": "TOBX", "SCMB": "MNPK"}

TYPE_ALL_CODES = {tc: [tc] for tc in TYPE_DEFS}
for _old, _new in LEGACY_MAP.items():
    if _new in TYPE_ALL_CODES:
        TYPE_ALL_CODES[_new].append(_old)

UC_COLUMNS = [
    "Category Code*", "Product Code*", "Name*", "Description", "Scan Identifier",
    "Length (mm)", "Width (mm)", "height (mm)", "Weight (gms)",
    "ean", "upc", "isbn", "color", "brand", "size",
    "Requires Customization", "Min Order Size",
    "Tax Type Code", "GST Tax Type Code", "HSN CODE",
    "Tags", "TAT", "Image Url", "Product Page URL", "Item Detail Fields",
    "Cost Price", "MRP", "Base Price",
    "Enabled", "Resync Inventory", "Type", "Scan Type",
    "Component Product Code", "Component Quantity", "Component Price",
    "Batch Group Code", "Dispatch Expiry Tolerance", "Shelf Life",
    "Tax Calculation Type", "Expirable", "Determine Expiry From",
    "grn Expiry Tolerance", "Return Expiry Tolerance", "Expiry Date as dd/MM/yyyy",
    "Sku Type", "Fragile", "Dangerous Good", "SKU Category",
]

_UC_DEFAULTS = {
    "Min Order Size": "1",
    "GST Tax Type Code": "18",
    "Enabled": "yes",
    "Batch Group Code": "EXP",
    "Shelf Life": "730",
    "Expirable": "1",
    "Determine Expiry From": "Expiry date",
    "Sku Type": "GOODS",
    "Fragile": "No",
    "Dangerous Good": "No",
}


# ── Serial extraction ──────────────────────────────────────────────────────────

def extract_serial(code, brand, type_codes):
    uc = code.upper()
    for tc in type_codes:
        prefix = (brand + tc).upper()
        if uc.startswith(prefix):
            rem = code[len(prefix):]
            m = re.match(r'^(\d+)[FBfb]', rem)
            if m:
                return int(m.group(1))
            m = re.match(r'^(\d{1,4})', rem)
            if m:
                digits = m.group(1)
                after = rem[len(digits):]
                if after and after[0].isdigit():
                    digits = digits[:3]
                return int(digits)
    return 0


def parse_catalog(csv_content_or_path):
    """
    Accepts either a file path (str) or CSV text (str with newlines).
    Returns: (catalog, bundles, comp_to_bundles, pools)
    """
    if "\n" in csv_content_or_path or "\r" in csv_content_or_path:
        reader = csv.DictReader(io.StringIO(csv_content_or_path))
    else:
        with open(csv_content_or_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        reader = csv.DictReader(io.StringIO(content))

    catalog = {}
    bundles = defaultdict(list)
    comp_to_bundles = defaultdict(set)

    for row in reader:
        code = row.get("Product Code", "").strip()
        if not code:
            continue
        row_type = row.get("Type", "").strip()
        enabled_raw = row.get("Enabled", "").strip().lower()

        if code not in catalog:
            catalog[code] = {
                "code": code,
                "name": row.get("Name", "").strip(),
                "brand_raw": row.get("Brand", "").strip(),
                "enabled": enabled_raw == "true",
                "type": row_type,
                "mrp": row.get("MRP", "").strip(),
                "hsn": row.get("HSN CODE", "").strip(),
                "sku_category": row.get("SKU Category", "").strip(),
                "ean": row.get("EAN", "").strip(),
            }

        if row_type == "BUNDLE":
            comp = row.get("Component Product Code", "").strip()
            qty = row.get("Component Quantity", "").strip()
            price = row.get("Component Price", "").strip()
            if comp:
                bundles[code].append((comp, qty, price))
                comp_to_bundles[comp].add(code)

    pools = {b: defaultdict(int) for b in BRANDS}
    for code in catalog:
        for brand in BRANDS:
            if not code.upper().startswith(brand.upper()):
                continue
            for tc, defn in TYPE_DEFS.items():
                s = extract_serial(code, brand, TYPE_ALL_CODES[tc])
                if s:
                    pools[brand][defn["pool"]] = max(pools[brand][defn["pool"]], s)

    return (
        catalog,
        dict(bundles),
        {k: list(v) for k, v in comp_to_bundles.items()},
        {b: dict(p) for b, p in pools.items()},
    )


# ── SKU generation ─────────────────────────────────────────────────────────────

def make_sku(brand, type_code, serial, filling=None):
    defn = TYPE_DEFS[type_code]
    base = f"{brand}{type_code}{serial:04d}"
    if defn["has_f"]:
        if filling is None or str(filling).strip() == "":
            filling = "0001"
        filling = str(filling).strip()
        if filling.isdigit():
            filling = f"{int(filling):04d}"
        return base + "F" + filling.upper()
    return base


def pool_next_serial(pools, brand, pool_key, overrides):
    current = pools.get(brand, {}).get(pool_key, 0)
    ov_key = f"{brand}.{pool_key}"
    current = max(current, overrides.get(ov_key, 0))
    return current + 1


def generate_product_skus(pools, overrides, brand, type_codes, filling, existing_serial=None):
    if existing_serial is not None:
        serial = int(existing_serial)
    else:
        pool = TYPE_DEFS[type_codes[0]]["pool"]
        serial = pool_next_serial(pools, brand, pool, overrides)
    skus = [make_sku(brand, tc, serial, filling) for tc in type_codes]
    return serial, skus


def generate_combo_skus(pools, overrides, brand, type_code, component_count):
    pool = TYPE_DEFS[type_code]["pool"]
    serial = pool_next_serial(pools, brand, pool, overrides)
    base = make_sku(brand, type_code, serial, component_count)
    return serial, base, base + "_S"


# ── Unicommerce export ─────────────────────────────────────────────────────────

def _blank_row(code, name, brand_uc, mrp, hsn, ean, cat_code, sku_cat, row_type):
    row = {col: "" for col in UC_COLUMNS}
    row.update(_UC_DEFAULTS)
    row.update({
        "Category Code*": cat_code,
        "Product Code*": code,
        "Name*": name,
        "Scan Identifier": ean if ean else code,
        "ean": ean,
        "brand": brand_uc,
        "MRP": mrp,
        "HSN CODE": hsn,
        "Type": row_type,
        "SKU Category": sku_cat,
        "Tax Calculation Type": "PRICE_OF_BUNDLE_SKU" if row_type == "BUNDLE" else "",
    })
    return row


def build_simple_rows(code, name, brand_code, mrp="", hsn="", ean=""):
    brand_uc = BRAND_UC.get(brand_code, brand_code)
    return [_blank_row(code, name, brand_uc, mrp, hsn, ean, "SINGLE", "MAIN", "SIMPLE")]


def build_combo_rows(base_code, simple_code, name, brand_code, components, mrp="", hsn="", ean=""):
    brand_uc = BRAND_UC.get(brand_code, brand_code)
    rows = []
    for comp_code, qty, price in components:
        row = _blank_row(base_code, name, brand_uc, mrp, hsn, ean, "COMBO", "COMBO", "BUNDLE")
        row["Component Product Code"] = comp_code
        row["Component Quantity"] = str(qty)
        row["Component Price"] = str(price) if price else ""
        rows.append(row)
    rows.append(_blank_row(simple_code, name, brand_uc, mrp, hsn, ean,
                           "COMBO_PACKED", "COMBO_PACKED", "SIMPLE"))
    return rows


def rows_to_csv_string(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=UC_COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def find_existing_combo(bundles, component_codes):
    """Return list of bundle codes that contain exactly the given set of components."""
    target = frozenset(c.upper() for c in component_codes)
    matches = []
    for bundle, comps in bundles.items():
        bundle_comps = frozenset(c.upper() for c, _, _ in comps)
        if bundle_comps == target:
            matches.append(bundle)
    return matches
