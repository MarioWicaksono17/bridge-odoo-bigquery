# Panduan Menambah Modul Odoo Baru

Panduan ini untuk tim **Data Analyst** & **IT**. Isinya: cara menambah satu sumber data baru
dari Odoo (misalnya "Sales Order") supaya ikut ditarik ke BigQuery — dijelaskan langkah demi
langkah, dari nol sampai jalan di server.

Tidak perlu jago ngoding untuk mengikutinya. Cukup teliti mengikuti langkah dan menyalin perintah.

---

## Hal terpenting yang harus dipegang

**Semua penyiapan modul dikerjakan di komputer LOKAL, lalu dikirim ke GitHub. Server hanya
mengambil hasilnya.**

Kenapa? Karena kode program tersimpan di GitHub sebagai "sumber kebenaran". Kalau kita mengedit
langsung di server, server jadi beda dari GitHub, dan perubahan itu bisa hilang atau bentrok saat
update berikutnya. Jadi aturannya: **jangan pernah mengedit kode langsung di server.** Cukup:
kerjakan di lokal → kirim ke GitHub → server tarik dari GitHub.

---

## Gambaran besar (7 langkah)

```
1. Jalankan script tambah_modul.py   → ambil daftar kolom dari Odoo
2. Susun daftar kolom yang dipakai    → cara manual ATAU minta bantuan AI
3. Tempel ke config_store.py          → atur filter, kolom, & nama kolom
4. Uji di lokal (buka dashboard)      → cek modul baru muncul
5. Uji di lokal (tarik data)          → cek tabelnya terisi di BigQuery
6. Kirim ke GitHub (commit & push)
7. Di server: tarik update + restart
```

Beberapa hal terjadi **otomatis**, jadi tidak perlu dikerjakan manual:
- Tabel di BigQuery dibuat sendiri saat data pertama kali ditarik.
- Program otomatis mengenali modul baru beserta kolom default-nya.

---

## Sebelum mulai — siapkan dulu (di komputer lokal)

1. **Ambil kode dari GitHub** dan masuk ke foldernya (`git clone ...` bila belum punya).

2. **Nyalakan "virtualenv"** (ruang kerja Python terisolasi) dan pasang komponen yang dibutuhkan:
   ```bash
   python -m venv venv
   # Windows:      .\venv\Scripts\Activate.ps1
   # Linux/Mac:    source venv/bin/activate
   python -m pip install -r requirements.txt
   ```

3. **Pastikan file `app.env` sudah berisi data Odoo yang ASLI** — bukan contoh. Yang dicek:
   `ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_API_KEY`. Script akan memakai ini untuk masuk
   ke Odoo. Cek cepat dengan perintah ini:
   ```bash
   python -c "import config_store as s; print(s.effective_odoo()['url'])"
   ```
   Kalau yang muncul masih `perusahaan.odoo.com` (alamat contoh), berarti `app.env` belum diisi
   dengan alamat Odoo asli Anda — perbaiki dulu.

4. **Pastikan file `tambah_modul.py` ada** di folder proyek.

---

## Langkah 1 — Jalankan script untuk mengambil daftar kolom

Script ini menghubungi Odoo dan mengambil semua kolom milik satu model, lalu mencetak
draf yang bisa Anda pakai.

Bentuk perintahnya:
```bash
python tambah_modul.py <model_odoo> <key> "<Label>" [--move-type TIPE]
```

Arti tiap bagian:
- **`<model_odoo>`** — nama model di Odoo, misalnya `sale.order` (Sales Order),
  `purchase.order` (Purchase Order), `stock.picking` (pengiriman).
- **`<key>`** — nama pendek unik untuk modul ini (huruf kecil, pakai garis bawah), misalnya
  `sale_order`. Nama tabel di BigQuery otomatis jadi `<key>_staging`.
- **`"<Label>"`** — nama yang tampil di dashboard, misalnya `"Sales Order"`.
- **`--move-type`** — HANYA dipakai kalau modelnya `account.move` (mis. `out_invoice` untuk
  faktur penjualan, `in_invoice` untuk tagihan vendor). Untuk model lain, abaikan saja.

