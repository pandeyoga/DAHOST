"""Tahap 6 — keputusan owner untuk Keuangan (2026-11-07), hermetik (FakeDB, tanpa server).

KU1  Jurnal otomatis per transaksi: pilihan akun tiap peran disaring JENISnya (kas/bank, piutang, hutang,
     pendapatan, beban/HPP, …) dengan aturan server `rahaza_coa.type_family` + daftar kas/bank SSOT
     (`fin_statements.cash_account_codes`). Server ikut menolak peran yang DIUBAH ke akun di luar jenisnya,
     kecuali peran itu dikirim di `off_type_ok` ("Tampilkan semua akun"); nilai lama yang tidak diubah tetap.
KU2  Aset tetap "Hutang pemasok — faktur menyusul" wajib pemasok dari master `rahaza_suppliers` (id + nama
     disimpan, divalidasi server); sumber dana lain tetap teks bebas. Pilihan pemasok lewat acquisition-options.
KU4  Baris jurnal manual ke akun kontrol piutang/hutang → peringatan di layar (penanda `control_kind` dari
     penanda akun / induk sub-ledger; kode 1-1301/2-1100 hanya cadangan). Simpan TIDAK diblokir.
"""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-rahasia")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
import routes.rahaza_coa as coa  # noqa: E402
import routes.rahaza_fixed_assets as fa  # noqa: E402
import routes.rahaza_journals as rj  # noqa: E402
import routes.rahaza_posting as rp  # noqa: E402
import routes.rahaza_posting_profiles as pp  # noqa: E402

FE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "erp"
USER = {"id": "u-fin", "name": "Staf Keuangan Uji", "email": "fin@x", "role": "accounting"}


def run(c):
    return asyncio.run(c)


def _fe(rel: str) -> str:
    p = FE / rel
    if not p.exists():
        pytest.skip(f"berkas layar tidak ada di checkout ini: {rel}")
    return p.read_text(encoding="utf-8")


def acc(code, type_, name=None, group=False, parent=None, active=True, flags=None):
    return {"id": f"id-{code}", "code": code, "name": name or f"Akun {code}", "type": type_, "is_group": group,
            "parent_code": parent, "active": active, "flags": flags or {}}


async def _auth(_req):
    return dict(USER)


async def _noop(*_a, **_k):
    return None


@pytest.fixture
def db(monkeypatch):
    d = fm.FakeDB()
    d.rahaza_coa_accounts.docs += [
        acc("1-1100", "ASSET", "Kas", group=True, flags={"is_cash": True}),
        acc("1-1101", "ASSET", "Kas Kecil", parent="1-1100", flags={"is_cash": True}),
        acc("1-1200", "ASSET", "Bank", group=True, flags={"is_bank": True}),
        acc("1-1201", "ASSET", "Bank Satu", parent="1-1200", flags={"is_bank": True}),
        acc("1-1202", "ASSET", "Bank Dua", parent="1-1200", flags={"is_bank": True}),
        acc("1-1209", "ASSET", "Bank Tiga (tanpa penanda)", parent="1-1200"),
        acc("1-1301", "ASSET", "Piutang Usaha", flags={"is_ar": True}),
        acc("1-1401", "ASSET", "Persediaan Bahan"),
        acc("2-1100", "LIABILITY", "Hutang Usaha", flags={"is_ap": True}),
        acc("2-1150", "LIABILITY", "Hutang Belum Ditagih"),
        acc("4-1100", "REVENUE", "Penjualan"),
        acc("4-9000", "OTHER_INCOME", "Pendapatan Lain"),
        acc("5-1000", "COGS", "HPP Bahan"),
        acc("6-2900", "EXPENSE", "Beban Umum"),
        acc("6-2000", "EXPENSE", "Beban (grup)", group=True),
    ]
    for mod in (coa, pp, rj, fa):
        monkeypatch.setattr(mod, "get_db", lambda d=d: d)
        if hasattr(mod, "log_activity"):
            monkeypatch.setattr(mod, "log_activity", _noop)
    for mod in (coa, pp, rj):
        monkeypatch.setattr(mod, "_require_fin", _auth)
    for mod in (coa, pp, fa):
        monkeypatch.setattr(mod, "require_auth", _auth)
    return d


