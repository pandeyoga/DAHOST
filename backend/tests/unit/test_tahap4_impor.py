"""Uji unit HERMETIK T4 (2026-11-06): impor Excel master lewat Data Transfer yang sudah ada.

Master: Supplier, Daftar Harga Supplier, Pelanggan, Kalender Libur, Rak/Bin Gudang
(`routes/data_transfer_masters.py`, dipasang di `routes/data_transfer.py`). Semua baris SINTETIS.

Angka harapan dihitung tangan:
  * Harga 1 roll = 1.250.000, 1 roll = 25 kg → harga per satuan dasar 50.000/kg.
  * Rak 3 susun × 4 slot = 12 bin; dinaikkan ke 3 × 5 → +3 bin (total 15), tanpa bin kembar.
  * Rak 30 × 20 = 600 bin lalu 30 × 21 → +30 bin (dulu `to_list(500)` memotong daftar bin lama).

Jalankan:  cd backend && python -m pytest tests/unit/test_tahap4_impor.py -q -n 0
"""
import asyncio
import io
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import openpyxl  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
import routes.data_transfer as dt  # noqa: E402
import routes.data_transfer_masters as dtm  # noqa: E402

ADMIN = {"id": "u-adm", "name": "Admin Uji", "email": "adm@x", "role": "admin"}
STAFF_HR = {"id": "u-hr", "name": "HR Uji", "email": "hr@x", "role": "staff_hr"}

# Judul kolom PERSIS seperti template owner (kelengkapan_master_data_2026-11-06.xlsx) — tanpa isi baris.
H_SUPPLIER = ["kode (kosongkan = otomatis)", "nama *", "status_pajak *", "npwp", "nama_di_npwp", "alamat", "kota",
              "provinsi", "kode_pos", "telepon", "email", "kontak_nama", "kontak_jabatan", "kontak_hp",
              "termin_bayar *", "mata_uang", "bank", "no_rekening", "atas_nama_rekening", "kategori_barang",
              "lama_kirim_hari", "min_order_rp", "catatan", "CV pemakai (info)", "sumber di berkas owner (info)",
              "hutang awal (info)", "yang perlu dipastikan (info)"]
H_PRICE = ["nama_supplier *", "kode_material *", "nama_material (info)", "kelompok (info)", "satuan_dasar (info)",
           "satuan_beli *", "harga_per_satuan_beli *", "mata_uang", "moq", "lama_kirim_hari", "berlaku_mulai *",
           "berlaku_sampai", "aktif", "catatan", "status kode (info)", "harga ERP sekarang (info)",
           "sumber harga (info)", "keyakinan (info)", "nota asli (info)", "Setuju? (owner)"]
H_CUSTOMER = ["kode (kosongkan = otomatis)", "nama *", "jenis", "npwp", "telepon", "email", "alamat", "termin",
              "batas_kredit_rp", "catatan"]
H_HOLIDAY = ["tanggal * (YYYY-MM-DD)", "nama *", "jenis *", "shift_terdampak", "catatan", "sumber (info)",
             "Setuju? (owner)"]
H_BIN = ["kode_gedung *", "nama_gedung", "kode_zona *", "nama_zona", "jenis_zona", "kode_rak *", "nama_rak",
         "jumlah_susun *", "slot_per_susun *", "kapasitas_per_slot", "satuan", "lokasi ERP terkait (info)", "catatan"]


def run(coro):
    return asyncio.run(coro)


def rows(headers, *values):
    """Baris mentah berjudul template owner (seperti keluaran `_parse_upload`)."""
    out = []
    for n, vals in enumerate(values, start=2):
        r = {h: None for h in headers}
        r.update(vals)
        r["__row__"] = n
        out.append(r)
    return out


