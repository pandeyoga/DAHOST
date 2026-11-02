"""Uji unit HERMETIK paket W2-A (2026-11-02) — retur & marketplace, keputusan owner.

  * K1  — retur Marketing hanya membuat Retur Fisik Pending; keputusan gudang (qty aktual)
          satu-satunya titik stok/jurnal; Tolak/Hapus sebelum keputusan membatalkan
          pekerjaan gudang; sesudah keputusan hanya lewat jurnal pembalik + stok keluar.
  * K36 — retur mengurangi omzet rekap HANYA setelah diputuskan gudang.
  * K3  — penarikan ditolak bila saldonya dari pencairan yang belum diposting (uji urutan).
  * K4  — satu pintu rekening tujuan per toko; jurnal penarikan pakai tautan TERBARU.
  * K5  — rekonsiliasi: pembanding setelah diskon penjual, selisih dipecah, periode wajib,
          `revenue_gross` order manual = harga sebelum diskon.
  * K6  — order manual tanpa reservasi; pesanan impor di luar antrean Fulfillment; batal
          setelah kirim ⇒ pengajuan Retur Fisik RTS; aksi Batal massal wajib alasan.
  * K35 — penomoran akun pendapatan toko = konfigurasi Auto Akun (`store_revenue`).
  * Butir 11 — impor "Retur & Refund" memakai nominal refund aktual dari berkas.
  * K7/K8 — skrip pembersih demo & pencocokan katalog (dry-run bawaan).

Bukti runtime terhadap Mongo sungguhan ada di laporan paket (backend uji dahost-fix-wa).
"""
import asyncio
import copy
import os
import re
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

import _fake_mongo as fm  # noqa: E402
from core import finance_sync as fs  # noqa: E402
from core import marketing_returns as mret  # noqa: E402
from core import platform_balance as pb  # noqa: E402
from core import returns_bridge as rb  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ── tiruan Mongo: _fake_mongo + aggregate($match/$group sum) & distinct ─────────
class AggCollection(fm.FakeCollection):
    async def distinct(self, field, q=None):
        out = []
        for d in self.docs:
            if fm.match(d, q):
                v = fm._get(d, field)
                if v is not fm._MISSING and v not in out:
                    out.append(v)
        return out

    def aggregate(self, pipeline):
        rows = [copy.deepcopy(d) for d in self.docs]
        for st in pipeline:
            if "$match" in st:
                rows = [d for d in rows if fm.match(d, st["$match"])]
            elif "$group" in st:
                g = st["$group"]
                key = g["_id"]
                groups = {}
                for d in rows:
                    k = d.get(key[1:]) if isinstance(key, str) else None
                    acc = groups.setdefault(k, {"_id": k})
                    for name, spec in g.items():
                        if name == "_id":
                            continue
                        arg = spec["$sum"]
                        val = arg if not isinstance(arg, str) else (d.get(arg[1:]) or 0)
                        acc[name] = acc.get(name, 0) + val
                rows = list(groups.values())

        class _C:
            async def to_list(self_, n=None):
                return rows
        return _C()


class AggDB(fm.FakeDB):
    def __getitem__(self, name):
        if name not in self._cols:
            self._cols[name] = AggCollection(name)
        return self._cols[name]


async def _fake_code(db):
    db._n = getattr(db, "_n", 0) + 1
    return f"RET-UJI-{db._n:03d}"


@pytest.fixture
def db(monkeypatch):
    d = AggDB()
    monkeypatch.setattr(rb, "_next_code", _fake_code)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# K1 — retur Marketing → Retur Fisik PENDING, tanpa stok
# ══════════════════════════════════════════════════════════════════════════════
def _mat(db, mid="M1", code="DA-2101-MHG-ALLSIZE"):
    db.rahaza_materials.docs.append({"id": mid, "code": code, "name": "Aisar", "type": "fg", "unit": "pcs"})
    db.marketing_catalog_items.docs.append({"id": "CI1", "fg_material_id": mid, "account_id": "A1"})


def test_marketing_return_creates_pending_job_without_stock(db, monkeypatch):
    _mat(db)

    async def boom(*a, **k):
        raise AssertionError("stok TIDAK boleh bergerak saat retur Marketing dibuat (K1)")
    monkeypatch.setattr(rb.stock_service, "add", boom)
    ret = {"id": "R1", "catalog_item_id": "CI1", "qty": 5, "item_condition": "Baik",
           "order_id": "TIDAK-ADA-999", "price": 107999, "refund_amount": 539995}
    db.marketing_returns.docs.append(dict(ret))
    out = run(rb.ensure_wh_return(db, ret, actor={"name": "uji"}))
    wh = out["wh_return"]
    assert out["created"] is True and out["restocked"] is False
    assert wh["status"] == "Pending" and wh["restocked"] is False and wh["qty"] == 5
    assert wh["link_status"] == rb.LINK_OK and wh["reported_condition"] == "Baik"
    assert "BELUM bergerak" in out["message"]
    stamped = run(db.marketing_returns.find_one({"id": "R1"}))
    assert stamped["wh_return_status"] == "Pending" and stamped["wh_restocked"] is False
    # idempoten: panggilan kedua tidak membuat pekerjaan baru
    again = run(rb.ensure_wh_return(db, stamped))
    assert again["created"] is False and len(db.wh_returns.docs) == 1


