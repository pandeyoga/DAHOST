"""Master Marketing/Toko & Cutting bisa diubah & dihapus dengan aman (permintaan owner 10 Nov 2026) — hermetik.

Kata owner: "pastikan table table master data bisa dihapus". Pola bersama: `core.hapus_master` (409 + kalimat
"… sudah dipakai di …") dan layar `lib/hapusMaster.js` (confirmDialog → hapus → bila 409 tawarkan Nonaktifkan).

Yang dikunci per master:
  * Katalog marketing: DELETE dulu menghapus katalog + SEMUA itemnya tanpa cek → kini 409 bila ada item yang
    dipakai (pesanan, retur, sesi live, sampel, ulasan, komplain, jadwal konten, permintaan kreator, Jembatan SKU);
  * Item katalog: DELETE dulu langsung hapus → kini 409 dengan daftar yang SAMA (`item_usage_checks`);
  * Kreator KOL, host live, templat tugas: tanpa `hard` tetap menonaktifkan (perilaku lama); `?hard=true` hapus
    permanen bila belum punya riwayat, 409 bila sudah;
  * Master potongan cutting: DELETE per baris memakai pemeriksaan `core.cut_panel_health.inspect` (tanpa salin cek);
  * gerbang peran tiap endpoint hapus, dan layar punya kolom Aksi (Ubah · Hapus) + hapusMaster.
"""
import asyncio
import inspect
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

REPO = Path(__file__).resolve().parents[3]
FE = REPO / "frontend" / "src"
ADMIN = {"id": "u-admin", "name": "Admin Uji", "role": "admin"}


def run(c):
    return asyncio.run(c)


async def _noop(*_a, **_k):
    return None


async def _admin(*_a, **_k):
    return dict(ADMIN)


def fe(rel: str) -> str:
    p = FE / rel
    if not p.exists():
        pytest.skip("frontend tidak ada di lingkungan ini")
    return p.read_text(encoding="utf-8")


def _import_mgmt():
    """Modul katalog membuat folder unggahan /app saat diimpor — pola uji lain (tanpa hak tulis /app)."""
    import pathlib
    orig = pathlib.Path.mkdir

    def _mkdir(self, *a, **k):
        try:
            return orig(self, *a, **k)
        except OSError:
            return None
    pathlib.Path.mkdir = _mkdir
    try:
        import routes.marketing_catalog_mgmt as cm
    finally:
        pathlib.Path.mkdir = orig
    return cm


# ══════════════════════════════ Item katalog & katalog ══════════════════════════════
@pytest.fixture
def katalog(monkeypatch):
    import routes.marketing_catalog_items as mci
    cm = _import_mgmt()
    db = fm.FakeDB()
    db.marketing_catalogs.docs = [{"id": "cat-a", "name": "Katalog Shopee A", "account_id": "acc-a", "is_active": True},
                                  {"id": "cat-b", "name": "Katalog TikTok B", "account_id": "acc-b", "is_active": True}]
    db.marketing_catalog_items.docs = [
        {"id": "it-1", "catalog_id": "cat-a", "sku": "KAOS-HTM-M", "name": "Kaos Hitam M", "is_active": True},
        {"id": "it-2", "catalog_id": "cat-a", "sku": "KAOS-HTM-L", "name": "Kaos Hitam L", "is_active": True},
        {"id": "it-9", "catalog_id": "cat-b", "sku": "KAOS-PTH-M", "name": "Kaos Putih M", "is_active": True},
    ]
    for m in (mci, cm):
        monkeypatch.setattr(m, "get_db", lambda: db)
        monkeypatch.setattr(m, "require_perm", _admin)
        monkeypatch.setattr(m, "log_activity", _noop)
    monkeypatch.setattr(mci, "_refresh_catalog_stats", _noop)
    return mci, cm, db


