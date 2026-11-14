"""core.marketing_record_scope — PENJAGA REKAMAN PER TOKO: satu tabel untuk semua rute ber-id (14 Nov 2026).

MASALAH YANG DITUTUP
--------------------
Owner (14 Nov 2026): "penerapan filtering berdasarkan toko di marketing belum sepenuhnya".
`middleware.marketing_scope_guard` hanya menolak permintaan yang MENYEBUT id toko (path `/accounts/{id}`,
query/body `account_id`). Rute yang membawa id REKAMAN — `/orders/{order_id}`, `/kol/creators/{creator_id}`,
`/livehost/{host_id}`, `/tasks/{task_id}` … — tidak pernah memeriksa toko rekaman itu. PIC toko A cukup
menukar id di URL untuk membuka, mengubah, atau menghapus pesanan, kreator, sesi live, dan tugas toko B.
Menambal ±45 handler satu per satu berarti handler ke-46 akan lupa; karena itu aturannya satu tabel.

TABEL
-----
`ATURAN` memetakan AWALAN pola rute sampai satu parameter (mis. ``/api/marketing/orders/{order_id}``,
berlaku juga untuk ``/orders/{order_id}/status``) → cara menemukan toko rekaman:

* ``toko``      — kolom toko di rekaman: teks (`account_id`) atau daftar (`assigned_account_ids`,
                  `target_account_ids`). Terlihat bila ADA toko yang dipegang pemakai.
* ``lewat``     — toko diambil dari rekaman lain (riwayat aksi katalog → katalog → toko;
                  usulan harga → item katalog → toko; progres pelatihan → host → toko).
* ``tulis_toko``— kolom toko yang dipakai untuk permintaan TULIS (peluncuran produk: hanya toko
                  pemilik rencana yang boleh mengubah; toko sasaran hanya melihat).
* ``tulis_semua``— permintaan TULIS butuh SEMUA tokonya dipegang (aksi yang menyentuh beberapa toko).
* ``kosong_boleh``— rekaman TANPA toko adalah milik bersama (skrip live global, templat umum).
* ``jenis="toko"``      — parameternya sendiri id/kode TOKO (`/accounts/{account_key}`).
* ``jenis="semua_toko"``— data yang belum bisa dipetakan ke toko (event webhook): hanya peran semua-toko.

Pemakai berlingkup toko (`SCOPED_ROLES`) yang tidak memegang toko rekaman → **404 "Data tidak ditemukan atau
milik toko lain."** (keberadaan rekaman tidak dibocorkan). Rekaman yang tidak ada dilewatkan — route-nya
menjawab 404 sendiri.

`BEBAS` = parameter yang SENGAJA tidak dijaga tabel ini, masing-masing dengan alasannya. Uji
`tests/unit/test_filter_toko_rekaman.py` menghitung SEMUA rute ber-parameter di `/api/marketing` dan
`/api/dewi/kreator-requests`; rute baru yang tidak ada di `ATURAN` maupun `BEBAS` membuat uji gagal.

`RUJUKAN_BODY` — id kreator/host yang dikirim di body JSON (`creator_id`, `kreator_id`, `host_id`,
`host_ids`) juga diperiksa: kreator/host yang sudah bertugas di toko lain dan TIDAK di toko pemakai → 403.
Kreator/host yang belum ditugaskan ke toko mana pun tidak ditolak (belum milik toko siapa pun).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from core.marketing_account_scope import ACCOUNTS, CREATORS, HOSTS, NO_ACCOUNT_HINT

M = "/api/marketing"
KREATOR_REQ = "/api/dewi/kreator-requests"
AWALAN = (M + "/", KREATOR_REQ)

PESAN_TIDAK_ADA = "Data tidak ditemukan atau milik toko lain."
PESAN_SEMUA_TOKO = ("Data ini belum terhubung ke toko mana pun, jadi hanya bisa dibuka peran yang melihat semua "
                    "toko (owner, SPV, atau manajer Marketing).")
METODE_BACA = ("GET", "HEAD", "OPTIONS")


@dataclass(frozen=True)
class Aturan:
    koleksi: str = ""
    kunci: Tuple[str, ...] = ("id",)
    toko: Tuple[str, ...] = ("account_id",)
    lewat: Optional[Tuple[str, str, str]] = None      # (kolom rekaman, koleksi induk, kolom toko induk)
    kosong_boleh: bool = False
    tulis_toko: Optional[Tuple[str, ...]] = None
    tulis_semua: bool = False
    jenis: str = "rekaman"                            # rekaman | toko | semua_toko
    label: str = "data"


@dataclass(frozen=True)
class Tolak:
    status: int
    detail: str


def _rek(koleksi: str, **kw) -> Aturan:
    return Aturan(koleksi=koleksi, **kw)


TOKO = Aturan(jenis="toko", label="toko")
SEMUA_TOKO = Aturan(jenis="semua_toko")
KREATOR = Aturan(koleksi=CREATORS, toko=("assigned_account_ids",), label="kreator")
HOST = Aturan(koleksi=HOSTS, toko=("assigned_account_ids",), label="host live")
KATALOG = _rek("marketing_catalogs", label="katalog")
SESI_IMPOR = _rek("marketing_data_import_sessions", kosong_boleh=True, label="sesi impor")

# ── TABEL PENJAGA: awalan pola rute (sampai satu parameter) → aturan ─────────
ATURAN: Dict[str, Aturan] = {
    # parameter = toko itu sendiri (id, kode toko, atau kode kanal lama)
    f"{M}/account-assign/{{account_id}}": TOKO,
    f"{M}/accounts/{{account_id}}": TOKO,
    f"{M}/accounts/{{account_key}}": TOKO,
    f"{M}/withdrawals/accounts/{{account_id}}": TOKO,
    # rekaman ber-`account_id`
    f"{M}/ads/campaigns/{{entry_id}}": _rek("marketing_ads_data"),
    f"{M}/budget/spend/{{sid}}": _rek("marketing_spend_entries"),
    f"{M}/complaints/{{complaint_id}}": _rek("marketing_complaints"),
    f"{M}/content-calendar/{{entry_id}}": _rek("marketing_content_calendar"),
    f"{M}/discounts/{{disc_id}}": _rek("marketing_discounts"),
    f"{M}/kol/requests/{{request_id}}": _rek("marketing_creator_item_requests"),
    f"{M}/kol/sessions/{{session_id}}": _rek("marketing_creator_sessions"),
    f"{M}/live/sessions/{{session_id}}": _rek("marketing_live_sessions"),
    f"{M}/livehost/shifts/{{shift_id}}": _rek("marketing_livehost_shifts"),
    f"{M}/orders/{{order_id}}": _rek("marketing_orders", kunci=("id", "order_id")),
    f"{M}/returns/credit-notes/{{cn_id}}": _rek("rahaza_credit_notes"),
    f"{M}/returns/{{return_id}}": _rek("marketing_returns"),
    f"{M}/reviews/{{review_id}}": _rek("marketing_reviews"),
    f"{M}/settlements/import/mapping/{{map_id}}": _rek("marketing_settlement_import_maps"),
    f"{M}/settlements/{{sid}}": _rek("marketing_settlements"),
    f"{M}/targets/{{target_id}}": _rek("marketing_account_targets"),
    f"{M}/tasks/{{task_id}}": _rek("marketing_tasks"),
    f"{M}/withdrawals/{{wid}}": _rek("marketing_platform_withdrawals"),
    f"{KREATOR_REQ}/{{request_id}}": _rek("dewi_kreator_requests"),
    f"{M}/catalogs/{{catalog_id}}": KATALOG,
    f"{M}/catalog-tools/{{catalog_id}}": KATALOG,
    f"{M}/data-import/sessions/{{session_id}}": SESI_IMPOR,
    f"{M}/impor-paket/sesi/{{session_id}}": SESI_IMPOR,
    # milik bersama bila tanpa toko
    f"{M}/livehost/scripts/{{script_id}}": _rek("marketing_livehost_scripts", kosong_boleh=True),
    f"{M}/task-templates/{{template_id}}": _rek("marketing_task_templates", kosong_boleh=True),
    # orang yang bertugas di beberapa toko (terlihat bila salah satu tokonya dipegang)
    f"{M}/kol/creators/{{creator_id}}": KREATOR,
    f"{M}/kol-leaderboard/{{kol_id}}": KREATOR,
    f"{M}/budget/kol-cost/{{creator_id}}": KREATOR,
    f"{M}/targets/creator/{{creator_id}}": KREATOR,
    f"{M}/livehost/{{host_id}}": HOST,
    # peluncuran: pemilik ATAU sasaran boleh melihat; hanya toko pemilik yang boleh mengubah
    f"{M}/product-launches/{{launch_id}}": _rek("marketing_product_launches",
                                               toko=("account_id", "target_account_ids"),
                                               tulis_toko=("account_id",)),
    # toko lewat rekaman lain
    f"{M}/catalog-tools/runs/{{run_id}}": _rek("marketing_catalog_bulk_runs", toko=(),
                                               lewat=("catalog_ids", "marketing_catalogs", "account_id"),
                                               tulis_semua=True),
    f"{M}/advanced-ai/pricing/suggestions/{{suggestion_id}}": _rek(
        "marketing_dynamic_pricing_suggestions", toko=(),
        lewat=("catalog_item_ids", "marketing_catalog_items", "account_id"), tulis_semua=True),
    f"{M}/livehost/training/progress/{{progress_id}}": _rek(
        "marketing_livehost_training_progress", toko=(), lewat=("host_id", HOSTS, "assigned_account_ids")),
    # belum bisa dipetakan ke toko (payload webhook tidak membawa toko kita)
    f"{M}/webhooks/events/{{event_id}}": SEMUA_TOKO,
}

# ── PARAMETER YANG SENGAJA TIDAK DIJAGA TABEL (dengan alasan) ────────────────
BEBAS: Dict[str, str] = {
    f"{M}/advanced-ai/ab-tests/{{exp_id}}":
        "Eksperimen A/B tidak tercatat per toko (hanya platform) — rekaman tanpa toko, lihat laporan.",
    f"{M}/advanced-ai/ab-tests/{{exp_id}}/variants/{{variant_id}}":
        "Varian di dalam satu eksperimen A/B (ikut eksperimennya).",
    f"{M}/catalogs/{{catalog_id}}/items/{{item_id}}":
        "Item selalu dicari bersama catalog_id ({'id': item_id, 'catalog_id': catalog_id}); katalognya dijaga.",
    f"{M}/data-import/formats/{{fingerprint}}":
        "Ingatan susunan kolom impor dipakai bersama semua toko (bukan data toko).",
    f"{M}/data-import/template/{{source_type}}":
        "Unduh templat berkas kosong — tidak ada data toko.",
    f"{M}/impor-paket/{{paket_id}}":
        "Paket impor milik pembuatnya: _muat hanya membuka paket sendiri (atau peran semua-toko) dan tiap "
        "berkas diperiksa assert_account_visible.",
    f"{M}/impor-paket/{{paket_id}}/berkas/{{idx}}":
        "Nomor urut berkas di dalam paket impor (ikut paketnya).",
    f"{M}/integration-settings/{{platform}}":
        "Pengaturan integrasi per PLATFORM, bukan per toko.",
    f"{M}/kol/catalog/{{item_id}}":
        "Pintu lama yang selalu menjawab 410 (katalog kreator = Manajemen Katalog).",
    f"{M}/kol/creators/{{creator_id}}/incentive/entries/{{entry_id}}":
        "Entri dihapus bersama creator_id ({'id': entry_id, 'creator_id': creator_id}); kreatornya dijaga.",
    f"{M}/live/sessions/{{session_id}}/products/{{line_id}}":
        "Baris rincian dicari bersama session_id; sesi live-nya dijaga.",
    f"{M}/livehost/portal/notifications/{{notif_id}}":
        "Portal host (token host, bukan pemakai ERP): hanya notifikasi milik host itu.",
    f"{M}/livehost/portal/training/{{progress_id}}":
        "Portal host (token host, bukan pemakai ERP): hanya progres milik host itu.",
    f"{M}/livehost/training/{{training_id}}":
        "Modul pelatihan host dipakai bersama semua toko (bukan data toko).",
    f"{M}/samples/{{sample_id}}":
        "Lingkup sampel diurus di routes/marketing_samples_routes.py (sedang diubah sesi sampel/anggaran).",
}

# id kreator/host di body JSON yang ikut diperiksa (lihat docstring)
RUJUKAN_BODY: Dict[str, Aturan] = {
    "creator_id": KREATOR, "kreator_id": KREATOR, "host_id": HOST, "host_ids": HOST,
}
# Body sampel tidak diperiksa di sini: lingkupnya diurus berkas sampel (sesi lain).
RUJUKAN_BODY_DILEWATI = (f"{M}/samples",)

_PARAM = re.compile(r"\{([^}:]+)(?::[^}]*)?\}")


def parameter_rute(pola: str) -> List[Tuple[str, str]]:
    """``/a/{x}/b/{y}`` → ``[("x", "/a/{x}"), ("y", "/a/{x}/b/{y}")]`` — kunci tabel per parameter."""
    return [(m.group(1), pola[:m.end()]) for m in _PARAM.finditer(pola)]


def dijaga(path: str) -> bool:
    return path.startswith(AWALAN[0]) or path == KREATOR_REQ or path.startswith(KREATOR_REQ + "/")


def _daftar(v: Any) -> List[str]:
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v if x]
    return [str(v)] if v else []


async def toko_rekaman(db, aturan: Aturan, nilai: str, *, tulis: bool = False) -> Optional[Set[str]]:
    """Himpunan toko satu rekaman; ``None`` = rekaman tidak ada."""
    kolom = aturan.tulis_toko if (tulis and aturan.tulis_toko) else aturan.toko
    q = ({aturan.kunci[0]: nilai} if len(aturan.kunci) == 1
         else {"$or": [{k: nilai} for k in aturan.kunci]})
    proj = {"_id": 0, "id": 1, **{k: 1 for k in kolom}}
    if aturan.lewat:
        proj[aturan.lewat[0]] = 1
    doc = await db[aturan.koleksi].find_one(q, proj)
    if doc is None:
        return None
    out: Set[str] = set()
    for k in kolom:
        out.update(_daftar(doc.get(k)))
    if aturan.lewat:
        kol, koleksi_induk, kol_toko = aturan.lewat
        ids = _daftar(doc.get(kol))
        if ids:
            induk = await db[koleksi_induk].find({"id": {"$in": ids}}, {"_id": 0, kol_toko: 1}).to_list(2000)
            for d in induk:
                out.update(_daftar(d.get(kol_toko)))
    return out


async def _periksa_satu(db, visible: List[str], metode: str, aturan: Aturan, nilai: str) -> Optional[Tolak]:
    if aturan.jenis == "semua_toko":
        return Tolak(403, PESAN_SEMUA_TOKO)
    if aturan.jenis == "toko":
        acc = await db[ACCOUNTS].find_one(
            {"$or": [{"id": nilai}, {"account_code": nilai}, {"code": nilai}, {"channel_code": nilai}]},
            {"_id": 0, "id": 1, "account_name": 1})
        if not acc or acc.get("id") in visible:
            return None
        return Tolak(403, "Toko berikut tidak di-assign ke Anda, jadi datanya tidak bisa dibuka atau diubah: "
                          f"{acc.get('account_name') or acc.get('id')}. " + NO_ACCOUNT_HINT)
    tulis = metode.upper() not in METODE_BACA
    toko = await toko_rekaman(db, aturan, nilai, tulis=tulis)
    if toko is None:
        return None                                   # rekaman tidak ada → 404 urusan route
    if not toko:
        return None if aturan.kosong_boleh else Tolak(404, PESAN_TIDAK_ADA)
    vis = set(visible)
    ok = toko <= vis if (tulis and aturan.tulis_semua) else bool(toko & vis)
    return None if ok else Tolak(404, PESAN_TIDAK_ADA)


async def periksa_rute(db, visible: List[str], metode: str, pola: str,
                       params: Dict[str, Any]) -> Optional[Tolak]:
    """Periksa setiap parameter rute yang ada di `ATURAN`. ``None`` = boleh lanjut."""
    for param, kunci in parameter_rute(pola):
        aturan = ATURAN.get(kunci)
        nilai = params.get(param)
        if aturan is None or nilai in (None, ""):
            continue
        tolak = await _periksa_satu(db, visible, metode, aturan, str(nilai))
        if tolak:
            return tolak
    return None


async def periksa_rujukan(db, visible: List[str], data: Any, path: str = "") -> Optional[Tolak]:
    """id kreator/host di body JSON: tolak bila orang itu bertugas di toko lain dan TIDAK di toko pemakai."""
    if not isinstance(data, dict) or any(path.startswith(p) for p in RUJUKAN_BODY_DILEWATI):
        return None
    vis = set(visible)
    for kunci, aturan in RUJUKAN_BODY.items():
        for nilai in _daftar(data.get(kunci)):
            toko = await toko_rekaman(db, aturan, nilai)
            if toko and not (toko & vis):
                return Tolak(403, f"{aturan.label.capitalize()} yang dipilih bertugas di toko yang tidak di-assign "
                                  f"ke Anda, jadi tidak bisa dipakai di sini. " + NO_ACCOUNT_HINT)
    return None


# ── pencocokan rute: tanya router FastAPI sendiri (urutan & regex persis sama) ──
def _rute_dijaga(app) -> list:
    routes = list(getattr(getattr(app, "router", None), "routes", None) or [])
    state = getattr(app, "state", None)
    hit = getattr(state, "_rute_lingkup_toko", None) if state is not None else None
    if hit and hit[0] == len(routes):
        return hit[1]
    pilih = [r for r in routes if hasattr(r, "matches") and dijaga(str(getattr(r, "path", "")))]
    if state is not None:
        try:
            state._rute_lingkup_toko = (len(routes), pilih)
        except Exception:  # noqa: BLE001
            pass
    return pilih


def cocokkan_rute(app, path: str, metode: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(pola rute, parameter) dari rute PERTAMA yang cocok penuh — sama dengan pilihan Starlette."""
    if app is None:
        return None
    from starlette.routing import Match
    scope = {"type": "http", "path": path, "root_path": "", "method": metode.upper(), "path_params": {}}
    for r in _rute_dijaga(app):
        try:
            m, child = r.matches(scope)
        except Exception:  # noqa: BLE001
            continue
        if m == Match.FULL:
            return str(r.path), dict((child or {}).get("path_params") or {})
    return None


def kunci_tabel() -> Iterable[str]:
    return list(ATURAN) + list(BEBAS)
