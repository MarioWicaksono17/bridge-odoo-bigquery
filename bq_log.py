"""
bq_log.py
=====================================================================
Penyimpanan saklar Start/Stop dan riwayat penarikan data — "numpang" di
BigQuery yang sama dengan data utama (tidak ada database tambahan).

Dua tabel (dibuat otomatis kalau belum ada):
  - pipeline_control  : 1 baris, saklar auto-sync (enabled/disabled)
  - pipeline_run_log  : 1 baris per modul tiap kali sync berjalan

OPSI B — Anti-expiration 60 hari (BigQuery sandbox / tanpa billing):
  Setiap kali menulis ke pipeline_run_log atau pipeline_control, properti
  `expires` tabel diperpanjang 59 hari ke depan (extend_expiry). Selama cron
  jalan minimal sekali dalam 60 hari, tabel tidak pernah kedaluwarsa.
  Lihat extend_expiry() dan pemanggilannya di bawah.

Semua operasi tulis memakai LOAD JOB (bukan DML/streaming insert) supaya tetap
jalan di BigQuery sandbox/free tier.
=====================================================================
"""

import uuid
from datetime import datetime, timezone, timedelta

from google.cloud import bigquery

import config_store as store

WIB = timezone(timedelta(hours=7))

CONTROL_TABLE = "pipeline_control"
LOG_TABLE = "pipeline_run_log"

# Opsi B: perpanjang masa berlaku tabel log/control tiap kali menulis.
# 59 hari memberi margin 1 hari di bawah batas 60 hari sandbox.
EXPIRY_EXTEND_DAYS = 59


def _bq_cfg():
    return store.effective_bq()


def _location():
    return _bq_cfg()["location"]


def _fq(client: bigquery.Client, table_name: str) -> str:
    bq = _bq_cfg()
    project = bq["project_id"] or client.project
    dataset = bq["dataset"]
    return f"{project}.{dataset}.{table_name}"


# --------------------------------------------------------------------
# Opsi B — perpanjang expiration tabel (anti kedaluwarsa 60 hari)
# --------------------------------------------------------------------
def extend_expiry(client: bigquery.Client, table_name: str, days: int = EXPIRY_EXTEND_DAYS):
    """Dorong `expires` tabel ke `days` hari dari sekarang.

    Dipanggil setelah setiap penulisan berhasil. Kalau gagal (mis. tabel baru
    saja dibuat / permission terbatas), TIDAK menggagalkan pipeline utama —
    hanya dicetak sebagai peringatan.
    """
    try:
        table_id = _fq(client, table_name)
        table = client.get_table(table_id)
        table.expires = datetime.now(timezone.utc) + timedelta(days=days)
        client.update_table(table, ["expires"])
    except Exception as e:
        print(f"[bq_log] extend_expiry '{table_name}' dilewati: {e}", flush=True)


# --------------------------------------------------------------------
# Setup tabel (idempotent — aman dipanggil berkali-kali)
# --------------------------------------------------------------------
def ensure_tables(client: bigquery.Client):
    loc = _location()
    control_id = _fq(client, CONTROL_TABLE)
    log_id = _fq(client, LOG_TABLE)

    client.query(f"""
        CREATE TABLE IF NOT EXISTS `{control_id}` (
            id STRING,
            enabled BOOL,
            updated_at TIMESTAMP,
            updated_by STRING
        )
    """, location=loc).result()

    client.query(f"""
        CREATE TABLE IF NOT EXISTS `{log_id}` (
            run_id STRING,
            waktu_mulai TIMESTAMP,
            waktu_selesai TIMESTAMP,
            durasi_detik FLOAT64,
            modul STRING,
            label_modul STRING,
            tabel_tujuan STRING,
            mode STRING,
            status STRING,
            jumlah_baris INT64,
            pesan STRING,
            dipicu_oleh STRING
        )
    """, location=loc).result()


# --------------------------------------------------------------------
# Saklar auto-sync (pipeline_control)
# --------------------------------------------------------------------
def get_control(client: bigquery.Client) -> dict:
    """Baca status saklar. Default enabled=True kalau belum pernah diset."""
    table_id = _fq(client, CONTROL_TABLE)
    try:
        rows = list(client.query(
            f"SELECT enabled, updated_at, updated_by FROM `{table_id}` WHERE id = 'global' LIMIT 1",
            location=_location(),
        ).result())
    except Exception:
        return {"enabled": True, "updated_at": None, "updated_by": None}
    if not rows:
        return {"enabled": True, "updated_at": None, "updated_by": None}
    r = rows[0]
    return {
        "enabled": bool(r["enabled"]),
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        "updated_by": r["updated_by"],
    }