def test_marketing_paths_never_request_auto_restock():
    for fname in ("marketing_returns_routes.py", "dewi_wh_returns.py", "marketing_data_import.py"):
        src = open(os.path.join(BACKEND, "routes", fname), encoding="utf-8").read()
        assert "auto_restock=True" not in src, fname
        assert not re.search(r"auto_restock=body\.get", src), fname
    sig = open(os.path.join(BACKEND, "core", "returns_bridge.py"), encoding="utf-8").read()
    assert "auto_restock: bool = False" in sig and "auto_restock: bool = True" not in sig


def test_decision_qty_bounded_by_received_qty():
    assert rb.decision_qty({"qty": 5}) == 5
    assert rb.decision_qty({"qty": 5, "received_qty": 3}) == 3
    assert rb.decision_qty({"qty": 5, "received_qty": 3}, 2) == 2
    for bad in (0, -1, 4):
        with pytest.raises(rb.ReturnBridgeError):
            rb.decision_qty({"qty": 5, "received_qty": 3}, bad)
    with pytest.raises(rb.ReturnBridgeError):          # paket kosong: tidak ada yang bisa diputuskan masuk stok
        rb.decision_qty({"qty": 5, "received_qty": 0})


def test_cancel_before_decision_cancels_job_after_decision_flags_only(db):
    db.wh_returns.docs += [
        {"id": "W1", "return_code": "RET-1", "status": "Received", "source_marketing_return_id": "R1",
         "timeline": []},
        {"id": "W2", "return_code": "RET-2", "status": "Resolved", "source_marketing_return_id": "R2",
         "action_taken": "Restock ke Gudang", "restocked": True, "timeline": []},
    ]
    r1 = run(rb.cancel_for_marketing_return(db, {"id": "R1"}, reason="ditolak"))
    assert r1["state"] == "cancelled" and r1["wh_return"]["status"] == "Cancelled"
    assert r1["wh_return"]["cancelled_by_marketing"] is True
    r2 = run(rb.cancel_for_marketing_return(db, {"id": "R2"}, reason="ditolak"))
    w2 = run(db.wh_returns.find_one({"id": "W2"}))
    assert r2["state"] == "decided" and "Balik Keputusan" in r2["message"]
    assert w2["status"] == "Resolved" and w2["restocked"] is True          # stok/jurnal TIDAK diubah diam-diam
    assert w2["marketing_rejected_after_decision"] is True
    assert run(rb.cancel_for_marketing_return(db, {"id": "R9"}))["state"] == "none"


def test_reverse_decision_issues_stock_posts_reversal_and_reopens(db, monkeypatch):
    from routes import rahaza_posting as rp
    issued, created = [], []

    async def fake_issue(mid, loc, qty, **kw):
        issued.append((mid, loc, qty, kw["ref"]["type"]))
        return {"qty": 98}

    async def fake_find(db_, sm, sr):
        return None

    async def fake_create(db_, d, memo, sm, sr, lines, user, **kw):
        created.append({"source_module": sm, "source_ref": sr, "lines": lines})
        return {"ok": True, "je_id": "JE-REV", "je_number": "JE-20261102-0099"}
    monkeypatch.setattr(rb.stock_service, "issue", fake_issue)
    monkeypatch.setattr(rp, "_find_existing_je", fake_find)
    monkeypatch.setattr(rp, "_create_posted_je", fake_create)
    # keputusan lama: 2 pcs × HPP 55.997,25 = 111.994,50 (Dr 1-1404 / Cr 5-1000)
    db.rahaza_journal_entries.docs.append({"id": "JE1", "je_number": "JE-1", "status": "posted", "lines": [
        {"account_code": "1-1404", "debit": 111994.5, "credit": 0},
        {"account_code": "5-1000", "debit": 0, "credit": 111994.5}]})
    db.fg_cost_layers.docs.append({"id": "L1", "material_id": "M1", "qty_remaining": 2, "unit_cost": 55997.25})
    db.marketing_returns.docs.append({"id": "R1"})
    db.wh_returns.docs.append({
        "id": "W1", "return_code": "RET-1", "status": "Resolved", "action_taken": "Restock ke Gudang",
        "restocked": True, "restock_qty": 2, "restock_location_id": "LOC-FG", "restock_location_code": "GD-L1-RAK",
        "material_id": "M1", "qty": 3, "received_qty": 2, "cogs_je_id": "JE1", "hpp_layer_id": "L1",
        "source_marketing_return_id": "R1", "timeline": []})
    with pytest.raises(rb.ReturnBridgeError):
        run(rb.reverse_decision(db, "W1", reason=" "))                     # alasan wajib
    out = run(rb.reverse_decision(db, "W1", actor={"name": "gudang"}, reason="Marketing menolak"))
    assert issued == [("M1", "LOC-FG", 2, "wh_return_reversal")]
    rev = created[0]
    assert rev["source_module"] == "wh_return_reversal" and rev["source_ref"] == "whret_reverse:JE1"
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in rev["lines"]] == [
        ("1-1404", 0.0, 111994.5), ("5-1000", 111994.5, 0.0)]                # debit ⇄ kredit
    old = run(db.wh_returns.find_one({"id": "W1"}))
    assert old["status"] == "Reversed" and old["restocked"] is False and old["superseded_by"]
    new = out["reopened"]
    assert new["status"] == "Received" and new["received_qty"] == 2 and new["supersedes_wh_return_id"] == "W1"
    assert run(db.fg_cost_layers.find_one({"id": "L1"}))["qty_remaining"] == 0
    assert run(db.marketing_returns.find_one({"id": "R1"}))["wh_return_id"] == new["id"]
    # keputusan yang sudah dibalik tidak bisa dibalik dua kali; linked job = yang baru
    with pytest.raises(rb.ReturnBridgeError):
        run(rb.reverse_decision(db, "W1", reason="lagi"))
    assert run(rb.find_linked_wh(db, {"id": "R1", "wh_return_id": "W1"}))["id"] == new["id"]