Contoh:
```bash
python tambah_modul.py sale.order sale_order "Sales Order"
```

Setelah dijalankan, script akan:
1. Menuliskan daftar kolom model itu ke file `katalog_fields_odoo.json` (modul lain tidak diutak-atik).
2. **Mencetak draf** ke layar berisi SEMUA kolom yang tersedia.

**Penting:** draf itu bisa memuat 100–200 kolom, dan sebagian besarnya adalah kolom teknis Odoo
yang tidak berguna untuk analisis. Anggap draf itu sebagai **menu lengkap**, bukan pesanan.
Tugas Anda di Langkah 2: memilih **8–20 kolom** yang benar-benar berguna saja.

---

## Langkah 2 — Pilih kolom yang berguna (pilih salah satu cara)

Draf mentah tadi terlalu banyak dan berantakan. Kita perlu menyaringnya jadi daftar pendek yang
bermakna, lalu memberi nama kolom yang rapi. Ada dua cara — pilih yang paling nyaman.

### Cara A — Manual (pilih & beri nama sendiri)

1. Dari daftar kolom yang tercetak, **hapus semuanya**, lalu **ketik ulang hanya kolom yang Anda
   butuhkan**. Biasanya yang berguna: identitas & nomor dokumen, tanggal, status, pihak terkait
   (pelanggan, sales, tim, cabang), nilai uang, dan kolom kustom `x_studio_*` yang relevan.
2. Beri nama rapi **hanya untuk kolom yang Anda pilih**, mengikuti pola di bagian
   "Panduan penamaan kolom" di bawah. Kolom yang namanya sudah jelas (mis. `amount_total`)
   tidak perlu diganti.

Cocok kalau Anda sudah paham kolom-kolom model itu dan ingin kontrol penuh.

### Cara B — Minta bantuan AI (tempel cetakan, minta dibuatkan)

1. **Salin seluruh draf** yang tercetak di layar (yang isinya ratusan kolom).
2. Tempel ke asisten AI, bersama **perintah berikut** (salin apa adanya):

   > Saya punya draf `MODULE_DEFS` untuk pipeline Odoo→BigQuery yang berisi SEMUA kolom sebuah
   > model (banyak yang teknis dan tidak berguna). Tolong buatkan versi **siap tempel** dengan
   > aturan berikut:
   > 1. **Pilih hanya kolom yang berguna untuk analisis**: identitas & referensi, tanggal,
   >    status, pihak terkait (partner/user/team/company), nilai uang, dan kolom kustom `x_studio_*`.
   > 2. **Buang** kolom teknis Odoo: yang berawalan `message_`, `activity_`, `access_`, `json_`,
   >    yang berakhiran `_count`, serta `display_name`, `create_uid`, `write_uid`, `write_date`,
   >    `id`, `__last_update`, dan penanda internal (`is_*`, `has_*`, `show_*`).
   > 3. **Jangan mengarang nama kolom** — gunakan HANYA nama yang ada di daftar saya.
   > 4. Isi `default_rename` hanya untuk kolom terpilih, dengan pola: `create_date→created_at`,
   >    `company_id→company_branch`, `team_id→sales_team`, `state→<dokumen>_status`,
   >    `name→<dokumen>_number`, `partner_id→customer` (atau `vendor` untuk pembelian),
   >    `amount_untaxed→amount_before_tax`, `amount_tax→tax_amount`, `x_studio_branch→branch`.
   >    Kolom yang namanya sudah jelas tidak perlu diganti.
   > 5. Keluarkan **hanya blok Python `MODULE_DEFS`** yang sudah rapi dan siap tempel.
   >
   > Berikut draf saya:
   > [tempel cetakan di sini]

3. AI akan mengembalikan blok yang sudah dipangkas dan diberi nama rapi. **Tetap periksa
   sebentar** hasilnya: pastikan kolom yang Anda perlukan ada, dan tidak ada nama kolom yang
   "dikarang" (semua nama harus benar-benar ada di draf asli).

