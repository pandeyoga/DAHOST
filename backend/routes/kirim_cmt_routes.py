"""Kirim ke CMT — API Tahap 9 (7 Nov 2026). Didaftarkan pada router `routes.vendor_shipment` (prefix /api).

  POST /api/kirim-cmt/preview                         hitungan kiriman (pratinjau = yang disimpan = yang dicetak)
  GET  /api/kirim-cmt/shipments/{sid}                 isi kiriman: potongan, aksesoris (satuan serah), dokumen keluar
  POST /api/kirim-cmt/shipments/{sid}/repost-journal  posting ulang jurnal pengeluaran (pindahan dari Pengeluaran Material)
  POST /api/kirim-cmt/shipments/{sid}/nota-aksesoris  buat nota aksesoris kiriman tersimpan (core.nota_aksesoris_cmt)
  GET  /api/kirim-cmt/nota-aksesoris                  daftar nota aksesoris (vendor CMT: hanya miliknya; ?dari&sampai)
  GET  /api/kirim-cmt/nota-aksesoris-berlaku          apakah vendor ini dibuatkan nota (CMT luar)
  GET  /api/kirim-cmt/nota-aksesoris-rekap[/pdf]      rekap gabungan nota satu CMT per periode
  GET  /api/kirim-cmt/nota-aksesoris/{nid}/pdf        cetak nota aksesoris
  POST /api/kirim-cmt/nota-aksesoris/{nid}/potong     potong sisa nota dari tagihan jahit CMT yang terbuka
  POST /api/kirim-cmt/nota-aksesoris/{nid}/batal      batalkan nota yang belum dibayar/dipotong (jurnal dibalik)
  GET  /api/kirim-cmt/requests                        tab "Permintaan tambahan" (vendor + staf), saring per portal
  GET  /api/kirim-cmt/requests/{src}/{rid}            rincian + pratinjau kiriman tambahan
  POST /api/kirim-cmt/requests                        input staf (dulu "Komponen Kurang")
  POST /api/kirim-cmt/requests/{src}/{rid}/approve    setujui → kiriman tambahan yang mengurangi stok
  POST /api/kirim-cmt/requests/{src}/{rid}/reject     tolak (alasan wajib)
  POST /api/kirim-cmt/accessory-plan/preview          rencana aksesoris di form PO (BOM → satuan serah)
  GET  /api/kirim-cmt/po/{po_id}/accessory-plan       rencana aksesoris PO tersimpan
  PUT  /api/kirim-cmt/po/{po_id}/accessory-plan       simpan rencana (rencana serah baris BOM + baris tambahan)
"""
from fastapi import HTTPException, Request

from auth import log_activity, require_auth, serialize_doc
from core import kirim_cmt
from core import kirim_permintaan as kp
from core import satuan_serah as ss
from core.cmt_override import resolve_override
from database import get_db
from core.authz import pesan_centang, wajib_centang
from routes.production_rbac import assert_prod_admin, PROD_ADMIN_ROLES, deny_klien, is_vendor, vendor_identity
from routes.vendor_shipment import router

FIN_REPOST_ROLES = PROD_ADMIN_ROLES + ['accounting', 'staff_keuangan', 'manager_keuangan', 'admin_gudang']


def _clean(calc: dict) -> dict:
    out = dict(calc)
    out["aksesoris"] = [{k: v for k, v in a.items() if not k.startswith("_")} for a in calc.get("aksesoris") or []]
    return serialize_doc(out)


async def _po_bt_ok(db, po: dict | None, business_type: str | None) -> None:
    if not po or not business_type:
        return
    bt = (po.get("business_type") or "internal")
    if business_type == "internal" and bt != "internal":
        raise HTTPException(400, "PO ini PO maklon — buka dari Portal Maklon.")
    if business_type == "maklon" and bt == "internal":
        raise HTTPException(400, "PO ini PO internal — buka dari Portal Produksi.")