def test_reverse_decision_refuses_when_stock_already_gone(db, monkeypatch):
    async def no_stock(*a, **k):
        raise ValueError("stok tinggal 0")
    monkeypatch.setattr(rb.stock_service, "issue", no_stock)
    db.wh_returns.docs.append({"id": "W1", "status": "Resolved", "restocked": True, "restock_qty": 2,
                               "restock_location_id": "L", "material_id": "M1", "timeline": []})
    with pytest.raises(rb.ReturnBridgeError) as e:
        run(rb.reverse_decision(db, "W1", reason="x"))
    assert "Stock Opname" in str(e.value)
    w = run(db.wh_returns.find_one({"id": "W1"}))
    assert w["status"] == "Resolved" and w["reversal_claimed"] is False      # klaim dilepas


def test_wh_routes_reject_qty_above_received_and_expose_reverse():
    src = open(os.path.join(BACKEND, "routes", "dewi_wh_returns.py"), encoding="utf-8").read()
    assert "_rb.decision_qty(doc, body.get(\"restock_qty\"))" in src
    assert "/returns/{return_id}/reverse-decision" in src and "received_qty" in src
    assert "_rb.ACTION_REJECT_TO_BUYER" in src


# ══════════════════════════════════════════════════════════════════════════════
# K36 — rekap hanya menghitung retur yang SUDAH diputuskan gudang
# ══════════════════════════════════════════════════════════════════════════════
def _r(rid, wh=None, action=None, status="pending", refund=100000.0):
    d = {"id": rid, "status": status, "refund_amount": refund, "qty": 1, "order_id": ""}
    if wh:
        d["wh_return_status"] = wh
    if action:
        d["wh_action_taken"] = action
    return d


def test_module_return_counted_only_after_warehouse_decision():
    assert mret.WH_NOT_COUNTED_ACTIONS == (rb.ACTION_REJECT_TO_BUYER,)
    assert mret.DECISION_FIELDS == ("wh_return_status", "wh_action_taken")
    cases = [(_r("p"), False), (_r("rcv", "Received"), False), (_r("ins", "Inspected"), False),
             (_r("ok", "Resolved", "Restock ke Gudang"), True),
             (_r("q", "Resolved", "Karantina (Rusak)"), True),
             (_r("buang", "Resolved", "Dibuang / Dispose"), True),
             (_r("tolak", "Resolved", rb.ACTION_REJECT_TO_BUYER), False),
             (_r("rev", "Reversed", "Restock ke Gudang"), False),
             (_r("can", "Cancelled"), False),
             (_r("mrej", "Resolved", "Restock ke Gudang", status="rejected"), False)]
    for ret, want in cases:
        assert mret.is_module_return_counted(ret) is want, ret["id"]
    rows = [c[0] for c in cases]
    kept = mret.select_uncovered_module_returns(rows, [])
    assert [r["id"] for r in kept] == ["ok", "q", "buang"]
    assert mret.split_module_returns(kept)["module_returns_value"] == 300000.0


def test_create_return_no_longer_refreshes_rekap_but_wh_decision_does():
    src = open(os.path.join(BACKEND, "routes", "marketing_returns_routes.py"), encoding="utf-8").read()
    body = src[src.index("async def create_return"):src.index("@router.put(")]
    assert "_refresh_rekap(" not in body
    wh = open(os.path.join(BACKEND, "routes", "dewi_wh_returns.py"), encoding="utf-8").read()
    for fn in ("async def resolve_return", "async def quick_restock", "async def reverse_decision"):
        seg = wh[wh.index(fn):]
        seg = seg[:seg.index("\n@router") if "\n@router" in seg else len(seg)]
        assert "_refresh_mkt_rekap(" in seg, fn


# ══════════════════════════════════════════════════════════════════════════════
# K3 — penarikan hanya dari pencairan yang SUDAH diposting (uji urutan)
# ══════════════════════════════════════════════════════════════════════════════
def test_withdrawal_sequence_requires_posted_settlement(db):
    from routes import marketing_withdrawals as mw
    acc = {"id": "T1", "account_code": "TTK-01", "account_name": "TikTok Daluna"}
    db.marketing_settlements.docs.append({"id": "S1", "account_id": "T1", "settlement_id": "TT-STMT-55",
                                          "settlement_date": "2026-10-20", "net_payout": 300000.0})
    # 1) pencairan belum dijurnal → saldo boleh tarik 0, saldo dokumen 300.000
    b = run(pb.withdrawable_balance(db, "T1"))
    assert (b["available"], b["document_available"], b["unposted_total"]) == (0.0, 300000.0, 300000.0)
    msg = mw.withdrawal_block_message(acc, 300000, b)
    assert msg and "Posting dulu pencairan toko ini" in msg and "TT-STMT-55 (belum dijurnal" in msg
    # 2) jurnal DRAF → tetap ditolak
    db.marketing_settlements.docs[0]["je_id"] = "JE-S1"
    db.rahaza_journal_entries.docs.append({"id": "JE-S1", "status": "draft"})
    b = run(pb.withdrawable_balance(db, "T1"))
    assert b["available"] == 0.0 and b["unposted"][0]["state"] == "draf"
    assert "Posting dulu" in mw.withdrawal_block_message(acc, 300000, b)
    # 3) jurnal POSTED → boleh 300.000
    db.rahaza_journal_entries.docs[0]["status"] = "posted"
    b = run(pb.withdrawable_balance(db, "T1"))
    assert b["available"] == 300000.0 and mw.withdrawal_block_message(acc, 300000, b) is None
    # 4) setelah penarikan 300.000 tercatat, Rp 1 berikutnya ditolak (pesan umum)
    db.marketing_platform_withdrawals.docs.append({"id": "W1", "account_id": "T1", "amount": 300000.0})
    b = run(pb.withdrawable_balance(db, "T1"))
    m = mw.withdrawal_block_message(acc, 1, b)
    assert b["available"] == 0.0 and m and "melebihi saldo" in m and "Posting dulu" not in m
    # jurnal/posting penarikan W1 sendiri tidak menghitung dirinya
    assert run(pb.withdrawable_balance(db, "T1", "W1"))["available"] == 300000.0
    # 5) pencairan di-VOID setelah penarikan → posting penarikan ditolak
    db.rahaza_journal_entries.docs[0]["status"] = "voided"
    b = run(pb.withdrawable_balance(db, "T1", "W1"))
    assert "Posting dulu" in mw.withdrawal_block_message(acc, 300000, b)