@pytest.fixture
def db(monkeypatch):
    d = fm.FakeDB()
    calls = []

    async def fake_subledger(db_, entity_type, doc, user=None, parent_code=None):
        # sub-akun dibuat SESUDAH entitas tersimpan
        coll = {"supplier": "rahaza_suppliers", "customer": "rahaza_customers"}[entity_type]
        assert await db_[coll].find_one({"id": doc["id"]}) is not None
        calls.append((entity_type, doc["id"], doc.get("code")))
        return {"ok": True, "created": True, "code": f"X-{doc.get('code')}"}

    import routes.coa_auto as coa_auto
    monkeypatch.setattr(coa_auto, "ensure_subledger_for_entity", fake_subledger)
    seq = {"n": 0}

    async def gen_code(db_, name=""):
        seq["n"] += 1
        return f"SUP-{9000 + seq['n']:04d}"   # tidak bertabrakan dengan kode seed SUP-0001/0002

    import routes.procurement_suppliers as ps
    monkeypatch.setattr(ps, "_gen_supplier_code", gen_code)

    async def gen_num(db_, coll, field, prefix, width=4, ctx=None, config_key=None):
        seq["n"] += 1
        return f"{prefix}{seq['n']:0{width}d}"

    import core.doc_number_policy as dnp
    monkeypatch.setattr(dnp, "gen_prefixed_number", gen_num)
    d.subledger_calls = calls
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Judul kolom & nilai sel
# ─────────────────────────────────────────────────────────────────────────────
def test_judul_template_owner_dikenali_semua_kolom_erp():
    for headers, cols in ((H_SUPPLIER, dtm.SUPPLIER_COLUMNS), (H_PRICE, dtm.PRICE_COLUMNS + [dtm._APPROVE]),
                          (H_CUSTOMER, dtm.CUSTOMER_COLUMNS), (H_HOLIDAY, dtm.HOLIDAY_COLUMNS + [dtm._APPROVE]),
                          (H_BIN, dtm.BIN_COLUMNS)):
        raw = rows(headers, {h: f"v{i}" for i, h in enumerate(headers)})
        mapped = dtm.map_rows(raw, cols)[0]
        info_cols = [h for h in headers if "(info)" in h and "lokasi" not in h]
        assert len([k for k in mapped if k != "__row__"]) == len(headers) - len(info_cols)
    assert dtm.norm_header("tanggal * (YYYY-MM-DD)") == "tanggal"
    assert dtm.norm_header("Setuju? (owner)") == "setuju"
    # kolom "(info)" lokasi ERP dipakai sebagai kode lokasi zona
    assert dtm.map_rows(rows(H_BIN, {"lokasi ERP terkait (info)": "GD-X (Area)"}), dtm.BIN_COLUMNS)[0][
        "location_code"] == "GD-X (Area)"


def test_angka_dan_tanggal():
    assert dtm._to_num("1.234.567") == 1234567
    assert dtm._to_num("Rp 1.234,50") == 1234.5
    assert dtm._to_num("8,3333") == 8.3333
    assert dtm._to_num(47500) == 47500
    errs = []
    assert dtm._num({"x": "47.500"}, "x", "harga", errs) is None and "ambigu" in errs[0]
    errs = []
    assert dtm._num({"x": "-1"}, "x", "harga", errs) is None and "kurang dari 0" in errs[0]
    errs = []
    assert dtm._date({"d": "25/12/2026"}, "d", "tanggal", errs) == "2026-12-25"
    assert dtm._date({"d": "2026-12-25 00:00:00"}, "d", "tanggal", errs) == "2026-12-25"
    assert dtm._date({"d": "besok"}, "d", "tanggal", errs) is None and "tidak dikenal" in errs[0]


def test_parse_upload_pilih_sheet_template_dan_nomor_baris_asli():
    wb = openpyxl.Workbook()
    wb.active.title = "CHECKLIST"
    wb.active.append(["bukan", "ini"])
    ws = wb.create_sheet("SUPPLIER")
    ws.append(["nama *", "termin_bayar *"])
    ws.append(["PT Satu", "NET 30"])
    ws.append([None, None])                       # baris kosong di tengah
    ws.append(["PT Dua", "COD"])
    buf = io.BytesIO()
    wb.save(buf)
    out = dt._parse_upload("x.xlsx", buf.getvalue(), ["SUPPLIER"])
    assert [r["nama *"] for r in out] == ["PT Satu", "PT Dua"]
    assert [r["__row__"] for r in out] == [2, 4]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Supplier
