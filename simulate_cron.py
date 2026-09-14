#!/usr/bin/env python
"""
simulate_cron.py — SIMULASI cron di localhost (ALAT TES, bukan untuk deploy).

Membaca ekspresi cron yang SAMA seperti dashboard (via croniter), lalu menembak
endpoint /api/cron/run tepat pada waktu yang dijadwalkan — meniru persis apa yang
akan dilakukan cron OS di Hostinger nanti.

Untuk tes CEPAT, pakai jadwal '* * * * *' (tiap menit) lewat --cron.

Contoh:
  python simulate_cron.py --cron "* * * * *" --token token-tes-123
  python simulate_cron.py --cron "*/2 * * * *"          # tiap 2 menit
  python simulate_cron.py                                # pakai SCHEDULE_CRON dari env

Hentikan dengan Ctrl+C. Ini TIDAK perlu di-commit / di-deploy — di server, cron OS
yang mengerjakan tugas ini.
"""
import argparse
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo
from croniter import croniter


def fire(url: str, token: str):
    full = f"{url}?token={token}"
    req = urllib.request.Request(full, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            print(f"    -> HTTP {r.status}: {r.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.HTTPError as e:
        print(f"    -> HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
    except Exception as e:
        print(f"    -> GAGAL konek: {e} (pastikan app.py sedang jalan di --url)")


def main():
    ap = argparse.ArgumentParser(description="Simulasi cron lokal untuk menembak /api/cron/run.")
    ap.add_argument("--cron", default=os.environ.get("SCHEDULE_CRON", ""),
                    help="ekspresi cron 5 kolom (mis. '* * * * *' untuk tiap menit)")
    ap.add_argument("--tz", default=os.environ.get("SCHEDULE_TZ", "Asia/Jakarta"))
    ap.add_argument("--url", default="http://localhost:8000/api/cron/run")
    ap.add_argument("--token", default=os.environ.get("CRON_TOKEN", "token-tes-123"))
    a = ap.parse_args()

    if not a.cron:
        print("ERROR: jadwal kosong. Beri --cron \"* * * * *\" atau set SCHEDULE_CRON di env.")
        sys.exit(1)

    tz = ZoneInfo(a.tz)
    print(f"Simulasi cron LOKAL | jadwal: '{a.cron}' | tz: {a.tz}")
    print(f"Menembak : {a.url}")
    print("Tekan Ctrl+C untuk berhenti.\n")

    try:
        while True:
            now = datetime.now(tz)
            # hitung ulang dari 'now' tiap putaran -> tidak melenceng walau penarikan lama
            nxt = croniter(a.cron, now).get_next(datetime)
            wait = (nxt - now).total_seconds()
            if wait > 0:
                print(f"[{now:%H:%M:%S}] menunggu tembakan berikutnya pukul "
                      f"{nxt:%H:%M:%S} (~{int(wait)} dtk)...")
                time.sleep(wait)
            fired_at = datetime.now(tz)
            print(f"[{fired_at:%H:%M:%S}] >>> TEMBAK /api/cron/run (meniru cron)")
            fire(a.url, a.token)
            print()
            # jeda 1 dtk supaya tidak menembak ganda dalam menit yang sama
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nSimulasi dihentikan.")


if __name__ == "__main__":
    main()