def test_withdrawal_journal_and_post_both_check_balance():
    src = open(os.path.join(BACKEND, "routes", "marketing_withdrawals.py"), encoding="utf-8").read()
    j = src[src.index("async def create_draft_journal"):src.index("async def post_withdrawal_journal")]
    p = src[src.index("async def post_withdrawal_journal"):]
    assert "await _check_balance(db, account, amt, exclude_id=wid, journal_stage=True)" in j
    assert "await _check_balance(db, _acc," in p and "journal_stage=True" in p


def test_journal_stage_blocks_only_unposted_dependency(db, monkeypatch):
    from routes import marketing_withdrawals as mw
    acc = {"id": "T1", "account_name": "TikTok"}
    # tanpa pencairan sama sekali (data lama): tahap jurnal tidak menolak, tahap catat menolak
    run(mw._check_balance(db, acc, 100, journal_stage=True))
    with pytest.raises(HTTPException):
        run(mw._check_balance(db, acc, 100))
    # pencairan 100 belum diposting: kedua tahap menolak dengan pesan K3
    db.marketing_settlements.docs.append({"id": "S1", "account_id": "T1", "settlement_id": "P1",
                                          "net_payout": 100.0})
    for stage in (True, False):
        with pytest.raises(HTTPException) as e:
            run(mw._check_balance(db, acc, 100, journal_stage=stage))
        assert "Posting dulu pencairan toko ini" in e.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# K4 — satu pintu rekening tujuan per toko
# ══════════════════════════════════════════════════════════════════════════════
def test_journal_uses_latest_store_link_unless_override():
    from routes import marketing_withdrawals as mw
    acc = {"coa_cash_code": "1-1102"}
    assert mw.journal_cash_code({"cash_code": "1-1101", "cash_code_source": "store_default"}, acc) == "1-1102"
    assert mw.journal_cash_code({"cash_code": "1-1101"}, acc) == "1-1102"             # data lama
    assert mw.journal_cash_code({"cash_code": "1-1105", "cash_code_source": "override"}, acc) == "1-1105"
    assert mw.cash_source_for("") == "store_default" and mw.cash_source_for(" 1-1105 ") == "override"


def test_account_api_rejects_cash_code_change():
    from routes import marketing_accounts as ma
    assert ma.cash_code_change_blocked("1-1201", "1-1101") is True
    assert ma.cash_code_change_blocked("1-1201", "1-1201") is False     # kirim ulang nilai sama → diabaikan
    assert ma.cash_code_change_blocked("1-1201", None) is False
    src = open(os.path.join(BACKEND, "routes", "marketing_accounts.py"), encoding="utf-8").read()
    upd = src[src.index("async def update_platform_account"):]
    assert 'for fname in ("coa_revenue_code", "coa_receivable_code"):' in upd


def test_set_store_cash_code_marks_source(db, monkeypatch):
    from core import payout_banks

    async def is_bank(db_, code):
        return code in ("1-1101", "1-1201")
    monkeypatch.setattr(payout_banks, "is_bank_code", is_bank)
    db.marketing_platform_accounts.docs.append({"id": "S1", "coa_cash_code": "1-1201", "coa_cash_source": "default"})
    res = run(fs.set_store_cash_code(db, {"id": "S1", "coa_cash_code": "1-1201"}, "1-1101",
                                     user={"email": "fin@x"}, source="excel_master"))
    s = run(db.marketing_platform_accounts.find_one({"id": "S1"}))
    assert res["code"] == "1-1101" and s["coa_cash_source"] == "excel_master" and s["coa_cash_updated_by"] == "fin@x"
    with pytest.raises(ValueError):
        run(fs.set_store_cash_code(db, {"id": "S1"}, "9-9999", source="finance"))
    mf = open(os.path.join(BACKEND, "core", "master_fill.py"), encoding="utf-8").read()
    assert 'set_store_cash_code(db, store, s["coa_cash_code"], user=user, source="excel_master")' in mf
    assert '{"$set": {"coa_cash_code": s["coa_cash_code"]' not in mf


def test_payout_bank_links_badge_for_default():
    src = open(os.path.join(REPO, "frontend", "src", "components", "erp", "finance", "PayoutBankLinks.jsx"),
               encoding="utf-8").read()
    assert "rekening bawaan {a.coa_cash_code} — belum diatur" in src and "cashIsConfirmed" in src