# ─────────────────────────────────────────────────────────────────────────────
def test_supplier_baru_update_by_kode_dan_nama_tanpa_duplikat(db):
    db.rahaza_suppliers.docs.append({
        "id": "S1", "code": "SUP-0100", "name": "PT. Benang Jaya", "name_key": "benang jaya",
        "payment_terms": "net30", "tax_type": "ppn", "contacts": [{"id": "c1", "name": "Lama", "is_primary": True}],
        "bank_accounts": [], "is_active": True})
    raw = rows(H_SUPPLIER,
               {"kode (kosongkan = otomatis)": "#CONTOH", "nama *": "PT Contoh"},
               {"nama *": "CV Benang Jaya", "status_pajak *": "PKP", "termin_bayar *": "NET 14",
                "kontak_hp": "0811", "bank": "BCA", "no_rekening": "123", "kategori_barang": "Benang, Kain"},
               {"nama *": "Toko Kancing Baru", "status_pajak *": "non-PKP", "termin_bayar *": "COD",
                "kategori_barang": "ATK / Kantor", "lama_kirim_hari": 3, "CV pemakai (info)": "DA"},
               {"nama *": "Toko Kancing Baru", "status_pajak *": "PKP", "termin_bayar *": "NET 7"})
    prep = run(dtm.prepare_suppliers(db, raw, ADMIN))
    assert len(prep.skipped) == 1
    assert [i["action"] for _, i in prep.valid] == ["update", "insert"]
    assert len(prep.invalid) == 1 and "sudah ada di baris 4" in prep.invalid[0]["errors"][0]

    raw = raw[:3]
    res = run(dtm.run_import("suppliers", db, raw, ADMIN, commit=True))
    assert (res["inserted"], res["updated"], res["skipped"]) == (1, 1, 1)
    s1 = run(db.rahaza_suppliers.find_one({"id": "S1"}))
    assert s1["payment_terms"] == "net14" and s1["payment_term_days"] == 14
    assert s1["categories"] == ["yarn", "fabric"]
    assert s1["contacts"][0]["id"] == "c1" and s1["contacts"][0]["phone"] == "0811"   # kontak utama digabung
    assert s1["bank_accounts"][0]["bank_name"] == "BCA" and s1["bank_accounts"][0]["is_primary"]
    baru = run(db.rahaza_suppliers.find_one({"name": "Toko Kancing Baru"}))
    assert baru["code"].startswith("SUP-") and baru["tax_type"] == "non_ppn" and baru["source"] == "import"
    assert baru["categories"] == ["office"] and baru["lead_time_days"] == 3
    # sub-akun hutang lewat Auto Akun untuk KEDUA supplier, sesudah tersimpan
    assert {c[0] for c in db.subledger_calls} == {"supplier"} and len(db.subledger_calls) == 2

    # impor ulang berkas yang sama → semuanya diperbarui, tidak ada supplier baru
    res = run(dtm.run_import("suppliers", db, raw, ADMIN, commit=True))
    assert (res["inserted"], res["updated"]) == (0, 2)
    assert len(db.rahaza_suppliers.docs) == 2


def test_supplier_pilihan_tidak_dikenal_ditolak_bukan_diganti_diam_diam(db):
    raw = rows(H_SUPPLIER,
               {"nama *": "PT A", "status_pajak *": "kena pajak?", "termin_bayar *": "NET 21",
                "mata_uang": "RUPIAH", "kategori_barang": "Kain, Alat jahit", "email": "bukan-email"},
               {"nama *": "PT B"})
    prep = run(dtm.prepare_suppliers(db, raw, ADMIN))
    e1 = " | ".join(prep.invalid[0]["errors"])
    for frag in ("status_pajak", "termin_bayar", "mata_uang", "'Alat jahit'", "email"):
        assert frag in e1
    e2 = " | ".join(prep.invalid[1]["errors"])
    assert "'status_pajak' wajib diisi" in e2 and "'termin_bayar' wajib diisi" in e2
    with pytest.raises(HTTPException) as ex:
        run(dtm.run_import("suppliers", db, raw, ADMIN, commit=True))
    assert ex.value.status_code == 400 and not db.rahaza_suppliers.docs


def test_supplier_kode_baru_dengan_nama_yang_sudah_dipakai_ditolak(db):
    db.rahaza_suppliers.docs.append({"id": "S1", "code": "SUP-0001", "name": "PT Benang Jaya",
                                     "name_key": "benang jaya"})
    raw = rows(H_SUPPLIER, {"kode (kosongkan = otomatis)": "SUP-0999", "nama *": "Benang Jaya",
                            "status_pajak *": "PKP", "termin_bayar *": "NET 30"})
    prep = run(dtm.prepare_suppliers(db, raw, ADMIN))
    assert "sudah dipakai supplier SUP-0001" in prep.invalid[0]["errors"][0]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Daftar harga supplier (sumber /procurement/price-lookup)