PEMAKAI_ITEM = [
    ("marketing_orders", {"id": "o1", "items": [{"catalog_item_id": "x"}, {"catalog_item_id": "it-1"}]}, "pesanan"),
    ("marketing_orders", {"id": "o2", "catalog_item_id": "it-1"}, "pesanan"),
    ("marketing_orders", {"id": "o3", "fulfillment_items": [{"catalog_item_id": "it-1"}]}, "pesanan"),
    ("marketing_live_session_products", {"id": "lp1", "catalog_item_id": "it-1"}, "produk sesi live"),
    ("marketing_live_sessions", {"id": "ls1", "products": [{"catalog_item_id": "it-1"}]}, "sesi live"),
    ("marketing_samples", {"id": "s1", "catalog_item_id": "it-1"}, "kiriman sampel"),
    ("marketing_returns", {"id": "r1", "catalog_item_id": "it-1"}, "retur"),
    ("marketing_reviews", {"id": "rv1", "catalog_item_id": "it-1"}, "ulasan"),
    ("marketing_complaints", {"id": "k1", "catalog_item_id": "it-1"}, "komplain"),
    ("marketing_content_calendar", {"id": "cc1", "catalog_item_id": "it-1"}, "jadwal konten"),
    ("marketing_creator_item_requests", {"id": "cr1", "catalog_item_id": "it-1"}, "permintaan produk kreator"),
    ("marketing_sku_bridge", {"platform_sku_id": "1729", "catalog_item_id": "it-1"}, "pemetaan SKU marketplace"),
]


def test_item_katalog_belum_dipakai_dihapus(katalog):
    mci, _cm, db = katalog
    out = run(mci.delete_catalog_item("cat-a", "it-1", fm.FakeRequest()))
    assert out["ok"] is True and out["deleted"] is True
    assert [d["id"] for d in db.marketing_catalog_items.docs] == ["it-2", "it-9"]


@pytest.mark.parametrize("koleksi,doc,label", PEMAKAI_ITEM)
def test_item_katalog_sudah_dipakai_ditolak_409(katalog, koleksi, doc, label):
    mci, _cm, db = katalog
    getattr(db, koleksi).docs = [doc]
    with pytest.raises(HTTPException) as e:
        run(mci.delete_catalog_item("cat-a", "it-1", fm.FakeRequest()))
    assert e.value.status_code == 409 and label in e.value.detail and "Kaos Hitam M" in e.value.detail
    assert "Nonaktifkan" in e.value.detail
    assert len(db.marketing_catalog_items.docs) == 3


def test_item_katalog_tidak_ada_404(katalog):
    mci, _cm, _db = katalog
    with pytest.raises(HTTPException) as e:
        run(mci.delete_catalog_item("cat-b", "it-1", fm.FakeRequest()))   # item ada, tapi bukan di katalog ini
    assert e.value.status_code == 404


def test_katalog_belum_dipakai_dihapus_beserta_itemnya(katalog):
    _mci, cm, db = katalog
    out = run(cm.delete_catalog("cat-a", fm.FakeRequest()))
    assert out["deleted"] is True and "2 item" in out["message"]
    assert [c["id"] for c in db.marketing_catalogs.docs] == ["cat-b"]
    assert [d["id"] for d in db.marketing_catalog_items.docs] == ["it-9"]   # katalog lain tidak tersentuh


@pytest.mark.parametrize("koleksi,doc,label", PEMAKAI_ITEM[:1] + PEMAKAI_ITEM[5:7] + PEMAKAI_ITEM[-1:])
def test_katalog_dengan_item_terpakai_ditolak_409(katalog, koleksi, doc, label):
    _mci, cm, db = katalog
    getattr(db, koleksi).docs = [doc]
    with pytest.raises(HTTPException) as e:
        run(cm.delete_catalog("cat-a", fm.FakeRequest()))
    assert e.value.status_code == 409 and label in e.value.detail and "Katalog Shopee A" in e.value.detail
    assert len(db.marketing_catalogs.docs) == 2 and len(db.marketing_catalog_items.docs) == 3


def test_katalog_lain_yang_dipakai_tidak_menahan(katalog):
    _mci, cm, db = katalog
    db.marketing_orders.docs = [{"id": "o1", "items": [{"catalog_item_id": "it-9"}]}]   # item katalog B
    run(cm.delete_catalog("cat-a", fm.FakeRequest()))
    assert [c["id"] for c in db.marketing_catalogs.docs] == ["cat-b"]


