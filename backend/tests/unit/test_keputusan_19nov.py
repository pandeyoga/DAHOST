"""Uji unit HERMETIK — keputusan owner 19 Nov 2026 atas kendala staf.

  · HPP Kirim Sample / katalog: WAC yang belum memuat kain (barang PO saldo awal cutoff, dinilai upah jahit) diganti
    HPP R&D (BOM) selama barangnya belum lahir dari cutting nyata; HPP R&D di bawah upah jahit tidak dipakai.
  · Kreator: status, tipe, target, dan catatan dipisah per toko; identitas tetap satu.

Jalankan:  cd backend && python -m pytest tests/unit/test_keputusan_19nov.py -q
"""
import asyncio
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from core import catalog_margin as cm  # noqa: E402
from core import kreator_per_toko as kt  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# Aurel GREY ALLSIZE di VPS 19 Nov: 9 pcs stok awal @47.424 + 41 pcs PO saldo awal @6.300 (upah saja)
AUREL = {"id": "F-AUREL", "code": "DA-2204-GRY-ALLSIZE", "unit_cost": 13702.32, "model_id": "M-AUREL",
         "wac_components": {"material": 8536.32, "labor": 5166.0, "overhead": 0.0}, "wac_tanpa_kain": True,
         "hpp": 0, "hpp_source": ""}
MODEL = {"id": "M-AUREL", "hpp_bom": 40913.87}


# ══ 1. HPP R&D bila WAC belum memuat kain ════════════════════════════════════
def test_wac_tanpa_kain_diganti_hpp_rnd_model():
    assert cm.wac_tanpa_kain(AUREL)
    assert cm.effective_fg_cost(AUREL)["source"] == cm.SRC_WAC_TANPA_KAIN
    assert cm.resolve_catalog_hpp(AUREL, MODEL) == (40913.87, "bom")      # dulu 13.702 (WAC)


def test_hpp_fg_bom_didahulukan_bila_layak():
    fg = {**AUREL, "hpp": 43088.0, "hpp_source": "bom"}
    eff = cm.effective_fg_cost(fg)
    assert eff["source"] == cm.SRC_ESTIMATE and eff["hpp"] == 43088.0


def test_hpp_rnd_di_bawah_upah_tidak_dipakai():
    # DA-1201 MCA: HPP R&D Rp659 (BOM belum lengkap) — lebih kecil dari upah jahit → WAC tetap dipakai
    fg = {**AUREL, "unit_cost": 26532.0, "wac_components": {"material": 0, "labor": 6000.0}, "hpp": 659}
    assert cm.effective_fg_cost(fg)["source"] == cm.SRC_WAC_TANPA_KAIN
    assert cm.resolve_catalog_hpp(fg, {"hpp_bom": 659}) == (26532.0, "wac_tanpa_kain")


def test_wac_lengkap_tidak_berubah():
    fg = {"unit_cost": 111396.10, "wac_components": {"material": 91396.10, "labor": 20000.0}, "hpp": 50000}
    assert not cm.wac_tanpa_kain(fg)
    assert cm.resolve_catalog_hpp(fg, MODEL) == (111396.10, "wac")
    # komponen bahan 0 (tanpa tanda) = tetap dianggap tanpa kain
    assert cm.wac_tanpa_kain({"unit_cost": 5000, "wac_components": {"material": 0, "labor": 5000}})


def test_margin_katalog_memakai_hpp_rnd():
    row = {"harga_jual": 89000, "hpp": 40913.87, "hpp_source": "bom", "fg_material_id": "F-AUREL"}
    out = cm.decorate(dict(row), cm.effective_fg_cost(AUREL))
    assert out["hpp_effective"] == 40913.87 and out["hpp_source_effective"] == cm.SRC_RND
    assert out["hpp_source_label"] == "HPP R&D (BOM)"