# ─────────────────────────────────────────────────────────────────────────────
def _seed_price_masters(db):
    db.rahaza_suppliers.docs += [{"id": "S1", "code": "SUP-0001", "name": "ACSM Uji", "name_key": "acsm uji",
                                  "payment_terms": "net30", "tax_type": "ppn"},
                                 {"id": "S2", "code": "SUP-0002", "name": "Waitex Uji", "name_key": "waitex uji",
                                  "payment_terms": "cod", "tax_type": "non_ppn"}]
    db.rahaza_materials.docs += [
        {"id": "M1", "code": "KN-TES-01", "name": "Kain Uji", "type": "fabric", "base_uom": "kg", "unit": "kg",
         "uoms": [{"code": "kg", "factor": 1, "is_base": True}, {"code": "roll", "factor": 25, "parent": "kg"}]},
        {"id": "M2", "code": "AC-TES-01", "name": "Kancing Uji", "type": "accessory", "unit": "pcs"},
    ]


def test_harga_validasi_bahan_satuan_harga_dan_isi(db):
    _seed_price_masters(db)
    raw = rows(H_PRICE,
               {"nama_supplier *": "ACSM Uji", "kode_material *": "KN-TES-01", "satuan_beli *": "roll",
                "harga_per_satuan_beli *": 1250000, "berlaku_mulai *": "2026-11-01", "aktif": "Ya"},
               {"nama_supplier *": "Tidak Ada", "kode_material *": "KN-XXX", "satuan_beli *": "kg",
                "harga_per_satuan_beli *": 10, "berlaku_mulai *": "2026-11-01"},
               {"nama_supplier *": "SUP-0002", "kode_material *": "KN-TES-01", "satuan_beli *": "yard",
                "harga_per_satuan_beli *": -5, "berlaku_mulai *": "2026-11-01"},
               {"nama_supplier *": "ACSM Uji", "kode_material *": "AC-TES-01", "satuan_beli *": "pcs",
                "harga_per_satuan_beli *": 0, "berlaku_mulai *": "2026-11-01", "Setuju? (owner)": "Tidak"},
               {"nama_supplier *": "ACSM Uji", "kode_material *": "AC-TES-01", "satuan_beli *": "pcs",
                "harga_per_satuan_beli *": 0, "berlaku_mulai *": "2026-11-01"})
    prep = run(dtm.prepare_supplier_prices(db, raw, ADMIN))
    assert len(prep.skipped) == 1 and "Setuju" in prep.skipped[0]["reason"]
    errs = {i["row"]: " | ".join(i["errors"]) for i in prep.invalid}
    assert "belum ada di Master Supplier" in errs[3] and "tidak ada di master bahan" in errs[3]
    assert "bukan satuan bahan KN-TES-01" in errs[4] and "kg, roll" in errs[4]
    assert "tidak boleh kurang dari 0" in errs[4]
    assert [i["row"] for _, i in prep.valid] == [2, 6]          # harga 0 boleh (≥ 0)
    plan = prep.valid[0][0]
    assert plan["doc"]["factor_to_base"] == 25 and plan["doc"]["price_base"] == 50000

    # isi per satuan beli berbeda dengan master → ditolak
    raw2 = [dict(raw[0], **{"isi_per_satuan_beli": 20})]
    prep2 = run(dtm.prepare_supplier_prices(db, raw2, ADMIN))
    assert "tidak sama dengan master bahan" in prep2.invalid[0]["errors"][0]