# ══════════════════════════════════════════════════════════════════════════════
# K5 — rekonsiliasi pencairan vs omzet
# ══════════════════════════════════════════════════════════════════════════════
def test_breakdown_gap_audit_example_return_not_pending_payout():
    from routes import marketing_settlements as ms
    # PCR-1003 (audit No.13): bruto 120.000, diskon penjual 12.001 → basis 107.999;
    # omzet setelah diskon 323.997 = IMP-A-3001 (RETUR) 215.998 + IMP-A-3002 107.999.
    out = ms.breakdown_gap(120000 - 12001, 323997, 215998, 0)
    assert out["gap"] == -215998.0
    assert out["components"] == {"retur_tidak_cair": 215998.0, "refund_parsial": 0.0,
                                 "belum_cair": 0.0, "cair_tanpa_pesanan": 0.0}
    assert [n["name"] for n in out["named"]] == ["retur_tidak_cair"]


def test_breakdown_gap_identity_partial_and_unpaid_and_excess():
    from routes import marketing_settlements as ms
    # omzet 500.000; retur 100.000; refund parsial 30.000; basis 300.000 → belum cair 70.000
    o = ms.breakdown_gap(300000, 500000, 100000, 30000)
    c = o["components"]
    assert c["belum_cair"] == 70000.0 and c["cair_tanpa_pesanan"] == 0.0
    assert 300000 == 500000 - c["retur_tidak_cair"] - c["refund_parsial"] - c["belum_cair"] + c["cair_tanpa_pesanan"]
    # basis 450.000 dengan omzet 400.000 → cair tanpa pesanan 50.000
    o2 = ms.breakdown_gap(450000, 400000, 0, 0)
    assert o2["components"]["cair_tanpa_pesanan"] == 50000.0 and o2["named"][-1]["name"] == "cair_tanpa_pesanan"
    assert ms.breakdown_gap(100, 100, 0, 0)["named"][0]["name"] == "cocok"


def test_reconcile_requires_period(monkeypatch):
    from routes import marketing_settlements as ms
    from core import marketing_account_scope as scope
    d = AggDB()
    d.marketing_settlements.docs.append({"id": "S1", "settlement_id": "PCR-1004", "account_id": "A1",
                                         "settlement_date": "2026-10-15"})

    async def user(req):
        return {"role": "admin"}

    async def vis(db_, u):
        return None
    monkeypatch.setattr(ms, "require_auth", user)
    monkeypatch.setattr(ms, "get_db", lambda: d)
    monkeypatch.setattr(scope, "visible_account_ids", vis)
    with pytest.raises(HTTPException) as e:
        run(ms.reconcile(fm.FakeRequest(), account_id="", date_from="", date_to="", settlement_id="S1"))
    assert e.value.status_code == 400 and "Periode pesanan" in e.value.detail
    with pytest.raises(HTTPException) as e2:
        run(ms.reconcile(fm.FakeRequest(), account_id="A1", date_from="2026-10-01", date_to="",
                         settlement_id=""))
    assert e2.value.status_code == 400 and "Periode wajib" in e2.value.detail


def test_manual_order_revenue_gross_uses_price_before_discount_and_no_reservation():
    from routes import marketing_orders_routes as mo
    assert mo.RESERVE_MANUAL_ORDERS is False
    assert "price_original" in mo.OrderItemBody.model_fields if hasattr(mo.OrderItemBody, "model_fields") \
        else "price_original" in mo.OrderItemBody.__fields__
    src = open(os.path.join(BACKEND, "routes", "marketing_orders_routes.py"), encoding="utf-8").read()
    assert "'price_original': round(max(_orig, _price), 2)," in src
    assert "if RESERVE_MANUAL_ORDERS and body.reserve_stock and _qty > 0:" in src


# ══════════════════════════════════════════════════════════════════════════════
# K6 — fulfillment, RTS, aksi Batal
# ══════════════════════════════════════════════════════════════════════════════
def test_fulfillment_queue_excludes_imported_orders():
    from routes import fulfillment as ff
    q = ff.queue_query()
    imp = {"id": "o1", "fulfillment_status": "pending_fulfillment", "_import_session_id": "sess-1"}
    imp_legacy = {"id": "o2", "fulfillment_status": "unallocated", "_import_session_id": "sess-2"}
    manual = {"id": "o3", "fulfillment_status": "pending_fulfillment", "_source_type": "manual_input"}
    assert [o["id"] for o in (imp, imp_legacy, manual) if fm.match(o, q)] == ["o3"]
    assert ff.is_imported_order(imp) and not ff.is_imported_order(manual)


def test_imported_orders_start_outside_fulfillment_queue():
    from core import fulfillment_status as fst
    from routes import marketing_data_import as mdi
    assert mdi.import_fulfillment_status({"status": "paid"})[0] == fst.NOT_REQUIRED
    assert mdi.import_fulfillment_status({"status": "new"})[0] == fst.NOT_REQUIRED
    assert mdi.import_fulfillment_status({"status": "cancelled"})[0] == fst.CANCELLED


