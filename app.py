"""
app.py — Bridge Odoo -> BigQuery (dashboard tunggal, terjadwal).

Desain gabungan (Opsi B):
  - SATU halaman: status saklar + pemilih kolom per modul + riwayat penarikan.
  - TIDAK ada tab Koneksi. Kredensial hanya dari environment variable.
  - TIDAK ada dry run. Menjalankan berarti benar-benar memuat ke BigQuery.
  - Riwayat & saklar disimpan di BigQuery (pipeline_run_log, pipeline_control),
    dengan perpanjangan expiry otomatis (anti kedaluwarsa 60 hari).

Cara jalan:
  - Dashboard web  : gunicorn wsgi:app   (atau python app.py untuk lokal)
  - Cron penarikan : python run_pipeline.py   (RUN_ONCE, tanpa server web)
                     atau POST /api/cron/run dengan header X-Cron-Token.
"""

import threading
import traceback
from datetime import datetime, timezone, timedelta

from flask import (
    Flask, request, jsonify, render_template, session, redirect, url_for
)
from werkzeug.security import check_password_hash

import config_store as store
import bridge as bridge_mod
import bq_log

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

# ============================================================= Login / sesi (setup)
_auth = store.auth()
# SECRET_KEY menyegel cookie sesi. Wajib diset di produksi; fallback hanya agar app tetap
# hidup saat belum dikonfigurasi (login akan ditolak karena username/hash kosong).
app.secret_key = _auth["secret_key"] or "dev-only-INSECURE-secret-change-me"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,               # cookie tak terbaca JavaScript
    SESSION_COOKIE_SAMESITE="Lax",              # peredam CSRF
    SESSION_COOKIE_SECURE=_auth["cookie_secure"],  # hanya dikirim lewat HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),  # sesi berlaku 8 jam
)

# Endpoint yang TIDAK dijaga sesi login:
#   login  : halaman/proses login itu sendiri (kalau dikunci, mustahil masuk)
#   logout : proses keluar
#   static : aset CSS/JS (halaman login perlu memuatnya sebelum login)
#   health : /api/health publik untuk pemantau uptime (hanya balas {"ok":true})
#   cron_run : /api/cron/run — pintu MESIN, dijaga token CRON_TOKEN, bukan sesi
_NO_SESSION_ENDPOINTS = {"login", "logout", "static", "health", "cron_run"}


@app.before_request
def _require_login():
    """Penjaga default-terkunci: semua rute butuh login KECUALI yang di daftar di atas.

    Rute baru otomatis ikut terlindungi tanpa perlu ingat memasang apa pun.
    """
    if request.endpoint in _NO_SESSION_ENDPOINTS:
        return None
    if session.get("logged_in"):
        return None
    # Belum login: request API dibalas 401 (agar frontend mengalihkan sendiri),
    # sedangkan navigasi halaman dialihkan ke /login.
    if request.path.startswith("/api/"):
        return jsonify({"error": "Sesi berakhir. Silakan login ulang.", "auth": False}), 401
    return redirect(url_for("login"))

# Status "Jalankan Sekarang" yang sedang berjalan (background thread).
_run_state = {"running": False, "started_at": None, "logs": [], "result": None, "error": None}
_run_lock = threading.Lock()