def test_harga_periode_bentrok_ditolak_dan_upsert_idempoten(db):
    _seed_price_masters(db)
    db.rahaza_supplier_price_lists.docs.append({
        "id": "P-old", "supplier_id": "S1", "material_id": "M1", "uom": "kg", "price": 45000, "price_base": 45000,
        "valid_from": "2026-09-23", "valid_to": None, "is_active": True})
    base = {"nama_supplier *": "ACSM Uji", "kode_material *": "KN-TES-01", "satuan_beli *": "kg"}
    raw = rows(H_PRICE,
               dict(base, **{"harga_per_satuan_beli *": 47500, "berlaku_mulai *": "2026-11-01"}),
               dict(base, **{"harga_per_satuan_beli *": 48000, "berlaku_mulai *": "2026-11-15",
                             "berlaku_sampai": "2026-12-31"}))
    prep = run(dtm.prepare_supplier_prices(db, raw, ADMIN))
    errs = {i["row"]: " | ".join(i["errors"]) for i in prep.invalid}
    assert "harga yang sudah ada (2026-09-23 s.d. seterusnya)" in errs[2]
    assert "bentrok" in errs[3]

    # tutup harga lama DI BERKAS YANG SAMA (kunci sama → diperbarui) → harga baru sah
    raw = rows(H_PRICE,
               dict(base, **{"harga_per_satuan_beli *": 45000, "berlaku_mulai *": "2026-09-23",
                             "berlaku_sampai": "2026-10-31"}),
               dict(base, **{"harga_per_satuan_beli *": 47500, "berlaku_mulai *": "2026-11-01"}))
    res = run(dtm.run_import("supplier_prices", db, raw, ADMIN, commit=True))
    assert (res["inserted"], res["updated"], res["invalid"]) == (1, 1, 0)
    old = run(db.rahaza_supplier_price_lists.find_one({"id": "P-old"}))
    assert old["valid_to"] == "2026-10-31" and old["price"] == 45000
    res = run(dtm.run_import("supplier_prices", db, raw, ADMIN, commit=True))
    assert (res["inserted"], res["updated"]) == (0, 2)
    assert len(db.rahaza_supplier_price_lists.docs) == 2

    # baris nonaktif tidak ikut pemeriksaan periode
    raw3 = rows(H_PRICE, dict(base, **{"harga_per_satuan_beli *": 1, "berlaku_mulai *": "2026-11-05",
                                       "aktif": "Tidak"}))
    assert run(dtm.prepare_supplier_prices(db, raw3, ADMIN)).invalid == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. Pelanggan
# ─────────────────────────────────────────────────────────────────────────────
def test_pelanggan_kode_otomatis_cocok_nama_dan_subakun_piutang(db):
    db.rahaza_customers.docs.append({"id": "C1", "code": "CUST-0001", "name": "Toko Lama", "active": True,
                                     "payment_terms": "cash", "credit_limit": 0})
    raw = rows(H_CUSTOMER,
               {"kode (kosongkan = otomatis)": "#CONTOH", "nama *": "Toko Contoh Grosir"},
               {"nama *": "toko  lama", "termin": "NET 14", "batas_kredit_rp": 5000000, "jenis": "badan usaha"},
               {"nama *": "Butik Baru", "termin": "tunai", "jenis": "perorangan"},
               {"kode (kosongkan = otomatis)": "CUST-0777", "nama *": "Ketik Kode", "termin": "NET 30"},
               {"nama *": "Termin Aneh", "termin": "NET 60"})
    prep = run(dtm.prepare_customers(db, raw, ADMIN))
    assert len(prep.skipped) == 1
    errs = {i["row"]: " | ".join(i["errors"]) for i in prep.invalid}
    assert "OTOMATIS" in errs[5]                    # mode otomatis: kode ketikan untuk pelanggan baru ditolak
    assert "'termin'" in errs[6]
    res = run(dtm.run_import("customers", db, raw[:3], ADMIN, commit=True))
    assert (res["inserted"], res["updated"], res["skipped"]) == (1, 1, 1)
    c1 = run(db.rahaza_customers.find_one({"id": "C1"}))
    assert c1["payment_terms"] == "net_14" and c1["credit_limit"] == 5000000 and c1["company_type"] == "company"
    baru = run(db.rahaza_customers.find_one({"name": "Butik Baru"}))
    assert baru["code"].startswith("CUST-") and baru["payment_terms"] == "cash" and baru["active"] is True
    assert [c[0] for c in db.subledger_calls] == ["customer", "customer"]
    res = run(dtm.run_import("customers", db, raw[:3], ADMIN, commit=True))
    assert (res["inserted"], res["updated"]) == (0, 2)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Kalender libur