def test_tanda_kain_dari_lapisan_dan_sinkron_katalog():
    from core import fg_cost_layers as fcl
    db = FakeDB()
    db.rahaza_materials.docs = [{k: v for k, v in AUREL.items() if k != "wac_tanpa_kain"}]
    db.rahaza_models.docs = [dict(MODEL)]
    db.marketing_catalog_items.docs = [{"id": "ci", "fg_material_id": "F-AUREL", "hpp": 13702.32, "hpp_source": "wac"}]
    # lapisan PO saldo awal (upah saja) → ditandai tanpa kain
    run(fcl._tandai_kain(db, "F-AUREL", {"batch": {"source": "production"},
                                         "breakdown": {"material_cost": 0, "material_source": "saldo_awal_nol"}}, None))
    assert db.rahaza_materials.docs[0]["wac_tanpa_kain"] is True
    run(fcl._sync_catalog(db, "F-AUREL", 13702.32))
    assert db.marketing_catalog_items.docs[0]["hpp"] == 40913.87
    assert db.marketing_catalog_items.docs[0]["hpp_source"] == "bom"
    # retur tidak mengubah tanda
    run(fcl._tandai_kain(db, "F-AUREL", {"batch": {"source": "return_receive"}, "breakdown": {"material_cost": 9}}, None))
    assert db.rahaza_materials.docs[0]["wac_tanpa_kain"] is True
    # barang dari cutting nyata (bahan aktual) → WAC dipakai lagi, dan tidak kembali ke tanpa kain
    run(fcl._tandai_kain(db, "F-AUREL", {"batch": {"source": "production"},
                                         "breakdown": {"material_cost": 30000, "material_source": "aktual"}}, None))
    m = db.rahaza_materials.docs[0]
    assert m["wac_tanpa_kain"] is False and m["wac_kain_nyata"] is True
    run(fcl._tandai_kain(db, "F-AUREL", {"batch": {"source": "production"},
                                         "breakdown": {"material_cost": 0, "material_source": "saldo_awal_nol"}}, None))
    assert db.rahaza_materials.docs[0]["wac_tanpa_kain"] is False
    m["wac_components"] = {"material": 20000.0, "labor": 6000.0}
    m["unit_cost"] = 26000.0
    run(fcl._sync_catalog(db, "F-AUREL", 26000.0))
    assert db.marketing_catalog_items.docs[0]["hpp"] == 26000.0
    assert db.marketing_catalog_items.docs[0]["hpp_source"] == "wac"


# ══ 2. Kreator: data kerja sama per toko ═════════════════════════════════════
KREATOR = {"id": "c1", "name": "MAMIFATMA", "status": "active", "creator_type": "kontrak",
           "kpi_targets": {"monthly_revenue": 10_000_000}, "notes": "awal",
           "assigned_account_ids": ["a-ob", "a-rina"]}


def test_nilai_toko_memakai_nilai_awal_lalu_dipecah():
    c = dict(KREATOR)
    assert kt.nilai_toko(c, "a-rina")["notes"] == "awal" and not kt.nilai_toko(c, "a-rina")["sendiri"]
    upd = kt.pecah(c, {"a-rina": {"notes": "Rina", "status": "inactive"}}, c["assigned_account_ids"], {"name": "Rina"})
    assert upd["per_toko.a-rina"]["notes"] == "Rina" and upd["per_toko.a-rina"]["status"] == "inactive"
    assert upd["per_toko.a-ob"]["notes"] == "awal" and upd["per_toko.a-ob"]["status"] == "active"   # dibekukan
    c["per_toko"] = {"a-rina": upd["per_toko.a-rina"], "a-ob": upd["per_toko.a-ob"]}
    # perubahan berikutnya hanya menyentuh toko yang diubah
    assert set(kt.pecah(c, {"a-ob": {"notes": "OB"}}, c["assigned_account_ids"], {})) == {"per_toko.a-ob"}


def test_terapkan_menampilkan_toko_sendiri_saja():
    c = {**KREATOR, "per_toko": {"a-rina": {"status": "inactive", "notes": "Rina"}}}
    rina = kt.terapkan(dict(c), ["a-rina"])
    assert rina["status"] == "inactive" and rina["notes"] == "Rina" and list(rina["per_toko"]) == ["a-rina"]
    ob = kt.terapkan(dict(c), ["a-ob"])
    assert ob["status"] == "active" and ob["notes"] == "awal"
    semua = kt.terapkan(dict(c), None)
    assert semua["toko_konteks"] is None and semua["beda_per_toko"] is True
    assert kt.terapkan(dict(c), None, "a-rina")["status"] == "inactive"


