"""
config_store.py — definisi modul, katalog kolom, dan pilihan kolom per modul.

PENTING (desain gabungan / Opsi B):
  - Kredensial (Odoo + BigQuery) HANYA dari environment variable.
    Tidak ada override lewat UI, tidak ada upload service-account key.
  - Yang disimpan ke config/config.json HANYA pilihan kolom per modul
    (selected/table/domain) — bukan rahasia apa pun.

Env yang dibaca:
  ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY
  BQ_PROJECT, BQ_DATASET, BQ_LOCATION
  GOOGLE_APPLICATION_CREDENTIALS (path) atau
    GOOGLE_SERVICE_ACCOUNT_JSON / BQ_SA_JSON (isi JSON) — opsional
  CRON_TOKEN — token pengaman endpoint cron (opsional)

Katalog field (katalog_fields_odoo.json) jadi sumber daftar kolom yang tampil
di UI, sehingga checklist langsung terisi tanpa perlu memanggil Odoo dulu.
"""

import json
import os
from copy import deepcopy
from pathlib import Path

BASE_DIR = Path(__file__).parent

# --- Muat app.env (satu file berisi SEMUA environment variable) sebelum env dibaca ---
# override=False: env yang SUDAH ada (mis. dari platform Railway atau dari shell) menang,
# file hanya mengisi yang kosong. Jadi kode yang sama jalan di Railway (tanpa file) maupun
# di Hostinger/lokal (dengan file). Dibungkus try supaya kalau python-dotenv belum
# terpasang, program tetap jalan dengan env dari OS/platform.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / "app.env", override=False)
except Exception:
    pass

CONFIG_DIR = Path(os.environ.get("OBQ_CONFIG_DIR", BASE_DIR / "config"))
CONFIG_FILE = CONFIG_DIR / "config.json"
CATALOG_FILE = BASE_DIR / "katalog_fields_odoo.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Filter baris yang ditarik dari Odoo.
# CONTOH demo — ganti dengan kriteria organisasi Anda (mis. nama company /
# cabang tertentu), atau pakai [] untuk menarik semua baris.
FILTER_COMPANY = ["company_id.name", "=like", "Demo Company%"]

# Tipe Odoo yang tak cocok dimuat ke satu sel BigQuery -> dinonaktifkan di UI.
_DISABLED_TYPES = {"binary", "one2many"}
_TYPE_NOTE = {
    "many2one": "relasi → nama",
    "many2many": "daftar; tag → nama",
    "one2many": "dilewati: daftar baris relasi",
    "binary": "dilewati: data biner/lampiran",
    "json": "disimpan sebagai teks",
    "selection": "nilai pilihan",
}


def classify_type(t: str):
    return (t not in _DISABLED_TYPES), _TYPE_NOTE.get(t, "")