# ─────────────────────────────────────────────────────────────────────────────
def test_kalender_upsert_per_tanggal(db):
    db.rahaza_shifts.docs.append({"id": "SH1", "code": "PAGI"})
    db.rahaza_production_calendar.docs.append({"id": "E1", "date": "2026-12-25", "name": "Natal", "type": "special",
                                                "notes": "lama"})
    raw = rows(H_HOLIDAY,
               {"tanggal * (YYYY-MM-DD)": "2026-12-25", "nama *": "Hari Raya Natal", "jenis *": "libur nasional"},
               {"tanggal * (YYYY-MM-DD)": "2026-12-24", "nama *": "Cuti Bersama Natal", "jenis *": "cuti bersama",
                "shift_terdampak": "pagi"},
               {"tanggal * (YYYY-MM-DD)": "2026-12-27", "nama *": "Masuk Pengganti", "jenis *": "hari kerja pengganti"},
               {"tanggal * (YYYY-MM-DD)": None, "nama *": "Isra Mikraj", "jenis *": "libur"},
               {"tanggal * (YYYY-MM-DD)": "2026-12-24", "nama *": "Ganda", "jenis *": "libur"},
               {"tanggal * (YYYY-MM-DD)": "2026-12-31", "nama *": "X", "jenis *": "libur", "shift_terdampak": "MALAM"},
               {"tanggal * (YYYY-MM-DD)": "2026-12-30", "nama *": "Ditolak", "jenis *": "libur",
                "Setuju? (owner)": "Tidak"})
    prep = run(dtm.prepare_holidays(db, raw, ADMIN))
    errs = {i["row"]: " | ".join(i["errors"]) for i in prep.invalid}
    assert "'tanggal' wajib diisi" in errs[5] and "sudah ada di baris 3" in errs[6] and "MALAM" in errs[7]
    assert len(prep.skipped) == 1
    res = run(dtm.run_import("holidays", db, raw[:3], ADMIN, commit=True))
    assert (res["inserted"], res["updated"]) == (2, 1)
    e1 = run(db.rahaza_production_calendar.find_one({"date": "2026-12-25"}))
    assert e1["id"] == "E1" and e1["type"] == "holiday" and e1["notes"] == "lama"
    cb = run(db.rahaza_production_calendar.find_one({"date": "2026-12-24"}))
    assert cb["type"] == "holiday" and cb["affects_shifts"] == ["PAGI"] and cb["month"] == 12
    assert run(db.rahaza_production_calendar.find_one({"date": "2026-12-27"}))["type"] == "exception"
    res = run(dtm.run_import("holidays", db, raw[:3], ADMIN, commit=True))
    assert (res["inserted"], res["updated"]) == (0, 3) and len(db.rahaza_production_calendar.docs) == 3


# ─────────────────────────────────────────────────────────────────────────────
# 5. Rak / bin gudang
# ─────────────────────────────────────────────────────────────────────────────
def test_rak_bin_dibuat_dengan_bin_dan_tautan_lokasi(db):
    db.rahaza_locations.docs += [{"id": "L1", "code": "GD-L1-RAK", "name": "Area Rak Stok", "active": True},
                                 {"id": "L2", "code": "GD-L2-CUT", "name": "Area Cutting", "active": True}]
    raw = rows(H_BIN,
               {"kode_gedung *": "GD-L1", "nama_gedung": "Gudang Lantai 1", "kode_zona *": "ZN-FG",
                "nama_zona": "Zona Barang Jadi", "jenis_zona": "barang jadi (fg)", "kode_rak *": "RK-01",
                "jumlah_susun *": 3, "slot_per_susun *": 4, "satuan": "pcs",
                "lokasi ERP terkait (info)": "GD-L1-RAK (Area Rak Stok)"},
               {"kode_gedung *": "GD-L1", "kode_zona *": "ZN-FG", "kode_rak *": "RK-02",
                "jumlah_susun *": 2, "slot_per_susun *": 2},
               {"kode_gedung *": "GD-L2", "kode_zona *": "ZN-CUT", "jenis_zona": "proses (wip)",
                "lokasi ERP terkait (info)": "GD-L2-CUT (Area Cutting)"},
               {"kode_gedung *": "GD-L2", "kode_zona *": "ZN-X", "lokasi ERP terkait (info)": "TIDAK-ADA"},
               {"kode_gedung *": "GD-L1", "kode_zona *": "ZN-FG", "kode_rak *": "RK-03"},
               {"kode_gedung *": "GD-L1", "kode_zona *": "ZN-FG", "nama_zona": "Nama Lain"})
    prep = run(dtm.prepare_bins(db, raw, ADMIN))
    errs = {i["row"]: " | ".join(i["errors"]) for i in prep.invalid}
    assert "tidak ada / nonaktif di Master Lokasi" in errs[5]
    assert "wajib diisi bila 'kode_rak' diisi" in errs[6]
    assert "berbeda dengan baris 2" in errs[7]
    res = run(dtm.run_import("wh_bins", db, raw[:3], ADMIN, commit=True))
    assert res["inserted"] == 3
    assert len(db.wh_buildings.docs) == 2 and len(db.wh_zones.docs) == 2 and len(db.wh_racks.docs) == 2
    fg = run(db.wh_zones.find_one({"code": "ZN-FG"}))
    assert fg["zone_type"] == "fg" and fg["location_id"] == "L1" and fg["location_code"] == "GD-L1-RAK"
    assert run(db.wh_zones.find_one({"code": "ZN-CUT"}))["zone_type"] == "wip"
    assert len(db.wh_positions.docs) == 12 + 4
    codes = [p["barcode"] for p in db.wh_positions.docs]
    assert len(set(codes)) == len(codes) and max(len(c) for c in codes) <= 18

    # impor ulang: tidak ada gedung/zona/rak/bin kembar
    res = run(dtm.run_import("wh_bins", db, raw[:3], ADMIN, commit=True))
    assert (res["inserted"], res["updated"]) == (0, 3) and len(db.wh_positions.docs) == 16
    # tambah slot → +3 bin; kurangi → ditolak
    bigger = [dict(raw[0], **{"slot_per_susun *": 5})]
    run(dtm.run_import("wh_bins", db, bigger, ADMIN, commit=True))
    rk = run(db.wh_racks.find_one({"code": "RK-01"}))
    assert rk["slots_per_shelf"] == 5 and len([p for p in db.wh_positions.docs if p["rack_id"] == rk["id"]]) == 15
    smaller = [dict(raw[0], **{"slot_per_susun *": 2})]
    assert "tidak bisa dikurangi" in run(dtm.prepare_bins(db, smaller, ADMIN)).invalid[0]["errors"][0]


