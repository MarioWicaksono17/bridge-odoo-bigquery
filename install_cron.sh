#!/usr/bin/env bash
#
# install_cron.sh — pasang / perbarui baris cron penarikan dari SATU sumber: SCHEDULE_CRON.
#
# Nilai SCHEDULE_CRON yang sama dipakai dashboard untuk menampilkan "berikutnya",
# sehingga tampilan dan eksekusi tidak mungkin melenceng.
#
# AMAN berdampingan dengan cron lain: skrip ini HANYA mengganti blok bertanda
# '# >>> bridge-schedule >>>' ... '# <<< bridge-schedule <<<'. Baris cron lain
# milik Anda / tim IT tidak tersentuh.
#
# Pemakaian:
#   1) Set SCHEDULE_CRON di app.env, mis:  SCHEDULE_CRON="0 7-19 * * 1-6"
#   2) Jalankan:  ./install_cron.sh
#   3) Cek hasil: crontab -l
#
# Path bisa disesuaikan lewat environment saat memanggil, mis:
#   APP_DIR=/home/deploy/pipeline ./install_cron.sh
#
set -euo pipefail

# --- Lokasi aplikasi, perintah yang dijalankan cron, dan file env ---
APP_DIR="${APP_DIR:-$HOME/pipeline}"
RUN_CMD="${RUN_CMD:-$APP_DIR/run_cron.sh}"
ENV_FILE="${ENV_FILE:-$APP_DIR/app.env}"

# --- Ambil SCHEDULE_CRON: dari environment, atau dari app.env ---
if [ -z "${SCHEDULE_CRON:-}" ] && [ -f "$ENV_FILE" ]; then
  SCHEDULE_CRON="$(grep -E '^[[:space:]]*SCHEDULE_CRON=' "$ENV_FILE" | tail -1 \
                    | cut -d= -f2- | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//')"
fi
if [ -z "${SCHEDULE_CRON:-}" ]; then
  echo "ERROR: SCHEDULE_CRON kosong. Set di environment atau di $ENV_FILE" >&2
  echo "Contoh:  SCHEDULE_CRON=\"0 7-19 * * 1-6\"" >&2
  exit 1
fi

if [ ! -x "$RUN_CMD" ]; then
  echo "PERINGATAN: $RUN_CMD tidak ditemukan / belum executable (chmod +x)." >&2
  echo "            Baris cron tetap dibuat, tapi pastikan path & izinnya benar." >&2
fi

BEGIN="# >>> bridge-schedule >>>"
END="# <<< bridge-schedule <<<"
LINE="$SCHEDULE_CRON $RUN_CMD >> $APP_DIR/cron_pipeline.log 2>&1"

# --- Ambil crontab lama; buang blok bridge lama; PERTAHANKAN sisanya ---
OLD="$(crontab -l 2>/dev/null || true)"
CLEAN="$(printf '%s\n' "$OLD" | sed "\|$BEGIN|,\|$END|d")"

# --- Tulis crontab baru: sisa cron lain + blok bridge yang baru ---
{
  printf '%s\n' "$CLEAN" | sed '/^[[:space:]]*$/d'   # baris cron lain (buang baris kosong)
  echo "$BEGIN"
  echo "# Jadwal penarikan Odoo->BigQuery — dihasilkan dari SCHEDULE_CRON. JANGAN edit tangan;"
  echo "# ubah SCHEDULE_CRON di app.env lalu jalankan ulang install_cron.sh."
  echo "$LINE"
  echo "$END"
} | crontab -

echo "OK: crontab diperbarui. Baris jadwal aktif:"
echo "    $LINE"
echo
echo "Verifikasi:  crontab -l"
echo "Ingat: restart dashboard agar teks 'berikutnya' di UI ikut menyesuaikan."