# ----------------------------------------------------------------- Definisi modul
# default_fields + default_rename = kolom yang TERCENTANG secara default.
MODULE_DEFS = [
    {
        "key": "crm_lead", "label": "CRM Lead", "model": "crm.lead", "move_type": None,
        "domain": [FILTER_COMPANY],
        "table": "crm_lead_staging",
        "default_fields": [
            "name", "stage_id", "type", "won_status", "active", "probability",
            "expected_revenue", "date_open", "date_deadline", "date_closed",
            "date_last_stage_update", "create_date", "user_id", "team_id",
            "company_id", "partner_id", "partner_name", "contact_name", "city",
            "country_id", "source_id", "medium_id", "campaign_id", "priority",
            "tag_ids", "lost_reason_id", "sale_amount_total", "sale_order_count",
            "x_studio_sales_rep", "x_studio_lead_category",
        ],
        "default_rename": {
            "stage_id": "stage", "won_status": "won_lost_status",
            "user_id": "salesperson_odoo", "x_studio_sales_rep": "sales_rep",
            "team_id": "sales_team", "company_id": "company_branch",
            "partner_id": "customer_contact", "partner_name": "customer_company",
            "source_id": "source", "medium_id": "medium", "campaign_id": "campaign",
            "tag_ids": "tags", "lost_reason_id": "lost_reason",
            "x_studio_lead_category": "lead_category", "sale_amount_total": "sum_of_orders",
            "sale_order_count": "order_count", "create_date": "created_at",
            "date_open": "assigned_at", "date_deadline": "expected_closing",
            "date_closed": "closed_at", "date_last_stage_update": "last_stage_update_at",
        },
    },
    {
        "key": "customer_invoice", "label": "Customer Invoice", "model": "account.move",
        "move_type": "out_invoice",
        "domain": [FILTER_COMPANY, ["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
        "table": "customer_invoice_staging",
        "default_fields": [
            "name", "move_type", "state", "ref", "invoice_date", "invoice_date_due",
            "create_date", "partner_id", "invoice_user_id", "team_id", "company_id",
            "amount_untaxed", "amount_tax", "amount_total", "amount_residual",
            "payment_state", "invoice_origin", "x_studio_branch",
            "x_studio_document_subtype",
        ],
        "default_rename": {
            "name": "invoice_number", "move_type": "document_type", "state": "invoice_status",
            "ref": "reference", "invoice_date_due": "due_date", "create_date": "created_at",
            "partner_id": "customer", "invoice_user_id": "salesperson", "team_id": "sales_team",
            "company_id": "company_branch", "amount_untaxed": "amount_before_tax",
            "amount_tax": "tax_amount", "amount_residual": "amount_unpaid",
            "payment_state": "payment_status", "invoice_origin": "source_document",
            "x_studio_branch": "branch",
            "x_studio_document_subtype": "document_subtype",
        },
    },
    {
        "key": "vendor_bill", "label": "Vendor Bill", "model": "account.move",
        "move_type": "in_invoice",
        "domain": [FILTER_COMPANY, ["move_type", "=", "in_invoice"], ["state", "=", "posted"]],
        "table": "vendor_bill_staging",
        "default_fields": [
            "name", "ref", "move_type", "state", "invoice_date", "invoice_date_due",
            "create_date", "partner_id", "user_id", "company_id", "invoice_origin",
            "amount_untaxed", "amount_tax", "amount_total", "amount_residual_signed",
            "payment_state", "journal_id", "x_studio_branch", "x_studio_note",
        ],
        "default_rename": {
            "name": "bill_number", "ref": "vendor_reference", "move_type": "document_type",
            "state": "bill_status", "invoice_date": "bill_date", "invoice_date_due": "due_date",
            "create_date": "created_at", "partner_id": "vendor", "user_id": "input_by",
            "company_id": "company_branch", "invoice_origin": "source_document",
            "amount_untaxed": "amount_before_tax", "amount_tax": "tax_amount",
            "amount_total": "amount_total", "amount_residual_signed": "amount_unpaid",
            "payment_state": "payment_status", "journal_id": "journal",
            "x_studio_branch": "branch", "x_studio_note": "note",
        },
    },
    {
        "key": "sale_order", "label": "Sales Order", "model": "sale.order", "move_type": None,
        "domain": [FILTER_COMPANY],
        "table": "sale_order_staging",
        "default_fields": [
            # identitas & tanggal
            "name", "date_order", "create_date", "validity_date", "commitment_date",
            # status
            "state", "invoice_status", "delivery_status",
            # pihak & tim
            "partner_id", "user_id", "team_id", "company_id",
            # nilai uang
            "amount_untaxed", "amount_tax", "amount_total",
            # referensi & sumber
            "client_order_ref", "origin", "campaign_id",
            # kolom kustom (x_studio)
            "x_studio_branch", "x_studio_sales_rep",
        ],
        "default_rename": {
            "name": "order_number",
            "date_order": "order_date",
            "create_date": "created_at",
            "validity_date": "quotation_expiry",
            "commitment_date": "delivery_date",
            "state": "order_status",
            "partner_id": "customer",
            "user_id": "salesperson",
            "team_id": "sales_team",
            "company_id": "company_branch",
            "amount_untaxed": "amount_before_tax",
            "amount_tax": "tax_amount",
            "client_order_ref": "customer_reference",
            "origin": "source_document",
            "campaign_id": "campaign",
            "x_studio_branch": "branch",
            "x_studio_sales_rep": "sales_rep",
        },
    },
]
MODULE_KEYS = [m["key"] for m in MODULE_DEFS]


def _default_module_state(d: dict) -> dict:
    """Susun state modul awal: kolom default tercentang + nama BigQuery-nya."""
    selected = {f: d["default_rename"].get(f, f) for f in d["default_fields"]}
    return {
        "key": d["key"], "label": d["label"], "model": d["model"],
        "move_type": d["move_type"], "domain": deepcopy(d["domain"]),
        "table": d["table"], "selected": selected,
    }


def _default_config() -> dict:
    return {"modules": [_default_module_state(d) for d in MODULE_DEFS]}


# ----------------------------------------------------------------- Katalog kolom
_catalog_cache = None


def load_catalog() -> dict:
    global _catalog_cache
    if _catalog_cache is None:
        try:
            _catalog_cache = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _catalog_cache = {}
    return _catalog_cache


def catalog_columns(module_key: str) -> list:
    """Daftar kolom tersedia dari katalog untuk satu modul (untuk UI)."""
    cat = load_catalog().get(module_key, {})
    cols = []
    for f in cat.get("fields", []):
        t = f.get("tipe", "")
        loadable, note = classify_type(t)
        cols.append({
            "name": f.get("nama_teknis"), "label": f.get("label") or f.get("nama_teknis"),
            "type": t, "loadable": loadable, "note": note,
            "in_use": bool(f.get("sedang_dipakai")),
        })
    cols.sort(key=lambda c: (not c["loadable"], c["label"].lower()))
    return cols


# ----------------------------------------------------------------- Baca/tulis config
def _read_raw() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_raw(cfg: dict):
    to_save = {"modules": cfg.get("modules", [])}
    CONFIG_FILE.write_text(json.dumps(to_save, indent=2, ensure_ascii=False), encoding="utf-8")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    """Config yang disimpan hanya berisi pilihan kolom per modul."""
    raw = _read_raw()
    cfg = {"modules": raw.get("modules") or _default_config()["modules"]}
    # pastikan ketiga modul selalu ada (kalau file lama belum lengkap)
    have = {m["key"] for m in cfg["modules"]}
    for d in MODULE_DEFS:
        if d["key"] not in have:
            cfg["modules"].append(_default_module_state(d))
    return cfg


def save_module(key: str, patch: dict) -> dict:
    """Perbarui satu modul (selected/table/domain)."""
    cfg = load_config()
    for m in cfg["modules"]:
        if m["key"] == key:
            m.update({k: v for k, v in patch.items() if k in ("selected", "table", "domain", "model")})
            break
    _write_raw(cfg)
    return load_config()


def reset_module(key: str) -> dict:
    cfg = load_config()
    d = next((x for x in MODULE_DEFS if x["key"] == key), None)
    if d:
        cfg["modules"] = [_default_module_state(d) if m["key"] == key else m for m in cfg["modules"]]
        _write_raw(cfg)
    return load_config()


def module_by_key(key: str) -> dict:
    for m in load_config()["modules"]:
        if m["key"] == key:
            return m
    return None


# ----------------------------------------------------------------- Kredensial (ENV SAJA)
def _env(name, default=""):
    return os.environ.get(name, default) or default


def effective_odoo() -> dict:
    return {
        "url": _env("ODOO_URL"),
        "db": _env("ODOO_DB"),
        "username": _env("ODOO_USERNAME"),
        "api_key": _env("ODOO_API_KEY"),
    }


def effective_bq() -> dict:
    return {
        "project_id": _env("BQ_PROJECT"),
        "dataset": _env("BQ_DATASET", "odoo_staging"),
        "location": _env("BQ_LOCATION", "asia-southeast2"),
        "write_mode": _env("BQ_WRITE_MODE", "WRITE_TRUNCATE"),
        "batch_size": int(_env("BQ_BATCH_SIZE", "1000")),
        "key_path": _env("GOOGLE_APPLICATION_CREDENTIALS"),
        "sa_json_env": _env("GOOGLE_SERVICE_ACCOUNT_JSON") or _env("BQ_SA_JSON"),
    }


def cron_token() -> str:
    return _env("CRON_TOKEN")


def auth() -> dict:
    """Kredensial login dashboard (satu akun bersama) — semua dari environment variable.

    DASHBOARD_USERNAME      : username (teks biasa, bukan rahasia).
    DASHBOARD_PASSWORD_HASH : sidik jari password (hash Werkzeug), BUKAN password mentah.
    SECRET_KEY              : kunci rahasia untuk menyegel cookie sesi.
    SESSION_COOKIE_SECURE   : default true (cookie hanya via HTTPS); set false hanya utk tes lokal http.
    """
    secure_raw = _env("SESSION_COOKIE_SECURE", "true").strip().lower()
    return {
        "username": _env("DASHBOARD_USERNAME"),
        "password_hash": _env("DASHBOARD_PASSWORD_HASH"),
        "secret_key": _env("SECRET_KEY"),
        "cookie_secure": secure_raw not in ("false", "0", "no", "off"),
    }


def schedule() -> dict:
    """Info jadwal penarikan untuk DITAMPILKAN di UI (baca-saja, tidak menjalankan apa pun).

    Sumber tunggal: env SCHEDULE_CRON (ekspresi cron 5 kolom, mis. '0 7-19 * * 1-6').
    Skrip install_cron.sh memakai nilai yang SAMA untuk menulis crontab, sehingga
    tampilan "berikutnya" dan eksekusi cron tidak mungkin melenceng.
    SCHEDULE_TZ default 'Asia/Jakarta' (samakan dengan zona waktu VPS).

    Kalau SCHEDULE_CRON kosong / tidak valid / croniter belum terpasang -> enabled=False
    (teks jadwal tidak muncul). Pipeline dan fitur lain TIDAK terpengaruh sama sekali.
    """
    cron_expr = _env("SCHEDULE_CRON").strip()
    tz_name = _env("SCHEDULE_TZ", "Asia/Jakarta").strip() or "Asia/Jakarta"
    out = {"enabled": False, "cron": cron_expr, "tz": tz_name, "next_run_iso": None}
    if not cron_expr:
        return out
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from croniter import croniter
        now = datetime.now(ZoneInfo(tz_name))
        nxt = croniter(cron_expr, now).get_next(datetime)
        out["enabled"] = True
        out["next_run_iso"] = nxt.isoformat()
    except Exception as e:
        print(f"[config_store] schedule() nonaktif: {e}", flush=True)
    return out


def env_status() -> dict:
    """Ringkas asal tiap kredensial untuk UI (tanpa membocorkan nilainya)."""
    bq = effective_bq()
    return {
        "odoo_url": bool(_env("ODOO_URL")),
        "odoo_db": bool(_env("ODOO_DB")),
        "odoo_username": bool(_env("ODOO_USERNAME")),
        "odoo_api_key": bool(_env("ODOO_API_KEY")),
        "bq_project": bool(bq["project_id"]),
        "bq_creds": bool(bq["key_path"] or bq["sa_json_env"]),
        "cron_token": bool(_env("CRON_TOKEN")),
    }
