"""
bridge.py — Extract/Transform/Load Odoo -> BigQuery untuk SEMUA modul.

Hanya operasi BACA dari Odoo (search_read). Kredensial diambil dari
config_store.effective_* (environment variable saja).

Pemilihan kolom per modul diambil dari config/config.json (diatur lewat UI).
Tiap modul selesai memanggil `on_module_done(row)` supaya app.py dapat mencatat
hasilnya ke pipeline_run_log (BigQuery) secara real-time.
"""

import json
import os
import xmlrpc.client
from datetime import datetime, timezone, timedelta

from google.cloud import bigquery
from google.oauth2 import service_account

import config_store as store

WIB = timezone(timedelta(hours=7))


# ----------------------------------------------------------------- Odoo
def connect_odoo(odoo: dict, log):
    url = (odoo.get("url") or "").rstrip("/")
    db, username, api_key = odoo.get("db"), odoo.get("username"), odoo.get("api_key")
    if not (url and db and username and api_key):
        raise RuntimeError("Kredensial Odoo belum lengkap (URL/DB/username/API key).")
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, username, api_key, {})
    if not uid:
        raise RuntimeError("Login Odoo GAGAL. Cek DB / username / API key.")
    log(f"[Odoo] Login berhasil (uid={uid})")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return models, uid


def get_model_fields(odoo, model, log=lambda *_: None):
    """Daftar SEMUA kolom model via fields_get (untuk refresh dari Odoo)."""
    if not model:
        raise RuntimeError("Model belum diisi.")
    models, uid = connect_odoo(odoo, log)
    meta = models.execute_kw(
        odoo["db"], uid, odoo["api_key"], model, "fields_get", [],
        {"attributes": ["string", "type", "store", "relation"]},
    )
    cols = []
    for name, info in meta.items():
        t = info.get("type", "")
        loadable, note = store.classify_type(t)
        cols.append({"name": name, "label": info.get("string", name) or name,
                     "type": t, "loadable": loadable, "note": note, "in_use": False})
    cols.sort(key=lambda c: (not c["loadable"], c["label"].lower()))
    return cols


def _extract(models, uid, odoo, model, domain, fields, cap, batch_size, log):
    db, api_key = odoo["db"], odoo["api_key"]
    records, offset = [], 0
    while True:
        page = batch_size
        if cap is not None:
            remaining = cap - len(records)
            if remaining <= 0:
                break
            page = min(batch_size, remaining)
        batch = models.execute_kw(
            db, uid, api_key, model, "search_read", [domain],
            {"fields": fields, "limit": page, "offset": offset},
        )
        if not batch:
            break
        records.extend(batch)
        offset += len(batch)
        log(f"[{model}] {len(records)} record ditarik...")
        if len(batch) < page:
            break
    return records


def _build_tag_map(models, uid, odoo, log):
    try:
        tags = models.execute_kw(odoo["db"], uid, odoo["api_key"],
                                 "crm.tag", "search_read", [[]], {"fields": ["name"]})
        return {t["id"]: t["name"] for t in tags}
    except Exception:
        return {}


def _clean(value):
    if value is False:
        return None
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[1], str):
            return value[1]
        return ", ".join(str(x) for x in value) if value else None
    return value


def _transform(records, rename, tag_map):
    pulled = datetime.now(WIB).isoformat()
    rows = []
    for rec in records:
        row = {}
        for key, val in rec.items():
            col = rename.get(key, key)
            if key == "tag_ids" and isinstance(val, list):
                row[col] = ", ".join(tag_map.get(i, str(i)) for i in val) or None
            else:
                row[col] = _clean(val)
        row["data_pull_time_stamp"] = pulled
        rows.append(row)
    return rows


# ----------------------------------------------------------------- BigQuery
def bq_client(bq: dict = None) -> bigquery.Client:
    """Client BigQuery: file kunci > JSON di env > Application Default Credentials.

    Kalau GOOGLE_APPLICATION_CREDENTIALS di-set tapi file-nya tidak ditemukan,
    langsung gagal dengan pesan jelas -- daripada diam-diam jatuh ke ADC dan
    memunculkan error "default credentials not found" yang membingungkan.
    """
    bq = bq or store.effective_bq()
    key_path = bq.get("key_path")
    project = bq.get("project_id") or None

    if key_path:
        if not os.path.exists(key_path):
            raise RuntimeError(
                f"GOOGLE_APPLICATION_CREDENTIALS diset ke '{key_path}' tapi file "
                f"itu tidak ditemukan. Cek lagi path-nya (Test-Path di PowerShell) "
                f"atau pastikan file .json sudah dipindah ke sana."
            )
        return bigquery.Client.from_service_account_json(key_path, project=project)

    sa_json = bq.get("sa_json_env")
    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info)
        return bigquery.Client(credentials=creds, project=project or info.get("project_id"))

    # Tidak ada key_path maupun sa_json_env -> ADC. Ini normal HANYA di Cloud Run
    # (service account otomatis menempel). Di lokal/Hostinger ini kemungkinan
    # besar berarti kredensial belum di-set.
    return bigquery.Client(project=project)


def bq_test(bq: dict = None) -> dict:
    client = bq_client(bq)
    datasets = list(client.list_datasets())
    return {"project": client.project, "dataset_count": len(datasets)}


