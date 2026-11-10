"""rahaza_inventory — FG Movements + FG Issues (pengeluaran produk jadi).

2026-11-10 (owner, "barang keluar tanpa scan bisa dicari dan pilih banyak"):
  GET  /api/rahaza/fg-pick           cari barang jadi + stok per lokasi (pemilih tanpa scan, `core.fg_pick`)
  POST /api/rahaza/fg-issue/batch    keluarkan BANYAK produk sekaligus — satu nomor, jalur yang sama dengan
                                     pengeluaran satu produk (`_check_issue_line` + `_post_issue_line`)
"""
# ruff: noqa: E741
from fastapi import Request, HTTPException
from database import get_db
from auth import require_auth, serialize_doc, log_activity
from typing import Optional
import uuid
from datetime import datetime, timezone
from routes.rahaza_inventory_shared import router


def _fg_uid(): return str(uuid.uuid4())
def _fg_now(): return datetime.now(timezone.utc)


FG_ISSUE_REASONS = {
    "surat_jalan_internal": "Surat Jalan Internal",
    "sample":               "Sample / Contoh",
    "koreksi_stok":         "Koreksi Stok (Adjustment)",
    "retur":                "Retur / Rusak",
    "lainnya":              "Lainnya",
}


@router.get("/fg-movements")
async def list_fg_movements(request: Request, fg_code: Optional[str] = None,
                            direction: Optional[str] = None, limit: int = 50):
    await require_auth(request)
    db = get_db()
    q: dict = {}
    if fg_code:
        q["fg_code"] = fg_code
    if direction:
        q["direction"] = direction
    movements = await db.rahaza_fg_movements.find(q, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(500)
    return serialize_doc(movements)


@router.get("/fg-issues")
async def list_fg_issues(request: Request, limit: int = 50):
    await require_auth(request)
    db = get_db()
    issues = await db.rahaza_fg_issues.find({}, {"_id": 0}).sort("issued_at", -1).limit(limit).to_list(500)
    return serialize_doc(issues)


@router.get("/fg-pick")
async def fg_pick(request: Request, q: Optional[str] = None, location_id: Optional[str] = None,
                  ada_stok: bool = False, limit: int = 50):
    """2026-11-10 (owner): cari barang jadi untuk dipilih TANPA scan (banyak sekaligus) — dipakai
    Scan Keluar Penjualan ("Pilih tanpa scan") dan formulir "Keluarkan stok". Hanya membaca."""
    await require_auth(request)
    from core import fg_pick as fp
    return serialize_doc(await fp.search(get_db(), q=q or "", location_id=location_id or "",
                                         only_in_stock=ada_stok, limit=limit))


async def _check_issue_line(db, material_id, location_id, qty) -> tuple:
    """Periksa satu baris pengeluaran (master FG, lokasi wajib, stok cukup) → (mat, loc_id, tersedia).
    SATU aturan untuk pengeluaran satu produk dan banyak produk."""
    if not material_id:
        raise HTTPException(400, "material_id wajib diisi")
    if qty <= 0:
        raise HTTPException(400, "qty harus lebih dari 0")
    mat = await db.rahaza_materials.find_one({"id": material_id}, {"_id": 0})
    if not mat:
        raise HTTPException(404, "Material tidak ditemukan")
    if mat.get("type") != "fg":
        raise HTTPException(400, "Material bukan produk jadi (type=fg)")

    # 2026-11-02 — No.18(a): lokasi asal WAJIB dipilih pengguna. Dulu dipakai "lokasi aktif
    # pertama" (di seed = KTR-PST Kantor Pusat) sehingga stok 36 pcs di GD-L1-RAK terbaca 0.
    loc_id = (location_id or "").strip()
    if not loc_id:
        raise HTTPException(400, "location_id wajib diisi — pilih lokasi asal barang jadi yang dikeluarkan.")
    from core import location_resolver
    if not await location_resolver.location_exists(db, loc_id):
        raise HTTPException(400, "Lokasi asal tidak ditemukan di Struktur Gudang.")
    stock_doc = await db.rahaza_material_stock.find_one(
        {"material_id": material_id, "location_id": loc_id}, {"_id": 0}
    )
    available = float(stock_doc.get("qty", 0)) if stock_doc else 0
    if qty > available:
        raise HTTPException(400, f"Stok tidak cukup di lokasi ini. Tersedia: {available} pcs, diminta: {qty} pcs")
    return mat, loc_id, available


async def _post_issue_line(db, user, *, mat: dict, loc_id: str, qty: int, available: float, reason: str,
                           customer_id, customer_name, ref_no: str, notes: str, issue_number: str,
                           batch: Optional[dict] = None) -> dict:
    """Satu baris pengeluaran: potong stok → dokumen → riwayat → jurnal HPP (WAC). Dipakai
    pengeluaran satu produk DAN banyak produk (jalur stok & jurnal yang sama)."""
    from core import stock_service
    material_id = mat["id"]
    try:
        await stock_service.issue(
            material_id, loc_id, qty,
            ref={"source": "fg_issue", "issue_number": issue_number, "customer_id": customer_id},
            actor={"id": str(user.get("id") or ""), "email": user.get("email", "")},
            db=db,
        )
    except stock_service.InsufficientStock:
        raise HTTPException(400, f"Stok tidak cukup. Tersedia: {available} pcs, diminta: {qty} pcs")

    issue_id = _fg_uid()
    issue_doc = {
        "id":               issue_id,
        "issue_number":     issue_number,
        "material_id":      material_id,
        "fg_code":          mat.get("code"),
        "fg_name":          mat.get("name"),
        "qty":              qty, "unit": mat.get("unit", "pcs"),
        "reason":           reason, "reason_label": FG_ISSUE_REASONS[reason],
        "customer_id":      customer_id, "customer_name": customer_name,
        "reference_number": ref_no, "notes": notes,
        "issued_by":        user.get("name", ""),
        "issued_by_id":     user.get("sub", ""),
        "issued_at":        _fg_now(),
        "stock_before":     available, "stock_after": available - qty,
        "location_id":      loc_id,
    }
    if batch:   # 2026-11-10: satu formulir banyak produk → satu nomor, baris berurutan
        issue_doc.update({"batch_id": batch["id"], "line_no": batch["line_no"], "batch_lines": batch["lines"]})
    await db.rahaza_fg_issues.insert_one(issue_doc)
    issue_doc.pop("_id", None)
    await db.rahaza_fg_movements.insert_one({
        "id":              _fg_uid(),
        "fg_code":         mat.get("code"),
        "material_id":     material_id,
        "fg_issue_id":     issue_id,
        "direction":       "out", "qty": qty,
        "source":          "manual_issue", "reason": reason,
        "customer_id":     customer_id, "customer_name": customer_name,
        "reference_number": ref_no,
        "notes":           notes or FG_ISSUE_REASONS[reason],
        "issued_by":       user.get("name", ""),
        "timestamp":       _fg_now(),
    })
    # 2026-11-02 (K41 = a): HPP barang yang keluar dinilai WAC dan DIJURNAL lewat helper paket WAC
    # (`post_fg_issue_cogs`: Dr akun alasan — profil `fg_issue` — / Cr 1-1404 senilai qty × WAC).
    # Dulu pengeluaran ini hanya memotong stok; nilai 1-1404 tidak pernah turun. Gagal jurnal tidak
    # membatalkan pengeluaran fisik, tetapi DICATAT di dokumen & dikembalikan ke layar.
    from routes.rahaza_posting import post_fg_issue_cogs
    try:
        gl = await post_fg_issue_cogs(db, issue_doc, user)
    except Exception as e:  # noqa: BLE001
        gl = {"ok": False, "error": str(e)}
    gl_set = {"gl_je_id": gl.get("je_id"), "gl_je_number": gl.get("je_number"),
              "cogs": gl.get("cogs"), "unit_cost": gl.get("unit_cost"), "cogs_basis": "wac",
              "debit_mapping": gl.get("debit_mapping"),
              "gl_post_error": None if gl.get("ok") else (gl.get("error") or "jurnal gagal")}
    await db.rahaza_fg_issues.update_one({"id": issue_id}, {"$set": gl_set})
    issue_doc.update(gl_set)
    await log_activity(user["id"], user.get("name", ""), "fg_issue_created", "rahaza.fg_issue",
                      f"{issue_number}: {mat.get('code')} qty={qty} reason={reason}"
                      + (f" je={gl.get('je_number')}" if gl.get("ok") else " (jurnal gagal)"))
    return issue_doc


async def _customer_name(db, customer_id):
    if not customer_id:
        return None
    cust = await db.rahaza_customers.find_one({"id": customer_id}, {"_id": 0})
    return cust.get("name") if cust else None


@router.post("/fg-issue")
async def create_fg_issue(request: Request):
    user = await require_auth(request)
    db   = get_db()
    body = await request.json()

    material_id = body.get("material_id")
    qty         = int(body.get("qty") or 0)
    reason      = body.get("reason", "lainnya")
    customer_id = body.get("customer_id")
    ref_no      = body.get("reference_number", "")
    notes       = body.get("notes", "")

    if not material_id:
        raise HTTPException(400, "material_id wajib diisi")
    if qty <= 0:
        raise HTTPException(400, "qty harus lebih dari 0")
    if reason not in FG_ISSUE_REASONS:
        raise HTTPException(400, f"reason harus salah satu: {list(FG_ISSUE_REASONS.keys())}")
    mat, loc_id, available = await _check_issue_line(db, material_id, body.get("location_id"), qty)
    customer_name = await _customer_name(db, customer_id)

    # SESI #27 — SATU PINTU kebijakan penomoran (Otomatis/Manual). Fungsi penomoran diimpor
    # dengan alias supaya tidak menimpa variabel `issue_number`.
    from core.doc_number_policy import issue_number as _issue_doc_number
    issue_number = await _issue_doc_number(
        db, "rahaza_fg_issues.issue_number",
        requested=(body.get("issue_number") or "").strip())

    issue_doc = await _post_issue_line(db, user, mat=mat, loc_id=loc_id, qty=qty, available=available,
                                       reason=reason, customer_id=customer_id, customer_name=customer_name,
                                       ref_no=ref_no, notes=notes, issue_number=issue_number)
    return serialize_doc({**issue_doc, "ok": True})


MAX_BATCH_LINES = 100


def parse_batch_lines(items) -> list:
    """Isi formulir banyak produk → [{material_id, location_id, qty, code}] (fungsi murni, semua galat
    sekaligus). Produk + lokasi yang sama dua kali ditolak (gabungkan jumlahnya)."""
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "Pilih minimal satu produk jadi.")
    if len(items) > MAX_BATCH_LINES:
        raise HTTPException(400, f"Paling banyak {MAX_BATCH_LINES} produk per pengeluaran — simpan bertahap.")
    out, errs, seen = [], [], set()
    for i, it in enumerate(items, start=1):
        it = it if isinstance(it, dict) else {}
        mid = str(it.get("material_id") or "").strip()
        loc = str(it.get("location_id") or "").strip()
        label = str(it.get("code") or f"Baris {i}")[:60]
        try:
            raw = float(it.get("qty") or 0)
        except (TypeError, ValueError):
            raw = 0.0
        qty = int(raw)
        if not mid:
            errs.append(f"Baris {i}: produk belum dipilih.")
        elif not loc:
            errs.append(f"{label}: pilih lokasi asal.")
        elif qty <= 0 or raw != qty:
            errs.append(f"{label}: jumlah harus angka bulat lebih dari 0.")
        elif (mid, loc) in seen:
            errs.append(f"{label}: produk dan lokasi yang sama dipilih dua kali — gabungkan jumlahnya.")
        else:
            seen.add((mid, loc))
            out.append({"material_id": mid, "location_id": loc, "qty": qty, "code": label})
    if errs:
        raise HTTPException(400, " ".join(errs))
    return out