# ══════════════════════════════ KU1 — jenis akun per peran ═══════════════════════════
def test_ku1_semua_peran_bawaan_berjenis_dan_akun_bawaannya_cocok():
    seed = {c[0]: {"code": c[0], "type": c[2], "is_group": c[3], "flags": c[4]} for c in coa.SEED_TEMPLATE}
    cash = {c for c, a in seed.items() if not a["is_group"] and ((a["flags"] or {}).get("is_cash")
                                                                 or (a["flags"] or {}).get("is_bank"))}
    tanpa_jenis, salah = [], []
    for p in pp.DEFAULT_PROFILES:
        for role, code in p["mapping"].items():
            fam = pp.role_family(p["event_type"], role)
            if not fam:
                tanpa_jenis.append(f"{p['event_type']}.{role}")
            elif code in seed and not pp.account_fits_family(seed[code], fam, cash):
                salah.append(f"{p['event_type']}.{role}={code} ({seed[code]['type']}) ≠ {fam}")
    assert not tanpa_jenis, tanpa_jenis
    assert not salah, salah
    # keluarga yang diminta owner: kas/bank, piutang, hutang, pendapatan, beban/HPP
    assert pp.role_family("ar_payment", "debit_cash_default") == "cash"
    assert pp.role_family("ar_invoice", "debit_ar") == "receivable"
    assert pp.role_family("ap_invoice", "credit_ap") == "liability"
    assert pp.role_family("ar_invoice", "credit_revenue") == "revenue"
    assert pp.role_family("cogs_shipment", "debit_cogs_material") == "expense"
    assert pp.role_family("x", "peran_buatan_sendiri") is None


def test_ku1_aturan_jenis_sama_dengan_type_family_server():
    assert pp.account_fits_family(acc("5-1000", "COGS"), "expense")            # HPP = keluarga beban
    assert pp.account_fits_family(acc("6-9000", "OTHER_EXPENSE"), "expense")
    assert pp.account_fits_family(acc("7-4000", "OTHER_INCOME"), "revenue")
    assert not pp.account_fits_family(acc("6-2900", "EXPENSE"), "revenue")
    assert not pp.account_fits_family(acc("1-1401", "ASSET"), "cash", {"1-1201"})   # aset bukan kas/bank
    assert pp.account_fits_family(acc("1-1401", "ASSET"), "cash", set())            # daftar kas kosong → tipe saja
    assert pp.account_fits_family({"code": "9-9"}, "cash", {"1-1201"})              # akun lama tanpa tipe: tak dinilai
    assert all(pp.ROLE_FAMILIES[f][1] in {coa.type_family(t) for t in coa.ACCOUNT_TYPES} for f in pp.ROLE_FAMILIES)


def test_ku1_meta_mengirim_jenis_peran_dan_daftar_kode_per_jenis(db):
    db.rahaza_posting_profiles.docs.append({"event_type": "expense", "mapping": {"credit_cash_default": "1-1201",
                                                                              "peran_lain": "6-2900"}})
    meta = run(pp.profiles_meta(fm.FakeRequest()))
    assert meta["role_families"]["expense.credit_cash_default"] == "cash"
    assert meta["role_families"]["ap_invoice.credit_ap"] == "liability"
    assert "expense.peran_lain" not in meta["role_families"]                       # peran tak dikenal → tanpa saring
    fc = meta["family_codes"]
    # kas/bank = SSOT cash_account_codes: penanda is_cash/is_bank ATAU anak 1-1100/1-1200; grup tidak ikut
    assert fc["cash"] == ["1-1101", "1-1201", "1-1202", "1-1209"]
    assert "1-1401" in fc["asset"] and "1-1401" not in fc["cash"]
    assert fc["revenue"] == ["4-1100", "4-9000"] and fc["expense"] == ["5-1000", "6-2900"]
    assert fc["liability"] == ["2-1100", "2-1150"]
    assert meta["families"]["cash"] == "kas/bank" and meta["families"]["expense"] == "beban/HPP"


def _profile(db, mapping):
    db.rahaza_posting_profiles.docs.append({"event_type": "expense", "active": True, "mapping": dict(mapping)})


def _put(mapping, off=None):
    body = {"mapping": mapping}
    if off is not None:
        body["off_type_ok"] = off
    return run(pp.update_profile("expense", fm.FakeRequest(body)))


