"""Uji katalog data Asisten AI (Tahap E, K1) — definisi dataset + pembangun pipeline (fungsi murni).

Hermetik: tanpa Mongo sungguhan dan tanpa API. Saringan `$match` diperiksa dengan pencocok `_fake_mongo.match`
(operator kueri); ekspresi agregasi diuji semantiknya terpisah terhadap Mongo 7 (lihat laporan agen DATA).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
for p in (str(BACKEND), os.path.dirname(os.path.abspath(__file__))):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

import _fake_mongo as fm  # noqa: E402

from core.asisten_ai import katalog_data as K  # noqa: E402
from core.asisten_ai.alat_base import _PII_KEY_RX  # noqa: E402
from core.asisten_ai.katalog_data import IsianSalah  # noqa: E402


def ds(ds_id: str) -> K.Dataset:
    d = K.cari_dataset(ds_id)
    assert d is not None, ds_id
    return d


def rencana(ds_id: str, isian: dict, **kw) -> K.Rencana:
    return K.bangun_rencana(ds(ds_id), {"dataset": ds_id, **isian}, **kw)


def tahap(r: K.Rencana, nama: str) -> list:
    return [s[nama] for s in r.pipeline if nama in s]


def facet(r: K.Rencana) -> dict:
    return tahap(r, "$facet")[0]


def semua_kunci(obj) -> set:
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= semua_kunci(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= semua_kunci(v)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Katalog: setiap dataset sah
# ══════════════════════════════════════════════════════════════════════════════
def test_katalog_dimuat_tanpa_galat_dan_cukup_dataset():
    assert K.muat_katalog(paksa=True) == {}
    ids = [d.id for d in K.semua_dataset()]
    assert len(ids) == len(set(ids))
    assert 12 <= len(ids) <= 20
    for wajib in ("penjualan_harian_toko", "pesanan_marketplace", "item_pesanan_marketplace", "iklan_harian",
                  "setoran_marketplace", "produk_varian", "posisi_stok", "mutasi_stok", "po_produksi", "kiriman_cmt",
                  "terima_qc_cmt", "tagihan_cmt", "po_pembelian", "faktur_pemasok", "baris_jurnal", "mutasi_kas_bank",
                  "karyawan", "absensi", "po_maklon"):
        assert wajib in ids


@pytest.mark.parametrize("d", K.semua_dataset(), ids=lambda d: d.id)
def test_setiap_dataset_valid(d):
    assert K.periksa_dataset(d) == []
    for k in K.kolom_lengkap(d).values():
        assert k.tipe in K.TIPE
        assert not _PII_KEY_RX.search(k.nama), k.nama
        if re.search(r"gaji|upah|salary|base_rate", k.nama):
            assert k.rahasia == "gaji", k.nama
        for p in ([k.path] if k.path else []) + list(k.cadangan):
            assert re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", p) and "$" not in p
        if k.tipe in ("tanggal", "waktu") and not k.dasar:
            assert k.simpan in K.SIMPAN
    if d.kolom_tanggal:
        assert K.kolom_lengkap(d)[d.kolom_tanggal].tipe in ("tanggal", "waktu")
    # pipeline bawaan selalu ber-$limit dan tanpa operator berbahaya
    r = K.bangun_rencana(d, {"dataset": d.id})
    assert any("$limit" in s for s in facet(r)["baris"])
    assert not semua_kunci(r.pipeline) & {"$where", "$function", "$accumulator", "$out", "$merge"}
    assert r.pipeline[0].get("$match") is not None   # data contoh selalu dibuang


@pytest.mark.parametrize("d", K.semua_dataset(), ids=lambda d: d.id)
def test_koleksi_terdaftar_resmi(d):
    from core.collection_registry import is_registered
    assert is_registered(d.koleksi)
    for g in d.gabung:
        assert is_registered(g.dari)


RAHASIA = {"bank_account_number", "account_number", "ktp_number", "npwp_number", "vendor_npwp", "supplier_bank",
           "phone", "email", "password", "token", "bpjs_kesehatan_number", "bpjs_ketenagakerjaan_number",
           "birth_date", "current_address", "ktp_address", "emergency_phone", "photo_selfie_url", "clock_in_geo",
           "cmt_price_snapshot", "cmt_rate_per_pcs", "breakdown", "credentials"}
PEMBELI = {"buyer_username", "customer_name", "customer_phone", "customer_address", "address_detail", "city",
           "province", "district", "village", "zipcode", "buyer_message", "tracking_number"}


@pytest.mark.parametrize("d", K.semua_dataset(), ids=lambda d: d.id)
def test_tidak_ada_field_rahasia_di_katalog(d):
    dipakai = set()
    for k in d.kolom:
        for p in ([k.path] if k.path else []) + list(k.cadangan):
            dipakai.add(p.split(".")[-1])
        dipakai |= {x.lstrip("$").split(".")[-1] for x in re.findall(r"\$[A-Za-z_.]+", json.dumps(k.ekspr))}
    for g in d.gabung:
        dipakai |= {a.split(".")[-1] for a in g.ambil}
    assert not dipakai & RAHASIA
    if d.koleksi == "marketing_orders":
        assert not dipakai & PEMBELI
    # gaji hanya lewat kolom rahasia
    for k in d.kolom:
        if k.path and k.path.split(".")[-1] in ("base_rate", "overtime_rate", "pay_scheme"):
            assert k.rahasia == "gaji"


def test_kolom_turunan_tanggal_utama():
    semua = K.kolom_lengkap(ds("baris_jurnal"))
    for t in ("tanggal_bulan", "tanggal_minggu", "tanggal_tahun"):
        assert semua[t].dasar == "tanggal" and semua[t].tipe == "teks" and not semua[t].bawaan


def test_definisi_tidak_sah_ditolak():
    salah = K.Dataset(id="x", label="", keterangan="", koleksi="Bad-Name", domain="lain", akses=K.Akses(),
                      kolom=(K.Kolom("Nama Salah", "", "teks"), K.Kolom("buyer_phone", "HP", "teks", path="a$b"),
                             K.Kolom("tgl", "Tgl", "tanggal", path="d"),
                             K.Kolom("gaji_x", "Gaji", "uang", path="g"),
                             K.Kolom("ex", "E", "teks", ekspr={"$function": {}})),
                      kolom_tanggal="tidak_ada", cv={"mode": "aneh"})
    errs = " | ".join(K.periksa_dataset(salah))
    for potongan in ("id harus", "label dan keterangan", "koleksi tidak sah", "domain", "akses wajib",
                     "snake_case", "data pribadi", "tidak sah", "simpan", "rahasia='gaji'", "terlarang",
                     "kolom_tanggal", "mode CV"):
        assert potongan in errs, potongan


# ══════════════════════════════════════════════════════════════════════════════
# Pembangun pipeline
# ══════════════════════════════════════════════════════════════════════════════
def test_mode_baris_bawaan_urut_tanggal_turun_dan_batas():
    r = rencana("baris_jurnal", {}, batas_maks=200, batas_bawaan=100)
    assert r.mode == "baris" and r.batas == 100
    st = facet(r)["baris"]
    assert st[0] == {"$sort": {"tanggal": -1}} and st[1] == {"$limit": 100}
    nama = [c["nama"] for c in r.kolom]
    assert "tanggal" in nama and "kode_akun" in nama and "periode" not in nama   # bukan kolom bawaan
    assert facet(r)["total"] == [{"$count": "n"}]


def test_filter_setiap_operator():
    r = rencana("baris_jurnal", {"filter": [
        {"kolom": "kode_akun", "op": "=", "nilai": "1-1100"},
        {"kolom": "jenis_akun", "op": "!=", "nilai": "ASSET"},
        {"kolom": "debit", "op": ">", "nilai": 10},
        {"kolom": "kredit", "op": "<=", "nilai": "250.5"},
        {"kolom": "modul_sumber", "op": "in", "nilai": ["manual", "expense"]},
        {"kolom": "no_jurnal", "op": "not_in", "nilai": ["JE-1"]},
        {"kolom": "keterangan", "op": "berisi", "nilai": "a.b*(c)"},
        {"kolom": "periode", "op": "kosong"},
        {"kolom": "nama_akun", "op": "tidak_kosong"},
        {"kolom": "tanggal", "op": ">=", "nilai": "2026-10-01"},
    ]})
    pasca = [s["$match"] for s in r.pipeline if "$match" in s][-1]["$and"]
    assert {"kode_akun": "1-1100"} in pasca
    assert {"jenis_akun": {"$ne": "ASSET"}} in pasca
    assert {"debit": {"$gt": 10.0}} in pasca
    assert {"kredit": {"$lte": 250.5}} in pasca
    assert {"modul_sumber": {"$in": ["manual", "expense"]}} in pasca
    assert {"no_jurnal": {"$nin": ["JE-1"]}} in pasca
    assert {"keterangan": {"$regex": re.escape("a.b*(c)"), "$options": "i"}} in pasca
    assert {"$or": [{"periode": None}, {"periode": ""}]} in pasca
    assert {"$and": [{"nama_akun": {"$ne": None}}, {"nama_akun": {"$ne": ""}}]} in pasca
    assert {"tanggal": {"$gte": "2026-10-01"}} in pasca
    # regex di-escape: titik/bintang tidak lagi berarti pola
    rx = next(f for f in pasca if "keterangan" in f)["keterangan"]
    assert fm.match({"k": "xa.b*(c)y"}, {"k": rx}) and not fm.match({"k": "axbbbc"}, {"k": rx})


def test_periode_teks_dan_campur_memakai_saringan_mentah_dan_pasca():
    r = rencana("baris_jurnal", {"periode": {"dari": "2026-10-01", "sampai": "2026-10-31"}})
    m0 = r.pipeline[0]["$match"]
    teks = json.dumps(m0)
    assert '"date": {"$gte": "2026-10-01", "$lte": "2026-10-31' in teks
    akhir = [s["$match"] for s in r.pipeline if "$match" in s][-1]
    assert {"tanggal": {"$gte": "2026-10-01", "$lte": "2026-10-31"}} in akhir.get("$and", [akhir])
    r2 = rencana("pesanan_marketplace", {"periode": {"dari": "2026-10-01", "sampai": "2026-10-31"}},
                 saringan_awal=[{"account_id": {"$in": ["t1"]}}])
    m0 = r2.pipeline[0]["$match"]
    from datetime import datetime, timezone
    doc_dt = {"account_id": "t1", "order_date": datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)}
    doc_str = {"account_id": "t1", "order_date": "2026-10-05 10:00"}
    doc_luar = {"account_id": "t1", "order_date": datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)}
    doc_toko_lain = {"account_id": "t2", "order_date": "2026-10-05"}
    assert fm.match(doc_dt, m0) and fm.match(doc_str, m0)
    assert not fm.match(doc_luar, m0) and not fm.match(doc_toko_lain, m0)


def test_periode_tidak_sah():
    with pytest.raises(IsianSalah, match="lebih awal"):
        rencana("baris_jurnal", {"periode": {"dari": "2026-10-31", "sampai": "2026-10-01"}})
    with pytest.raises(IsianSalah, match="paling panjang"):
        rencana("baris_jurnal", {"periode": {"dari": "2020-01-01", "sampai": "2026-10-01"}})
    with pytest.raises(IsianSalah, match="bukan tanggal"):
        rencana("baris_jurnal", {"periode": {"dari": "31-10-2026"}})
    with pytest.raises(IsianSalah, match="tidak punya kolom tanggal"):
        rencana("produk_varian", {"periode": {"dari": "2026-10-01"}})


def test_kelompok_agregasi_dan_turunan_bulan():
    r = rencana("baris_jurnal", {"kelompok": ["tanggal_bulan", "jenis_akun"], "agregasi": [
        {"fungsi": "jumlah", "kolom": "debit"}, {"fungsi": "rata", "kolom": "kredit", "nama": "rata_kredit"},
        {"fungsi": "min", "kolom": "tanggal"}, {"fungsi": "maks", "kolom": "debit"},
        {"fungsi": "hitung"}, {"fungsi": "hitung", "kolom": "keterangan"},
        {"fungsi": "hitung_unik", "kolom": "no_jurnal"}]})
    assert r.mode == "kelompok"
    assert tahap(r, "$set") and "tanggal_bulan" in tahap(r, "$set")[0]
    proj = tahap(r, "$project")[0]
    assert "tanggal" in proj and "tanggal_bulan" not in proj      # turunan dihitung dari kolom dasar
    grp = tahap(r, "$group")[0]
    assert grp["_id"] == {"tanggal_bulan": "$tanggal_bulan", "jenis_akun": "$jenis_akun"}
    assert grp["jumlah_debit"] == {"$sum": "$debit"} and grp["rata_kredit"] == {"$avg": "$kredit"}
    assert grp["min_tanggal"] == {"$min": "$tanggal"} and grp["maks_debit"] == {"$max": "$debit"}
    assert grp["jumlah_baris"] == {"$sum": 1}
    assert "$cond" in grp["hitung_keterangan"]["$sum"]
    assert grp["hitung_unik_no_jurnal"] == {"$addToSet": "$no_jurnal"}
    proj2 = tahap(r, "$project")[1]
    assert proj2["hitung_unik_no_jurnal"] == {"$size": {"$setDifference": ["$hitung_unik_no_jurnal", [None, ""]]}}
    assert proj2["tanggal_bulan"] == "$_id.tanggal_bulan"
    # kelompok waktu → urut naik menurut kelompok
    assert facet(r)["baris"][0] == {"$sort": {"tanggal_bulan": 1, "jenis_akun": 1}}
    tipe = {c["nama"]: c["tipe"] for c in r.kolom}
    assert tipe["jumlah_debit"] == "uang" and tipe["jumlah_baris"] == "angka" and tipe["min_tanggal"] == "tanggal"


def test_kelompok_tanpa_agregasi_menghitung_baris_dan_urut_terbesar():
    r = rencana("mutasi_kas_bank", {"kelompok": ["kategori"]})
    assert [c["nama"] for c in r.kolom] == ["kategori", "jumlah_baris"]
    assert facet(r)["baris"][0] == {"$sort": {"jumlah_baris": -1}}
    r = rencana("mutasi_kas_bank", {"agregasi": [{"fungsi": "jumlah", "kolom": "masuk"}]})
    assert tahap(r, "$group")[0]["_id"] is None


def test_urut_dan_batas():
    r = rencana("baris_jurnal", {"kelompok": ["kode_akun"], "agregasi": [{"fungsi": "jumlah", "kolom": "debit"}],
                                 "urut": [{"kolom": "jumlah_debit", "arah": "turun"}], "batas": 7})
    assert facet(r)["baris"][:2] == [{"$sort": {"jumlah_debit": -1}}, {"$limit": 7}]
    with pytest.raises(IsianSalah, match="kolom kelompok atau nama agregasi"):
        rencana("baris_jurnal", {"kelompok": ["kode_akun"], "urut": [{"kolom": "debit"}]})
    r = rencana("baris_jurnal", {"batas": 1000}, batas_maks=200)
    assert r.batas == 200 and any("diturunkan" in c for c in r.catatan)
    r = rencana("baris_jurnal", {"batas": 4000}, batas_maks=5000)
    assert r.batas == 4000
    with pytest.raises(IsianSalah, match="Batas"):
        rencana("baris_jurnal", {"batas": 0})
    # urut mode baris memakai kolom yang tidak ditampilkan → tetap diproyeksikan, tidak dikeluarkan
    r = rencana("baris_jurnal", {"kolom": ["no_jurnal"], "urut": [{"kolom": "debit", "arah": "naik"}]})
    assert "debit" in tahap(r, "$project")[0]
    assert facet(r)["baris"][-1] == {"$project": {"_id": 0, "no_jurnal": 1}}


@pytest.mark.parametrize("isian,pesan", [
    ({"kolom": ["tidak_ada"]}, "tidak ada di data"),
    ({"kolom": ["$where"]}, "tidak ada di data"),
    ({"filter": [{"kolom": "debit", "op": "$gt", "nilai": 1}]}, "Operator"),
    ({"filter": [{"kolom": "debit", "op": "=", "nilai": {"$gt": 1}}]}, "bukan objek"),
    ({"filter": [{"kolom": "kode_akun", "op": "=", "nilai": "$account_code"}]}, "tanda \\$"),
    ({"filter": [{"kolom": "kode_akun", "op": "in", "nilai": [{"$ne": 1}]}]}, "bukan objek"),
    ({"filter": [{"kolom": "kode_akun", "op": "in", "nilai": [["a"]]}]}, "bukan objek"),
    ({"filter": [{"kolom": "kode_akun", "op": "in", "nilai": "a"}]}, "daftar nilai"),
    ({"filter": [{"kolom": "debit", "op": "berisi", "nilai": "1"}]}, "hanya untuk kolom teks"),
    ({"filter": [{"kolom": "debit", "op": "=", "nilai": "seribu"}]}, "bukan angka"),
    ({"filter": [{"kolom": "debit", "op": "=", "nilai": True}]}, "ya/tidak"),
    ({"filter": [{"kolom": "tanggal", "op": "=", "nilai": "kemarin"}]}, "bukan tanggal"),
    ({"filter": [{"kolom": "debit", "op": "=", "nilai": 1, "$where": "x"}]}, "kolom, op, nilai"),
    ({"filter": {"kolom": "debit"}}, "daftar"),
    ({"agregasi": [{"fungsi": "median", "kolom": "debit"}]}, "tidak dikenal"),
    ({"agregasi": [{"fungsi": "jumlah", "kolom": "kode_akun"}]}, "angka/uang"),
    ({"agregasi": [{"fungsi": "jumlah"}]}, "butuh kolom"),
    ({"agregasi": [{"fungsi": "hitung", "nama": "$x"}]}, "snake_case"),
    ({"kelompok": ["kode_akun"], "agregasi": [{"fungsi": "hitung", "nama": "kode_akun"}]}, "bentrok"),
    ({"pipeline": [{"$out": "x"}]}, "tidak dikenal"),
    ({"filter": [{"kolom": "kode_akun", "op": "=", "nilai": "x" * 300}]}, "paling panjang"),
])
def test_isian_berbahaya_atau_salah_ditolak(isian, pesan):
    with pytest.raises(IsianSalah, match=pesan):
        rencana("baris_jurnal", isian)


def test_nilai_tidak_pernah_menjadi_operator_atau_ekspresi():
    """Nilai isian hanya muncul sebagai literal di $match kueri — tidak pernah di $expr/proyeksi."""
    r = rencana("baris_jurnal", {"filter": [{"kolom": "kode_akun", "op": "=", "nilai": "1-1100"},
                                            {"kolom": "keterangan", "op": "berisi", "nilai": "listrik"}]})
    teks = json.dumps([s for s in r.pipeline if "$match" not in s])
    assert "1-1100" not in teks and "listrik" not in teks
    assert "$expr" not in json.dumps(r.pipeline)


def test_kolom_tersembunyi_ditolak_dan_tidak_di_bawaan():
    d = ds("karyawan")
    boleh = {n for n, k in K.kolom_lengkap(d).items() if k.rahasia != "gaji"}
    r = K.bangun_rencana(d, {"dataset": "karyawan"}, kolom_boleh=boleh)
    assert "gaji_pokok" not in [c["nama"] for c in r.kolom]
    assert "_gaji" not in json.dumps(r.pipeline)          # gabung gaji tidak dipasang sama sekali
    for isian in ({"kolom": ["gaji_pokok"]}, {"filter": [{"kolom": "gaji_pokok", "op": ">", "nilai": 1}]},
                  {"kelompok": ["skema_gaji"]}, {"agregasi": [{"fungsi": "jumlah", "kolom": "gaji_pokok"}]}):
        with pytest.raises(IsianSalah, match="tidak boleh dibaca"):
            K.bangun_rencana(d, {"dataset": "karyawan", **isian}, kolom_boleh=boleh)


def test_samaran_dipulihkan_untuk_filter_dan_ditandai_untuk_keluaran():
    peta = {"VND-001": "CV Jahit Maju"}
    r = rencana("tagihan_cmt", {"filter": [{"kolom": "vendor", "op": "=", "nilai": "VND-001"},
                                           {"kolom": "vendor", "op": "berisi", "nilai": "VND-001"}],
                                "kolom": ["vendor", "nilai_tagihan"]}, pulihkan=peta.get)
    pasca = [s["$match"] for s in r.pipeline if "$match" in s][-1]["$and"]
    assert {"vendor": "CV Jahit Maju"} in pasca
    assert {"vendor": {"$regex": re.escape("CV Jahit Maju"), "$options": "i"}} in pasca
    assert r.samaran == {"vendor": "vendor"}
    r = rencana("tagihan_cmt", {"kelompok": ["vendor"], "agregasi": [{"fungsi": "jumlah", "kolom": "nilai_tagihan"}]})
    assert r.samaran == {"vendor": "vendor"}


def test_data_contoh_dan_dok_batal_dibuang():
    r = rencana("faktur_pemasok", {})
    m0 = r.pipeline[0]["$match"]
    assert fm.match({"status": "sent"}, m0)
    assert not fm.match({"status": "sent", "_seed_origin": True}, m0)
    assert not fm.match({"status": "sent", "_seed_origin": "demo_seed"}, m0)
    assert fm.match({"status": "sent", "_seed_origin": False}, m0)
    assert not fm.match({"status": "cancelled"}, m0)
    r = rencana("tagihan_cmt", {})
    m0 = r.pipeline[0]["$match"]
    for st in ("cancelled", "void", "voided"):
        assert not fm.match({"status": st}, m0)
    assert fm.match({"status": "posted"}, m0)
    r = rencana("mutasi_stok", {})
    m0 = r.pipeline[0]["$match"]
    assert fm.match({"op": "add"}, m0) and not fm.match({"op": "reserve"}, m0) and not fm.match({"op": "uom_rebase"}, m0)


def test_unwind_gabung_dan_saringan_cv_setelah_gabung():
    r = rencana("tagihan_cmt", {}, saringan_gabung=[ds("tagihan_cmt").cv["DA"]])
    jenis = [next(iter(s)) for s in r.pipeline]
    assert jenis.index("$lookup") < jenis.index("$match", 1) < jenis.index("$project")
    lk = tahap(r, "$lookup")[0]
    assert lk["from"] == "production_pos" and lk["as"] == "_po"
    # kolom gabung tidak diminta & tanpa CV → lookup tidak dipasang
    r = rencana("tagihan_cmt", {"kolom": ["no_tagihan"]})
    assert not tahap(r, "$lookup")
    # dataset baris: lookup banyak + unwind yang mempertahankan dok tanpa baris
    r = rencana("po_produksi", {})
    assert tahap(r, "$unwind")[0] == {"path": "$_baris", "preserveNullAndEmptyArrays": True}
    r = rencana("item_pesanan_marketplace", {})
    assert tahap(r, "$unwind")[0] == {"path": "$items", "preserveNullAndEmptyArrays": False}


def test_saringan_cv_jenis_po_mencakup_dok_tanpa_field():
    d = ds("po_produksi")
    da, smu = d.cv["DA"], d.cv["SMU"]
    assert fm.match({}, da) and fm.match({"business_type": "internal"}, da)
    assert not fm.match({"business_type": "maklon"}, da)
    assert fm.match({"business_type": "maklon"}, smu) and not fm.match({}, smu)
    t = ds("tagihan_cmt").cv
    assert fm.match({"_po": {"business_type": "internal"}}, t["DA"])
    assert fm.match({}, t["DA"])                                   # tagihan tanpa PO = DA
    assert fm.match({"entity": "SMU"}, t["SMU"]) and not fm.match({"entity": "SMU"}, t["DA"])
    assert fm.match({"_po": {"business_type": "maklon"}}, t["SMU"])
