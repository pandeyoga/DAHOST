"""Alur permintaan aksesoris R&D (2026-11-10) — keputusan owner.

  1. Baris dipilih dari master aksesoris (kode, nama, satuan dari master); ketikan bebas tetap boleh
     sebagai cadangan ("belum tertaut"); master yang tidak ada / nonaktif ditolak.
  2. Peminta / tim R&D / manajemen membatalkan permintaan yang BELUM diserahkan (alasan wajib).
  3. Notifikasi lewat bel yang ada (`notif_insert`): tim aksesoris saat permintaan masuk (Perlu Tindakan,
     tertutup sendiri saat diserahkan / ditolak / dibatalkan); peminta saat disiapkan / diserahkan /
     ditolak / dibatalkan orang lain.
  4. Ringkasan layar R&D hanya menghitung sampel R&D.
  5. Stok kurang saat serah → layar mendapat baris kekurangan; tombol membuat SATU draf Request
     Pembelian Aksesoris (tidak memotong stok, tetap diajukan manual).
  6. Status sample tidak berubah karena aksesoris; daftar sample diberi keterangan status aksesoris.
  7. PUT sample tidak bisa mengubah status / data persetujuan; sample yang sudah diputuskan terkunci.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB  # noqa: E402
from core import accessory_issue as ai  # noqa: E402
import core.doc_number_policy as dnp  # noqa: E402
import routes.dewi_accessory_requests as req_mod  # noqa: E402
import routes.dewi_rnd_samples as smp  # noqa: E402

T0 = datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc)
RND = {"id": "u-rnd", "name": "Staf RnD", "role": "rnd_staff"}
RND2 = {"id": "u-rnd2", "name": "Staf RnD Dua", "role": "rnd_staff"}
ADMIN_ACC = {"id": "u-acc", "name": "Admin Aksesoris", "role": "admin_aksesoris"}
OPERATOR = {"id": "u-op", "name": "Operator", "role": "operator"}
OWNER = {"id": "u-own", "name": "Owner", "role": "owner"}


def run(coro):
    return asyncio.run(coro)


def _mat(mid="ACC1", code="KCG", unit="pcs", cost=2000.0, active=True):
    return {"id": mid, "code": code, "name": f"Kancing {code}", "type": "accessory", "active": active,
            "unit": unit, "unit_cost": cost}


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    d.rahaza_materials.docs = [_mat(), _mat("ACC2", "RSL", unit="m", cost=500.0)]
    monkeypatch.setattr(req_mod, "get_db", lambda: d)
    monkeypatch.setattr(smp, "get_db", lambda: d)
    n = {"i": 0}

    async def number(db_, key, *, ctx=None, requested=""):
        n["i"] += 1
        prefix = "PRA" if key.startswith("acc_purchase") else (ctx or {}).get("TIPE", "REQ")
        return f"{prefix}-UJI-{n['i']:03d}"
    monkeypatch.setattr(dnp, "issue_number", number)
    return d


@pytest.fixture
def stock(monkeypatch):
    qty = {}

    async def usable(db_, mid):
        return float(qty.get(mid, 0))
    monkeypatch.setattr(ai, "_usable_qty", usable)
    return qty


def _req(rid="r1", status="submitted", rtype="rnd_sample", requester=RND, **kw):
    return {"id": rid, "request_code": f"REQ-AKS-{rid}", "request_type": rtype, "status": status,
            "requester_id": requester["id"], "requester_name": requester["name"], "style_code": "ST-01",
            "items": [{"material_id": "ACC1", "material_code": "KCG", "material_name": "Kancing KCG",
                       "qty": 4, "unit": "pcs"}],
            "created_at": T0, **kw}


def _notifs(d, subtype=None):
    return [n for n in d.notifications.docs if subtype is None or n.get("subtype") == subtype]


# ═════════════════════════ 1. baris dari master ═════════════════════════
def test_baris_master_mengambil_kode_nama_satuan_dari_master_dan_ketikan_tetap_boleh(db):
    out = run(req_mod.create_request({
        "request_type": "rnd_sample", "status": "submitted", "sample_request_id": "S1",
        "items": [
            {"material_id": "ACC2", "material_code": "ketikan", "material_name": "nama ketikan",
             "qty": 1.5, "unit": "pcs"},                                   # satuan ketikan diabaikan
            {"material_code": "", "material_name": "kancing kayu khusus", "qty": 3, "unit": "pcs"},
        ]}, RND))
    a, b = out["items"]
    assert (a["material_id"], a["material_code"], a["material_name"], a["unit"], a["qty"]) == \
        ("ACC2", "RSL", "Kancing RSL", "m", 1.5)
    assert (b["material_id"], b["material_name"]) == ("", "kancing kayu khusus")      # belum tertaut


@pytest.mark.parametrize("mats", [[], [_mat(active=False)]])
def test_master_tidak_ada_atau_nonaktif_ditolak(db, mats):
    db.rahaza_materials.docs = mats
    with pytest.raises(HTTPException) as e:
        run(req_mod.create_request({"request_type": "rnd_sample", "status": "submitted",
                                    "items": [{"material_id": "ACC1", "qty": 1}]}, RND))
    assert e.value.status_code == 400 and "Baris 1" in e.value.detail
    assert db.dewi_accessory_requests.docs == []


def test_ubah_baris_tautan_baru_wajib_master_tautan_lama_tetap(db):
    db.dewi_accessory_requests.docs = [_req(items=[{"material_id": "LAMA", "material_code": "OLD",
                                                    "material_name": "Lama", "qty": 1}])]
    run(req_mod.update_request("r1", {"items": [{"material_id": "LAMA", "material_code": "OLD",
                                                 "material_name": "Lama", "qty": 2}]}, RND))
    assert db.dewi_accessory_requests.docs[0]["items"][0]["qty"] == 2.0
    with pytest.raises(HTTPException) as e:
        run(req_mod.update_request("r1", {"items": [{"material_id": "HILANG", "qty": 1}]}, RND))
    assert e.value.status_code == 400


# ═════════════════════════ 2. batal ═════════════════════════
@pytest.mark.parametrize("status", ["draft", "submitted", "allocated"])
def test_peminta_membatalkan_selama_belum_diserahkan(db, status):
    db.dewi_accessory_requests.docs = [_req(status=status)]
    run(req_mod.cancel_request("r1", {"reason": "Sample ditunda"}, RND))
    d = db.dewi_accessory_requests.docs[0]
    assert (d["status"], d["cancel_reason"], d["cancelled_by_id"]) == ("cancelled", "Sample ditunda", RND["id"])


@pytest.mark.parametrize("status", ["delivered", "rejected", "cancelled"])
def test_tidak_bisa_batal_setelah_selesai(db, status):
    db.dewi_accessory_requests.docs = [_req(status=status)]
    with pytest.raises(HTTPException) as e:
        run(req_mod.cancel_request("r1", {"reason": "x"}, RND))
    assert e.value.status_code == 400 and db.dewi_accessory_requests.docs[0]["status"] == status


def test_batal_wajib_alasan_dan_menghormati_kunci_serah(db):
    db.dewi_accessory_requests.docs = [_req(status="allocated")]
    with pytest.raises(HTTPException) as e:
        run(req_mod.cancel_request("r1", {"reason": "  "}, RND))
    assert e.value.status_code == 400
    db.dewi_accessory_requests.docs = [_req(status="allocated", delivering=True)]
    with pytest.raises(HTTPException) as e:
        run(req_mod.cancel_request("r1", {"reason": "batal"}, RND))
    assert e.value.status_code == 409 and db.dewi_accessory_requests.docs[0]["status"] == "allocated"
    db.dewi_accessory_requests.docs = [_req(status="allocated", stock_issue_partial=True)]
    with pytest.raises(HTTPException) as e:
        run(req_mod.cancel_request("r1", {"reason": "batal"}, RND))
    assert e.value.status_code == 400


def test_siapa_boleh_membatalkan(db):
    # rekan R&D boleh untuk sampel R&D; operator tidak; manajemen boleh
    db.dewi_accessory_requests.docs = [_req("a"), _req("b"), _req("c")]
    run(req_mod.cancel_request("a", {"reason": "x"}, RND2))
    with pytest.raises(HTTPException) as e:
        run(req_mod.cancel_request("b", {"reason": "x"}, OPERATOR))
    assert e.value.status_code == 403
    run(req_mod.cancel_request("c", {"reason": "x"}, OWNER))
    # permintaan divisi milik orang lain: rekan R&D tidak boleh
    db.dewi_accessory_requests.docs = [_req("d", rtype="internal_issuance", requester=ADMIN_ACC)]
    with pytest.raises(HTTPException) as e:
        run(req_mod.cancel_request("d", {"reason": "x"}, RND))
    assert e.value.status_code == 403


# ═════════════════════════ 3. notifikasi ═════════════════════════
def test_permintaan_masuk_memberi_tahu_tim_aksesoris_sebagai_perlu_tindakan(db):
    db.dewi_rnd_sample_requests.docs = [{"id": "S1", "sample_code": "SR-0001"}]
    run(req_mod.create_request({"request_type": "rnd_sample", "status": "draft",
                                "items": [{"material_id": "ACC1", "qty": 1}]}, RND))
    assert _notifs(db) == []                                                # draf: belum ada kabar
    out = run(req_mod.create_request({"request_type": "rnd_sample", "status": "submitted", "urgent": True,
                                      "sample_request_id": "S1", "style_code": "ST-01",
                                      "items": [{"material_id": "ACC1", "qty": 2}]}, RND))
    [n] = _notifs(db, "acc_request_submitted")
    assert n["kind"] == "action" and n["resolved_at"] is None and n["source_id"] == out["id"]
    assert n["source_collection"] == "dewi_accessory_requests"
    assert {"admin_aksesoris", "spv_aksesoris", "superadmin"} <= set(n["meta"]["target_roles"])
    assert n["meta"]["exclude_user_ids"] == [RND["id"]] and n["meta"]["link_module"] == "accessories-inbox"
    assert "mendesak" in n["title"] and "SR-0001" in n["body"] and "Kancing KCG 2 pcs" in n["body"]
    assert n["action"]["label"] == "Siapkan permintaan"
    # draf yang diajukan belakangan juga memberi tahu
    draft = db.dewi_accessory_requests.docs[0]
    run(req_mod.submit_request(draft["id"], RND))
    assert len(_notifs(db, "acc_request_submitted")) == 2


def test_peminta_dikabari_saat_disiapkan_ditolak_dan_tindakan_tim_tertutup(db):
    db.dewi_accessory_requests.docs = [_req("r1"), _req("r2")]
    run(req_mod._notify_team(db, db.dewi_accessory_requests.docs[0], RND, event="submitted"))
    run(req_mod.allocate_request("r1", {}, ADMIN_ACC))
    [st] = _notifs(db, "acc_request_status")
    assert st["user_id"] == RND["id"] and st["meta"]["event"] == "allocated"
    assert st["meta"]["link_module"] == "rnd-accessory-requests"
    assert _notifs(db, "acc_request_submitted")[0]["resolved_at"] is None   # disiapkan: masih perlu diserahkan
    run(req_mod.reject_request("r1", {"reason": "Barang tidak standar"}, ADMIN_ACC))
    last = _notifs(db, "acc_request_status")[-1]
    assert last["meta"]["event"] == "rejected" and "Barang tidak standar" in last["body"]
    assert _notifs(db, "acc_request_submitted")[0]["resolved_at"] is not None


def test_pelaku_yang_sama_dengan_peminta_tidak_dikabari(db):
    db.dewi_accessory_requests.docs = [_req(requester=ADMIN_ACC)]
    run(req_mod.allocate_request("r1", {}, ADMIN_ACC))
    assert _notifs(db, "acc_request_status") == []


def test_serah_mengabari_peminta_dan_menutup_tindakan(db, stock, monkeypatch):
    async def issue(db_, user, *, acc_id, qty, **kw):
        stock[acc_id] -= qty
        return {"material_id": acc_id, "material_code": "KCG", "material_name": "Kancing KCG", "qty_issued": qty,
                "unit": "pcs", "unit_cost": 0, "value": 0, "je": {}}

    async def target(db_, **kw):
        return {"cost_target": "rnd_sample"}

    async def guard(*a, **k):
        return []
    monkeypatch.setattr(ai, "issue_accessory", issue)
    monkeypatch.setattr(ai, "resolve_cost_target", target)
    monkeypatch.setattr(ai, "guard_po_over_issue", guard)
    db.dewi_accessory_requests.docs = [_req(status="allocated")]
    run(req_mod._notify_team(db, db.dewi_accessory_requests.docs[0], RND, event="submitted"))
    stock["ACC1"] = 10
    run(req_mod.deliver_request("r1", {}, ADMIN_ACC))
    assert stock["ACC1"] == 6
    assert _notifs(db, "acc_request_submitted")[0]["resolved_at"] is not None
    assert _notifs(db, "acc_request_status")[-1]["meta"]["event"] == "delivered"


def test_batal_mengabari_tim_dan_peminta_bila_dibatalkan_rekan(db):
    db.dewi_accessory_requests.docs = [_req(status="allocated")]
    run(req_mod._notify_team(db, db.dewi_accessory_requests.docs[0], RND, event="submitted"))
    run(req_mod.cancel_request("r1", {"reason": "Desain diganti"}, RND2))
    [c] = _notifs(db, "acc_request_cancelled")
    assert c["kind"] == "info" and "Desain diganti" in c["body"] and c["meta"]["exclude_user_ids"] == [RND2["id"]]
    assert _notifs(db, "acc_request_status")[-1]["user_id"] == RND["id"]
    assert _notifs(db, "acc_request_submitted")[0]["resolved_at"] is not None
    # draf yang dibatalkan peminta sendiri: tim tidak pernah menerima, jadi tidak dikabari
    db.notifications.docs = []
    db.dewi_accessory_requests.docs = [_req(status="draft")]
    run(req_mod.cancel_request("r1", {"reason": "x"}, RND))
    assert _notifs(db) == []


def test_notifikasi_gagal_tidak_menggagalkan_permintaan(db, monkeypatch):
    import utils.notif_unified as nu

    async def boom(*a, **k):
        raise RuntimeError("bel mati")
    monkeypatch.setattr(nu, "notif_insert", boom)
    out = run(req_mod.create_request({"request_type": "rnd_sample", "status": "submitted",
                                      "items": [{"material_id": "ACC1", "qty": 1}]}, RND))
    assert out["status"] == "submitted" and len(db.dewi_accessory_requests.docs) == 1


# ═════════════════════════ 4. ringkasan per jenis ═════════════════════════
def test_ringkasan_bisa_dibatasi_ke_sampel_rnd(db):
    db.dewi_accessory_requests.docs = [
        _req("a"), _req("b", status="allocated", urgent=True), _req("c", status="delivered"),
        _req("d", rtype="internal_issuance"), _req("e", rtype="internal_issuance", status="allocated", urgent=True),
    ]
    semua = run(req_mod.stats_summary(None, ADMIN_ACC))
    rnd = run(req_mod.stats_summary("rnd_sample", RND))
    assert (semua["total"], semua["submitted"], semua["urgent_pending"]) == (5, 2, 2)
    assert (rnd["total"], rnd["submitted"], rnd["allocated"], rnd["delivered"], rnd["urgent_pending"]) == (3, 1, 1, 1, 1)
    assert semua["by_request_type"]["internal_issuance"] == 2


# ═════════════════════════ 5. stok kurang → draf pembelian ═════════════════════════
def test_stok_kurang_saat_serah_mengirim_baris_kekurangan(db, stock):
    db.dewi_accessory_requests.docs = [_req(status="allocated", items=[
        {"material_id": "ACC1", "qty": 4}, {"material_id": "ACC1", "qty": 2}, {"material_id": "ACC2", "qty": 1}])]
    stock.update({"ACC1": 5, "ACC2": 3})
    with pytest.raises(HTTPException) as e:
        run(req_mod.deliver_request("r1", {}, ADMIN_ACC))
    det = e.value.detail
    assert e.value.status_code == 400 and det["code"] == "stock_short"
    # ACC1 dijumlah: butuh 4 + 2 = 6, bisa dipakai 5 → kurang 1; ACC2 cukup
    assert [(ln["material_id"], ln["needed"], ln["usable"], ln["short"]) for ln in det["lines"]] == \
        [("ACC1", 6.0, 5.0, 1.0)]
    assert db.dewi_accessory_requests.docs[0]["status"] == "allocated"


def test_draf_pembelian_berisi_kekurangan_dan_tidak_dobel(db, stock):
    db.dewi_accessory_requests.docs = [_req(status="allocated", urgent=True, items=[
        {"material_id": "ACC1", "qty": 10}, {"material_id": "ACC2", "qty": 1},
        {"material_id": "", "material_name": "kancing kayu", "qty": 2}])]
    stock.update({"ACC1": 4, "ACC2": 3, "ACC3": 0})
    db.rahaza_materials.docs.append(_mat("ACC3", "KYU", cost=1500.0))
    # baris ketikan dipilihkan master di form serah → ikut dihitung dan disimpan
    out = run(req_mod.create_purchase_draft("r1", {"item_links": [{"index": 2, "material_id": "ACC3"}]}, ADMIN_ACC))
    [pr] = db.acc_purchase_requests.docs
    assert out["already"] is False and out["pr_number"] == pr["pr_number"] and pr["status"] == "Draft"
    assert pr["priority"] == "Urgent" and pr["source_type"] == "accessory_request" and pr["source_id"] == "r1"
    assert [(i["acc_id"], i["qty_requested"], i["estimated_price"]) for i in pr["items"]] == \
        [("ACC1", 6.0, 2000.0), ("ACC3", 2.0, 1500.0)]
    assert pr["total_estimated"] == 6 * 2000 + 2 * 1500
    req = db.dewi_accessory_requests.docs[0]
    assert req["purchase_draft_number"] == pr["pr_number"] and req["items"][2]["material_id"] == "ACC3"
    assert req["status"] == "allocated" and stock["ACC1"] == 4                 # stok tidak disentuh
    again = run(req_mod.create_purchase_draft("r1", {}, ADMIN_ACC))
    assert again["already"] is True and again["pr_number"] == pr["pr_number"]
    assert len(db.acc_purchase_requests.docs) == 1
    # draf ditolak → boleh dibuat lagi
    pr["status"] = "Rejected"
    run(req_mod.create_purchase_draft("r1", {}, ADMIN_ACC))
    assert len(db.acc_purchase_requests.docs) == 2


def test_draf_pembelian_ditolak_bila_tidak_ada_yang_kurang_atau_bukan_tim(db, stock):
    db.dewi_accessory_requests.docs = [_req(status="allocated")]
    stock["ACC1"] = 100
    with pytest.raises(HTTPException) as e:
        run(req_mod.create_purchase_draft("r1", {}, ADMIN_ACC))
    assert e.value.status_code == 400 and db.acc_purchase_requests.docs == []
    stock["ACC1"] = 0
    with pytest.raises(HTTPException) as e:
        run(req_mod.create_purchase_draft("r1", {}, RND))
    assert e.value.status_code == 403
    db.dewi_accessory_requests.docs = [_req(status="delivered")]
    with pytest.raises(HTTPException) as e:
        run(req_mod.create_purchase_draft("r1", {}, ADMIN_ACC))
    assert e.value.status_code == 400


# ═════════════════════════ 6. keterangan aksesoris di daftar sample ═════════════════════════
def test_status_aksesoris_per_sample(db):
    db.dewi_rnd_sample_requests.docs = [
        {"id": s, "sample_code": f"SR-{s}", "status": "approved", "created_at": T0} for s in "ABCDE"]
    db.dewi_accessory_requests.docs = [
        _req("1", status="delivered", sample_request_id="A"), _req("2", status="submitted", sample_request_id="A"),
        _req("3", status="allocated", sample_request_id="B"), _req("4", status="delivered", sample_request_id="B"),
        _req("5", status="delivered", sample_request_id="C"), _req("6", status="rejected", sample_request_id="C"),
        _req("7", status="cancelled", sample_request_id="D"),
        _req("8", status="rejected", sample_request_id="E"),
    ]
    rows = {r["id"]: r["accessory_status"] for r in run(smp.list_sample_requests(limit=200, user=RND))}
    assert rows["A"]["state"] == "submitted" and (rows["A"]["delivered"], rows["A"]["total"]) == (1, 2)
    assert rows["B"]["state"] == "allocated"
    assert rows["C"]["state"] == "delivered" and rows["C"]["rejected"] == 1
    assert rows["D"] is None                                       # yang dibatalkan tidak dihitung
    assert rows["E"]["state"] == "rejected"
    assert all(r["status"] == "approved" for r in db.dewi_rnd_sample_requests.docs)   # status sample tetap
    assert run(smp.get_sample_request("A", RND))["accessory_status"]["state"] == "submitted"


# ═════════════════════════ 7. PUT sample terkunci ═════════════════════════
def _sample(status="draft"):
    return {"id": "S1", "sample_code": "SR-1", "status": status, "notes": "awal", "approved_by": None,
            "created_by": RND["id"], "created_at": T0}


def test_put_sample_tidak_bisa_mengubah_status(db):
    db.dewi_rnd_sample_requests.docs = [_sample("submitted")]
    with pytest.raises(HTTPException) as e:
        run(smp.update_sample_request("S1", {"status": "approved"}, RND))
    assert e.value.status_code == 400 and db.dewi_rnd_sample_requests.docs[0]["status"] == "submitted"


def test_put_sample_membuang_data_persetujuan_tetapi_mengubah_isi(db):
    db.dewi_rnd_sample_requests.docs = [_sample("draft")]
    run(smp.update_sample_request("S1", {"notes": "revisi", "status": "draft", "approved_by": "u-x",
                                         "approval_status": "approved", "created_by": "u-x"}, RND))
    d = db.dewi_rnd_sample_requests.docs[0]
    assert (d["notes"], d["status"], d["approved_by"], d["created_by"]) == ("revisi", "draft", None, RND["id"])
    assert "approval_status" not in d


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_sample_yang_sudah_diputuskan_terkunci(db, status):
    db.dewi_rnd_sample_requests.docs = [_sample(status)]
    with pytest.raises(HTTPException) as e:
        run(smp.update_sample_request("S1", {"notes": "ubah diam-diam"}, RND))
    assert e.value.status_code == 400 and db.dewi_rnd_sample_requests.docs[0]["notes"] == "awal"


def test_put_sample_tidak_ada(db):
    with pytest.raises(HTTPException) as e:
        run(smp.update_sample_request("X", {"notes": "a"}, RND))
    assert e.value.status_code == 404