def test_katalog_kosong_dihapus(katalog):
    _mci, cm, db = katalog
    db.marketing_catalog_items.docs = [d for d in db.marketing_catalog_items.docs if d["catalog_id"] != "cat-a"]
    out = run(cm.delete_catalog("cat-a", fm.FakeRequest()))
    assert out["deleted"] is True and "0 item" in out["message"]


# ══════════════════════════════ Kreator KOL ══════════════════════════════
@pytest.fixture
def kreator(monkeypatch):
    import routes.marketing_kol_creators as mkc
    db = fm.FakeDB()
    db.marketing_kol_creators.docs = [{"id": "kr1", "name": "Rina Live", "creator_code": "KOL-01", "status": "active"}]
    monkeypatch.setattr(mkc, "get_db", lambda: db)
    monkeypatch.setattr(mkc, "require_perm", _admin)
    monkeypatch.setattr(mkc, "log_activity", _noop)
    return mkc, db


def test_kreator_belum_punya_riwayat_dihapus(kreator):
    mkc, db = kreator
    out = run(mkc.deactivate_creator("kr1", fm.FakeRequest(), hard=True))
    assert out["deleted"] is True and db.marketing_kol_creators.docs == []


@pytest.mark.parametrize("koleksi,doc,label", [
    ("marketing_creator_sessions", {"id": "s1", "creator_id": "kr1"}, "sesi live kreator"),
    ("marketing_live_sessions", {"id": "l1", "creator_id": "kr1"}, "sesi live"),
    ("marketing_orders", {"id": "o1", "creator_id": "kr1"}, "pesanan"),
    ("marketing_samples", {"id": "sp1", "creator_id": "kr1"}, "kiriman sampel"),
    ("marketing_creator_item_requests", {"id": "q1", "creator_id": "kr1"}, "permintaan produk"),
    ("dewi_kreator_requests", {"id": "dk1", "kreator_id": "kr1"}, "permintaan kreator"),
    ("marketing_content_calendar", {"id": "c1", "creator_id": "kr1"}, "jadwal konten"),
    ("marketing_creator_incentive_entries", {"id": "i1", "creator_id": "kr1"}, "catatan insentif"),
    ("marketing_creator_weekly_reports", {"id": "w1", "creator_id": "kr1"}, "rapor mingguan"),
])
def test_kreator_punya_riwayat_ditolak_409(kreator, koleksi, doc, label):
    mkc, db = kreator
    getattr(db, koleksi).docs = [doc]
    with pytest.raises(HTTPException) as e:
        run(mkc.deactivate_creator("kr1", fm.FakeRequest(), hard=True))
    assert e.value.status_code == 409 and label in e.value.detail and "Rina Live" in e.value.detail
    assert len(db.marketing_kol_creators.docs) == 1


def test_kreator_tanpa_hard_tetap_nonaktifkan(kreator):
    mkc, db = kreator
    run(mkc.deactivate_creator("kr1", fm.FakeRequest(), hard=False))
    assert db.marketing_kol_creators.docs[0]["status"] == "inactive"


# ══════════════════════════════ Host live ══════════════════════════════
HOST = "3f2b8c1e-1111-4a2b-9c3d-123456789abc"


@pytest.fixture
def host(monkeypatch):
    import routes.marketing_livehost_portal as mlp
    db = fm.FakeDB()
    db.marketing_livehosts.docs = [{"id": HOST, "name": "Dina Host", "status": "active"}]
    db.marketing_livehost_training_progress.docs = [
        {"id": "tp1", "host_id": HOST, "status": "not_started"},
        {"id": "tp9", "host_id": "host-lain", "status": "not_started"},
    ]
    monkeypatch.setattr(mlp, "get_db", lambda: db)
    monkeypatch.setattr(mlp, "require_auth", _admin)
    monkeypatch.setattr(mlp, "log_activity", _noop)
    return mlp, db