Cocok kalau kolomnya sangat banyak dan Anda ingin cepat. Apa pun caranya, **selalu tinjau ulang**
sebelum dipakai.

> Catatan: bagian **filter data** (`domain`) tetap Anda tentukan sendiri di Langkah 3 —
> baik script maupun AI tidak tahu baris mana yang ingin Anda tarik.

---

## Langkah 3 — Tempel ke `config_store.py` dan rapikan

1. Buka file `config_store.py`, cari bagian bernama `MODULE_DEFS` (daftar definisi semua modul).
2. Tempel blok modul baru Anda **di dalam** daftar itu — setelah blok modul terakhir, sebelum
   tanda kurung siku penutup `]`. **Jangan lupa tanda koma** setelah kurung kurawal `}`.
3. Rapikan tiga bagian ini:
   - **`domain`** (filter baris) — menentukan data mana yang ditarik. Default `[FILTER_NEW]`
     hanya menarik data yang nama perusahaannya diawali `[NEW]`. Bisa ditambah syarat, misalnya
     `[FILTER_NEW, ["state", "=", "sale"]]` untuk hanya menarik order berstatus "sale".
   - **`default_fields`** (daftar kolom) — pastikan sudah dipangkas seperti Langkah 2.
   - **`default_rename`** (penggantian nama) — pastikan hanya untuk kolom yang Anda pilih.
4. Cek tidak ada salah ketik dengan perintah ini:
   ```bash
   python -c "import config_store as c; print([m['key'] for m in c.MODULE_DEFS])"
   ```
   Harus muncul daftar semua modul termasuk yang baru, **tanpa pesan error**. Kalau error,
   biasanya ada koma atau kurung yang kurang/lebih di blok yang baru ditempel.

---

## Langkah 4 — Uji di lokal: cek tampilan dashboard

```bash
python app.py
```
Buka `http://localhost:8000` di browser, lalu login. Yang harus terlihat:
- **Tab modul baru muncul** (mis. "Sales Order").
- Klik tab itu → **daftar kolom** yang bisa dicentang muncul, dengan kolom pilihan Anda sudah
  tercentang.

Kalau sudah muncul, berarti pengaturannya terbaca dengan benar. Tutup dengan menekan `Ctrl+C`
di terminal.

---

## Langkah 5 — Uji di lokal: tarik data ke BigQuery

```bash
python run_pipeline.py
```
Ini akan menarik data dan membuat tabel baru **`<key>_staging`** di BigQuery. Buka BigQuery
Console dan cek: tabel baru muncul, terisi data, dan nama kolomnya sesuai yang Anda atur.

Kalau ada error yang menyebut satu kolom tertentu (kolom itu ternyata tak bisa ditarik), cukup
**hapus kolom itu** dari `default_fields`, lalu jalankan lagi. Biasanya hanya 1–2 kolom yang perlu
dibuang.

> **Ingin ekstra aman saat menguji?** Supaya tidak menyentuh data produksi, Anda bisa sementara
> mengubah `BQ_DATASET` di `app.env` ke dataset uji coba (buat dulu di lokasi `asia-southeast2`),
> lalu kembalikan lagi setelah selesai menguji.

---

## Langkah 6 — Kirim ke GitHub

Pertama, cek file apa saja yang berubah:
```bash
git status
```
Biasanya hanya dua file: `config_store.py` dan `katalog_fields_odoo.json`.
**Pastikan `app.env` TIDAK ikut muncul** (file itu berisi rahasia dan tidak boleh naik ke GitHub).
Kalau sudah benar:
```bash
git add config_store.py katalog_fields_odoo.json
git commit -m "Tambah modul <key> (<Label>)"
git push
```

---

## Langkah 7 — Terapkan di server (dilakukan tim IT)