# ================================================================= Orkestrasi bersama
def jalankan_sekali(log=print, *, force=False, dipicu_oleh=None):
    """Menjalankan pipeline sekali. Dipakai oleh cron DAN tombol Jalankan Sekarang.

    force=False (cron terjadwal): kalau saklar auto-sync DIMATIKAN, dilewati
      dan dicatat sebagai 'dilewati' — tanpa menarik apa pun.
    force=True (tombol Jalankan Sekarang): selalu jalan, apa pun status saklar.
    """
    client = bridge_mod.bq_client()
    bq_log.ensure_tables(client)

    if dipicu_oleh is None:
        dipicu_oleh = "manual" if force else "terjadwal"

    # Hormati saklar (kecuali dipaksa manual)
    if not force:
        control = bq_log.get_control(client)
        if not control["enabled"]:
            log("[Saklar] Auto-sync DIMATIKAN — pipeline dilewati.")
            run_id = bq_log.new_run_id()
            now = datetime.now(timezone.utc)
            rows = [
                {
                    "run_id": run_id, "waktu_mulai": now, "waktu_selesai": now,
                    "modul": m["key"], "label_modul": m["label"], "tabel_tujuan": m["table"],
                    "mode": "dilewati", "status": "dilewati", "jumlah_baris": 0,
                    "pesan": "Auto-sync dimatikan dari UI", "dipicu_oleh": dipicu_oleh,
                }
                for m in store.load_config()["modules"]
            ]
            bq_log.log_module_results(client, rows)   # SATU load job untuk semua modul
            bq_log.extend_expiry(client, bq_log.LOG_TABLE)   # 1x per run (bukan per baris)
            return {"dilewati_karena_saklar": True, "summary": []}

    run_id = bq_log.new_run_id()

    def on_module_done(row):
        bq_log.log_module_result(client, **row)

    hasil = bridge_mod.run_all(
        log, client=client, limit=None, only_keys=None,
        on_module_done=on_module_done, run_id=run_id, dipicu_oleh=dipicu_oleh,
    )
    bq_log.extend_expiry(client, bq_log.LOG_TABLE)   # 1x per run (bukan per modul)
    return hasil


# ================================================================= Halaman
# ============================================================= Login / Logout
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("logged_in"):
            return redirect(url_for("index"))
        return render_template("login.html")

    # --- POST: verifikasi kredensial ---
    cfg = store.auth()
    if not cfg["username"] or not cfg["password_hash"]:
        return render_template(
            "login.html",
            error="Login belum dikonfigurasi di server (DASHBOARD_USERNAME / DASHBOARD_PASSWORD_HASH belum diset).",
        ), 503

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    ok = (username == cfg["username"]) and check_password_hash(cfg["password_hash"], password)
    if not ok:
        return render_template("login.html", error="Username atau password salah."), 401

    session.clear()
    session["logged_in"] = True
    session["user"] = username
    session.permanent = True    # ikut PERMANENT_SESSION_LIFETIME (8 jam)
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


# ================================================================= Katalog & modul
@app.get("/api/catalog")
def get_catalog():
    cfg = store.load_config()
    out = []
    for m in cfg["modules"]:
        out.append({
            "key": m["key"], "label": m["label"], "model": m["model"],
            "move_type": m.get("move_type"), "table": m["table"], "domain": m.get("domain", []),
            "available": store.catalog_columns(m["key"]),
            "selected": m.get("selected", {}),
        })
    return jsonify({"modules": out, "bigquery": store.effective_bq(), "env": store.env_status()})


@app.post("/api/modules/save")
def post_module_save():
    body = request.get_json(force=True) or {}
    key = body.get("key")
    if not key:
        return jsonify({"error": "key modul belum diisi."}), 400
    patch = {k: body[k] for k in ("selected", "table", "domain") if k in body}
    store.save_module(key, patch)
    return jsonify({"ok": True})


@app.post("/api/modules/reset")
def post_module_reset():
    body = request.get_json(force=True) or {}
    store.reset_module(body.get("key"))
    return jsonify({"ok": True})


@app.post("/api/odoo/fields")
def odoo_fields():
    body = request.get_json(force=True) or {}
    model = (body.get("model") or "").strip()
    if not model:
        return jsonify({"error": "Model belum diisi."}), 400
    try:
        cols = bridge_mod.get_model_fields(store.effective_odoo(), model)
        return jsonify({"model": model, "columns": cols})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ================================================================= Status & saklar
@app.get("/api/status")
def api_status():
    try:
        client = bridge_mod.bq_client()
        bq_log.ensure_tables(client)
        control = bq_log.get_control(client)
        last = bq_log.last_run_summary(client)
        conn_ok = True
        conn_err = None
    except Exception as e:
        control, last, conn_ok, conn_err = {"enabled": True}, None, False, str(e)
    modules = [{"key": m["key"], "label": m["label"], "table": m["table"]}
               for m in store.load_config()["modules"]]
    with _run_lock:
        running = _run_state["running"]
    return jsonify({
        "control": control, "last_run": last, "modules": modules,
        "connection": {"ok": conn_ok, "error": conn_err},
        "run_now": {"running": running},
        "schedule": store.schedule(),
        "env": store.env_status(),
    })


