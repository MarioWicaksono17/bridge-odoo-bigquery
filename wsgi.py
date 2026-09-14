"""
wsgi.py — entry point untuk server produksi (gunicorn / hPanel Setup Python App).

hPanel "Setup Python App":
    Application startup file : wsgi.py
    Application Entry point  : app

gunicorn manual:
    gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 120 wsgi:app
"""

from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