@router.post("/fg-issue/batch")
async def create_fg_issue_batch(request: Request):
    """2026-11-10 (owner, "bisa dicari dan pilih banyak"): keluarkan BANYAK produk jadi sekaligus.

    Satu formulir = SATU nomor pengeluaran; setiap produk menjadi satu baris `rahaza_fg_issues`
    (nomor sama, `batch_id` + `line_no`) yang diproses lewat jalur yang SAMA dengan pengeluaran satu
    produk (`_check_issue_line` + `_post_issue_line`: potong stok, riwayat, jurnal HPP WAC). Semua baris
    diperiksa DULU (stok cukup, lokasi, master) — satu saja salah ⇒ tidak ada yang dikeluarkan.
    `client_batch_id` (dari layar) mencegah Simpan dobel."""
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    reason = body.get("reason", "lainnya")
    if reason not in FG_ISSUE_REASONS:
        raise HTTPException(400, "Pilih alasan pengeluaran.")
    batch_id = str(body.get("client_batch_id") or "").strip()[:80] or _fg_uid()
    prev = await db.rahaza_fg_issues.find({"batch_id": batch_id}, {"_id": 0}).sort("line_no", 1).to_list(500)
    if prev:
        return serialize_doc({"ok": True, "duplicate": True, "issue_number": prev[0].get("issue_number"),
                              "batch_id": batch_id, "lines": prev, "failed": []})
    rows = parse_batch_lines(body.get("items"))
    checked, errs = [], []
    for r in rows:
        try:
            checked.append((r, *await _check_issue_line(db, r["material_id"], r["location_id"], r["qty"])))
        except HTTPException as e:
            errs.append(f"{r['code']}: {e.detail}")
    if errs:
        raise HTTPException(400, "Belum ada yang dikeluarkan. " + " ".join(errs))
    customer_id = body.get("customer_id")
    customer_name = await _customer_name(db, customer_id)
    from core.doc_number_policy import issue_number as _issue_doc_number
    issue_number = await _issue_doc_number(
        db, "rahaza_fg_issues.issue_number",
        requested=(body.get("issue_number") or "").strip())
    done, failed = [], []
    for n, (r, mat, loc_id, available) in enumerate(checked, start=1):
        try:
            done.append(await _post_issue_line(
                db, user, mat=mat, loc_id=loc_id, qty=r["qty"], available=available, reason=reason,
                customer_id=customer_id, customer_name=customer_name,
                ref_no=body.get("reference_number", ""), notes=body.get("notes", ""),
                issue_number=issue_number, batch={"id": batch_id, "line_no": n, "lines": len(checked)}))
        except HTTPException as e:   # stok berubah di antara pemeriksaan dan pemotongan (perangkat lain)
            failed.append({"material_id": r["material_id"], "code": r["code"], "qty": r["qty"], "error": e.detail})
    return serialize_doc({"ok": not failed, "duplicate": False, "issue_number": issue_number,
                          "batch_id": batch_id, "lines": done, "failed": failed})