@app.post("/api/control")
def api_control():
    body = request.get_json(force=True) or {}
    if "enabled" not in body:
        return jsonify({"error": "field 'enabled' wajib diisi (true/false)."}), 400
    try:
        client = bridge_mod.bq_client()
        bq_log.ensure_tables(client)
        control = bq_log.set_control(client, bool(body["enabled"]), actor=body.get("actor", "ui"))
        return jsonify({"ok": True, "control": control})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ================================================================= Jalankan Sekarang (async)
@app.post("/api/run-now")
def api_run_now():
    with _run_lock:
        if _run_state["running"]:
            return jsonify({"ok": False, "error": "Masih ada proses berjalan."}), 409
        _run_state.update({"running": True, "started_at": datetime.now(timezone.utc).isoformat(),
                           "logs": [], "result": None, "error": None})

    def worker():
        def log(msg):
            print(msg, flush=True)
            with _run_lock:
                _run_state["logs"].append(str(msg))
        try:
            hasil = jalankan_sekali(log=log, force=True, dipicu_oleh="manual")
            with _run_lock:
                _run_state["result"] = hasil
        except Exception as e:
            traceback.print_exc()
            with _run_lock:
                _run_state["error"] = str(e)
            log(f"[ERROR] {e}")
        finally:
            with _run_lock:
                _run_state["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"ok": True, "started": True})


@app.get("/api/run-now/status")
def api_run_now_status():
    with _run_lock:
        return jsonify({
            "running": _run_state["running"],
            "started_at": _run_state["started_at"],
            "logs": _run_state["logs"][-200:],
            "result": _run_state["result"],
            "error": _run_state["error"],
        })


# ================================================================= Riwayat
@app.get("/api/logs")
def api_logs():
    try:
        client = bridge_mod.bq_client()
        bq_log.ensure_tables(client)
        modul = request.args.get("modul", "semua")
        q = request.args.get("q", "").strip() or None
        limit = min(int(request.args.get("limit", 300)), 1000)
        rows = bq_log.list_logs(client, modul=modul, q=q, limit=limit)
        return jsonify({"rows": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"rows": [], "count": 0, "error": str(e)})


@app.post("/api/logs/clear")
def api_logs_clear():
    body = request.get_json(force=True) or {}
    if body.get("confirm") != "HAPUS":
        return jsonify({"error": "Konfirmasi tidak cocok."}), 400
    try:
        client = bridge_mod.bq_client()
        bq_log.clear_log(client)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/data/clear")
def api_data_clear():
    body = request.get_json(force=True) or {}
    if body.get("confirm") != "HAPUS":
        return jsonify({"error": "Konfirmasi tidak cocok."}), 400
    try:
        client = bridge_mod.bq_client()
        hasil = bq_log.clear_staging_tables(client)
        return jsonify({"ok": all(h["ok"] for h in hasil), "detail": hasil})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ================================================================= Cron (backup entry)
@app.post("/api/cron/run")
def cron_run():
    token = request.headers.get("X-Cron-Token") or request.args.get("token", "")
    expected = store.cron_token()
    if not expected:
        return jsonify({"error": "CRON_TOKEN belum diset di environment."}), 503
    if token != expected:
        return jsonify({"error": "Token cron tidak valid."}), 403
    logs = []
    try:
        hasil = jalankan_sekali(log=logs.append, force=False)
        return jsonify({"ok": True, "summary": hasil.get("summary", []),
                        "dilewati_karena_saklar": hasil.get("dilewati_karena_saklar", False),
                        "logs": logs})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e), "logs": logs}), 500


if __name__ == "__main__":
    print("Bridge Odoo -> BigQuery — http://localhost:8000")
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=True)
