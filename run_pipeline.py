"""
run_pipeline.py — ENTRYPOINT CRON (tanpa server web).

Dipakai oleh cron Hostinger: menjalankan penarikan SEKALI lalu keluar.
Menghormati saklar auto-sync (pipeline_control): kalau dimatikan dari
dashboard, penarikan dilewati dan dicatat sebagai 'dilewati'.

Kredensial HANYA dari environment variable (lihat config_store.py).

Contoh pakai (di run_cron.sh):
    export ODOO_URL=...   ODOO_DB=...   ODOO_USERNAME=...   ODOO_API_KEY=...
    export BQ_PROJECT=... BQ_DATASET=odoo_staging BQ_LOCATION=asia-southeast2
    export GOOGLE_APPLICATION_CREDENTIALS=/home/USER/private/sa.json
    python3 run_pipeline.py

Kode keluar (exit code):
    0 = semua modul sukses / dilewati wajar
    1 = ada modul gagal
    2 = error fatal (mis. kredensial kurang)
"""

import sys
import traceback

from app import jalankan_sekali   # pakai orkestrasi yang sama dengan dashboard


def main():
    # Cron tidak punya terminal interaktif; orang yang mengetik manual punya.
    dipicu_oleh = "manual (terminal)" if sys.stdin.isatty() else "terjadwal"
    try:
        hasil = jalankan_sekali(log=print, force=False, dipicu_oleh=dipicu_oleh)
        if hasil.get("dilewati_karena_saklar"):
            print("Auto-sync dimatikan — tidak menarik data.")
            sys.exit(0)
        gagal = [s for s in hasil.get("summary", []) if s.get("error")]
        sys.exit(1 if gagal else 0)
    except Exception as e:
        print("FATAL:", e, flush=True)
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()