def test_ku1_simpan_menolak_akun_di_luar_jenis(db):
    _profile(db, {"debit_expense_default": "6-2900", "credit_cash_default": "1-1201"})
    with pytest.raises(HTTPException) as e:
        _put({"debit_expense_default": "4-1100", "credit_cash_default": "6-2900"})
    msg = e.value.detail
    assert e.value.status_code == 400
    assert "[credit_cash_default]" in msg and "bukan akun kas/bank" in msg
    assert "[debit_expense_default]" in msg and "bukan akun beban/HPP" in msg
    assert "Tampilkan semua akun" in msg
    with pytest.raises(HTTPException) as e:                       # aset non-kas tidak boleh di peran kas/bank
        _put({"debit_expense_default": "6-2900", "credit_cash_default": "1-1401"})
    assert "[credit_cash_default]" in e.value.detail
    assert db.rahaza_posting_profiles.docs[0]["mapping"]["credit_cash_default"] == "1-1201"   # tidak tersimpan


def test_ku1_simpan_akun_sejenis_lolos(db):
    _profile(db, {"debit_expense_default": "6-2900", "credit_cash_default": "1-1201"})
    out = _put({"debit_expense_default": "5-1000", "credit_cash_default": "1-1209"})   # HPP; bank tanpa penanda
    assert out["mapping"] == {"debit_expense_default": "5-1000", "credit_cash_default": "1-1209"}


def test_ku1_tampilkan_semua_akun_dan_nilai_lama_di_luar_jenis(db):
    _profile(db, {"debit_expense_default": "6-2900", "credit_cash_default": "1-1201"})
    # sengaja dipilih di luar jenis lewat "Tampilkan semua akun" → off_type_ok
    out = _put({"debit_expense_default": "1-1401", "credit_cash_default": "1-1201"}, off=["debit_expense_default"])
    assert out["mapping"]["debit_expense_default"] == "1-1401"
    # nilai lama di luar jenis yang TIDAK diubah tidak menghalangi simpan peran lain
    out = _put({"debit_expense_default": "1-1401", "credit_cash_default": "1-1202"})
    assert out["mapping"] == {"debit_expense_default": "1-1401", "credit_cash_default": "1-1202"}
    # peran tak dikenal tidak disaring
    out = _put({"debit_expense_default": "1-1401", "credit_cash_default": "1-1202", "peran_lain": "4-1100"})
    assert out["mapping"]["peran_lain"] == "4-1100"


# ══════════════════════════════ KU2 — pemasok master untuk beli kredit ═══════════════
PROFILES = {"asset_acquisition": {"debit_fixed_asset": "1-2500", "credit_ap_clearing": "2-1150"}}


@pytest.fixture
def asset_db(db, monkeypatch):
    for code, t in (("1-2500", "ASSET"), ("1-2501", "ASSET"), ("6-2730", "EXPENSE")):
        db.rahaza_coa_accounts.docs.append(acc(code, t))
    db.rahaza_cash_accounts.docs.append({"id": "ca-1", "code": "1-1201", "name": "Bank Satu",
                                         "gl_account_code": "1-1201", "active": True})
    db.rahaza_suppliers.docs += [
        {"id": "sup-b", "code": "SUP-B", "name": "PT Pemasok Beta", "is_active": True, "bank_account": "rahasia"},
        {"id": "sup-a", "code": "SUP-A", "name": "CV Pemasok Alfa", "is_active": True},
        {"id": "sup-x", "code": "SUP-X", "name": "PT Pemasok Nonaktif", "is_active": False},
    ]

    async def gm(_db, et):
        return dict(PROFILES.get(et, {}))
    monkeypatch.setattr(rp, "get_mapping", gm)
    monkeypatch.setattr(pp, "get_mapping", gm)
    jes = []

    async def fake_je(db_, je_date, memo, source_module, source_ref, lines, user, status="posted",
                      allow_closed_period=False, **_kw):
        jes.append({"memo": memo, "source_module": source_module, "source_ref": source_ref,
                    "lines": {(ln["account_code"], ln["debit"], ln["credit"]) for ln in lines}})
        return {"ok": True, "je_id": f"je-{len(jes)}", "je_number": f"JE-{len(jes):04d}"}
    monkeypatch.setattr(rp, "_create_posted_je", fake_je)
    db.jes = jes
    return db