# ── 1. Pratinjau kiriman ─────────────────────────────────────────────────────────────────────────────────────────
@router.post("/kirim-cmt/preview")
async def kirim_preview(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    body = await request.json()
    po_id = body.get("po_id") or next((i.get("po_id") for i in body.get("items") or [] if i.get("po_id")), "")
    if not po_id:
        raise HTTPException(400, "po_id wajib diisi")
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0, "business_type": 1})
    stype = (body.get("shipment_type") or "NORMAL").upper()
    if po and po.get("business_type") == "maklon" and stype == "NORMAL" and body.get("refresh_bom", True):
        try:   # BOM Katalog Buyer terbaru ikut (perilaku pratinjau aksesoris 2026-11-05)
            from routes.dewi_maklon_bom_templates import explode_maklon_bom_for_po
            await explode_maklon_bom_for_po(db, po_id, user=user)
        except Exception:  # noqa: BLE001 — pratinjau tetap jalan dengan BOM terakhir
            pass
    lines = [{"po_item_id": i.get("po_item_id"), "qty": i.get("qty_sent", i.get("qty"))} for i in body.get("items") or []]
    calc = await kirim_cmt.compute(db, po_id=po_id, lines=lines, accessory_input=body.get("accessory_items"),
                                   materials=body.get("materials"), mode="normal" if stype == "NORMAL" else "tambahan")
    out = _clean(calc)
    if body.get("vendor_id"):      # 2026-11-11: apakah aksesoris kiriman ini dibuatkan nota (CMT luar)?
        from core import nota_aksesoris_cmt as nac
        b = await nac.berlaku(db, vendor_id=body["vendor_id"])
        out["nota_aksesoris"] = {"berlaku": b["berlaku"], "alasan": b["alasan"], "cara_bayar": nac.CARA_BAYAR,
                                 "cara_bawaan": nac.CARA_BAWAAN}
    return out