def test_cancel_after_ship_creates_rts_jobs_idempotent(db):
    _mat(db)
    order = {"id": "O1", "order_id": "IMP-A-3002", "status": "completed", "platform": "shopee",
             "tracking_number": "SPX123", "account_id": "A1",
             "items": [{"fg_material_id": "M1", "quantity": 2, "product_name_raw": "Aisar"},
                       {"quantity": 1, "seller_sku": "SKU-ASING", "product_name_raw": "Lain"}]}
    db.marketing_orders.docs.append(dict(order))
    assert rb.was_shipped(order) and not rb.was_shipped({"status": "paid"})
    assert rb.was_shipped({"status": "paid", "shipped_date": "2026-10-16"})
    res = run(rb.ensure_rts_returns(db, order, reason="Gagal kirim"))
    assert len(res["created"]) == 2 and res["existing"] == []
    w1, w2 = db.wh_returns.docs
    assert (w1["status"], w1["return_type"], w1["rts"], w1["qty"], w1["link_status"]) == \
        ("Pending", "expedition_return", True, 2, rb.LINK_OK)
    assert w1["restocked"] is False and w1["resi_number"] == "SPX123"
    assert w2["link_status"] == rb.LINK_NONE and w2["material_id"] is None
    again = run(rb.ensure_rts_returns(db, order))
    assert again["created"] == [] and len(again["existing"]) == 2 and len(db.wh_returns.docs) == 2


def test_apply_status_cancel_after_ship_triggers_rts(db, monkeypatch):
    from core import order_status as os_
    from core import marketing_daily_rollup as rollup

    async def noop(*a, **k):
        return {}
    monkeypatch.setattr(rollup, "recompute_for_orders", noop)
    _mat(db)
    db.marketing_orders.docs += [
        {"id": "O1", "order_id": "X-1", "status": "shipped", "account_id": "A1",
         "items": [{"fg_material_id": "M1", "quantity": 1}]},
        {"id": "O2", "order_id": "X-2", "status": "paid", "account_id": "A1",
         "items": [{"fg_material_id": "M1", "quantity": 1}]}]
    r1 = run(os_.apply_status(db, "O1", "cancelled", note="paket ditolak"))
    r2 = run(os_.apply_status(db, "O2", "cancelled", note="batal sebelum kirim"))
    assert r1["rts"] and len(r1["rts"]["created"]) == 1
    assert r2["rts"] is None and len(db.wh_returns.docs) == 1


def test_bulk_cancel_shipped_requires_reason():
    from routes import marketing_orders_routes as mo
    shipped = {"order_id": "X-1", "status": "delivered"}
    assert "wajib disertai alasan" in mo.cancel_after_ship_block(shipped, "cancelled", None)
    assert mo.cancel_after_ship_block(shipped, "cancelled", "  ") is not None
    assert mo.cancel_after_ship_block(shipped, "cancelled", "gagal kirim") is None
    assert mo.cancel_after_ship_block({"status": "new"}, "cancelled", None) is None
    assert mo.cancel_after_ship_block(shipped, "returned", None) is None


def test_portal_nav_hides_fulfillment_and_picklist():
    nav = open(os.path.join(REPO, "frontend", "src", "components", "erp", "portal-shell", "portalNav.js"),
               encoding="utf-8").read()
    assert not re.search(r"id:\s*'fulfillment'", nav) and not re.search(r"id:\s*'wh-picklist'", nav)
    assert re.search(r"id:\s*'wh-returns'", nav)


# ══════════════════════════════════════════════════════════════════════════════
# K35 — penomoran akun pendapatan toko = konfigurasi Auto Akun
# ══════════════════════════════════════════════════════════════════════════════
def _coa_db(fmt=None, extra_codes=()):
    d = AggDB()
    d.rahaza_coa_accounts.docs += [
        {"code": "4-1110", "name": "Penjualan Online Shop – Shopee", "type": "REVENUE", "is_group": True,
         "active": True},
        *[{"code": f"4-111{n}", "name": f"Penjualan – Shopee T{n}", "type": "REVENUE", "is_group": False,
           "active": True, "parent_code": "4-1110"} for n in range(1, 8)],
        *[{"code": c, "name": f"Penjualan – {c}", "type": "REVENUE", "is_group": False, "active": True,
           "parent_code": "4-1110"} for c in extra_codes],
    ]
    if fmt:
        d.rahaza_coa_auto_settings.docs.append({"id": "default", "entity_types": {
            "store_revenue": {"enabled": True, "code_format": fmt, "parent_by_platform": {}}}})
    return d


def test_default_format_keeps_legacy_numbering_and_capacity():
    d = _coa_db()
    r = run(fs.ensure_store_revenue_account(d, {"account_code": "SHP-99", "account_name": "Uji 99",
                                                "platform": "shopee"}, used=set()))
    assert r == {"code": "4-1118", "created": True}
    d2 = _coa_db(extra_codes=("4-1118", "4-1119"))
    with pytest.raises(ValueError) as e:
        run(fs.ensure_store_revenue_account(d2, {"account_code": "SHP-98", "account_name": "Uji 98",
                                                 "platform": "shopee"}, used=set()))
    assert "Auto Akun" in str(e.value)


def test_configured_format_allows_more_than_nine_per_group():
    d = _coa_db("{parent}-{seq:02d}", extra_codes=("4-1118", "4-1119"))
    a = run(fs.ensure_store_revenue_account(d, {"account_code": "SHP-10", "account_name": "Uji 10",
                                                "platform": "shopee"}, used=set()))
    b = run(fs.ensure_store_revenue_account(d, {"account_code": "SHP-11", "account_name": "Uji 11",
                                                "platform": "shopee"}, used=set()))
    assert (a["code"], b["code"]) == ("4-1110-01", "4-1110-02")
    acc = run(d.rahaza_coa_accounts.find_one({"code": "4-1110-02"}))
    assert acc["parent_code"] == "4-1110" and acc["code_format"] == "{parent}-{seq:02d}"
    # toko lama tidak diubah: kode lama tetap dikenali sebagai akun pendapatan toko
    accs = run(fs._store_revenue_accounts(d))
    assert {"4-1111", "4-1119", "4-1110-01", "4-1110-02"} <= set(accs)
    d3 = _coa_db("{parent}-{store_code}")
    c = run(fs.ensure_store_revenue_account(d3, {"account_code": "shp-09", "account_name": "Uji 9",
                                                 "platform": "shopee"}, used=set()))
    assert c["code"] == "4-1110-SHP-09"