def test_host_belum_punya_riwayat_dihapus_beserta_tugas_pelatihan_belum_mulai(host):
    mlp, db = host
    out = run(mlp.delete_livehost(fm.FakeRequest(), host_id=HOST, hard=True))
    assert out["deleted"] is True and db.marketing_livehosts.docs == []
    assert [p["id"] for p in db.marketing_livehost_training_progress.docs] == ["tp9"]   # host lain tidak tersentuh


@pytest.mark.parametrize("koleksi,doc,label", [
    ("marketing_livehost_shifts", {"id": "sh1", "host_id": HOST}, "jadwal shift"),
    ("marketing_live_sessions", {"id": "ls1", "host_id": HOST}, "sesi live"),
    ("marketing_livehost_training_progress", {"id": "tp2", "host_id": HOST, "status": "completed"},
     "pelatihan yang sudah dikerjakan"),
])
def test_host_punya_riwayat_ditolak_409(host, koleksi, doc, label):
    mlp, db = host
    getattr(db, koleksi).docs.append(doc)
    with pytest.raises(HTTPException) as e:
        run(mlp.delete_livehost(fm.FakeRequest(), host_id=HOST, hard=True))
    assert e.value.status_code == 409 and label in e.value.detail and "Dina Host" in e.value.detail
    assert len(db.marketing_livehosts.docs) == 1
    assert any(p["id"] == "tp1" for p in db.marketing_livehost_training_progress.docs)


def test_host_tanpa_hard_tetap_nonaktifkan(host):
    mlp, db = host
    run(mlp.delete_livehost(fm.FakeRequest(), host_id=HOST, hard=False))
    assert db.marketing_livehosts.docs[0]["status"] == "inactive"
    assert len(db.marketing_livehost_training_progress.docs) == 2


# ══════════════════════════════ Templat tugas ══════════════════════════════
@pytest.fixture
def templat(monkeypatch):
    import routes.marketing_task_templates as mtt
    db = fm.FakeDB()
    db.marketing_task_templates.docs = [{"id": "tpl1", "template_name": "Rekap harian", "is_active": True}]
    monkeypatch.setattr(mtt, "get_db", lambda: db)
    monkeypatch.setattr(mtt, "require_auth", _admin)
    monkeypatch.setattr(mtt, "log_activity", _noop)
    return mtt, db


def test_templat_belum_menerbitkan_tugas_dihapus(templat):
    mtt, db = templat
    out = run(mtt.delete_task_template("tpl1", fm.FakeRequest(), hard=True))
    assert out["deleted"] is True and db.marketing_task_templates.docs == []


def test_templat_sudah_menerbitkan_tugas_ditolak_409(templat):
    mtt, db = templat
    db.marketing_tasks.docs = [{"id": "t1", "template_id": "tpl1"}, {"id": "t2", "template_id": "tpl1"}]
    with pytest.raises(HTTPException) as e:
        run(mtt.delete_task_template("tpl1", fm.FakeRequest(), hard=True))
    assert e.value.status_code == 409 and "2 tugas yang sudah terbit" in e.value.detail and "Rekap harian" in e.value.detail
    assert len(db.marketing_task_templates.docs) == 1


def test_templat_tanpa_hard_tetap_nonaktifkan(templat):
    mtt, db = templat
    run(mtt.delete_task_template("tpl1", fm.FakeRequest(), hard=False))
    assert db.marketing_task_templates.docs[0]["is_active"] is False


