# Panduan Tes Program di Lokal

Panduan langkah demi langkah untuk menguji program **Bridge Odoo → BigQuery** di komputer
sendiri (localhost) sebelum di-commit & push ke GitHub. Ditulis untuk Windows (PowerShell).

Tidak perlu jago ngoding — cukup ikuti urutannya dan salin perintahnya.

Yang akan diuji:
1. **`run_pipeline.py`** — penarikan data langsung (jalur cron), tanpa dashboard.
2. **`app.py`** — dashboard web (login, status, pilih kolom).
3. **Penarikan otomatis tiap 5 menit** — simulasi jadwal, memakai dua terminal.

---

## Langkah 0 — Siapkan file yang TIDAK ikut ke GitHub

Sebagian file **sengaja tidak disimpan di GitHub** karena berisi rahasia. Jadi setelah
`git clone` atau download zip, file ini **belum ada** dan harus Anda siapkan manual.

### a) File kunci BigQuery (`service-account.json`) — WAJIB

Ini file kunci berisi kredensial rahasia untuk mengakses BigQuery. Karena rahasia, ia
**tidak pernah** ada di repo — Anda harus menaruhnya sendiri.

1. Dapatkan file kuncinya dari admin BigQuery / tim IT (biasanya berupa file `.json`, mis.
   `service-account-xxxxx.json`).
2. Di dalam folder proyek, buat folder baru bernama **`secret`**:
   ```powershell
   mkdir secret
   ```
3. Taruh file kunci itu ke dalam folder `secret`. (Folder `secret/` sudah diatur agar
   **diabaikan Git**, jadi kuncinya aman, tidak akan ikut ter-push.)
4. Nanti di Langkah 6, tunjuk lokasi file ini lewat `GOOGLE_APPLICATION_CREDENTIALS` di `app.env`.

> **Alternatif:** file kunci boleh juga ditaruh di **luar** folder proyek (mis. `C:/keys/service-account.json`).
> Yang penting jangan pernah menaruhnya di folder proyek di luar `secret/`, supaya tidak
> berisiko ikut ter-commit.

### b) `app.env` — WAJIB

File konfigurasi berisi semua kredensial. Belum ada setelah clone; kita buat di Langkah 4–6.

### c) `simulate_cron.py` & `tambah_modul.py` — sudah ADA

Kedua alat bantu ini **sudah termasuk dalam repo**, jadi otomatis ikut saat clone/download.
Tidak perlu disiapkan manual.

---

## Langkah 1 — Buat "virtualenv" (ruang kerja Python)

Virtualenv adalah ruang terisolasi supaya komponen program tidak tercampur dengan Python lain
di komputer Anda. Buka PowerShell, masuk ke folder proyek, lalu buat venv:

```powershell
cd "C:\path\ke\odoo_bigquery_pipeline_gui"    # ganti dengan lokasi folder proyek Anda
python -m venv venv
```

---

## Langkah 2 — Aktifkan virtualenv

```powershell
.\venv\Scripts\Activate.ps1
```

Kalau muncul error *"running scripts is disabled on this system"*, jalankan perintah ini **sekali**
lalu ulangi aktivasi di atas:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Kalau berhasil, awal baris prompt akan diawali tulisan `(venv)`.

---

## Langkah 3 — Pasang semua komponen yang dibutuhkan

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Ini memasang Flask, koneksi BigQuery, python-dotenv, croniter, dan lainnya.

---

## Langkah 4 — Buat file `app.env` dari contoh

`app.env` adalah satu file berisi semua konfigurasi rahasia (kredensial Odoo, BigQuery, login).
Salin dari templatnya:

```powershell
copy app.env.contoh app.env
```

---

## Langkah 5 — Buat password hash & secret key

Login dashboard tidak menyimpan password mentah, melainkan **hash**-nya (bentuk teracak yang aman).
Selain itu program butuh **secret key** untuk mengunci cookie login. Buat keduanya (venv harus aktif),
lalu **salin hasilnya** untuk ditempel ke `app.env` di langkah berikutnya:

```powershell
# Hash dari password 'admin123' (ganti sesuka Anda)
python -c "from werkzeug.security import generate_password_hash as g; print(g('admin123'))"

# Kunci rahasia acak untuk cookie login
python -c "import secrets; print(secrets.token_hex(32))"
```

- Perintah **pertama** menghasilkan teks panjang diawali `scrypt:...` → itu **hash password**.
- Perintah **kedua** menghasilkan deretan huruf/angka → itu **secret key**.

---

## Langkah 6 — Isi `app.env`

Buka filenya: `notepad app.env` (atau `code app.env`), lalu isi nilainya:

```
ODOO_URL=https://<alamat-odoo-asli>.odoo.com
ODOO_DB=<nama database asli>
ODOO_USERNAME=<username/email asli>
ODOO_API_KEY=<api key asli>

BQ_PROJECT=<project-id-bigquery-anda>
BQ_DATASET=<nama-dataset-anda>
BQ_LOCATION=asia-southeast2
GOOGLE_APPLICATION_CREDENTIALS=C:/path/ke/odoo_bigquery_pipeline_gui/secret/service-account.json

DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD_HASH=<tempel hash scrypt dari Langkah 5>
SECRET_KEY=<tempel secret key dari Langkah 5>
SESSION_COOKIE_SECURE=false

CRON_TOKEN=token-tes-123

SCHEDULE_CRON=0 7-19 * * 1-6
SCHEDULE_TZ=Asia/Jakarta
```

