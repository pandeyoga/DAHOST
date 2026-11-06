"""core.po_wip — SISA WIP per PO produksi (aktual vs standar) + penutupannya. 2026-11-06 (Tahap 2).

KENAPA
------
WIP 1-1403 DIDEBIT bahan yang benar-benar keluar (MI × biaya saat keluar, aksesoris, upah CMT
PO internal), tetapi DIKREDIT lapisan FG saat Terima FG = BOM standar × harga HARI ITU + upah SPK.
Selisihnya (pemakaian kain lebih/kurang dari BOM, harga berubah, retur) tidak pernah ditutup —
di data lokal WIP berakhir −3,4 juta tanpa satu pun PO yang bisa ditunjuk.

YANG DILAKUKAN
--------------
* :func:`po_wip_position` — saldo WIP satu PO dari BUKU BESAR, dikelompokkan per sumber. Jurnal
  tidak menyimpan nomor PO, jadi jurnalnya DITELUSURI dari dokumen sumber yang menunjuk PO:
  MI (PO/job) · Retur Material (MI-nya) · pemakaian aksesoris (permintaan ber-PO) · tagihan CMT ·
  lapisan FG / Terima FG (WIP→FG + koreksi) · WIP→FG job · selisih yang sudah ditutup.
* :func:`clear_po_wip` — sisa itu dipindah ke akun selisih produksi (profil posting
  `production_po_wip_variance`, bawaan 5-1960 Selisih Produksi): sisa > 0 ⇒ Dr selisih / Cr WIP,
  sisa < 0 ⇒ Dr WIP / Cr selisih. Dipanggil saat PO ditutup (:func:`on_po_closed`) dan bisa
  dijalankan Keuangan dari layar untuk PO yang sudah tertutup. Idempoten: sisa 0 ⇒ tidak ada jurnal;
  jurnal susulan memakai nomor urut (`po_wip_var:<po>:<n>`).
Hanya PO INTERNAL (bahan maklon milik klien; aksesoris DA untuk maklon dibebankan ke 5-4100).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROFILE = "production_po_wip_variance"
SOURCE_MODULE = "po_wip_variance"
CLOSED_STATUSES = ("Closed", "Closed Short", "Completed")

# kelompok sumber (label tampil)
SRC_LABEL = {
    "material_issue": "Bahan keluar (Material Issue)",
    "material_return": "Retur material",
    "accessory_issue": "Pemakaian aksesoris",
    "cmt_bill": "Upah CMT (tagihan)",
    "fg_receipt": "Pindah ke barang jadi (Terima FG)",
    "job_complete": "Pindah ke barang jadi (job selesai)",
    "variance": "Selisih yang sudah ditutup",
}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def summarize_wip_lines(lines: list, je_source: dict) -> dict:
    """Ringkas baris jurnal akun WIP (fungsi murni). `je_source` = {je_id: kelompok}."""
    by: dict = {}
    for ln in lines or []:
        k = je_source.get(ln.get("je_id"), "lainnya")
        slot = by.setdefault(k, {"debit": 0.0, "credit": 0.0})
        slot["debit"] += _f(ln.get("debit"))
        slot["credit"] += _f(ln.get("credit"))
    groups = [{"source": k, "label": SRC_LABEL.get(k, k), "debit": round(v["debit"], 2),
               "credit": round(v["credit"], 2), "net": round(v["debit"] - v["credit"], 2)}
              for k, v in sorted(by.items())]
    residual = round(sum(g["net"] for g in groups), 2)
    return {"groups": groups, "residual": residual}


def variance_lines(residual: float, variance_code: str, wip_code: str, memo: str) -> list:
    """Baris jurnal penutup sisa WIP (fungsi murni)."""
    amt = round(abs(_f(residual)), 2)
    if amt < 0.01:
        return []
    if residual > 0:      # aktual > standar: WIP masih bersaldo debit → bebankan
        return [{"account_code": variance_code, "debit": amt, "credit": 0, "description": memo},
                {"account_code": wip_code, "debit": 0, "credit": amt, "description": memo}]
    return [{"account_code": wip_code, "debit": amt, "credit": 0, "description": memo},
            {"account_code": variance_code, "debit": 0, "credit": amt, "description": memo}]


async def _mapping(db) -> dict:
    from routes.rahaza_posting_profiles import get_mapping
    return await get_mapping(db, PROFILE)


async def _je_sources(db, po_id: str) -> dict:
    """{je_id: kelompok} — jurnal yang menyentuh WIP untuk PO ini, ditelusuri dari dokumen sumber."""
    out: dict = {}
    jobs = [j["id"] async for j in db.production_jobs.find({"po_id": po_id}, {"_id": 0, "id": 1})]
    mi_q = {"$or": [{"production_po_id": po_id}] + ([{"job_id": {"$in": jobs}}] if jobs else [])}
    mi_ids = [m["id"] async for m in db.rahaza_material_issues.find(mi_q, {"_id": 0, "id": 1})]
    ret_ids = [r["id"] async for r in db.production_material_returns.find(
        {"material_issue_id": {"$in": mi_ids}}, {"_id": 0, "id": 1})] if mi_ids else []
    req_ids = [r["id"] async for r in db.dewi_accessory_requests.find({"po_id": po_id}, {"_id": 0, "id": 1})]
    mv_ids = [m["id"] async for m in db.rahaza_material_movements.find(
        {"reference_type": "accessory_request", "reference_id": {"$in": req_ids}},
        {"_id": 0, "id": 1})] if req_ids else []
    refs = ([(f"mi:{i}", "material_issue") for i in mi_ids] + [(f"pmr:{i}", "material_return") for i in ret_ids]
            + [(f"accmv:{i}", "accessory_issue") for i in mv_ids]
            + [(f"wip_fg_job:{j}", "job_complete") for j in jobs])
    kind_by_ref = dict(refs)
    if refs:
        async for je in db.rahaza_journal_entries.find(
                {"source_ref": {"$in": list(kind_by_ref)}, "status": "posted"},
                {"_id": 0, "id": 1, "source_ref": 1}):
            out[je["id"]] = kind_by_ref.get(je.get("source_ref"), "lainnya")
    # jurnal yang id-nya disimpan dokumen sumber
    async for ly in db.fg_cost_layers.find({"batch.po_id": po_id, "gl_je_id": {"$nin": [None, ""]}},
                                           {"_id": 0, "gl_je_id": 1}):
        out.setdefault(ly["gl_je_id"], "fg_receipt")
    async for rc in db.cmt_receipts.find({"po_id": po_id}, {"_id": 0, "wip_fg_je_id": 1, "wip_fg_extra_jes": 1}):
        for jid in [rc.get("wip_fg_je_id")] + [x.get("je_id") for x in (rc.get("wip_fg_extra_jes") or [])]:
            if jid:
                out.setdefault(jid, "fg_receipt")
    async for p in db.dewi_cmt_payments.find({"po_id": po_id, "gl_je_id": {"$nin": [None, ""]}},
                                             {"_id": 0, "gl_je_id": 1}):
        out.setdefault(p["gl_je_id"], "cmt_bill")
    async for je in db.rahaza_journal_entries.find(
            {"source_module": SOURCE_MODULE, "source_ref": {"$regex": f"^po_wip_var:{po_id}:"}, "status": "posted"},
            {"_id": 0, "id": 1}):
        out[je["id"]] = "variance"
    return out


async def po_wip_position(db, po_id: str) -> dict:
    """Saldo WIP satu PO per kelompok sumber + sisa yang belum ditutup."""
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0}) or {}
    if not po:
        return {"ok": False, "error": "PO produksi tidak ditemukan."}
    mapping = await _mapping(db)
    wip_code = mapping.get("credit_wip")
    bt = po.get("business_type") or ("internal" if not po.get("vendor_id") else "maklon")
    out = {"ok": True, "po_id": po_id, "po_number": po.get("po_number"), "status": po.get("status"),
           "business_type": bt, "wip_account": wip_code, "groups": [], "residual": 0.0,
           "closed": po.get("status") in CLOSED_STATUSES,
           "variance_account": mapping.get("debit_variance")}
    if not wip_code:
        out["error"] = f"Pemetaan akun '{PROFILE}' belum lengkap (akun WIP)."
        return out
    sources = await _je_sources(db, po_id)
    lines = await db.rahaza_journal_lines.find(
        {"je_id": {"$in": list(sources)}, "account_code": wip_code},
        {"_id": 0, "je_id": 1, "debit": 1, "credit": 1}).to_list(20000) if sources else []
    out.update(summarize_wip_lines(lines, sources))
    out["journal_count"] = len(sources)
    return out


async def clear_po_wip(db, po_id: str, user: dict, *, reason: str = "") -> dict:
    """Pindahkan sisa WIP PO ke akun selisih produksi (lihat docstring modul)."""
    pos = await po_wip_position(db, po_id)
    if not pos.get("ok") or pos.get("error"):
        return {**pos, "ok": False, "posted": False}
    if pos["business_type"] != "internal":
        return {**pos, "ok": True, "posted": False,
                "note": "PO maklon: bahan milik klien — tidak ada WIP DA yang ditutup."}
    if abs(pos["residual"]) < 0.01:
        return {**pos, "ok": True, "posted": False, "note": "Sisa WIP PO ini sudah 0."}
    from routes.rahaza_posting import post_po_wip_variance
    seq = 1 + await db.rahaza_journal_entries.count_documents(
        {"source_module": SOURCE_MODULE, "source_ref": {"$regex": f"^po_wip_var:{po_id}:"}})
    res = await post_po_wip_variance(db, po={"id": po_id, "po_number": pos.get("po_number")},
                                     residual=pos["residual"], seq=seq, user=user, reason=reason)
    if res.get("ok") and not res.get("already_posted"):
        await db.production_pos.update_one({"id": po_id}, {"$push": {"wip_variance_jes": {
            "je_id": res.get("je_id"), "je_number": res.get("je_number"), "amount": pos["residual"],
            "seq": seq, "reason": reason, "by": (user or {}).get("name") or "system"}}})
    return {**pos, "ok": bool(res.get("ok")), "posted": bool(res.get("ok")), "posting": res}


async def on_po_closed(db, po: dict, user: dict) -> dict:
    """Kait penutupan PO: tutup sisa WIP. Tidak pernah menggagalkan penutupan PO."""
    try:
        return await clear_po_wip(db, (po or {}).get("id"), user, reason="PO ditutup")
    except Exception as e:  # noqa: BLE001
        log.exception("penutupan sisa WIP PO %s gagal", (po or {}).get("po_number"))
        return {"ok": False, "posted": False, "error": str(e)}


async def open_residuals(db, *, limit: int = 100) -> list:
    """PO internal TERTUTUP yang masih punya sisa WIP (untuk layar Keuangan)."""
    out = []
    async for po in db.production_pos.find(
            {"status": {"$in": list(CLOSED_STATUSES)},
             "$or": [{"business_type": "internal"}, {"business_type": {"$exists": False}}]},
            {"_id": 0, "id": 1}).sort("closed_at", -1).limit(limit):
        pos = await po_wip_position(db, po["id"])
        if pos.get("ok") and abs(pos.get("residual") or 0) >= 0.01:
            out.append(pos)
    return out