# ══════════════════════════════ Master potongan cutting ══════════════════════════════
@pytest.fixture
def potongan(monkeypatch):
    import routes.cutting as cut
    from core import cut_panel_health as cph
    db = fm.FakeDB()
    db.rahaza_materials.docs = [
        {"id": "kain1", "code": "KAIN-01", "name": "Kain katun", "active": True},
        {"id": "p1", "code": "CUT-KAOS-HTM-M", "name": "Potongan kaos hitam M", "is_cut_panel": True,
         "created_from": "cutting", "source_material_id": "kain1", "cutting_order_id": "co-lama", "unit": "pcs"},
        {"id": "bukan", "code": "KAIN-02", "name": "Kain biasa", "active": True},
    ]
    stok = {"p1": 0.0}

    async def _onhand(mid, *, db=None):
        return stok.get(mid, 0.0)

    # FakeCollection.count_documents tidak menerima `limit=` (dipakai cut_panel_health._references)
    orig = fm.FakeCollection.count_documents

    async def _count(self, q=None, **_kw):
        return await orig(self, q)
    monkeypatch.setattr(fm.FakeCollection, "count_documents", _count)
    monkeypatch.setattr(cph.stock_service, "get_onhand", _onhand)
    monkeypatch.setattr(cut, "get_db", lambda: db)
    monkeypatch.setattr(cut, "_require_cutting_user", _admin)
    monkeypatch.setattr(cut, "log_activity", _noop)
    return cut, db, stok


def test_potongan_belum_dipakai_dihapus(potongan):
    cut, db, _stok = potongan
    out = run(cut.delete_panel("p1", fm.FakeRequest()))
    assert out["deleted"] is True
    assert [m["id"] for m in db.rahaza_materials.docs] == ["kain1", "bukan"]


@pytest.mark.parametrize("koleksi,doc,label", [
    ("cutting_orders", {"id": "co1", "output_material_id": "p1"}, "order cutting"),
    ("rahaza_stock_ledger", {"id": "l1", "material_id": "p1"}, "buku besar stok"),
    ("rahaza_material_movements", {"id": "m1", "material_id": "p1"}, "kartu stok"),
    ("rahaza_boms", {"id": "b1", "materials": [{"material_id": "p1"}]}, "BOM produksi"),
    ("rahaza_material_issues", {"id": "mi1", "items": [{"material_id": "p1"}]}, "pengeluaran material"),
])
def test_potongan_sudah_dipakai_ditolak_409(potongan, koleksi, doc, label):
    cut, db, _stok = potongan
    getattr(db, koleksi).docs = [doc]
    with pytest.raises(HTTPException) as e:
        run(cut.delete_panel("p1", fm.FakeRequest()))
    assert e.value.status_code == 409 and label in e.value.detail and "CUT-KAOS-HTM-M" in e.value.detail
    assert len(db.rahaza_materials.docs) == 3


def test_potongan_masih_berstok_ditolak_409(potongan):
    cut, db, stok = potongan
    stok["p1"] = 12
    with pytest.raises(HTTPException) as e:
        run(cut.delete_panel("p1", fm.FakeRequest()))
    assert e.value.status_code == 409 and "stok 12 pcs" in e.value.detail
    assert len(db.rahaza_materials.docs) == 3


def test_hapus_potongan_hanya_untuk_master_potongan(potongan):
    cut, db, _stok = potongan
    with pytest.raises(HTTPException) as e:
        run(cut.delete_panel("bukan", fm.FakeRequest()))
    assert e.value.status_code == 404 and len(db.rahaza_materials.docs) == 3


def test_hapus_potongan_memakai_pemeriksaan_yang_sudah_ada():
    import routes.cutting as cut
    src = inspect.getsource(cut.delete_panel)
    assert "cut_panel_health.inspect" in src and "REFERENCE_CHECKS" not in src.split('"""')[-1]
    assert "_require_cutting_user" in src


# ══════════════════════════════ gerbang peran ══════════════════════════════
def _deps(router, method, path):
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return [getattr(getattr(d, "dependency", None) or getattr(d, "call", None), "__name__", "") for d in r.dependencies]
    raise AssertionError(f"rute {method} {path} tidak ada")


@pytest.mark.parametrize("modname,path", [
    ("routes.marketing_livehost_portal", "/api/marketing/livehost/{host_id}"),
    ("routes.marketing_task_templates", "/api/marketing/task-templates/{template_id}"),
    ("routes.sku_bridge", "/api/sku-bridge/mappings/{platform_sku_id}"),
])
def test_endpoint_hapus_dijaga_peran(modname, path):
    import importlib
    mod = importlib.import_module(modname)
    names = _deps(mod.router, "DELETE", path)
    assert any(n.startswith("require_roles[") for n in names), names