_CONTROL_SCHEMA = [
    bigquery.SchemaField("id", "STRING"),
    bigquery.SchemaField("enabled", "BOOL"),
    bigquery.SchemaField("updated_at", "TIMESTAMP"),
    bigquery.SchemaField("updated_by", "STRING"),
]


def set_control(client: bigquery.Client, enabled: bool, actor: str = "ui") -> dict:
    """Nyalakan/matikan saklar via LOAD JOB (WRITE_TRUNCATE 1 baris)."""
    table_id = _fq(client, CONTROL_TABLE)
    row = {
        "id": "global",
        "enabled": bool(enabled),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": actor,
    }
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=_CONTROL_SCHEMA)
    client.load_table_from_json([row], table_id, job_config=job_config, location=_location()).result()
    extend_expiry(client, CONTROL_TABLE)   # Opsi B
    return get_control(client)


# --------------------------------------------------------------------
# Riwayat penarikan (pipeline_run_log)
# --------------------------------------------------------------------
def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


_LOG_SCHEMA = [
    bigquery.SchemaField("run_id", "STRING"),
    bigquery.SchemaField("waktu_mulai", "TIMESTAMP"),
    bigquery.SchemaField("waktu_selesai", "TIMESTAMP"),
    bigquery.SchemaField("durasi_detik", "FLOAT64"),
    bigquery.SchemaField("modul", "STRING"),
    bigquery.SchemaField("label_modul", "STRING"),
    bigquery.SchemaField("tabel_tujuan", "STRING"),
    bigquery.SchemaField("mode", "STRING"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("jumlah_baris", "INT64"),
    bigquery.SchemaField("pesan", "STRING"),
    bigquery.SchemaField("dipicu_oleh", "STRING"),
]


def log_module_result(client: bigquery.Client, *, run_id, waktu_mulai, waktu_selesai,
                      modul, label_modul, tabel_tujuan, mode, status,
                      jumlah_baris, pesan, dipicu_oleh):
    """Catat 1 baris hasil (per modul) ke pipeline_run_log via LOAD JOB (APPEND).

    Kegagalan mencatat riwayat TIDAK BOLEH menggagalkan pipeline utama.
    """
    table_id = _fq(client, LOG_TABLE)
    row = {
        "run_id": run_id,
        "waktu_mulai": waktu_mulai.isoformat(),
        "waktu_selesai": waktu_selesai.isoformat(),
        "durasi_detik": round((waktu_selesai - waktu_mulai).total_seconds(), 2),
        "modul": modul,
        "label_modul": label_modul,
        "tabel_tujuan": tabel_tujuan,
        "mode": mode,
        "status": status,
        "jumlah_baris": int(jumlah_baris or 0),
        "pesan": (pesan or "")[:1500],
        "dipicu_oleh": dipicu_oleh,
    }
    try:
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", schema=_LOG_SCHEMA)
        client.load_table_from_json([row], table_id, job_config=job_config, location=_location()).result()
    except Exception as e:
        print("[bq_log] gagal menulis log:", e, flush=True)


def log_module_results(client: bigquery.Client, rows: list):
    """Catat BANYAK baris hasil sekaligus lewat SATU load job.

    Dipakai saat semua modul dicatat serentak (mis. 'dilewati' karena saklar
    mati). Menulis satu-per-satu akan menembak banyak load-job + update metadata
    beruntun yang bisa menabrak rate limit BigQuery per tabel — sebagian penulisan
    gagal diam-diam sehingga baris hilang. Satu load job menghindari itu.

    `rows` = list dict dgn field mentah yang sama seperti parameter log_module_result
    (waktu_mulai / waktu_selesai berupa datetime). Kegagalan mencatat riwayat TIDAK
    menggagalkan pipeline utama.
    """
    if not rows:
        return
    table_id = _fq(client, LOG_TABLE)
    payload = []
    for r in rows:
        payload.append({
            "run_id": r["run_id"],
            "waktu_mulai": r["waktu_mulai"].isoformat(),
            "waktu_selesai": r["waktu_selesai"].isoformat(),
            "durasi_detik": round((r["waktu_selesai"] - r["waktu_mulai"]).total_seconds(), 2),
            "modul": r["modul"],
            "label_modul": r["label_modul"],
            "tabel_tujuan": r["tabel_tujuan"],
            "mode": r["mode"],
            "status": r["status"],
            "jumlah_baris": int(r.get("jumlah_baris") or 0),
            "pesan": (r.get("pesan") or "")[:1500],
            "dipicu_oleh": r["dipicu_oleh"],
        })
    try:
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", schema=_LOG_SCHEMA)
        client.load_table_from_json(payload, table_id, job_config=job_config, location=_location()).result()
    except Exception as e:
        print("[bq_log] gagal menulis log (batch):", e, flush=True)


def list_logs(client: bigquery.Client, modul: str = None, q: str = None, limit: int = 300) -> list:
    table_id = _fq(client, LOG_TABLE)
    where, params = [], []
    if modul and modul != "semua":
        where.append("modul = @modul")
        params.append(bigquery.ScalarQueryParameter("modul", "STRING", modul))
    if q:
        where.append("""(
            LOWER(label_modul) LIKE @q OR LOWER(modul) LIKE @q OR
            LOWER(status) LIKE @q OR LOWER(IFNULL(pesan,'')) LIKE @q OR
            LOWER(dipicu_oleh) LIKE @q OR LOWER(tabel_tujuan) LIKE @q
        )""")
        params.append(bigquery.ScalarQueryParameter("q", "STRING", f"%{q.lower()}%"))
    params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        rows = client.query(f"""
            SELECT run_id, waktu_mulai, waktu_selesai, durasi_detik, modul, label_modul,
                   tabel_tujuan, mode, status, jumlah_baris, pesan, dipicu_oleh
            FROM `{table_id}`
            {where_sql}
            ORDER BY waktu_mulai DESC
            LIMIT @limit
        """, job_config=bigquery.QueryJobConfig(query_parameters=params), location=_location()).result()
    except Exception:
        return []
    out = []
    for r in rows:
        out.append({
            "run_id": r["run_id"],
            "waktu_mulai": r["waktu_mulai"].isoformat() if r["waktu_mulai"] else None,
            "waktu_selesai": r["waktu_selesai"].isoformat() if r["waktu_selesai"] else None,
            "durasi_detik": r["durasi_detik"],
            "modul": r["modul"],
            "label_modul": r["label_modul"],
            "tabel_tujuan": r["tabel_tujuan"],
            "mode": r["mode"],
            "status": r["status"],
            "jumlah_baris": r["jumlah_baris"],
            "pesan": r["pesan"],
            "dipicu_oleh": r["dipicu_oleh"],
        })
    return out


def last_run_summary(client: bigquery.Client) -> dict:
    """Ringkasan sync terakhir (dikelompokkan per run_id terbaru)."""
    table_id = _fq(client, LOG_TABLE)
    try:
        rows = list(client.query(f"""
            SELECT run_id, MAX(waktu_mulai) AS waktu_mulai, MAX(waktu_selesai) AS waktu_selesai,
                   COUNTIF(status='sukses') AS sukses, COUNTIF(status='gagal') AS gagal,
                   COUNTIF(status='dilewati') AS dilewati, SUM(jumlah_baris) AS total_baris,
                   ANY_VALUE(dipicu_oleh) AS dipicu_oleh
            FROM `{table_id}`
            GROUP BY run_id
            ORDER BY waktu_mulai DESC
            LIMIT 1
        """, location=_location()).result())
    except Exception:
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        "run_id": r["run_id"],
        "waktu_mulai": r["waktu_mulai"].isoformat() if r["waktu_mulai"] else None,
        "waktu_selesai": r["waktu_selesai"].isoformat() if r["waktu_selesai"] else None,
        "sukses": r["sukses"], "gagal": r["gagal"], "dilewati": r["dilewati"],
        "total_baris": r["total_baris"] or 0, "dipicu_oleh": r["dipicu_oleh"],
    }


def clear_log(client: bigquery.Client):
    """Hapus semua riwayat. DROP+CREATE supaya selalu berhasil."""
    table_id = _fq(client, LOG_TABLE)
    client.query(f"DROP TABLE IF EXISTS `{table_id}`", location=_location()).result()
    ensure_tables(client)


# --------------------------------------------------------------------
# Kosongkan tabel staging BigQuery (bukan menghapus data di Odoo!)
# --------------------------------------------------------------------
def clear_staging_tables(client: bigquery.Client) -> list:
    """Kosongkan tabel staging via LOAD JOB kosong (WRITE_TRUNCATE, 0 baris)."""
    hasil = []
    for m in store.load_config()["modules"]:
        table_id = _fq(client, m["table"])
        try:
            tabel = client.get_table(table_id)   # ambil skema yang sudah ada
            job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=tabel.schema)
            client.load_table_from_json([], table_id, job_config=job_config, location=_location()).result()
            hasil.append({"modul": m["key"], "table": table_id, "ok": True})
        except Exception as e:
            hasil.append({"modul": m["key"], "table": table_id, "ok": False, "error": str(e)})
    return hasil