def test_code_format_validation_and_settings_patch(monkeypatch):
    for good in fs.STORE_REVENUE_FORMATS:
        assert fs.validate_code_format(good) == good
    for bad in ("", "{parent}", "{seq}", "{parent}-{seq}-{store_code}", "{parent}-{x}", "{parent}_{seq}"):
        with pytest.raises(ValueError):
            fs.validate_code_format(bad)
    assert fs.seq_capacity("{prefix}{seq}") == 9 and fs.seq_capacity("{parent}-{seq:02d}") == 99
    from routes import coa_auto as ca
    assert ca.DEFAULT_ENTITY_TYPES["store_revenue"]["collection"] == ""          # backfill subledger melewatinya
    d = _coa_db()
    d.rahaza_coa_accounts.docs.append({"code": "1-1201", "type": "ASSET", "name": "BCA"})
    out = run(ca._patch_store_revenue(d, {"code_format": "{prefix}{seq}"},
                                      {"code_format": "{parent}-{seq:03d}", "parent_by_platform": {"Shopee": "4-1110"}}))
    assert out["code_format"] == "{parent}-{seq:03d}" and out["parent_by_platform"]["shopee"] == "4-1110"
    with pytest.raises(HTTPException):
        run(ca._patch_store_revenue(d, {}, {"code_format": "{seq}"}))
    with pytest.raises(HTTPException):
        run(ca._patch_store_revenue(d, {}, {"parent_by_platform": {"shopee": "1-1201"}}))


# ══════════════════════════════════════════════════════════════════════════════
# Butir 11 — impor "Retur & Refund": nominal refund aktual dari berkas
# ══════════════════════════════════════════════════════════════════════════════
def test_import_refund_amount_uses_file_value_first():
    from routes import marketing_data_import as mdi
    f = mdi.import_refund_amount
    assert f({"refund_amount": 95000, "refund_type": "full_refund", "price": 107999, "quantity": 3}) == \
        (95000.0, "berkas", "")
    assert f({"refund_amount": 0, "refund_type": "full_refund", "price": 107999})[:2] == (0.0, "berkas")
    assert f({"refund_type": "full_refund", "price": 107999, "quantity": 3})[:2] == (323997.0, "harga_x_qty")
    amt, src, warn = f({"refund_type": "partial_refund", "price": 107999, "quantity": 1})
    assert (amt, src) == (0.0, "belum_diisi") and "70%" in warn
    assert f({"refund_type": "replacement", "price": 1})[:2] == (0.0, "tanpa_refund")