def _load(client, rows, bq, full_table_id, log):
    cfg = bigquery.LoadJobConfig(write_disposition=bq["write_mode"], autodetect=True)
    job = client.load_table_from_json(rows, full_table_id, job_config=cfg, location=bq["location"])
    job.result()
    tbl = client.get_table(full_table_id)
    log(f"[BigQuery] {full_table_id} -> {tbl.num_rows} baris.")
    return tbl.num_rows


# ----------------------------------------------------------------- Orkestrasi
def run_all(log, *, client=None, limit=None, only_keys=None,
            on_module_done=None, run_id=None, dipicu_oleh="terjadwal"):
    """Tarik & muat SEMUA modul terpilih ke BigQuery (full refresh).

    Parameter:
      log            : fungsi(str) untuk streaming log.
      client         : BigQuery client (dibuat otomatis kalau None).
      limit          : batas baris per modul (None = semua).
      only_keys      : daftar kunci modul untuk dijalankan (None = semua).
      on_module_done : callback(dict) dipanggil tiap 1 modul selesai; dipakai
                       app.py untuk mencatat ke pipeline_run_log secara live.
      run_id         : id run bersama untuk seluruh modul di sesi ini.
      dipicu_oleh    : "terjadwal" | "manual" — dicatat di riwayat.

    Mengembalikan ringkasan {"summary": [...]} yang setiap item punya
    key/label/records/loaded/(skipped/error).
    """
    cfg = store.load_config()
    odoo = store.effective_odoo()
    bq = store.effective_bq()
    modules = [m for m in cfg["modules"] if (only_keys is None or m["key"] in only_keys)]

    log("=" * 54)
    log("BRIDGE Odoo -> BigQuery (semua sumber)")
    log(f"  Batas : {limit if limit is not None else 'SEMUA'} per sumber")
    log(f"  Tujuan: project={bq['project_id'] or '(otomatis)'} dataset={bq['dataset']}")
    log(f"  Dipicu: {dipicu_oleh}")
    log("=" * 54)

    models, uid = connect_odoo(odoo, log)
    if client is None:
        client = bq_client(bq)
    if not bq["project_id"]:
        bq["project_id"] = client.project

    summary = []
    for m in modules:
        key, label, model = m["key"], m["label"], m["model"]
        table = m["table"]
        full_id = f"{bq['project_id']}.{bq['dataset']}.{table}"
        selected = m.get("selected", {})
        fields = list(selected.keys())
        rename = dict(selected)
        domain = m.get("domain", [])
        waktu_mulai = datetime.now(WIB)

        log("")
        log(f"--- {label} ({model}) : {len(fields)} kolom ---")

        try:
            if not fields:
                log(f"[{label}] Tidak ada kolom dipilih, dilewati.")
                summary.append({"key": key, "label": label, "records": 0, "loaded": 0, "skipped": True})
                _report(on_module_done, run_id, waktu_mulai, m, dipicu_oleh,
                        status="dilewati", jumlah_baris=0, pesan="Tidak ada kolom dipilih")
                continue

            tag_map = _build_tag_map(models, uid, odoo, log) if "tag_ids" in fields else {}
            records = _extract(models, uid, odoo, model, domain, fields, limit, bq["batch_size"], log)
            log(f"[{label}] Total {len(records)} record.")

            if not records:
                # PENGAMAN: jangan menimpa tabel dengan data kosong
                log(f"[{label}] 0 baris — tidak memuat (pengaman).")
                summary.append({"key": key, "label": label, "records": 0, "loaded": 0})
                _report(on_module_done, run_id, waktu_mulai, m, dipicu_oleh,
                        status="dilewati", jumlah_baris=0, pesan="0 record ditarik dari Odoo")
                continue

            rows = _transform(records, rename, tag_map)
            loaded = _load(client, rows, bq, full_id, log)
            summary.append({"key": key, "label": label, "records": len(rows),
                            "loaded": loaded, "table": full_id})
            _report(on_module_done, run_id, waktu_mulai, m, dipicu_oleh,
                    status="sukses", jumlah_baris=loaded, pesan="")

        except Exception as e:
            log(f"[{label}] GAGAL: {e}")
            summary.append({"key": key, "label": label, "records": 0, "loaded": 0, "error": str(e)})
            _report(on_module_done, run_id, waktu_mulai, m, dipicu_oleh,
                    status="gagal", jumlah_baris=0, pesan=str(e))

    log("")
    log("=== SELESAI ===")
    return {"summary": summary}


def _report(on_module_done, run_id, waktu_mulai, m, dipicu_oleh, *, status, jumlah_baris, pesan):
    """Panggil callback riwayat kalau ada. Kegagalan mencatat TIDAK menggagalkan pipeline."""
    if on_module_done is None:
        return
    try:
        on_module_done({
            "run_id": run_id,
            "waktu_mulai": waktu_mulai,
            "waktu_selesai": datetime.now(WIB),
            "modul": m["key"],
            "label_modul": m["label"],
            "tabel_tujuan": m["table"],
            "mode": "load",
            "status": status,
            "jumlah_baris": jumlah_baris,
            "pesan": pesan,
            "dipicu_oleh": dipicu_oleh,
        })
    except Exception as e:
        print(f"[bridge] gagal mencatat riwayat modul '{m.get('key')}': {e}", flush=True)
