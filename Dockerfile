FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Pilihan kolom (config.json) disimpan di sini. Filesystem Cloud Run bersifat
# sementara — mount volume (mis. GCS) ke /data/config bila ingin perubahan UI
# bertahan antar-restart. Untuk kolom default, ini tidak wajib.
ENV OBQ_CONFIG_DIR=/data/config
RUN mkdir -p /data/config

# 2 worker + timeout longgar supaya "Jalankan Sekarang" (thread latar) tak terputus.
CMD exec gunicorn -w 2 --threads 4 -t 120 -b 0.0.0.0:${PORT:-8080} wsgi:app