def test_rak_besar_tidak_menggandakan_bin_lama(db):
    """2026-11-06 (pola P7): dulu daftar bin lama `to_list(500)` → rak 600 bin dibuat ulang sebagian."""
    from routes import wms_structure as ws
    b = ws.building_doc(ws.BuildingIn(code="GD-9", name="G"), ADMIN)
    run(db.wh_buildings.insert_one(b))
    z = ws.zone_doc(b, ws.ZoneIn(building_id=b["id"], code="ZN-9", name="Z"), {}, ADMIN)
    run(db.wh_zones.insert_one(z))
    rack, n = run(ws.insert_rack(db, z, b, ws.RackIn(zone_id=z["id"], code="RK-9", name="R", num_shelves=30,
                                                     slots_per_shelf=20), ADMIN))
    assert n == 600
    run(db.wh_racks.update_one({"id": rack["id"]}, {"$set": {"slots_per_shelf": 21}}))
    assert run(ws.add_missing_positions(db, rack["id"])) == 30
    codes = [p["barcode"] for p in db.wh_positions.docs]
    assert len(codes) == 630 and len(set(codes)) == 630


def test_unduh_lalu_unggah_ulang_hanya_memperbarui(db):
    """Berkas Unduh = format template impor: diunggah lagi tanpa perubahan → semua 'update', nol galat."""
    _seed_price_masters(db)
    db.rahaza_locations.docs.append({"id": "L1", "code": "GD-L1-RAK", "name": "Area Rak", "active": True})
    run(dtm.run_import("suppliers", db, rows(H_SUPPLIER, {
        "nama *": "PT Satu Uji", "status_pajak *": "PKP", "termin_bayar *": "NET 30", "kontak_nama": "Bu A",
        "bank": "BRI", "kategori_barang": "Kain, Jasa"}), ADMIN, commit=True))
    run(dtm.run_import("supplier_prices", db, rows(H_PRICE, {
        "nama_supplier *": "ACSM Uji", "kode_material *": "KN-TES-01", "satuan_beli *": "roll",
        "harga_per_satuan_beli *": 1250000, "berlaku_mulai *": "2026-11-01"}), ADMIN, commit=True))
    run(dtm.run_import("customers", db, rows(H_CUSTOMER, {"nama *": "Butik Uji", "termin": "NET 7"}), ADMIN,
                       commit=True))
    run(dtm.run_import("holidays", db, rows(H_HOLIDAY, {"tanggal * (YYYY-MM-DD)": "2026-12-25", "nama *": "Natal",
                                                        "jenis *": "libur"}), ADMIN, commit=True))
    run(dtm.run_import("wh_bins", db, rows(H_BIN, {
        "kode_gedung *": "GD-L1", "kode_zona *": "ZN-FG", "jenis_zona": "fg", "kode_rak *": "RK-01",
        "jumlah_susun *": 2, "slot_per_susun *": 3, "lokasi ERP terkait (info)": "GD-L1-RAK"},
        {"kode_gedung *": "GD-L1", "kode_zona *": "ZN-QC"}), ADMIN, commit=True))
    for key in ("suppliers", "supplier_prices", "customers", "holidays", "wh_bins"):
        h = dtm.HANDLERS[key]
        exported = run(h["export"](db))
        assert exported, key
        raw = [{c["header"]: r.get(c["name"]) for c in h["columns"]} for r in exported]
        res = run(dtm.run_import(key, db, raw, ADMIN, commit=False))
        assert res["invalid"] == 0, (key, res["preview_invalid"])
        assert res["would_insert"] == 0 and res["would_update"] == len(exported), key


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint Data Transfer: hak akses, pratinjau → terapkan, template, log aktivitas
# ─────────────────────────────────────────────────────────────────────────────
class _File:
    def __init__(self, data, name="isian.xlsx"):
        self.filename, self._data = name, data

    async def read(self):
        return self._data


