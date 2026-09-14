#!/usr/bin/env python
"""
tambah_modul.py — ALAT BANTU LOKAL (dev tool) untuk menambah modul Odoo baru.

Apa yang dilakukan:
  1. Konek ke Odoo (kredensial dari app.env, sama seperti aplikasi).
  2. Ambil SEMUA kolom model baru via fields_get (pakai bridge.get_model_fields).
  3. Tulis / perbarui entri katalog di katalog_fields_odoo.json (entri lain dipertahankan).
  4. Cetak DRAF blok MODULE_DEFS ke layar — tinggal Anda tempel ke config_store.py
     lalu rapikan domain / default_fields / default_rename sesuai kebutuhan.

Skrip ini TIDAK mengubah config_store.py (MODULE_DEFS tetap keputusan Anda) dan
TIDAK menarik data. Jalankan di LOKAL saat menyiapkan modul, lalu commit & push.
Di server cukup 'git pull' + restart — server tidak menjalankan skrip ini.

Cara pakai:
  python tambah_modul.py <model_odoo> <key> "<Label>" [--move-type TIPE]

Contoh:
  python tambah_modul.py sale.order sale_order "Sales Order"
  python tambah_modul.py account.move refund "Credit Note" --move-type out_refund
"""
import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
CATALOG_FILE = BASE_DIR / "katalog_fields_odoo.json"


def main():
    ap = argparse.ArgumentParser(description="Tambah entri katalog modul Odoo baru.")
    ap.add_argument("model", help="nama model Odoo, mis. sale.order")
    ap.add_argument("key", help="key unik modul (huruf kecil/garis bawah), mis. sale_order")
    ap.add_argument("label", help="nama tampilan, mis. \"Sales Order\"")
    ap.add_argument("--move-type", default=None,
                    help="hanya untuk account.move (mis. out_invoice/in_invoice/out_refund)")
    a = ap.parse_args()

    # Impor di sini supaya pesan error argumen muncul lebih dulu bila salah pakai.
    import config_store as store   # memuat app.env
    import bridge

    odoo = store.effective_odoo()
    if not odoo.get("url") or not odoo.get("api_key"):
        print("ERROR: kredensial Odoo kosong. Pastikan app.env berisi ODOO_URL/DB/USERNAME/API_KEY.")
        sys.exit(1)

    print(f"Mengambil kolom model '{a.model}' dari Odoo ...")
    try:
        cols = bridge.get_model_fields(odoo, a.model, log=lambda *_: None)
    except Exception as e:
        print(f"GAGAL mengambil field dari Odoo: {e}")
        sys.exit(1)

    if not cols:
        print("Tidak ada field yang dikembalikan — cek nama model.")
        sys.exit(1)

    # --- susun entri katalog (format sama seperti entri yang sudah ada) ---
    fields = [
        {
            "nama_teknis": c["name"],
            "label": c.get("label") or c["name"],
            "tipe": c.get("type", ""),
            "sedang_dipakai": False,   # default belum dipakai; dicentang lewat UI / default_fields
        }
        for c in cols
    ]
    entry = {
        "label_modul": a.label,
        "model": a.model,
        "move_type": a.move_type,
        "jumlah_field": len(fields),
        "fields": fields,
    }

    # --- muat katalog lama, perbarui HANYA key ini, tulis kembali ---
    try:
        catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8")) if CATALOG_FILE.exists() else {}
    except json.JSONDecodeError as e:
        print(f"ERROR: katalog_fields_odoo.json rusak/tidak valid JSON: {e}")
        sys.exit(1)

    if a.key in catalog:
        print(f"CATATAN: key '{a.key}' sudah ada di katalog — akan DIPERBARUI (ditimpa).")
    catalog[a.key] = entry
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: katalog diperbarui -> {CATALOG_FILE.name} (key '{a.key}', {len(fields)} kolom).")

    # --- cetak DRAF blok MODULE_DEFS untuk ditempel ---
    loadable = [c["name"] for c in cols if c.get("loadable")]
    move_type_py = "None" if a.move_type is None else repr(a.move_type)
    # susun default_fields multi-baris biar rapi
    df_lines, line = [], "        "
    for name in loadable:
        piece = f'"{name}", '
        if len(line) + len(piece) > 92:
            df_lines.append(line.rstrip())
            line = "        "
        line += piece
    if line.strip():
        df_lines.append(line.rstrip())
    default_fields_block = "\n".join(df_lines)

    print("\n" + "=" * 70)
    print("DRAF blok MODULE_DEFS — tempel ke list MODULE_DEFS di config_store.py,")
    print("lalu RAPIKAN: sesuaikan 'domain', pangkas 'default_fields', isi 'default_rename'.")
    print("=" * 70)
    print(f"""    {{
        "key": "{a.key}", "label": "{a.label}", "model": "{a.model}", "move_type": {move_type_py},
        "domain": [FILTER_NEW],            # <-- SESUAIKAN filter baris yang ditarik
        "table": "{a.key}_staging",
        "default_fields": [
{default_fields_block}
        ],
        "default_rename": {{
            # "nama_odoo": "nama_bigquery",   # <-- isi bila ingin ganti nama kolom
        }},
    }},""")
    print("=" * 70)
    print("\nLangkah berikutnya:")
    print("  1. Tempel & rapikan blok di atas ke MODULE_DEFS (config_store.py).")
    print("  2. python app.py         -> cek tab & pemilih kolom modul baru muncul.")
    print("  3. python run_pipeline.py-> cek tabel baru terisi di BigQuery.")
    print("  4. commit & push. Di server: git pull + restart dashboard.")


if __name__ == "__main__":
    main()