def test_insentif_dan_target_portal():
    c = {**KREATOR, "creator_type": "new",
         "per_toko": {"a-rina": {"creator_type": "kontrak", "kpi_targets": {"monthly_revenue": 4_000_000}},
                      "a-ob": {"kpi_targets": {"monthly_revenue": 6_000_000}}}}
    assert kt.tipe_insentif(c) == "kontrak"
    assert kt.kpi_total(c)["monthly_revenue"] == 10_000_000
    # belum dipisah → nilai awal, tidak dikali jumlah toko
    assert kt.kpi_total(dict(KREATOR))["monthly_revenue"] == 10_000_000
    with pytest.raises(Exception):
        kt.bersihkan({"status": "hapus"})


def _kc(monkeypatch, db, user):
    import auth
    import routes.marketing_kol_creators as kc

    async def _auth(req):
        req.state.user = user
        return user

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(kc, "require_auth", _auth)
    monkeypatch.setattr(kc, "get_db", lambda: db)
    monkeypatch.setattr(kc, "log_activity", _noop)
    monkeypatch.setattr(auth, "get_db", lambda: db)
    return kc


def _db_kreator():
    db = FakeDB()
    db.users.docs = [{"id": "u-rina", "name": "Rina", "role": "PIC Toko", "status": "active"},
                     {"id": "u-mar", "name": "Mar'atus", "role": "pic_toko", "status": "active"},
                     {"id": "u-owner", "name": "Owner", "role": "owner", "status": "active"}]
    db.marketing_platform_accounts.docs = [
        {"id": "a-ob", "account_name": "Shopee OB", "status": "active", "pic_user_id": "u-mar"},
        {"id": "a-rina", "account_name": "TikTok Daluna", "status": "active", "pic_user_id": "u-rina"}]
    db.marketing_kol_creators.docs = [{**KREATOR, "kpi_targets": dict(KREATOR["kpi_targets"]), "created_at": "x"}]
    return db


RINA = {"id": "u-rina", "name": "Rina", "role": "PIC Toko", "status": "active"}
MAR = {"id": "u-mar", "name": "Mar'atus", "role": "pic_toko", "status": "active"}


def test_rina_mengubah_kreator_toko_lain_tidak_ikut_berubah(monkeypatch):
    from routes.marketing_kol_shared import CreatorUpdate
    db = _db_kreator()
    kc = _kc(monkeypatch, db, RINA)
    # layar lama (tanpa per_toko): field kerja sama tingkat atas dari staf toko → hanya toko Rina
    run(kc.update_creator("c1", CreatorUpdate(notes="pindah jadwal", status="inactive",
                                             kpi_targets={"monthly_revenue": 3_000_000}), FakeRequest()))
    doc = db.marketing_kol_creators.docs[0]
    assert doc["status"] == "active" and doc["notes"] == "awal"            # nilai awal tidak disentuh
    assert doc["per_toko"]["a-rina"]["status"] == "inactive"
    assert doc["per_toko"]["a-ob"]["status"] == "active" and doc["per_toko"]["a-ob"]["notes"] == "awal"
    # Mar'atus melihat data tokonya sendiri
    kc = _kc(monkeypatch, db, MAR)
    out = run(kc.list_creators(FakeRequest(), status=None, account_id=None, page=1, limit=20))
    c = out["creators"][0]
    assert c["status"] == "active" and c["kpi_targets"]["monthly_revenue"] == 10_000_000
    assert list(c["per_toko"]) == ["a-ob"]
    # penyaring status per toko
    assert run(kc.list_creators(FakeRequest(), status="inactive", account_id=None, page=1, limit=20))["creators"] == []
    kc = _kc(monkeypatch, db, RINA)
    assert len(run(kc.list_creators(FakeRequest(), status="inactive", account_id=None, page=1, limit=20))["creators"]) == 1
    # per_toko ke toko yang tidak dipegang → 403
    with pytest.raises(Exception) as e:
        run(kc.update_creator("c1", CreatorUpdate(per_toko={"a-ob": {"notes": "x"}}), FakeRequest()))
    assert getattr(e.value, "status_code", None) == 403