def _xlsx(sheets: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, (headers, data) in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(headers)
        for r in data:
            ws.append([r.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_endpoint_impor_supplier_dari_workbook_owner(db, monkeypatch):
    import routes.procurement_suppliers as ps
    logs = []

    async def auth(_r):
        return ADMIN

    async def guard(_r):
        return ADMIN

    async def log_act(*a, **k):
        logs.append(a)
    monkeypatch.setattr(dt, "require_auth", auth)
    monkeypatch.setattr(dt, "get_db", lambda: db)
    monkeypatch.setattr(dt, "log_activity", log_act)
    monkeypatch.setattr(ps, "_require_procurement", guard)
    data = _xlsx({"CHECKLIST": (["a"], []),
                  "SUPPLIER": (H_SUPPLIER, [{"nama *": "PT Uji Satu", "status_pajak *": "PKP",
                                             "termin_bayar *": "NET 30"}])})
    prev = run(dt.import_table("suppliers", object(), _File(data), mode="dry_run"))
    assert (prev["valid"], prev["would_insert"], prev["invalid"]) == (1, 1, 0) and not db.rahaza_suppliers.docs
    done = run(dt.import_table("suppliers", object(), _File(data), mode="commit"))
    assert done["committed"] and done["inserted"] == 1 and len(db.rahaza_suppliers.docs) == 1
    assert logs and logs[-1][2] == "import" and logs[-1][3] == "data-transfer:suppliers"

    # pengguna yang ditolak penjaga pengadaan → 403
    async def deny(_r):
        raise HTTPException(403, "Forbidden")
    monkeypatch.setattr(ps, "_require_procurement", deny)
    with pytest.raises(HTTPException) as ex:
        run(dt.import_table("suppliers", object(), _File(data), mode="commit"))
    assert ex.value.status_code == 403


def test_hak_akses_kalender_dan_bin_ikut_peran_master():
    hol, bins = dt.REGISTRY["holidays"], dt.REGISTRY["wh_bins"]
    assert dt._can_import({"role": "staff_hr"}, hol) and dt._can_import({"role": "admin_produksi"}, hol)
    assert not dt._can_import({"role": "admin_gudang"}, hol)
    assert dt._can_import({"role": "admin_gudang"}, bins) and not dt._can_import({"role": "staff_hr"}, bins)
    assert dt._can_import({"role": "owner"}, bins) and dt._can_import({"role": "superadmin"}, hol)


def test_template_memakai_judul_kolom_owner(monkeypatch):
    async def auth(_r):
        return ADMIN
    monkeypatch.setattr(dt, "require_auth", auth)
    resp = run(dt.template_table("holidays", object(), format="xlsx"))

    async def body():
        return b"".join([c async for c in resp.body_iterator])
    data = run(body())
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws.title == "KALENDER_LIBUR"
    assert [c.value for c in ws[1]] == [c["header"] for c in dtm.HOLIDAY_COLUMNS]
    assert ws["A1"].comment is not None and str(ws["A2"].value).startswith("#")
    # baris contoh template dilewati saat diunggah kembali
    raw = dt._parse_upload("t.xlsx", data, dtm.HANDLERS["holidays"]["sheet_names"])
    assert dtm._skip_reason(dtm.map_rows(raw, dtm.HOLIDAY_COLUMNS)[0], "date")