def test_endpoint_hapus_katalog_dan_kreator_dijaga_izin_toko():
    import routes.marketing_catalog_items as mci
    import routes.marketing_kol_creators as mkc
    cm = _import_mgmt()
    for fn in (cm.delete_catalog, mci.delete_catalog_item, mkc.deactivate_creator):
        src = inspect.getsource(fn)
        assert "require_perm(request, 'toko.manage'" in src, fn.__name__


def test_daftar_pemakaian_katalog_satu_sumber():
    """Hapus katalog memakai daftar cek item yang sama dengan hapus item (tidak ada dua daftar)."""
    cm = _import_mgmt()
    src = inspect.getsource(cm.delete_catalog)
    assert "item_usage_checks" in src and "marketing_orders" not in src


# ══════════════════════════════ layar ══════════════════════════════
def test_layar_katalog_hapus_aman_dan_tawarkan_nonaktif():
    src = fe("components/erp/CatalogManagementModule.jsx")
    for frag in ("hapusMaster", "catalog-edit-", "catalog-delete-", "Ubah katalog", "Hapus katalog",
                 "is_active: false", "/archive", "e.status = r.status", "label: 'Aksi'"):
        assert frag in src, frag
    assert "confirmDialog" not in src     # alur konfirmasi lewat hapusMaster


def test_layar_jembatan_sku_konfirmasi_dan_ganti():
    src = fe("components/erp/SkuBridgeModule.jsx")
    for frag in ("confirmDialog", "Lepas pemetaan SKU", "Belum tertaut", "remap-", "unmap-", "onUbah", "mapped_to",
                 "label: 'Aksi'"):
        assert frag in src, frag
    unmap = src[src.index("const unmap = async"):src.index("const kolom = [", src.index("const unmap = async"))]
    assert unmap.index("confirmDialog") < unmap.index("apiDelete")   # konfirmasi DULU, baru lepas
    # "Ganti barang gudang" = POST /map ulang; jejak warisan di item LAMA ikut dilepas (seperti remove_mapping)
    import routes.sku_bridge as rsb
    mapsrc = inspect.getsource(rsb.map_sku)
    assert "'$pull': {'platform_sku_ids': psid, 'bridge_keys': psid}" in mapsrc


def test_layar_kreator_host_templat_punya_ubah_hapus():
    kol = fe("components/erp/KOLCreatorModule.jsx")
    for frag in ("hapusMaster", "creator-row-delete-", "edit-creator-btn", "?hard=true", "e.status = r.status",
                 "label: 'Aksi'"):
        assert frag in kol, frag
    hostsrc = fe("components/erp/marketing/live-host/LiveHostsTab.jsx")
    for frag in ("hapusMaster", "delete-host-", "edit-host-", "?hard=true", "e.status = res.status", "label: 'Aksi'"):
        assert frag in hostsrc, frag
    tpl = fe("components/erp/TaskTemplatesModule.jsx")
    for frag in ("hapusMaster", "delete-tpl-", "edit-tpl-", "toggle-tpl-", "?hard=true", "label: 'Aksi'"):
        assert frag in tpl, frag


def test_layar_master_potongan_punya_ubah_hapus():
    src = fe("components/erp/cutting/CuttingPanelsModule.jsx")
    for frag in ("hapusMaster", "cutting-panel-row-edit-", "cutting-panel-row-delete-", "/cutting/panels/${m.id}",
                 "/rahaza/materials/${m.id}", "UbahPotonganForm", "FormPopup", "e.status = res.status", "label: 'Aksi'"):
        assert frag in src, frag



# ══ 10 Nov 2026 (keputusan owner): target bulanan bukan riwayat — ikut terhapus bersama kreator ══
def test_kreator_hanya_punya_target_tetap_terhapus(kreator):
    mkc, db = kreator[0], kreator[1]
    db.marketing_creator_targets.docs.append({"id": "t1", "creator_id": "kr1"})
    out = run(mkc.deactivate_creator("kr1", fm.FakeRequest(), hard=True))
    assert out["deleted"] is True and db.marketing_creator_targets.docs == []