# ── 2. Isi kiriman & posting ulang jurnal ───────────────────────────────────────────────────────────────────────
@router.get("/kirim-cmt/shipments/{sid}")
async def kirim_shipment_detail(sid: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    ship = await db.vendor_shipments.find_one({"id": sid}, {"_id": 0})
    if not ship:
        raise HTTPException(404, "Kiriman tidak ditemukan")
    ov = await resolve_override(request, user, db)
    if is_vendor(user) and ship.get("vendor_id") != vendor_identity(user):
        raise HTTPException(403, "Pengiriman ini bukan milik vendor Anda")
    if ov and ship.get("vendor_id") != ov["vendor_id"]:
        raise HTTPException(403, f"Pengiriman ini bukan milik {ov['vendor_name']}")
    items = await db.vendor_shipment_items.find({"shipment_id": sid}, {"_id": 0}).to_list(500)
    children = await db.vendor_shipments.find({"parent_shipment_id": sid}, {"_id": 0}).to_list(100)
    for c in children:
        c["total_pcs"] = sum(int(i.get("qty_sent") or 0) for i in await db.vendor_shipment_items.find(
            {"shipment_id": c["id"]}, {"_id": 0, "qty_sent": 1}).to_list(500))
    lines = await kirim_cmt.shipment_lines(db, ship)
    req = None
    if ship.get("material_request_id"):
        req = await db.material_requests.find_one({"id": ship["material_request_id"]},
                                                  {"_id": 0, "request_number": 1, "request_type": 1, "reason": 1})
    po = await db.production_pos.find_one({"id": ship.get("po_id")}, {"_id": 0}) if ship.get("po_id") else None
    return serialize_doc({"shipment": ship, "items": items, "children": children, **lines,
                          "request": req, "sample_warning": await kirim_cmt.sample_warning(db, po),
                          "allowed_next": ["Received"] if ship.get("status") == "Sent" else [],
                          "nota_aksesoris": await _nota_kiriman_info(db, ship, lines)})


# ── 2b. Nota aksesoris ke CMT (permintaan owner 10–11 Nov 2026, `core.nota_aksesoris_cmt`) ────────────────────────
def _boleh_kelola_nota(user: dict) -> bool:
    """Centang aksi endpoint (potong nota = Tagihan CMT › Setujui, batal = Kirim ke CMT › Setujui) atau izin Keuangan.

    14 Nov 2026: daftar peran lama (admin produksi/maklon, keuangan) hanya berlaku selama owner belum mengatur
    centang peran itu — dulu daftar itu menolak peran yang sudah dicentang."""
    from core.authz import boleh_centang
    from core.roles import FINANCE_ROLES
    return boleh_centang(user, "finance.manage", peran_lama=FIN_REPOST_ROLES + list(FINANCE_ROLES))


async def _nota_kiriman_info(db, ship: dict, lines: dict) -> dict:
    """Nota kiriman ini (bila ada) + bisa/tidaknya dibuat dari rincian (kiriman lama, tambahan, atau terlewat)."""
    from core import nota_aksesoris_cmt as nac
    doc = await nac.nota_kiriman(db, ship["id"])
    b = await nac.berlaku(db, vendor_id=ship.get("vendor_id"), shipment=ship)
    baris = nac.baris_kiriman(lines.get("aksesoris") or [])
    return {"nota": nac.ringkas(doc), "berlaku": b["berlaku"], "alasan": b["alasan"],
            "status_kiriman": ship.get("nota_aksesoris_status") or "",
            "bisa_dibuat": bool(b["berlaku"] and not doc and baris), "baris": baris,
            "cara_bayar": nac.CARA_BAYAR, "cara_bawaan": nac.CARA_BAWAAN}


async def _nota_or_404(db, nid: str, request: Request, user: dict) -> dict:
    from core import nota_aksesoris_cmt as nac
    doc = await db[nac.COLL].find_one({"id": nid, "source_module": nac.SOURCE}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Nota aksesoris tidak ditemukan.")
    scope = await _scope(request, user, db)
    if scope.get("vendor_id") and doc.get("vendor_id") != scope["vendor_id"]:
        raise HTTPException(403, "Nota ini bukan milik vendor Anda.")
    return doc


@router.post("/kirim-cmt/shipments/{sid}/nota-aksesoris")
async def kirim_nota_create(sid: str, request: Request):
    """Buat nota untuk kiriman yang sudah tersimpan (kiriman sejak cutoff, kiriman tambahan/pengganti, terlewat)."""
    from core import nota_aksesoris_cmt as nac
    user = await require_auth(request)
    deny_klien(user)
    if is_vendor(user):
        raise HTTPException(403, "Akun vendor tidak boleh membuat nota aksesoris.")
    assert_prod_admin(user)
    db = get_db()
    ship = await db.vendor_shipments.find_one({"id": sid}, {"_id": 0})
    if not ship:
        raise HTTPException(404, "Kiriman tidak ditemukan")
    inp = nac.parse_input(await request.json()) or {"cara_bayar": nac.CARA_BAWAAN, "harga": {}}
    aks = (await kirim_cmt.shipment_lines(db, ship)).get("aksesoris") or []
    rows = nac.baris_kiriman(aks)
    if not rows:
        raise HTTPException(400, "Kiriman ini tidak menyerahkan aksesoris dari gudang — tidak ada yang dijual.")
    kurang = nac.belum_berharga(rows, inp["harga"])
    if kurang:
        raise HTTPException(400, "Isi harga jual aksesoris (isi 0 bila gratis): " + ", ".join(kurang[:6]) + ".")
    doc = await nac.buat(db, shipment=ship, lines=nac.baris_dari_kiriman(aks, inp["harga"]),
                         cara_bayar=inp["cara_bayar"], user=user)
    return serialize_doc({"nota": nac.ringkas(doc), "gratis": doc is None})


@router.get("/kirim-cmt/nota-aksesoris")
async def kirim_nota_list(request: Request, status: str = "", vendor_id: str = "", po_id: str = "", dari: str = "",
                          sampai: str = "", limit: int = 500):
    """Daftar nota aksesoris (per penyerahan). Vendor CMT (Portal Vendor) hanya melihat notanya sendiri."""
    from core import nota_aksesoris_cmt as nac
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    scope = await _scope(request, user, db)
    rows = await nac.daftar(db, vendor_id=scope.get("vendor_id") or vendor_id or None, status=status or None,
                            po_id=po_id or None, dari=dari or None, sampai=sampai or None,
                            limit=max(1, min(int(limit or 500), 1000)))
    return serialize_doc([nac.ringkas(r) for r in rows])


@router.get("/kirim-cmt/nota-aksesoris-berlaku")
async def kirim_nota_berlaku(request: Request, vendor_id: str = ""):
    """Apakah penyerahan ke vendor ini dibuatkan nota (CMT luar) — dipakai layar Serahkan di Portal Aksesoris."""
    from core import nota_aksesoris_cmt as nac
    user = await require_auth(request)
    deny_klien(user)
    b = await nac.berlaku(get_db(), vendor_id=vendor_id)
    return {"berlaku": b["berlaku"], "alasan": b["alasan"], "vendor_name": (b.get("vendor") or {}).get("name") or "",
            "cara_bayar": nac.CARA_BAYAR, "cara_bawaan": nac.CARA_BAWAAN}


async def _rekap_vendor(request: Request, user: dict, db, vendor_id: str) -> str:
    scope = await _scope(request, user, db)
    vid = scope.get("vendor_id") or vendor_id
    if not vid:
        raise HTTPException(400, "Pilih vendor CMT untuk rekap.")
    return vid


@router.get("/kirim-cmt/nota-aksesoris-rekap")
async def kirim_nota_rekap(request: Request, vendor_id: str = "", dari: str = "", sampai: str = ""):
    """Rekap gabungan nota satu CMT per periode (owner 11 Nov): daftar nota, dipotong, dibayar langsung, sisa."""
    from core import nota_aksesoris_cmt as nac
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    vid = await _rekap_vendor(request, user, db, vendor_id)
    return serialize_doc(await nac.rekap(db, vendor_id=vid, dari=dari or None, sampai=sampai or None))


@router.get("/kirim-cmt/nota-aksesoris-rekap/pdf")
async def kirim_nota_rekap_pdf(request: Request, vendor_id: str = "", dari: str = "", sampai: str = ""):
    from fastapi.responses import Response

    from core import nota_aksesoris_cmt as nac
    from core import pdf_template
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    vid = await _rekap_vendor(request, user, db, vendor_id)
    data = await nac.rekap(db, vendor_id=vid, dari=dari or None, sampai=sampai or None)
    profile = await pdf_template.company_profile(db, nac.ISSUER)
    template = await pdf_template.resolve(db, "sales-note")
    pdf = nac.build_rekap_pdf(data, profile=profile, template=template, printed_by=user.get("name") or "")
    name = f"Rekap-Nota-Aksesoris_{(data['vendor'].get('code') or 'CMT')}_{data['dari'] or 'awal'}_{data['sampai'] or 'kini'}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.get("/kirim-cmt/nota-aksesoris/{nid}/pdf")
async def kirim_nota_pdf(nid: str, request: Request):
    from fastapi.responses import Response

    from core import nota_aksesoris_cmt as nac
    from core import pdf_template
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    doc = await _nota_or_404(db, nid, request, user)
    vendor = await nac.vendor_doc(db, doc.get("vendor_id")) or {"name": doc.get("vendor_name")}
    profile = await pdf_template.company_profile(db, nac.ISSUER)
    template = await pdf_template.resolve(db, "sales-note")
    pdf = nac.build_pdf(doc, vendor=vendor, profile=profile, template=template, printed_by=user.get("name") or "")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Nota-Aksesoris_{doc.get("invoice_number", nid)}.pdf"'})


@router.post("/kirim-cmt/nota-aksesoris/{nid}/potong")
async def kirim_nota_potong(nid: str, request: Request):
    """Potong sisa nota dari tagihan jahit CMT yang terbuka sekarang (sisanya menunggu tagihan berikutnya)."""
    from core import nota_aksesoris_cmt as nac
    user = await require_auth(request)
    deny_klien(user)
    if is_vendor(user) or not _boleh_kelola_nota(user):
        raise HTTPException(403, pesan_centang(user, apa="memotong tagihan CMT"))
    db = get_db()
    await _nota_or_404(db, nid, request, user)
    return serialize_doc(nac.ringkas(await nac.potong_sekarang(db, nid, user)))


@router.post("/kirim-cmt/nota-aksesoris/{nid}/batal")
async def kirim_nota_batal(nid: str, request: Request):
    from core import nota_aksesoris_cmt as nac
    user = await require_auth(request)
    deny_klien(user)
    if is_vendor(user) or not _boleh_kelola_nota(user):
        raise HTTPException(403, pesan_centang(user, apa="membatalkan nota aksesoris"))
    db = get_db()
    await _nota_or_404(db, nid, request, user)
    body = await request.json()
    return serialize_doc(nac.ringkas(await nac.batal(db, nid, user, body.get("alasan") or "")))


@router.post("/kirim-cmt/shipments/{sid}/repost-journal")
async def kirim_repost_journal(sid: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    wajib_centang(user, peran_lama=FIN_REPOST_ROLES, apa="memposting ulang jurnal")
    db = get_db()
    ship = await db.vendor_shipments.find_one({"id": sid}, {"_id": 0})
    if not ship:
        raise HTTPException(404, "Kiriman tidak ditemukan")
    mis = await db.rahaza_material_issues.find(
        {"vendor_shipment_id": sid, "status": "issued"}, {"_id": 0}).to_list(20)
    if not mis:
        raise HTTPException(400, "Kiriman ini tidak punya dokumen pengeluaran yang sudah keluar — tidak ada jurnal.")
    from routes.rahaza_inventory_shared import _enrich_mi
    from routes.rahaza_posting import post_inventory_issue
    out = []
    for mi in mis:
        await _enrich_mi(db, mi)
        res = await post_inventory_issue(db, mi, user)
        out.append({"mi_number": mi.get("mi_number"), "ok": bool(res.get("ok")), "je_number": res.get("je_number"),
                    "already": bool(res.get("already_posted")), "error": res.get("error") or ""})
    await log_activity(user["id"], user.get("name", ""), "Repost", "Vendor Shipment",
                       f"Posting ulang jurnal kiriman {ship.get('shipment_number')}")
    return {"ok": all(r["ok"] for r in out), "results": out}


# ── 3. Permintaan tambahan (satu daftar) ─────────────────────────────────────────────────────────────────────────
async def _scope(request: Request, user: dict, db) -> dict:
    ov = await resolve_override(request, user, db)
    if is_vendor(user):
        return {"vendor_id": vendor_identity(user) or "__none__"}
    if ov:
        return {"vendor_id": ov["vendor_id"]}
    return {}


@router.get("/kirim-cmt/requests")
async def kirim_requests(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    sp = request.query_params
    scope = await _scope(request, user, db)
    rows = await kp.list_requests(db, business_type=sp.get("business_type"), source=sp.get("source") or "",
                                  search=sp.get("search") or "", vendor_id=sp.get("vendor_id") or "", scope=scope)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in kp.STATUS_LABEL}
    st = sp.get("status") or ""
    if st:
        rows = [r for r in rows if r["status"] == st]
    try:
        page = max(1, int(sp.get("page") or 1))
        per = min(100, max(1, int(sp.get("per_page") or 25)))
    except ValueError:
        page, per = 1, 25
    total = len(rows)
    return serialize_doc({"items": rows[(page - 1) * per: page * per], "total": total, "page": page, "per_page": per,
                          "counts": counts})


async def _load_request(db, src: str, rid: str) -> dict:
    if src == kp.SRC_VENDOR:
        doc = await db.material_requests.find_one({"id": rid}, {"_id": 0})
    elif src == kp.SRC_STAF:
        doc = await db.dewi_cmt_component_requests.find_one({"id": rid}, {"_id": 0})
    else:
        raise HTTPException(404, "Jenis permintaan tidak dikenal")
    if not doc:
        raise HTTPException(404, "Permintaan tidak ditemukan")
    return doc


@router.get("/kirim-cmt/requests/{src}/{rid}")
async def kirim_request_detail(src: str, rid: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    doc = await _load_request(db, src, rid)
    scope = await _scope(request, user, db)
    if scope.get("vendor_id") and (doc.get("vendor_id") or doc.get("cmt_partner_id")) != scope["vendor_id"]:
        raise HTTPException(403, "Permintaan ini bukan milik vendor Anda")
    row = kp._mr_row(doc) if src == kp.SRC_VENDOR else kp._krg_row(doc, {})
    payload = await kp.request_payload(db, src, doc)
    pending = row["status"] == "menunggu"
    calc = await kp.preview(db, src, doc) if pending else None
    shortages = []
    if src == kp.SRC_VENDOR and pending and doc.get("request_type") == "ADDITIONAL" and doc.get("category") != "accessories":
        from routes.exceptions import _accessory_shortages_for_request
        shortages = await _accessory_shortages_for_request(db, doc)
    nota = None
    if pending:   # 11 Nov 2026: nota aksesoris terbit saat Setujui & kirim (CMT luar)
        from core import nota_aksesoris_cmt as nac
        b = await nac.berlaku(db, vendor_id=payload.get("vendor_id"))
        nota = {"berlaku": b["berlaku"], "alasan": b["alasan"], "cara_bayar": nac.CARA_BAYAR, "cara_bawaan": nac.CARA_BAWAAN}
    return serialize_doc({"row": row, "lines": payload["lines"], "materials": payload["materials"],
                          "accessory_shortages": shortages, "preview": _clean(calc) if calc else None,
                          "reason": doc.get("reason") or doc.get("notes") or "", "nota_aksesoris": nota})


@router.post("/kirim-cmt/requests")
async def kirim_request_create(request: Request):
    user = await require_auth(request)
    deny_klien(user)
    wajib_centang(user, peran_lama=PROD_ADMIN_ROLES + ["admin_maklon", "manager_produksi"])
    db = get_db()
    body = await request.json()
    po = await db.production_pos.find_one({"id": body.get("po_id")}, {"_id": 0, "business_type": 1})
    await _po_bt_ok(db, po, body.get("business_type"))
    doc = await kp.create_staff_request(db, body, user)
    await log_activity(user["id"], user.get("name", ""), "Create", "Permintaan tambahan CMT", doc["request_code"])
    return serialize_doc({k: v for k, v in doc.items() if k != "_id"})


@router.post("/kirim-cmt/requests/{src}/{rid}/approve")
async def kirim_request_approve(src: str, rid: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    wajib_centang(user, peran_lama=PROD_ADMIN_ROLES + ["admin_maklon", "manager_produksi"])
    db = get_db()
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    await _load_request(db, src, rid)
    from core import doc_lock
    coll = "material_requests" if src == kp.SRC_VENDOR else "dewi_cmt_component_requests"
    token = await doc_lock.claim(db, coll, rid, field="decide_lock", actor=user, not_found="Permintaan tidak ditemukan",
                                 busy="Permintaan ini sedang diputuskan pengguna lain — muat ulang.")
    try:
        doc = await _load_request(db, src, rid)
        if src == kp.SRC_VENDOR:
            if doc.get("status") != "Pending":
                raise HTTPException(400, f"Permintaan sudah '{doc.get('status')}'.")
            res = await kp.approve_material_request(db, doc, body, user)
            number = res.get("child_shipment_number")
        else:
            res = await kp.approve_component_request(db, doc, user, body)
            number = res.get("shipment_number")
    finally:
        await doc_lock.release(db, coll, rid, token, field="decide_lock")
    await log_activity(user["id"], user.get("name", ""), "Approve", "Permintaan tambahan CMT",
                       f"{rid} → kiriman {number}")
    return serialize_doc({"ok": True, "shipment_number": number, "result": res})


@router.post("/kirim-cmt/requests/{src}/{rid}/reject")
async def kirim_request_reject(src: str, rid: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    wajib_centang(user, peran_lama=PROD_ADMIN_ROLES + ["admin_maklon", "manager_produksi"])
    db = get_db()
    body = await request.json()
    doc = await _load_request(db, src, rid)
    await kp.reject(db, src, doc, body.get("reason") or body.get("admin_notes") or "", user)
    return {"ok": True}


# ── 4. Rencana aksesoris PO (form PO) ────────────────────────────────────────────────────────────────────────────
async def _internal_plan_preview(db, items: list) -> tuple:
    from core import bom_uom
    rows, warnings, total = {}, [], 0
    for it in items:
        qty = int(float(it.get("qty") or 0))
        if qty <= 0:
            continue
        pi = dict(it)
        if it.get("rahaza_variant_id"):
            v = await db.rahaza_model_variants.find_one({"id": it["rahaza_variant_id"]}, {"_id": 0})
            if v:
                pi.update({"model_id": v.get("model_id"), "size_id": v.get("size_id"), "sku": v.get("sku"),
                           "color": v.get("color_name") or pi.get("color"), "color_code": v.get("color_code")})
        if not pi.get("model_id") or not pi.get("size_id"):
            continue
        total += qty
        bom, problem = await kirim_cmt.resolve_bom(db, pi)
        if problem:
            warnings.append(problem)
            continue
        mats, uw = await bom_uom.ensure_uom(db, bom)
        warnings.extend(w for w in uw if w not in warnings)
        for m in mats:
            if kirim_cmt.kind_of(line=m) == kirim_cmt.KIND_POTONGAN:
                continue
            key = m.get("material_id") or (m.get("code") or m.get("name") or "").upper()
            r = rows.setdefault(key, {"material_id": m.get("material_id"), "code": m.get("code") or "",
                                      "name": m.get("name") or "", "material_type": m.get("material_type") or "",
                                      "unit": bom_uom.base_unit_of(m), "qty": 0.0})
            r["qty"] += bom_uom.qty_base_of(m) * qty
    by_id = {m["id"]: m async for m in db.rahaza_materials.find(
        {"id": {"$in": [r["material_id"] for r in rows.values() if r["material_id"]]}}, {"_id": 0})}
    out = []
    for r in rows.values():
        mat = by_id.get(r["material_id"])
        if kirim_cmt.kind_of(mat, {"code": r["code"], "material_type": r["material_type"], "unit": r["unit"]}) \
                != kirim_cmt.KIND_AKSESORIS:
            continue
        out.append({"accessory_id": r["material_id"], "accessory_code": (mat or {}).get("code") or r["code"],
                    "accessory_name": (mat or {}).get("name") or r["name"], "unlinked": mat is None,
                    "ownership": "", **ss.plan_fields(mat, bom_qty_base=round(r["qty"], 4), source=ss.SOURCE_BOM,
                                                      usage_unit=r["unit"])})
    return out, warnings, total


async def _maklon_plan_preview(db, items: list) -> tuple:
    from routes.dewi_maklon_bom_templates import accessory_rows_from_materials, aggregate_template_lines
    norm = [{"catalog_id": (it.get("catalog_item_id") or it.get("catalog_id") or "").strip(),
             "qty": int(float(it.get("qty") or 0)), "label": it.get("label") or it.get("product_name") or ""}
            for it in items]
    agg, total, warnings, _t = await aggregate_template_lines(db, [n for n in norm if n["catalog_id"] and n["qty"] > 0])
    materials = [{"material_name": r["material_name"], "material_category": r.get("material_category"),
                  "line_type": r["line_type"], "unit": r["unit"], "qty_estimated": round(r["qty_estimated"], 4),
                  "material_id": r.get("material_id"), "ownership": r.get("ownership") or "client_provided",
                  "source_template_version": r.get("source_template_version")} for r in agg.values()]
    rows, unlinked, uom_issues = await accessory_rows_from_materials(db, materials)
    by_id = {m["id"]: m async for m in db.rahaza_materials.find(
        {"id": {"$in": [r["accessory_id"] for r in rows if r.get("accessory_id")]}}, {"_id": 0})}
    out = [{**r, **ss.plan_fields(by_id.get(r.get("accessory_id")), bom_qty_base=r.get("qty_needed"),
                                  source=ss.SOURCE_BOM, usage_unit=r.get("unit") or "")} for r in rows]
    if unlinked:
        warnings.append("Baris BOM berikut belum tertaut master material: " + ", ".join(unlinked[:10]))
    return out, warnings + uom_issues[:10], total


@router.post("/kirim-cmt/accessory-plan/preview")
async def accessory_plan_preview(request: Request):
    """Rencana aksesoris untuk item PO yang MASIH DI FORM (baca saja). Angkanya sama dengan yang ditulis mesin BOM
    saat PO disimpan (`core.satuan_serah.plan_fields`)."""
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    body = await request.json()
    items = body.get("items") or []
    if (body.get("business_type") or "internal") == "maklon":
        rows, warnings, total = await _maklon_plan_preview(db, items)
    else:
        rows, warnings, total = await _internal_plan_preview(db, items)
    rows.sort(key=lambda r: (r.get("accessory_name") or "").lower())
    return serialize_doc({"rows": rows, "warnings": warnings, "total_pcs": total})


@router.get("/kirim-cmt/po/{po_id}/accessory-plan")
async def accessory_plan_get(po_id: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    db = get_db()
    po = await db.production_pos.find_one({"id": po_id}, {"_id": 0})
    if not po:
        raise HTTPException(404, "PO tidak ditemukan")
    plan = await kirim_cmt.po_plan(db, po)
    return serialize_doc({"rows": [{k: v for k, v in r.items() if k != "material"} for r in plan["rows"]],
                          "client_rows": plan["client_rows"], "excluded_potongan": plan["excluded_potongan"]})


@router.put("/kirim-cmt/po/{po_id}/accessory-plan")
async def accessory_plan_put(po_id: str, request: Request):
    user = await require_auth(request)
    deny_klien(user)
    assert_prod_admin(user)
    db = get_db()
    body = await request.json()
    if not await db.production_pos.find_one({"id": po_id}, {"_id": 1}):
        raise HTTPException(404, "PO tidak ditemukan")
    from core.po_lock import assert_po_open
    await assert_po_open(db, po_id, "perubahan rencana aksesoris PO")
    from core import rencana_aksesoris
    res = await rencana_aksesoris.apply_rows(db, po_id, body.get("rows") or [],
                                             replace_tambahan=bool(body.get("replace_tambahan", True)))
    return {"ok": True, **res}
