"""Enam temuan Produksi/Gudang/Keuangan (owner 14 Nov 2026: "Ya, kerjakan") — centang owner = satu-satunya penentu.

  1. Jembatan SKU › Buat varian / Buat master hanya untuk yang dicentang Tambah Master Produk (Produksi atau RnD).
  2. Input atas nama CMT: centang modul "Input atas nama Vendor CMT", bukan daftar kode peran (layar & header).
  3. Hapus PO ditolak bila PO sudah berjalan (job, progres, Terima & QC, kiriman hasil, bahan sudah keluar gudang).
  4. Setujui opname dipisah per jenis sesi: aksesoris ↔ Stok Opname Aksesoris, gudang ↔ Opname Stok Gudang.
  5. Tombol Bayar/Jurnal hutang mengikuti centang yang diminta server (kunci di layar dikunci uji ini).
  6. Teks yang terlihat staf menyebut "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses", bukan "Manajemen Role".
Hermetik: tanpa Mongo (FakeDB).
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402
from data.module_catalog import request_key  # noqa: E402

LETAK = "Administrasi Sistem › Kontrol Akses › Peran & Hak Akses"


def run(coro):
    return asyncio.run(coro)


def U(role, *perms):
    return {"id": f"u-{role}", "name": role, "role": role, "_permissions": list(perms), "_role_perms": list(perms)}


# ═══════════════════════════ 1. Jembatan SKU: buat varian/master = R&D ═══════════════════════════
@pytest.fixture
def sku(monkeypatch):
    import routes.sku_bridge as sb
    db = FakeDB()
    monkeypatch.setattr(sb, "get_db", lambda: db)

    async def _log(*a, **k):
        return None
    monkeypatch.setattr(sb, "log_activity", _log)
    return sb


def test_hak_buat_master_dari_centang_master_produk(sku):
    assert sku.boleh_buat_master(U("owner"))
    assert sku.boleh_buat_master(U("Staf R&D", "mod.rnd_master_product.create"))
    assert sku.boleh_buat_master(U("Admin Produksi", "mod.prod_master_product.create"))
    # Centang penuh Jembatan SKU (portal gudang/toko) TIDAK cukup; Lihat master produk juga tidak.
    assert not sku.boleh_buat_master(U("Staf Marketing", "mod.wh_sku_bridge.create", "mod.wh_sku_bridge.edit",
                                       "mod.prod_master_product.view", "mod.rnd_master_product.edit"))
    assert not sku.boleh_buat_master(U("admin_gudang"))                      # kode peran tidak menentukan


def test_buat_master_ditolak_untuk_yang_tidak_dicentang(sku):
    staf = U("Staf Marketing", "mod.wh_sku_bridge.view", "mod.wh_sku_bridge.create")
    for apply in (False, True):                                          # pratinjau pun ditolak
        with pytest.raises(HTTPException) as e:
            run(sku.create_master(sku.CreateMasterIn(platform_sku_id="1729", apply=apply), staf))
        assert e.value.status_code == 403 and e.value.detail == sku.PESAN_BUAT_MASTER
    assert "R&D" in sku.PESAN_BUAT_MASTER and "tautkan" in sku.PESAN_BUAT_MASTER
    for aksi in (["map", "create_variant"], ["create_master"]):
        with pytest.raises(HTTPException) as e:
            run(sku.bulk_resolve(sku.BulkResolveIn(actions=aksi, apply=True), staf))
        assert e.value.status_code == 403


def test_tautkan_varian_yang_ada_tetap_untuk_semua(sku, monkeypatch):
    dipanggil = {}

    async def _bulk(db, *, actions, limit, account_id, user, dry_run):
        dipanggil.update(actions=actions, dry_run=dry_run)
        return {"applied_count": 0, "created_models": 0, "created_variants": 0, "orders_updated": 0}
    monkeypatch.setattr(sku.bridge, "bulk_resolve", _bulk)
    staf = U("Staf Marketing", "mod.wh_sku_bridge.view")
    run(sku.bulk_resolve(sku.BulkResolveIn(actions=["map"], apply=False), staf))
    assert dipanggil == {"actions": ("map",), "dry_run": True}
    # Pemilik centang R&D boleh memakai aksi buat lewat jalur yang sama.
    run(sku.bulk_resolve(sku.BulkResolveIn(actions=["map", "create_variant"]), U("Staf R&D", "mod.rnd_master_product.create")))
    assert dipanggil["actions"] == ("map", "create_variant")


def test_layar_membaca_hak_dari_health(sku, monkeypatch):
    async def _health(db, account_id=None):
        return {"orders": 3, "lines": 5}
    monkeypatch.setattr(sku.bridge, "health", _health)
    assert run(sku.bridge_health(None, U("Staf Marketing", "mod.wh_sku_bridge.view")))["boleh_buat_master"] is False
    out = run(sku.bridge_health(None, U("Staf R&D", "mod.rnd_master_product.create")))
    assert out["boleh_buat_master"] is True and out["orders"] == 3
    jsx = (REPO / "frontend/src/components/erp/SkuBridgeModule.jsx").read_text(encoding="utf-8")
    assert "boleh_buat_master" in jsx and sku.PESAN_BUAT_MASTER in jsx      # pesan layar = pesan server


# ═══════════════════════════ 2. Input atas nama CMT: centang, bukan kode peran ═══════════════════════════
class _Req:
    def __init__(self, method="GET", vendor="ven-1"):
        self.method = method
        self.headers = {"X-CMT-Override-Vendor": vendor} if vendor else {}

        class _S:
            pass
        self.state = _S()


@pytest.fixture
def ovdb():
    db = FakeDB()
    db.vendor_partners.docs = [{"id": "ven-1", "name": "CMT Maju", "code": "CM1", "is_active": True}]
    return db


def test_peran_lain_bercentang_boleh_atas_nama_vendor(ovdb):
    from core import cmt_override as ov
    kp = U("Koordinator Packing", "mod.prod_cmt_override.view", "mod.prod_cmt_override.create")
    ctx = run(ov.resolve_override(_Req("POST"), kp, ovdb))
    assert ctx["vendor_id"] == "ven-1" and ctx["staff_role"] == "koordinator packing"
    assert run(ov.resolve_override(_Req("GET"), kp, ovdb))["vendor_name"] == "CMT Maju"
    assert ov.is_override_role(kp)
    assert run(ov.resolve_override(_Req("PUT"), U("superadmin"), ovdb))["vendor_id"] == "ven-1"


def test_admin_produksi_tanpa_centang_ditolak(ovdb):
    from core import cmt_override as ov
    ap = U("admin_produksi", "mod.prod_po.view", "mod.prod_po.create")      # dulu ada di daftar kode peran
    for method in ("GET", "POST"):
        with pytest.raises(HTTPException) as e:
            run(ov.resolve_override(_Req(method), ap, ovdb))
        assert e.value.status_code == 403
        assert LETAK in e.value.detail and "Input atas nama Vendor CMT" in e.value.detail
        assert "admin_produksi" not in e.value.detail and "Role yang diizinkan" not in e.value.detail
    assert not ov.is_override_role(ap)


def test_aksi_header_mengikuti_metode(ovdb):
    from core import cmt_override as ov
    lihat = U("Supervisor", "mod.prod_cmt_override.view")
    assert ov.is_override_role(lihat)                                    # layar terbuka (Lihat)
    run(ov.resolve_override(_Req("GET"), lihat, ovdb))
    with pytest.raises(HTTPException) as e:                              # tetapi tidak boleh mengisi
        run(ov.resolve_override(_Req("POST"), lihat, ovdb))
    assert '"Tambah"' in e.value.detail
    ubah = U("PPIC Baru", "mod.prod_cmt_override.edit")
    assert ov.boleh_atas_nama(ubah, "PATCH") and ov.boleh_atas_nama(ubah, "GET")
    assert not ov.boleh_atas_nama(ubah, "POST") and not ov.boleh_atas_nama(ubah, "DELETE")
    assert run(ov.resolve_override(_Req("GET", vendor=""), lihat, ovdb)) is None   # tanpa header = mode biasa


def test_layar_input_atas_nama_cmt_tanpa_daftar_peran():
    jsx = (REPO / "frontend/src/components/erp/CMTOverridePortalModule.jsx").read_text(encoding="utf-8")
    assert "ALLOWED_ROLES" not in jsx and "mod.prod_cmt_override" in jsx and "punyaCentang" in jsx


# ═══════════════════════════ 3. Hapus PO yang sudah berjalan ditolak ═══════════════════════════
@pytest.fixture
def podb():
    db = FakeDB()
    db.production_pos.docs = [{"id": "po-1", "po_number": "PO-MKL-0007", "business_type": "maklon", "status": "Draft"}]
    db.po_items.docs = [{"id": "pi-1", "po_id": "po-1", "qty": 50}]
    # Kasus nyata: PO maklon Draf dengan satu surat jalan berstatus Dikirim, tanpa pengeluaran bahan dan tanpa job.
    db.vendor_shipments.docs = [{"id": "sj-1", "po_id": "po-1", "shipment_number": "SJ-0001", "status": "Sent"}]
    db.vendor_shipment_items.docs = [{"id": "si-1", "shipment_id": "sj-1", "po_id": "po-1", "po_item_id": "pi-1"}]
    return db


def test_po_draf_dengan_surat_jalan_tanpa_bahan_keluar_boleh_dihapus(podb):
    from cascade_delete import alasan_tolak_hapus_po
    assert run(alasan_tolak_hapus_po(podb, "po-1")) == []
    # MI masih draf / sudah diretur penuh / penerimaan dibatalkan → bukan penghalang
    podb.rahaza_material_issues.docs = [
        {"id": "mi-0", "mi_number": "MI-0", "vendor_shipment_id": "sj-1", "status": "draft"},
        {"id": "mi-r", "mi_number": "MI-R", "vendor_shipment_id": "sj-1", "status": "issued", "return_status": "full"}]
    podb.cmt_receipts.docs = [{"id": "r0", "po_id": "po-1", "status": "cancelled"}]
    assert run(alasan_tolak_hapus_po(podb, "po-1")) == []


@pytest.mark.parametrize("koleksi,dok,kata", [
    ("production_jobs", {"id": "j1", "po_id": "po-1"}, "job produksi"),
    ("production_jobs", {"id": "j2", "vendor_shipment_id": "sj-1"}, "job produksi"),
    ("cmt_receipts", {"id": "r1", "po_id": "po-1", "status": "on_qc"}, "Terima & QC"),
    ("buyer_shipments", {"id": "b1", "po_id": "po-1"}, "kiriman hasil"),
    ("rahaza_material_issues", {"id": "m1", "mi_number": "MI-0042", "vendor_shipment_id": "sj-1", "status": "issued"},
     "MI-0042"),
])
def test_po_berjalan_ditolak(podb, koleksi, dok, kata):
    from cascade_delete import alasan_tolak_hapus_po
    getattr(podb, koleksi).docs = [dok]
    alasan = run(alasan_tolak_hapus_po(podb, "po-1"))
    assert alasan and any(kata in a for a in alasan)


def test_progres_lewat_work_order_ditolak(podb):
    from cascade_delete import alasan_tolak_hapus_po
    podb.work_orders.docs = [{"id": "wo-1", "po_id": "po-1"}]
    podb.production_progress.docs = [{"id": "pg-1", "work_order_id": "wo-1", "completed_quantity": 5}]
    assert any("progres" in a for a in run(alasan_tolak_hapus_po(podb, "po-1")))


@pytest.fixture
def hapus(monkeypatch, podb):
    import cascade_delete
    import routes.production_pos as pp

    async def _auth(req):
        return {"id": "u-owner", "name": "Owner", "role": "superadmin"}

    async def _log(*a, **k):
        return None
    monkeypatch.setattr(pp, "require_auth", _auth)
    monkeypatch.setattr(pp, "get_db", lambda: podb)
    monkeypatch.setattr(pp, "log_activity", _log)
    monkeypatch.setattr(cascade_delete, "get_db", lambda: podb)
    return pp


def test_route_hapus_po_409_tanpa_menghapus_apa_pun(hapus, podb):
    podb.production_jobs.docs = [{"id": "j1", "po_id": "po-1"}]
    with pytest.raises(HTTPException) as e:
        run(hapus.delete_po("po-1", object()))
    assert e.value.status_code == 409 and "PO-MKL-0007" in e.value.detail and "Tutup PO" in e.value.detail
    assert podb.production_pos.docs and podb.vendor_shipments.docs and podb.production_jobs.docs


def test_route_hapus_po_draf_tanpa_bahan_keluar(hapus, podb):
    assert run(hapus.delete_po("po-1", object())) == {"success": True}
    assert not podb.production_pos.docs and not podb.vendor_shipments.docs and not podb.po_items.docs


# ═══════════════════════════ 4. Setujui opname: per jenis sesi ═══════════════════════════
SESI_AKSESORIS = {"id": "s-acc", "mode": "cycle", "source": "aksesoris", "kinds": ["aksesoris"]}
SESI_GUDANG = {"id": "s-gd", "mode": "full", "source": "gudang", "kinds": []}


def test_setuju_opname_tidak_lintas_jenis():
    from data.module_catalog import expand_permissions
    from routes.wms_opname3 import assert_can_approve, jenis_sesi
    assert jenis_sesi(SESI_AKSESORIS) == "aksesoris" and jenis_sesi(SESI_GUDANG) == "gudang"
    assert jenis_sesi({"source": "gudang", "kinds": ["aksesoris"]}) == "gudang"      # asal sesi yang menentukan
    acc = U("Admin Aksesoris", *expand_permissions(["mod.acc_opname.approve"]))
    gd = U("Kepala Gudang", *expand_permissions(["mod.wh_opname.approve"]))       # + izin lama wh.opname.approve
    assert_can_approve(acc, "menyetujui opname aksesoris", SESI_AKSESORIS)
    assert_can_approve(gd, "menyetujui opname", SESI_GUDANG)
    with pytest.raises(HTTPException) as e:
        assert_can_approve(acc, "menyetujui opname", SESI_GUDANG)
    assert e.value.status_code == 403 and "Opname Stok Gudang" in e.value.detail and LETAK in e.value.detail
    with pytest.raises(HTTPException) as e:
        assert_can_approve(gd, "menolak opname aksesoris", SESI_AKSESORIS)
    assert "Stok Opname Aksesoris" in e.value.detail and "Portal Aksesoris" in e.value.detail
    # izin lama wh.opname.approve tetap dihormati untuk sesi gudang saja
    assert_can_approve(U("Peran Lama", "wh.opname.approve"), "menyetujui opname", SESI_GUDANG)
    with pytest.raises(HTTPException):
        assert_can_approve(U("Peran Lama", "wh.opname.approve"), "menyetujui opname", SESI_AKSESORIS)
    assert_can_approve(U("owner"), "menyetujui opname", SESI_AKSESORIS)


def test_layar_aksesoris_menyetujui_lewat_pintu_aksesoris():
    assert request_key("POST", "/api/acc/opname/s-acc/approve") == "mod.acc_opname.approve"
    assert request_key("POST", "/api/acc/opname/s-acc/reject") == "mod.acc_opname.approve"
    jsx = (REPO / "frontend/src/components/erp/WMSOpnameScanModule.jsx").read_text(encoding="utf-8")
    assert "/api/acc/opname/" in jsx and "sess.source === 'aksesoris'" in jsx


# ═══════════════════════════ 5. Kunci centang tombol Bayar/Jurnal = kunci server ═══════════════════════════
def test_kunci_tombol_bayar_dan_jurnal_sama_dengan_gerbang():
    js = (REPO / "frontend/src/lib/financeRoles.js").read_text(encoding="utf-8")
    bayar = re.search(r"CENTANG_BAYAR = '([^']+)'", js).group(1)
    jurnal = re.search(r"CENTANG_JURNAL_CMT = '([^']+)'", js).group(1)
    for method, path in (("POST", "/api/rahaza/ap-invoices/f1/payment"),
                         ("POST", "/api/dewi/maklon/finance/cmt-payments/c1/pay"),
                         ("POST", "/api/dewi/maklon/finance/cmt-payments/c1/disbursements/d1/void")):
        assert request_key(method, path) == bayar, path
    assert request_key("POST", "/api/dewi/maklon/finance/cmt-payments/c1/post-ap") == jurnal
    for berkas in ("finance/HutangModule.jsx", "ProductionCMTBillingModule.jsx", "procurement/SupplierInvoiceModule.jsx"):
        isi = (REPO / "frontend/src/components/erp" / berkas).read_text(encoding="utf-8")
        assert "punyaCentang(hasPerm, CENTANG_BAYAR)" in isi and "isFinanceRole(" not in isi, berkas


# ═══════════════════════════ 6. Teks letak centang ═══════════════════════════
def _string_non_docstring(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                doc.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc:
            yield node.value


def test_tidak_ada_lagi_manajemen_role_di_teks_staf():
    lewati = {"middleware/module_permission_gate.py"}                   # diurus cabang lain
    temuan = []
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "scripts/")) or "/_archive/" in rel or rel in lewati:
            continue
        if any("Manajemen Role" in s for s in _string_non_docstring(p)):
            temuan.append(rel)
    for p in (REPO / "frontend/src").rglob("*.js*"):
        if "__tests__" in p.parts:
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            t = ln.strip()
            if "Manajemen Role" in t and not t.startswith(("//", "*", "/*")):
                temuan.append(p.relative_to(REPO).as_posix())
    assert not temuan, temuan