Masuk ke server VPS, lalu:
```bash
cd ~/pipeline        # sesuaikan dengan folder aplikasi di server
git pull             # tarik kode terbaru dari GitHub
sudo systemctl restart odoo-bq-dashboard    # muat perubahan ke dashboard
```
Setelah itu:
- Tab modul baru langsung muncul di dashboard server.
- Tabel `<key>_staging` dibuat otomatis saat penarikan terjadwal berikutnya (atau saat menekan
  tombol "Jalankan Sekarang" di dashboard).

**Server tidak menjalankan `tambah_modul.py`.** Semua penyiapan sudah selesai di lokal; server
cukup menarik hasilnya lewat `git pull`.

---

## Lampiran: bentuk satu blok modul (MODULE_DEFS)

```python
{
    "key": "sale_order",              # nama pendek unik; jadi nama tabel <key>_staging
    "label": "Sales Order",           # nama yang tampil di dashboard
    "model": "sale.order",            # nama model di Odoo
    "move_type": None,                # None; diisi hanya untuk account.move (out_invoice, dll)
    "domain": [FILTER_NEW],           # filter: baris mana yang ditarik
    "table": "sale_order_staging",    # nama tabel tujuan di BigQuery
    "default_fields": [ ... ],        # kolom yang ditarik & tercentang default
    "default_rename": { ... },        # (opsional) ubah nama kolom: nama_odoo -> nama_bigquery
},
```

## Lampiran: panduan penamaan kolom (default_rename)

Ikuti pola yang sudah dipakai modul lama (`crm_lead`, `customer_invoice`, `vendor_bill`) supaya
seragam antar-modul:

| Kolom Odoo | Diberi nama |
|---|---|
| `name` | `<dokumen>_number` (mis. `order_number`, `invoice_number`) |
| `create_date` | `created_at` |
| `state` | `<dokumen>_status` (mis. `order_status`) |
| `partner_id` | `customer` (penjualan) / `vendor` (pembelian) |
| `user_id` / `invoice_user_id` | `salesperson` |
| `team_id` | `sales_team` |
| `company_id` | `company_branch` |
| `amount_untaxed` | `amount_before_tax` |
| `amount_tax` | `tax_amount` |
| `payment_state` | `payment_status` |
| `invoice_origin` / `origin` | `source_document` |
| `x_studio_branch` | `branch` |
| `x_studio_sales_rep` | `sales_rep` |

Kolom yang namanya sudah jelas (`amount_total`, `invoice_status`, `delivery_status`) tidak perlu diganti.

## Lampiran: kolom yang biasanya DIBUANG (teknis Odoo)

Kolom berawalan `message_`, `activity_`, `access_`, `json_`; berakhiran `_count`; serta
`display_name`, `create_uid`, `write_uid`, `write_date`, `id`, `__last_update`, dan penanda
internal (`is_*`, `has_*`, `show_*`). Semua ini tidak berguna untuk analisis.

---

## Kalau ada masalah (troubleshooting)

| Yang terjadi | Kemungkinan sebab & cara memperbaiki |
|---|---|
| Pesan `kredensial Odoo kosong` | `app.env` belum berisi data `ODOO_*` yang asli |
| Pesan `404 Not Found` di `/xmlrpc/...` | `ODOO_URL` salah/masih contoh; harus diawali `https://` dan tanpa `/` di akhir |
| Pesan `Access Denied` | `ODOO_DB` / `ODOO_USERNAME` / `ODOO_API_KEY` salah |
| Error saat cek `config_store` | ada salah ketik di blok baru (koma/kurung kurang) |
| Tab baru tak muncul di dashboard | `app.py` belum di-restart; atau `key` sudah dipakai modul lain |
| Error menyebut satu kolom saat menarik data | hapus kolom itu dari `default_fields`, lalu ulangi |
| Tabel tak muncul di BigQuery | pastikan penarikan berhasil & dataset (BQ_DATASET) ada di lokasi (BQ_LOCATION) yang benar |
| Modul baru hilang setelah tim IT `git pull` | perubahan belum di-`push`, atau kode diedit langsung di server (jangan lakukan ini) |