BASE = {"name": "Mesin Uji", "category": "peralatan", "purchase_cost": 5_000_000, "useful_life_months": 60,
        "purchase_date": "2026-10-10", "acquisition_type": "purchase", "funding_source": "payable"}


@pytest.mark.parametrize("patch,needle", [
    ({}, "wajib memilih pemasok dari Master Pemasok"),
    ({"supplier": "Toko ketik sendiri"}, "wajib memilih pemasok dari Master Pemasok"),   # teks bebas ditolak
    ({"supplier_id": "tidak-ada"}, "tidak ada di Master Pemasok"),
    ({"supplier_id": "sup-x"}, "nonaktif"),
])
def test_ku2_beli_kredit_wajib_pemasok_master(asset_db, patch, needle):
    with pytest.raises(HTTPException) as e:
        run(fa.register_fixed_asset(asset_db, {**BASE, **patch}, USER, code="FA-U1"))
    assert e.value.status_code == 400 and needle in e.value.detail
    assert asset_db.rahaza_fixed_assets.docs == [] and asset_db.jes == []


def test_ku2_beli_kredit_menyimpan_id_dan_nama_master(asset_db):
    out = run(fa.register_fixed_asset(asset_db, {**BASE, "supplier_id": "sup-a", "supplier": "ketikan lain"},
                                      USER, code="FA-U2"))
    doc = asset_db.rahaza_fixed_assets.docs[0]
    assert (doc["supplier_id"], doc["supplier"], doc["supplier_code"]) == ("sup-a", "CV Pemasok Alfa", "SUP-A")
    assert out["funding_source"] == "payable" and out["acquisition_credit_code"] == "2-1150"
    # jurnal perolehan: Dr akun aset / Cr Hutang Belum Ditagih (GRNI tanpa rincian per pemasok), memo bernama pemasok
    je = asset_db.jes[-1]
    assert je["lines"] == {("1-2500", 5_000_000, 0), ("2-1150", 0, 5_000_000)}
    assert "CV Pemasok Alfa" in je["memo"] and "payable" not in je["memo"]


def test_ku2_sumber_dana_lain_tetap_teks_bebas(asset_db):
    body = {**BASE, "funding_source": "cash", "cash_account_id": "ca-1", "supplier": "Toko Bangunan Ketik"}
    run(fa.register_fixed_asset(asset_db, body, USER, code="FA-U3"))
    doc = asset_db.rahaza_fixed_assets.docs[0]
    assert doc["supplier"] == "Toko Bangunan Ketik" and "supplier_id" not in doc


def test_ku2_pilihan_pemasok_dari_acquisition_options(asset_db):
    out = run(fa.acquisition_options(fm.FakeRequest()))
    assert out["suppliers"] == [{"id": "sup-a", "code": "SUP-A", "name": "CV Pemasok Alfa"},
                                {"id": "sup-b", "code": "SUP-B", "name": "PT Pemasok Beta"}]   # aktif, urut nama, ringkas


def test_ku2_ubah_pemasok_aset_kredit_harus_dari_master(asset_db, monkeypatch):
    monkeypatch.setattr(fa, "_enrich_nbv", _noop)                     # nilai buku (aggregate) tidak diuji di sini
    run(fa.register_fixed_asset(asset_db, {**BASE, "supplier_id": "sup-a"}, USER, code="FA-U4"))
    aid = asset_db.rahaza_fixed_assets.docs[0]["id"]
    with pytest.raises(HTTPException) as e:
        run(fa.update_fixed_asset(aid, fm.FakeRequest({"supplier": "Nama ketikan"})))
    assert e.value.status_code == 400 and "Master Pemasok" in e.value.detail
    out = run(fa.update_fixed_asset(aid, fm.FakeRequest({"supplier_id": "sup-b"})))
    assert (out["supplier_id"], out["supplier"]) == ("sup-b", "PT Pemasok Beta")


