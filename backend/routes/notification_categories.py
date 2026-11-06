"""
NOTIFIKASI BERKATEGORI — CV. Dewi Aditya (2026-07-27)

MASALAH YANG DIPERBAIKI (laporan owner)
---------------------------------------
Bel notifikasi lama menumpahkan SEMUA notifikasi apa adanya: tidak ada kategori,
tidak jelas datang dari portal mana, dan admin tidak bisa mengatur siapa menerima
apa. Akibatnya notifikasi jadi kebisingan, bukan alat bantu kerja.

YANG DITAMBAHKAN
----------------
1. KATEGORI = PORTAL SUMBER. Notifikasi lama TIDAK perlu dimigrasi: kategori
   diturunkan saat baca dari `link_module` (prefix modul = portal) lalu `type`.
   Jadi seluruh notifikasi historis langsung ikut terkategori.
2. KONFIGURASI ADMIN: matriks kategori × role (`notif_category_config`) — role
   apa boleh menerima kategori apa. Default: semua kategori aktif untuk role yang
   memang punya akses portal tersebut (diturunkan dari PORTAL_ACCESS, jadi
   konsisten dengan RBAC dan tidak jadi sumber kebenaran kedua).
3. PREFERENSI PER-USER (`notif_user_prefs`): user boleh membisukan kategori
   tertentu untuk dirinya sendiri, tapi TIDAK bisa membuka kategori yang sudah
   ditutup admin.
4. KATEGORI "UNTUK SAYA" (2026-08-07, perbaikan POC RBAC 3 FAIL). Notifikasi yang
   dialamatkan LANGSUNG ke seseorang (user_id / target_user_ids / target_roles
   berisi role-nya) dulu bisa HILANG dari bel bila kategori turunannya bukan
   kategori portal yang biasa ia lihat — contohnya subtype tak dikenal yang jatuh
   ke 'sysadmin', padahal 'sysadmin' hanya untuk admin. Sekarang notifikasi
   semacam itu ditampung di kategori bawaan `personal` ("Untuk Saya") yang selalu
   aktif untuk semua orang dan tidak bisa ditutup admin maupun dibisukan user.
   Kategori ini TIDAK melonggarkan RBAC: aturan audiens (`notif_audience_query`)
   tetap satu-satunya penentu siapa boleh menerima apa.

Endpoint (prefix /api/notifications):
  GET  /categories                daftar kategori + hitungan (untuk bel ringkas)
  GET  /categorized               daftar notifikasi + kategori (untuk popup)
  GET  /category-config           matriks admin
  PUT  /category-config           simpan matriks (admin)
  GET  /my-category-prefs         kategori yang dibisukan user
  PUT  /my-category-prefs         simpan pembisuan user
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from auth import require_auth, serialize_doc
from database import get_db
from routes.shared import PORTAL_ACCESS, SUPER_ROLES
from utils.notif_unified import (
    CATEGORY_CONFIG, KIND_ACTION, RETENTION_DEFAULT_DAYS, action_of, clamp_retention_days, kind_of,
    link_for_portals, notif_is_unread_for, notif_times_iso, notif_user_id, resolve_rows,
    resolved_label, source_collection_of,
)


def _explicitly_addressed(notif: dict, user: dict) -> bool:
    """Ditujukan LANGSUNG ke user ini (personal / daftar user / role-nya).

    Notifikasi yang jelas-jelas dialamatkan ke seseorang WAJIB sampai, walaupun
    kategorinya bukan kategori portal yang biasa ia lihat. Filter kategori hanya
    untuk menyaring notifikasi siaran antar-portal (2026-08-07).
    """
    uid = notif_user_id(user)
    role = (user.get("role") or "").lower()
    meta = notif.get("meta") or {}
    if notif.get("user_id") and notif.get("user_id") == uid:
        return True
    if uid in (list(notif.get("target_user_ids") or []) + list(meta.get("target_user_ids") or [])):
        return True
    roles = [str(r).lower() for r in (list(notif.get("target_roles") or [])
                                      + list(meta.get("target_roles") or []))]
    return bool(role) and role in roles

router = APIRouter(prefix="/api/notifications", tags=["notifications-category"])

CFG = CATEGORY_CONFIG  # 2026-11-06 (pola P2): koleksi dibaca lewat konstanta penulisnya (satu nama, tidak ada koleksi hantu)
PREF = "notif_user_prefs"

# Kategori = portal sumber. `key` sengaja sama dengan portal id supaya tombol
# "buka modul" bisa langsung memakai router portal yang sudah ada.
CATEGORIES = [
    {"key": "personal",    "label": "Untuk Saya",         "icon": "user-check"},
    {"key": "warehouse",   "label": "Gudang",             "icon": "warehouse"},
    {"key": "procurement", "label": "Pengadaan",          "icon": "shopping-cart"},
    {"key": "production",  "label": "Produksi",           "icon": "factory"},
    {"key": "cutting",     "label": "Cutting",            "icon": "scissors"},
    {"key": "maklon",      "label": "Maklon",             "icon": "package"},
    {"key": "finance",     "label": "Keuangan",           "icon": "landmark"},
    {"key": "hr",          "label": "SDM",                "icon": "users"},
    {"key": "toko",        "label": "Marketing",          "icon": "shopping-bag"},
    {"key": "accessories", "label": "Aksesoris",          "icon": "sparkles"},
    {"key": "assets",      "label": "Aset",               "icon": "boxes"},
    {"key": "rnd",         "label": "RnD",                "icon": "flask"},
    {"key": "sysadmin",    "label": "Sistem",             "icon": "shield"},
]
CATEGORY_KEYS = [c["key"] for c in CATEGORIES]
CATEGORY_LABEL = {c["key"]: c["label"] for c in CATEGORIES}
# Kategori bawaan yang SELALU aktif untuk semua orang: penampung notifikasi yang
# dialamatkan langsung ke user tetapi kategori portalnya di luar jangkauannya.
PERSONAL_CATEGORY = "personal"

# Prefix moduleId → kategori (urutan penting: yang paling spesifik dulu).
_PREFIX = [
    # 2026-08-06 — `proc-` HARUS dicek sebelum prefix lain: Portal Pengadaan kini
    # pemilik notifikasi PR/PO/faktur supplier (sebelumnya nyasar ke Gudang &
    # Keuangan sehingga staf pengadaan tidak melihat pekerjaannya sendiri).
    ("proc-", "procurement"),
    ("cutting-", "cutting"), ("acc-", "accessories"), ("accessories-", "accessories"),
    ("asset-", "assets"), ("wh-", "warehouse"), ("wms-", "warehouse"),
    ("warehouse-", "warehouse"), ("prod-", "production"), ("production-", "production"),
    ("cmt-", "maklon"), ("maklon-", "maklon"), ("fin-", "finance"), ("finance-", "finance"),
    ("hr-", "hr"), ("payroll-", "hr"), ("portal-", "hr"), ("self-", "hr"),
    ("marketing-", "toko"), ("toko-", "toko"), ("rnd-", "rnd"),
    ("mgmt-", "sysadmin"), ("management-", "sysadmin"), ("admin-", "sysadmin"),
]
# Fallback berdasarkan `type` notifikasi bila link_module kosong.
_TYPE = {
    # 2026-08-06 — token pengadaan didahulukan: "purchase_invoice" harus jatuh ke
    # Pengadaan, bukan Keuangan (token "invoice" ada di kelompok finance di bawah).
    "purchase_request": "procurement", "purchase_order": "procurement",
    "procurement": "procurement", "purchase": "procurement",
    "supplier": "procurement", "vendor": "procurement", "3way": "procurement",
    "low_stock": "warehouse", "stock": "warehouse", "reorder": "warehouse",
    "opname": "warehouse", "receiving": "warehouse",
    "production": "production", "job": "production", "qc": "production",
    "cmt": "maklon", "maklon": "maklon",
    "invoice": "finance", "payment": "finance", "journal": "finance",
    "budget": "finance", "expense": "finance", "kasbon": "finance",
    "leave": "hr", "attendance": "hr", "payroll": "hr", "kpi": "hr",
    "recruitment": "hr", "birthday": "hr",
    "marketing": "toko", "kol": "toko", "order": "toko",
    "accessory": "accessories", "asset": "assets", "rnd": "rnd",
    "backup": "sysadmin", "system": "sysadmin", "collab": "sysadmin",
}


def categorize(notif: dict) -> str:
    # `link_module` bisa di akar (penulis lama) atau di `meta` (notif_insert SSOT).
    mod = (notif.get("link_module")
           or (notif.get("meta") or {}).get("link_module") or "").lower()
    for pref, cat in _PREFIX:
        if mod.startswith(pref):
            return cat
    # `subtype` lebih spesifik daripada `type` domain ('rahaza'/'dewi'), cek dulu.
    t = f"{notif.get('subtype') or ''} {notif.get('type') or ''}".lower()
    for token, cat in _TYPE.items():
        if token in t:
            return cat
    return "sysadmin"


def _default_matrix() -> dict:
    """Default: sebuah role menerima kategori X bila role itu memang punya akses
    portal X (diturunkan dari PORTAL_ACCESS agar tidak menciptakan sumber
    kebenaran RBAC kedua)."""
    roles = sorted({r for lst in PORTAL_ACCESS.values() for r in lst})
    matrix = {}
    for role in roles:
        allowed = [c for c in CATEGORY_KEYS if role in PORTAL_ACCESS.get(c, [])]
        # Semua orang berhak tahu urusan SDM yang menyangkut dirinya.
        if "hr" not in allowed:
            allowed.append("hr")
        # "Untuk Saya" tidak pernah bisa ditutup — isinya memang milik user itu.
        if PERSONAL_CATEGORY not in allowed:
            allowed.append(PERSONAL_CATEGORY)
        matrix[role] = sorted(allowed)
    for sr in SUPER_ROLES:
        matrix[sr] = list(CATEGORY_KEYS)
    return matrix


async def get_matrix(db) -> dict:
    doc = await db[CFG].find_one({"id": "default"}, {"_id": 0})
    if not doc:
        doc = {"id": "default", "matrix": _default_matrix(),
               "updated_at": datetime.now(timezone.utc), "updated_by": "system"}
        await db[CFG].insert_one(dict(doc))
    return doc


async def category_scope(db, user: dict) -> dict:
    """Cakupan kategori untuk satu user — DUA lapis yang sengaja dipisah:

    · `base`  = kategori yang DIBUKA ADMIN untuk peran ini (matriks × role).
    · `muted` = kategori yang DIBISUKAN SENDIRI oleh user (pilihannya).

    Bedanya penting untuk perilaku bel:
      - Kategori di luar `base` (celah RBAC) tapi notifikasinya dialamatkan
        langsung ke user → dialihkan ke "Untuk Saya" supaya tidak hilang.
      - Kategori yang user BISUKAN SENDIRI → benar-benar disembunyikan (tidak
        dialihkan ke "Untuk Saya"), karena itu keputusan sadar si user.
      - "Untuk Saya" tidak bisa ditutup admin maupun dibisukan user.
    """
    role = (user.get("role") or "").lower()
    if role in SUPER_ROLES:
        base = list(CATEGORY_KEYS)
    else:
        cfg = await get_matrix(db)
        base = list(cfg["matrix"].get(role) or ["hr"])
    if PERSONAL_CATEGORY not in base:
        base.insert(0, PERSONAL_CATEGORY)
    base = [c for c in CATEGORY_KEYS if c in base]
    pref = await db[PREF].find_one({"user_id": user.get("id")}, {"_id": 0}) or {}
    muted = {c for c in (pref.get("muted_categories") or []) if c != PERSONAL_CATEGORY}
    return {"base": base, "muted": sorted(muted),
            "allowed": [c for c in base if c not in muted]}


async def allowed_categories(db, user: dict) -> list[str]:
    """Kategori yang aktif untuk user (setelah pembisuan). Dipakai UI & guard."""
    return (await category_scope(db, user))["allowed"]


def effective_category(notif: dict, user: dict, scope: dict) -> Optional[str]:
    """Kategori yang dipakai untuk MENAMPILKAN notifikasi ini kepada `user`.

    · Kategori dibisukan user → None (dihormati, tidak dialihkan).
    · Kategori aktif → pakai kategori itu.
    · Kategori di luar jangkauan peran TAPI notifikasi dialamatkan langsung ke
      user (personal / daftar user / role-nya) → "Untuk Saya" (jaring penyelamat
      bug 2026-08-07: dulu notifikasi seperti ini hilang dari bel).
    · Selain itu → None (siaran antar-portal yang bukan urusannya).

    Dipakai bersama `/categories` (hitungan) dan `/categorized` (daftar) supaya
    angka di bel selalu cocok dengan isi popupnya.
    """
    cat = categorize(notif)
    if cat in scope["muted"]:
        return None
    if cat in scope["allowed"]:
        return cat
    if (PERSONAL_CATEGORY in scope["allowed"]
            and _explicitly_addressed(notif, user)):
        return PERSONAL_CATEGORY
    return None


def _present(notif: dict, cat: str, unread: bool, portals=None) -> dict:
    """Bentuk baris siap-tampil untuk bel.

    Menormalkan dua beda konvensi penulis notifikasi supaya UI tidak perlu tahu:
    `body` (SSOT `notif_insert`) vs `message` (penulis lama), dan `link_module`
    yang bisa berada di akar dokumen ATAU di dalam `meta`.

    2026-11-02 (K30/K37) — ikut dikirim `kind`, tombol `action` (tujuan sudah
    disesuaikan dengan portal penerima), dan status penutupan untuk riwayat.
    `portals` = portal efektif penerima (None = tanpa alias per peran).
    """
    meta = notif.get("meta") or {}
    # 2026-11-02 — `link_id` (id rekaman) & `hub_tab` ikut dikirim supaya bel bisa
    # meneruskannya ke navigasi; id modul mati dipetakan ke id hidup; waktu
    # dikirim ber-zona (lihat utils/notif_unified.iso_utc).
    params = dict(notif.get("link_params") or meta.get("link_params") or {})
    if meta.get("hub_tab") and not params.get("tab"):
        params["tab"] = meta["hub_tab"]
    kind = kind_of(notif)
    action = action_of(notif, portals)
    if action:
        # `action.filter` sudah memuat link_params + tab hub (disesuaikan peran).
        link_module = action.get("target_menu") or ""
        params = dict(action.get("filter") or {})
    else:
        link_module, tab = link_for_portals(notif.get("link_module") or meta.get("link_module") or "", portals)
        if tab:
            params["tab"] = tab
    return {
        **notif_times_iso(notif),
        "category": cat,
        "category_label": CATEGORY_LABEL.get(cat, cat),
        "read": not unread,
        "message": notif.get("message") or notif.get("body") or "",
        "body": notif.get("body") or notif.get("message") or "",
        "link_module": link_module or "",
        "link_id": notif.get("link_id") or notif.get("source_id") or meta.get("link_id") or None,
        "link_params": params or None,
        "kind": kind,
        "action": action,
        "resolved_reason": notif.get("resolved_reason"),
        "resolved_label": resolved_label(notif.get("resolved_reason")),
    }


# Field minimum untuk menentukan kategori, audiens, status baca, dan jenis
# (perlu tindakan/pemberitahuan) — dipakai untuk MENGHITUNG seluruh notifikasi
# tanpa memuat judul/isi (2026-11-02).
_LIGHT = {"_id": 0, "id": 1, "type": 1, "subtype": 1, "user_id": 1, "read": 1,
          "read_by": 1, "link_module": 1, "target_user_ids": 1, "target_roles": 1,
          "meta.link_module": 1, "meta.target_user_ids": 1, "meta.target_roles": 1,
          "meta.read_by": 1, "meta.stage": 1, "kind": 1, "resolved_at": 1, "source_id": 1,
          "source_type": 1, "source_collection": 1, "resolve_rule": 1}

# Tab kotak masuk (K30): Perlu Tindakan / Pemberitahuan / Riwayat (action tertutup).
TAB_ACTION, TAB_INFO, TAB_HISTORY = "action", "info", "history"


def _tab_of(r: dict) -> str:
    if kind_of(r) == KIND_ACTION:
        return TAB_HISTORY if r.get("resolved_at") else TAB_ACTION
    return TAB_INFO


async def _scan(db, user, scope, *, category=None, unread_only=False, tab=None, rows_out=None):
    """SEMUA notifikasi audiens user (terbaru dulu) → [(id, kategori, belum_dibaca, tab)].

    2026-11-02 — dulu bel hanya membaca 200 dokumen terbaru (`_fetch`) ⇒ angka
    bel superadmin 200 padahal 787 belum dibaca, dan popup tidak bisa melihat
    lebih jauh. Pemindaian ringan ini menjadi dasar hitungan DAN paginasi, jadi
    angka bel selalu = isi popup. `tab` menyaring jenis (K30); `rows_out`
    (list) menampung dokumen ringan action terbuka untuk resolver/pengecualian.
    """
    from utils.notif_unified import notif_audience_query
    out = []
    async for r in db.notifications.find(notif_audience_query(user), _LIGHT).sort("created_at", -1):
        cat = effective_category(r, user, scope)
        if cat is None or (category and cat != category):
            continue
        t = _tab_of(r)
        if tab and t != tab:
            continue
        unread = notif_is_unread_for(r, user)
        if unread_only and not unread:
            continue
        if rows_out is not None and t == TAB_ACTION:
            rows_out.append(r)
        out.append((r["id"], cat, unread, t))
    return out


def _source_key(r: dict):
    return (source_collection_of(r), r.get("source_id"))


async def _user_portals(db, user: dict):
    """Portal efektif penerima (untuk K37: tujuan tautan per peran)."""
    try:
        from routes.shared import resolve_role_access
        return (await resolve_role_access(db, dict(user)))["portals"]
    except Exception:  # noqa: BLE001 — tanpa info portal ⇒ tujuan bawaan
        return None


async def _action_groups(db, user: dict, open_rows: list) -> list:
    """Grup "Perlu Tindakan" dari dokumen (Approval Badge lama) tanpa hitung dobel."""
    try:
        from routes.approval_badge import approval_groups
        exclude = {_source_key(r) for r in open_rows if r.get("source_id")}
        return [g for g in await approval_groups(db, user, exclude=exclude) if g["count"] > 0]
    except Exception:  # noqa: BLE001 — bel tidak boleh mati karena satu sumber
        import logging
        logging.getLogger(__name__).warning("[notif] grup Perlu Tindakan gagal", exc_info=True)
        return []


async def _load_full(db, ids):
    """Dokumen lengkap untuk `ids`, urutan dipertahankan."""
    if not ids:
        return []
    rows = await db.notifications.find({"id": {"$in": list(ids)}}, {"_id": 0}).to_list(len(ids))
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


async def _fetch(db, user, limit=200):
    """Ambil notifikasi yang DITUJUKAN kepada user (aturan audiens tunggal).

    Sejak 2026-08-07 memakai `notif_audience_query` di `utils/notif_unified`:
    `user_id` == saya, ATAU `target_user_ids` memuat saya, ATAU `target_roles`
    memuat role saya. Notifikasi tanpa target hanya untuk admin/owner.
    Sebelumnya bel hanya membaca konvensi lama (target_user_ids/target_roles di
    akar dokumen) sehingga peringatan PO/piutang, cuti, payroll, absensi dan
    rapor RnD tersimpan tetapi tidak pernah tampil.
    """
    from utils.notif_unified import notif_audience_query
    rows = await db.notifications.find(
        notif_audience_query(user), {"_id": 0}).sort("created_at", -1).to_list(limit)
    return rows


@router.get("/categories")
async def list_categories(request: Request):
    """Untuk bel ringkas: kategori + jumlah belum dibaca + hitungan kotak masuk.

    2026-11-02 (K30) — `action_open` = lencana bel "Perlu Tindakan": notifikasi
    action terbuka + pekerjaan yang dihitung dari dokumen (Approval Badge lama)
    yang belum diwakili notifikasi; `info_unread` = pemberitahuan belum dibaca.
    `total_unread` tidak lagi menghitung action yang sudah tertutup (riwayat)."""
    user = await require_auth(request)
    db = get_db()
    scope = await category_scope(db, user)
    allowed = scope["allowed"]
    # 2026-11-02 — hitungan dari SELURUH notifikasi (bukan 200 terbaru).
    try:
        n_latest = max(1, min(10, int(request.query_params.get("latest") or 3)))
    except ValueError:
        n_latest = 3
    open_rows: list = []
    rows = await _scan(db, user, scope, rows_out=open_rows)
    counts = {k: {"total": 0, "unread": 0, "action": 0} for k in allowed}
    tabs = {TAB_ACTION: 0, TAB_INFO: 0, TAB_HISTORY: 0}
    info_unread = 0
    for _id, cat, unread, tab in rows:
        tabs[tab] += 1
        if tab == TAB_HISTORY:
            continue
        counts[cat]["total"] += 1
        if unread:
            counts[cat]["unread"] += 1
        if tab == TAB_ACTION:
            counts[cat]["action"] += 1
        elif unread:
            info_unread += 1
    groups = await _action_groups(db, user, open_rows)
    from_docs = sum(g["count"] for g in groups)
    head = [r for r in rows if r[3] != TAB_HISTORY][:n_latest]
    full = await _load_full(db, [r[0] for r in head])
    meta_of = {r[0]: r for r in head}
    latest = [_present(d, meta_of[d["id"]][1], meta_of[d["id"]][2]) for d in full]
    return serialize_doc({
        "categories": [
            {**c, **counts[c["key"]]} for c in CATEGORIES if c["key"] in counts
        ],
        "total_unread": sum(v["unread"] for v in counts.values()),
        "total": sum(v["total"] for v in counts.values()),
        "latest": latest,
        "action_open": tabs[TAB_ACTION] + from_docs,
        "action_notifications": tabs[TAB_ACTION],
        "action_from_documents": from_docs,
        "info_unread": info_unread,
        "info_total": tabs[TAB_INFO],
        "history_total": tabs[TAB_HISTORY],
    })


@router.get("/categorized")
async def list_categorized(request: Request, category: Optional[str] = None,
                           unread_only: bool = Query(False), limit: int = Query(100, ge=1, le=300),
                           skip: int = Query(0, ge=0), tab: Optional[str] = None):
    """Daftar untuk popup "Pusat Notifikasi".

    2026-11-02 — paginasi sederhana (`skip` + `limit`, `has_more`, `total`).
    Dulu hanya 300 dokumen terbaru yang dipindai ⇒ notifikasi lama tak terjangkau.
    `tab` opsional (action/info/history, K30); tanpa `tab` = semua kecuali riwayat.
    """
    user = await require_auth(request)
    db = get_db()
    scope = await category_scope(db, user)
    allowed = scope["allowed"]
    if category and category not in allowed:
        raise HTTPException(403, "Kategori ini tidak diaktifkan untuk peran Anda.")
    if tab and tab not in (TAB_ACTION, TAB_INFO, TAB_HISTORY):
        raise HTTPException(400, "tab harus action, info, atau history")
    rows = await _scan(db, user, scope, category=category, unread_only=unread_only, tab=tab)
    if not tab:
        rows = [r for r in rows if r[3] != TAB_HISTORY]
    page = rows[skip:skip + limit]
    full = await _load_full(db, [r[0] for r in page])
    meta_of = {r[0]: r for r in page}
    portals = await _user_portals(db, user)
    out = [_present(d, meta_of[d["id"]][1], meta_of[d["id"]][2], portals) for d in full]
    return serialize_doc({"items": out, "count": len(out), "total": len(rows),
                          "unread": sum(1 for r in rows if r[2]),
                          "skip": skip, "limit": limit,
                          "has_more": skip + len(page) < len(rows),
                          "allowed_categories": allowed,
                          "categories": [c for c in CATEGORIES if c["key"] in allowed]})


@router.get("/inbox")
async def unified_inbox(request: Request, tab: str = Query(TAB_ACTION),
                        category: Optional[str] = None,
                        limit: int = Query(30, ge=1, le=200), skip: int = Query(0, ge=0)):
    """SATU kotak masuk (K30): bel + Approval Inbox lama.

    · tab=action  — "Perlu Tindakan": `groups` (pekerjaan dari dokumen yang belum
      diwakili notifikasi) + `items` (notifikasi action terbuka). Sebelum
      ditampilkan, action milik user diperiksa ulang (`resolve_rows`) supaya yang
      sudah selesai langsung pindah ke riwayat.
    · tab=info    — "Pemberitahuan".
    · tab=history — action yang sudah tertutup (alasan + waktu).
    """
    if tab not in (TAB_ACTION, TAB_INFO, TAB_HISTORY):
        raise HTTPException(400, "tab harus action, info, atau history")
    user = await require_auth(request)
    db = get_db()
    scope = await category_scope(db, user)
    if category and category not in scope["allowed"]:
        raise HTTPException(403, "Kategori ini tidak diaktifkan untuk peran Anda.")
    groups: list = []
    if tab == TAB_ACTION:
        mine: list = []
        await _scan(db, user, scope, tab=TAB_ACTION, rows_out=mine)
        try:
            await resolve_rows(db, mine)
        except Exception:  # noqa: BLE001 — penyegaran gagal ⇒ tetap tampilkan data terakhir
            import logging
            logging.getLogger(__name__).warning("[notif] penyegaran action gagal", exc_info=True)
    open_rows: list = []
    all_rows = await _scan(db, user, scope, category=category, rows_out=open_rows)
    rows = [r for r in all_rows if r[3] == tab]
    if tab == TAB_ACTION and not category:
        groups = await _action_groups(db, user, open_rows)
    page = rows[skip:skip + limit]
    full = await _load_full(db, [r[0] for r in page])
    meta_of = {r[0]: r for r in page}
    portals = await _user_portals(db, user)
    items = [_present(d, meta_of[d["id"]][1], meta_of[d["id"]][2], portals) for d in full]
    n_tab = {TAB_ACTION: 0, TAB_INFO: 0, TAB_HISTORY: 0}
    info_unread = 0
    for r in all_rows:
        n_tab[r[3]] += 1
        if r[3] == TAB_INFO and r[2]:
            info_unread += 1
    from_docs = sum(g["count"] for g in groups) if tab == TAB_ACTION else None
    return serialize_doc({
        "tab": tab, "items": items, "groups": groups, "count": len(items),
        "total": len(rows), "skip": skip, "limit": limit,
        "has_more": skip + len(page) < len(rows),
        "counts": {"action": n_tab[TAB_ACTION] + (from_docs or 0) if from_docs is not None else None,
                   "action_notifications": n_tab[TAB_ACTION],
                   "info_unread": info_unread, "info_total": n_tab[TAB_INFO],
                   "history": n_tab[TAB_HISTORY]},
        "categories": [c for c in CATEGORIES if c["key"] in scope["allowed"]],
    })


@router.get("/category-config")
async def read_config(request: Request):
    user = await require_auth(request)
    if (user.get("role") or "").lower() not in SUPER_ROLES:
        raise HTTPException(403, "Hanya admin yang boleh melihat konfigurasi notifikasi.")
    db = get_db()
    cfg = await get_matrix(db)
    roles = sorted(set(list(cfg["matrix"].keys()) +
                       [r for lst in PORTAL_ACCESS.values() for r in lst]))
    return serialize_doc({"categories": CATEGORIES, "roles": roles,
                          "matrix": cfg["matrix"], "updated_at": cfg.get("updated_at"),
                          "locked_categories": [PERSONAL_CATEGORY],
                          # K31 (2026-11-02) — retensi diatur di pengaturan yang SAMA.
                          "retention_days": clamp_retention_days(
                              cfg.get("retention_days") or RETENTION_DEFAULT_DAYS),
                          "retention_default_days": RETENTION_DEFAULT_DAYS})


@router.put("/category-config")
async def save_config(request: Request):
    user = await require_auth(request)
    if (user.get("role") or "").lower() not in SUPER_ROLES:
        raise HTTPException(403, "Hanya admin yang boleh mengubah konfigurasi notifikasi.")
    db = get_db()
    body = await request.json()
    matrix = body.get("matrix")
    has_retention = body.get("retention_days") not in (None, "")
    if matrix is None and has_retention:
        matrix = (await get_matrix(db))["matrix"]      # simpan retensi saja
    if not isinstance(matrix, dict):
        raise HTTPException(400, "matrix wajib berupa objek {role: [kategori]}")
    clean = {}
    for role, cats in matrix.items():
        if not isinstance(cats, list):
            raise HTTPException(400, f"nilai untuk role '{role}' harus berupa daftar kategori")
        bad = [c for c in cats if c not in CATEGORY_KEYS]
        if bad:
            raise HTTPException(400, f"kategori tidak dikenal: {bad}")
        clean[str(role).lower()] = sorted(set(cats) | {PERSONAL_CATEGORY})
    for sr in SUPER_ROLES:
        clean[sr] = list(CATEGORY_KEYS)  # admin selalu menerima semuanya
    upd = {"matrix": clean, "updated_at": datetime.now(timezone.utc),
           "updated_by": user.get("name") or user.get("id")}
    if has_retention:
        try:
            days = int(body["retention_days"])
        except (TypeError, ValueError):
            raise HTTPException(400, "retention_days harus bilangan bulat (hari)")
        if clamp_retention_days(days) != days:
            raise HTTPException(400, "retention_days harus antara 7 dan 3650 hari")
        upd["retention_days"] = days
    await db[CFG].update_one({"id": "default"}, {"$set": upd}, upsert=True)
    cfg = await get_matrix(db)
    return {"ok": True, "matrix": clean, "locked_categories": [PERSONAL_CATEGORY],
            "retention_days": clamp_retention_days(cfg.get("retention_days") or RETENTION_DEFAULT_DAYS)}


@router.get("/my-category-prefs")
async def read_prefs(request: Request):
    user = await require_auth(request)
    db = get_db()
    scope = await category_scope(db, user)
    return serialize_doc({
        "muted_categories": scope["muted"],
        # kategori yang boleh diatur user (yang dibuka admin untuk perannya)
        "available": scope["base"],
        # yang benar-benar aktif sekarang (setelah pembisuan)
        "active": scope["allowed"],
        "locked_categories": [PERSONAL_CATEGORY],
        "categories": [c for c in CATEGORIES if c["key"] in scope["base"]],
    })


@router.put("/my-category-prefs")
async def save_prefs(request: Request):
    user = await require_auth(request)
    db = get_db()
    body = await request.json()
    muted = body.get("muted_categories") or []
    bad = [c for c in muted if c not in CATEGORY_KEYS]
    if bad:
        raise HTTPException(400, f"kategori tidak dikenal: {bad}")
    # "Untuk Saya" selalu aktif — permintaan membisukannya diabaikan (bukan error)
    clean = sorted({c for c in muted if c != PERSONAL_CATEGORY})
    await db[PREF].update_one({"user_id": user.get("id")}, {"$set": {
        "user_id": user.get("id"), "muted_categories": clean,
        "updated_at": datetime.now(timezone.utc),
    }}, upsert=True)
    return {"ok": True, "muted_categories": clean,
            "active": await allowed_categories(db, user),
            "locked_categories": [PERSONAL_CATEGORY]}