def test_returns_import_bridges_pending_and_refreshes_rekap(db, monkeypatch):
    from routes import marketing_data_import as mdi
    calls = []

    async def fake_refresh(db_, *docs, actor="system"):
        calls.append(len(docs))
        return {"pairs": len(docs)}
    monkeypatch.setattr(mret, "refresh_rekap_for_docs", fake_refresh)
    db.marketing_returns.docs += [
        {"id": "IR1", "_import_session_id": "S", "status": "pending", "account_id": "A1", "date": "2026-10-21",
         "quantity": 3, "qty": 3, "product": "Aisar"},
        {"id": "IR2", "_import_session_id": "S", "status": "rejected", "account_id": "A1", "date": "2026-10-21"}]
    out = run(mdi._after_returns_import(db, "S", {"email": "uji@x"}))
    assert out["wh_created"] == 1 and calls == [2]
    assert db.wh_returns.docs[0]["status"] == "Pending" and db.wh_returns.docs[0]["qty"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# K7 / K8 — skrip (dry-run bawaan)
# ══════════════════════════════════════════════════════════════════════════════
def test_cleanup_demo_plan_selects_only_strict_demo(tmp_path):
    import cleanup_demo_data as cd
    d = AggDB()
    d.marketing_returns.docs += [
        {"id": "dr", "created_by": "system", "reason_detail": "Warna berbeda dari foto", "product": "Outer Cardigan"},
        {"id": "real", "created_by": "cs@da.id", "reason_detail": "Warna berbeda dari foto"},
        {"id": "ragu", "created_by": "system", "reason_detail": "teks lain"}]
    d.marketing_complaints.docs += [{"id": "c1", "_import_session_id": "seed-demo"},
                                    {"id": "c2", "_import_session_id": "sesi-nyata"}]
    d.marketing_samples.docs += [{"id": "s1", "_seed_origin": True, "created_by": "system"}, {"id": "s2"}]
    d.marketing_account_health.docs += [{"id": "h1", "notes": []}, {"id": "h2", "source": "manual", "notes": []}]
    d.marketing_catalog_items.docs += [
        {"id": "ci-demo", "_seed_origin": True, "source": "seed_demo", "created_by": "system"},
        {"id": "ci-ref", "_seed_origin": True, "source": "seed_demo", "created_by": "system"},
        {"id": "ci-real", "source": "master_import"}]
    d.marketing_reviews.docs.append({"id": "rv", "catalog_item_id": "ci-ref", "created_by": "u@x"})
    d.wh_returns.docs.append({"id": "w-dr", "status": "Pending", "source_marketing_return_id": "dr"})
    d.rahaza_coa_accounts.docs += [{"code": "1-1303-GATE42-1"}, {"code": "1-1303-GATE42-2"}, {"code": "1-1303-SHP-01"}]
    d.rahaza_journal_lines.docs.append({"account_code": "1-1303-GATE42-2", "debit": 1})
    p = run(cd.plan(d))
    ids = {k: [x["id"] for x in v["docs"]] for k, v in p["collections"].items()}
    assert ids["marketing_returns"] == ["dr"] and p["collections"]["marketing_returns"]["ragu"] == 1
    assert ids["marketing_complaints"] == ["c1"] and ids["marketing_samples"] == ["s1"]
    assert ids["marketing_account_health"] == ["h1"] and ids["marketing_catalog_items"] == ["ci-demo"]
    assert [a["code"] for a in p["coa"]["docs"]] == ["1-1303-GATE42-1"]
    assert [w["id"] for w in p["wh_returns"]["docs"]] == ["w-dr"]
    # backup ditulis sebelum hapus; apply hanya menghapus yang direncanakan
    files = cd.write_backup(p, tmp_path / "bk")
    assert (tmp_path / "bk" / "MANIFEST.json").exists() and files["marketing_returns"]["count"] == 1
    res = run(cd.apply(d, p))
    assert res["marketing_returns"] == 1 and [r["id"] for r in d.marketing_returns.docs] == ["real", "ragu"]
    assert [a["code"] for a in d.rahaza_coa_accounts.docs] == ["1-1303-GATE42-2", "1-1303-SHP-01"]
    src = open(os.path.join(REPO, "scripts", "cleanup_demo_data.py"), encoding="utf-8").read()
    assert '"--terapkan", action="store_true"' in src
    assert src.index("files = write_backup(p, out_dir)\n        print(f\"  BACKUP") < src.index("res = await apply(db, p)")


def test_match_catalog_classify():
    import match_catalog_sku as mc
    cat = [{"id": "CAT1"}]
    mat = {"id": "M1", "code": "DA-2101-MHG-ALLSIZE", "type": "fg"}
    item = {"id": "I1", "account_id": "A1", "fg_material_id": "M1", "sku": "da-2101-mhg-allsize"}
    assert mc.classify(item, cat, mat, None, set())[:2] == (mc.COCOK, "CAT1")
    assert mc.classify(item, cat, mat, None, {"DA-2101-MHG-ALLSIZE"})[0] == mc.RAGU          # duplikat
    assert mc.classify({**item, "sku": "LAIN"}, cat, mat, None, set())[0] == mc.RAGU
    assert mc.classify(item, cat + [{"id": "CAT2"}], mat, None, set())[0] == mc.RAGU
    assert mc.classify(item, [], mat, None, set())[0] == mc.TIDAK
    assert mc.classify({**item, "fg_material_id": None}, cat, None, None, set())[0] == mc.TIDAK
    assert mc.classify(item, cat, None, None, set())[0] == mc.TIDAK
    assert mc.classify({**item, "sku": "VAR-1"}, cat, mat, {"sku": "VAR-1"}, set())[0] == mc.COCOK


def test_match_catalog_run_dry_vs_apply(tmp_path):
    import match_catalog_sku as mc
    d = AggDB()
    d.marketing_catalogs.docs.append({"id": "CAT1", "account_id": "A1"})
    d.rahaza_materials.docs += [{"id": "M1", "code": "SKU-1", "type": "fg"}, {"id": "M2", "code": "SKU-2", "type": "fg"}]
    d.marketing_catalog_items.docs += [
        {"id": "I1", "account_id": "A1", "fg_material_id": "M1", "sku": "SKU-1", "catalog_id": None},
        {"id": "I2", "account_id": "A1", "fg_material_id": "M2", "sku": "SALAH"},
        {"id": "I3", "account_id": "A9", "fg_material_id": "M1", "sku": "SKU-1"}]
    r = run(mc.run(d, apply=False, csv_path=tmp_path / "k8.csv"))
    assert r["counts"] == {"cocok": 1, "ragu": 1, "tidak_cocok": 1} and r["applied"] == 0
    assert all(i.get("catalog_id") in (None,) for i in d.marketing_catalog_items.docs)
    assert (tmp_path / "k8.csv").read_text(encoding="utf-8").count("\n") == 4
    r2 = run(mc.run(d, apply=True, csv_path=tmp_path / "k8b.csv"))
    assert r2["applied"] == 1
    assert run(d.marketing_catalog_items.find_one({"id": "I1"}))["catalog_id"] == "CAT1"
    assert run(d.marketing_catalog_items.find_one({"id": "I2"})).get("catalog_id") is None


def test_release_manual_reservation_script_query_and_default_dry_run():
    import release_manual_order_reservations as rm
    q = rm.manual_holding_query()
    hold = {"_source_type": "manual_input", "status": "delivered", "stock_reserved": True}
    cancelled = {"_source_type": "manual_input", "status": "cancelled", "stock_reserved": True}
    imported = {"_import_session_id": "x", "status": "paid", "stock_reserved": True}
    assert fm.match(hold, q) and not fm.match(cancelled, q) and not fm.match(imported, q)
    src = open(os.path.join(REPO, "scripts", "release_manual_order_reservations.py"), encoding="utf-8").read()
    assert "_os.release_reservations(db, o, reason=REASON)" in src and '"--terapkan"' in src