Tiga hal yang paling sering menyebabkan gagal:

- **`SESSION_COOKIE_SECURE=false`** — wajib untuk tes lokal (yang memakai http). Kalau ini `true`,
  login akan gagal terus (berputar kembali ke halaman login).
- **`GOOGLE_APPLICATION_CREDENTIALS`** — isi dengan **path lengkap** ke file kunci di folder
  `secret/` (dari Langkah 0), pakai garis miring depan `/`, bukan `\`.
- **Tanpa tanda kutip** — tulis `KEY=value` langsung. Pastikan hash `scrypt:...` tersalin **utuh**
  dalam satu baris (hash-nya panjang; jangan sampai terpotong).

---

## Langkah 7 — Jalankan `run_pipeline.py` dulu (uji penarikan)

```powershell
python run_pipeline.py
```

Ini menguji "jalur cron" — menarik data dari Odoo langsung ke BigQuery, tanpa membuka dashboard.

Yang seharusnya terjadi: muncul log penarikan untuk tiap modul (CRM Lead, Customer Invoice,
Vendor Bill, dan **Sales Order** yang baru), lalu di BigQuery muncul/terisi tabel
`crm_lead_staging`, `customer_invoice_staging`, `vendor_bill_staging`, dan `sale_order_staging`.

> Kalau muncul error yang menyebut satu kolom tertentu di `sale_order`, hapus kolom itu dari
> `default_fields` di `config_store.py`, lalu jalankan lagi. Biasanya hanya 1–2 kolom yang perlu dibuang.

---

## Langkah 8 — Jalankan `app.py` (uji dashboard)

```powershell
python app.py
```

Buka **http://localhost:8000** di browser. Pastikan:

1. Diarahkan ke halaman **login** → masuk dengan `admin` / `admin123`.
2. Indikator **"BigQuery terhubung"** berwarna hijau.
3. Header menampilkan **"penarikan terjadwal berikutnya …"**.
4. Ada **tab "Sales Order"** yang jika diklik menampilkan pilihan kolomnya.

Kalau semua muncul, dashboard beres. **Biarkan `app.py` tetap berjalan** untuk langkah berikutnya
(jangan ditutup).

---

## Langkah 9 — Uji penarikan otomatis tiap 5 menit (dua terminal)

Langkah ini meniru cron yang menembak berkala, memakai **dua terminal** sekaligus.

**Terminal 1** — sudah menjalankan `app.py` dari Langkah 8. Biarkan berjalan.

**Terminal 2** — buka PowerShell BARU, masuk ke folder proyek, aktifkan venv, lalu jalankan
simulator dengan jadwal **tiap 5 menit**:

```powershell
cd "C:\path\ke\odoo_bigquery_pipeline_gui"    # ganti dengan lokasi folder proyek Anda
.\venv\Scripts\Activate.ps1
python simulate_cron.py --cron "*/5 * * * *" --token token-tes-123
```

> Token `token-tes-123` harus **sama persis** dengan `CRON_TOKEN` di `app.env`.

Yang akan terjadi: simulator menghitung waktu tembakan berikutnya (di menit kelipatan 5 — :00,
:05, :10, …), menunggu sampai waktunya, lalu menembak endpoint penarikan. Setiap tembakan:

- Kalau **saklar auto-sync ON** → semua modul tertarik; muncul baris **sukses** di tabel Riwayat.
- Kalau **saklar OFF** → muncul baris **dilewati**.

Amati minimal 2 kali tembakan (± 10 menit), dan coba geser saklar on/off di dashboard untuk
melihat kedua perilaku. Untuk berhenti: tekan **Ctrl+C** di Terminal 2 (simulator), lalu **Ctrl+C**
juga di Terminal 1 (app.py).

---

## Kalau ada masalah (troubleshooting)

| Yang terjadi | Kemungkinan sebab & solusi |
|---|---|
| `No module named ...` | venv belum aktif, atau `pip install -r requirements.txt` belum dijalankan |
| Login berputar kembali ke halaman login | `SESSION_COOKIE_SECURE` belum di-set `false` di `app.env` |
| Indikator BigQuery merah / tidak terhubung | cek `BQ_PROJECT` dan path `GOOGLE_APPLICATION_CREDENTIALS` (pakai `/`, pastikan filenya ada di `secret/`) |
| `File ... service-account.json not found` | file kunci belum ditaruh di folder `secret/`, atau path di `app.env` salah |
| `404 Not Found` / muncul `perusahaan.odoo.com` | `ODOO_URL` masih alamat contoh; isi dengan alamat Odoo asli (diawali `https://`, tanpa `/` di akhir) |
| `Access Denied` saat menarik | `ODOO_DB` / `ODOO_USERNAME` / `ODOO_API_KEY` salah |
| Login ditolak padahal password benar | hash `scrypt:...` di `app.env` tidak tersalin utuh (terpotong) |
| Simulator "GAGAL konek" | `app.py` di Terminal 1 belum berjalan, atau token beda dengan `CRON_TOKEN` |
| Teks "berikutnya" tidak muncul | `SCHEDULE_CRON` kosong atau salah format |

---

## Setelah semua lolos

Program siap di-commit & push ke GitHub. Ingat: **`app.env`, folder `secret/`, dan file kunci
tidak akan ikut ter-push** (sudah diabaikan Git), jadi rahasia Anda aman. Pastikan `git status`
hanya menampilkan file yang memang Anda ubah, dan tidak ada file rahasia yang muncul di sana.