# ══════════════════════════════ KU4 — peringatan akun kontrol ════════════════════════
def test_ku4_akun_kontrol_dari_penanda_dan_induk_subledger():
    rows = [
        acc("1-1301", "ASSET", flags={"is_ar": True}),
        acc("2-1100", "LIABILITY", flags={"is_ap": True}),
        acc("1-1305", "ASSET"),                                         # tanpa penanda, induk sub-ledger maklon
        acc("1-1305-K01", "ASSET", parent="1-1305", flags={"subledger": True, "subledger_entity_type": "maklon_client",
                                                            "subledger_parent": "1-1305"}),
        acc("2-1110", "LIABILITY"),
        acc("2-1110-V01", "LIABILITY", parent="2-1110", flags={"subledger": True, "subledger_entity_type": "cmt_vendor",
                                                               "subledger_parent": "2-1110"}),
        acc("1-1209", "ASSET", parent="1-1200", flags={"subledger": True, "subledger_entity_type": "bank",
                                                        "subledger_parent": "1-1200"}),
        acc("4-1500-K01", "REVENUE", parent="4-1500", flags={"subledger": True, "subledger_entity_type": "maklon_revenue",
                                                             "subledger_parent": "4-1500"}),
        acc("6-2900", "EXPENSE"),
    ]
    kinds = coa.control_account_kinds(rows)
    assert kinds == {"1-1301": "ar", "2-1100": "ap", "1-1305": "ar", "1-1305-K01": "ar",
                     "2-1110": "ap", "2-1110-V01": "ap"}                   # bank & pendapatan maklon bukan kontrol
    # tanpa penanda sama sekali → cadangan kode tetap
    assert coa.control_account_kinds([acc("1-1301", "ASSET"), acc("6-2900", "EXPENSE")]) == {"1-1301": "ar",
                                                                                              "2-1100": "ap"}


def test_ku4_daftar_akun_with_control_menandai_meski_tersaring(db):
    db.rahaza_coa_accounts.docs += [
        acc("1-1305", "ASSET", "Piutang Maklon"),
        acc("1-1305-K01", "ASSET", parent="1-1305", active=False,
            flags={"subledger": True, "subledger_entity_type": "maklon_client", "subledger_parent": "1-1305"}),
    ]
    rows = run(coa.list_accounts(fm.FakeRequest(), active_only=True, search="1-13", with_control=True))
    got = {r["code"]: r.get("control_kind") for r in rows}
    assert got == {"1-1301": "ar", "1-1305": "ar"}                     # anak nonaktif tersaring, induk tetap ditandai
    plain = run(coa.list_accounts(fm.FakeRequest(), active_only=True, search="1-13"))
    assert all("control_kind" not in r for r in plain)                 # tanpa with_control: bentuk lama


def test_ku4_jurnal_manual_ke_akun_kontrol_tetap_tersimpan(db, monkeypatch):
    async def gen(_db, _d, requested="", *_a, **_k):
        return "JE-U-0001"
    monkeypatch.setattr(rj, "_gen_je_number", gen)
    monkeypatch.setattr(rj, "_check_period_open", _noop)
    body = {"date": "2026-10-15", "memo": "UJI reklas", "post": False,
            "lines": [{"account_code": "1-1301", "debit": 100_000, "credit": 0},
                      {"account_code": "2-1100", "debit": 0, "credit": 100_000}]}
    out = run(rj.create_journal(fm.FakeRequest(body)))
    assert out["status"] == "draft" and len(db.rahaza_journal_entries.docs) == 1


# ══════════════════════════════ kontrak layar ════════════════════════════════════════
def test_layar_kontrak_tahap6():
    pp_src = _fe("RahazaPostingProfilesModule.jsx")
    for needle in ("Tampilkan semua akun", "di luar jenis yang disarankan", "off_type_ok", "family_codes",
                   "role_families", 'data-testid="pp-show-all"'):
        assert needle in pp_src, needle
    je_src = _fe("RahazaJournalEntryModule.jsx")
    assert "/api/rahaza/coa/accounts?with_control=true" in je_src and "control-warning" in je_src
    # peringatan saja: tombol simpan tidak ikut dimatikan oleh akun kontrol
    assert "disabled={!balanced || !nomorSiap || !!lineProblem}" in je_src
    fa_src = _fe("FixedAssetsModule.jsx")
    assert 'data-testid="asset-supplier-master"' in fa_src and "supplier_id: creditPurchase" in fa_src
    assert "/api/procurement/suppliers/options" not in fa_src            # dulu 403 untuk staf Keuangan
    for src in (pp_src, je_src, fa_src):
        assert "<select" not in src
