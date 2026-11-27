"""core.penyesuaian_stok_jurnal — jurnal yang menyertai Batalkan/Pulihkan penyesuaian stok.

Paket 1 (audit keuangan 25 Nov 2026). Layar Gudang › "Batalkan penyesuaian stok"
(`routes.dewi_warehouse_smart`) membalik STOK lewat `stock_service.adjust`, tetapi jurnal persediaan
penyesuaian itu tetap ⇒ stok ≠ buku besar. Modul ini menyusun jurnal pembaliknya.

Tautan entri yang dibatalkan → jurnalnya
---------------------------------------
* Entri yang bisa dibatalkan = baris `rahaza_stock_ledger` ber-`op='adjust'`. Penulisnya kini HANYA approve Sesi
  Opname (`core.opname_engine._apply_approval` → `stock_service.adjust_by`) dengan
  `ref = {source: 'opname', session_id, session_no}`. Tambah/kurangi qty manual (`apply_material_adjust`) menulis
  `op='add'/'issue'` (jurnalnya `mvadj:<id mutasi>`) dan tidak tampil di layar itu.
* Jurnal opname = SATU per sesi: `source_ref = opname:<session_id>`, modul `inventory_count_variance`
  (stok awal: `inventory_opening_count`). Nilainya = selisih × `unit_cost` baris sesi
  (`wh_opname3_sessions.lines[]` / `result.lines[]`, kunci baris level lokasi = material_id).
  Mutasi `rahaza_material_movements` sesi itu (`ref_type='opname'`, `ref_id=<session_id>`) hanya cermin.

Karena satu jurnal sesi mencakup banyak barang, jurnal asal TIDAK di-void. Dibuat jurnal BARU sebesar perubahan
stok yang benar-benar terjadi × `unit_cost` baris sesi (dasar nilai jurnal asal), dengan akun yang sama dengan
jurnal sesi: persediaan per jenis (profil `inventory_adjust`) lawan selisih/rusak (profil
`inventory_count_variance`) — atau ekuitas saldo awal untuk sesi stok awal. Tanggal = hari ini (hari stoknya
berubah). Pulihkan = jurnal searah aslinya. Kunci sumber unik per siklus: `<arah>:<ledger_id>:<n>`.

Entri tanpa sesi opname, sesi tanpa jurnal (nilai 0 / jurnalnya sudah dibatalkan), atau barang bernilai 0 →
tidak perlu jurnal (dicatat alasannya).
"""
from __future__ import annotations

from fastapi import HTTPException

from utils.waktu import today_wib

ARAH_UNDO = "undo_adjustment"
ARAH_RESTORE = "restore_adjustment"
_ARAH_LABEL = {ARAH_UNDO: "Batalkan", ARAH_RESTORE: "Pulihkan"}


def tanpa_jurnal(alasan: str) -> dict:
    return {"perlu": False, "alasan": alasan}


def baris_sesi(sess: dict, material_id: str) -> dict | None:
    """Baris sesi (level lokasi) satu barang: hasil evaluasi saat approve (`result.lines`, memuat selisih &
    nilainya) lebih dulu, cadangan baris sesi (`lines`)."""
    for src in (((sess or {}).get("result") or {}).get("lines") or [], (sess or {}).get("lines") or []):
        for ln in src:
            if ln.get("material_id") == material_id and not ln.get("bin_id"):
                return ln
    return None


def susun_baris(nilai: float, inv_code: str, contra_code: str, memo: str) -> list:
    """Stok naik (nilai > 0): Dr persediaan / Cr lawan; stok turun: Dr lawan / Cr persediaan."""
    a = round(abs(nilai), 2)
    if nilai > 0:
        return [{"account_code": inv_code, "debit": a, "credit": 0, "description": memo},
                {"account_code": contra_code, "debit": 0, "credit": a, "description": memo}]
    return [{"account_code": contra_code, "debit": a, "credit": 0, "description": memo},
            {"account_code": inv_code, "debit": 0, "credit": a, "description": memo}]


async def rencana(db, entry: dict, qty_berubah: float, *, arah: str, urutan: int) -> dict:
    """Jurnal yang harus menyertai perubahan stok `qty_berubah` (bertanda: + stok naik) atas entri penyesuaian
    `entry` (baris `rahaza_stock_ledger`). Hanya MEMBACA.

    Return `{"perlu": False, "alasan"}` atau `{"perlu": True, source_module, source_ref, je_date, memo, lines,
    nilai, alasan: None}`. HTTPException 400 bila jurnal diperlukan tetapi akunnya belum dipetakan."""
    from core import opname_engine as oe
    from routes import rahaza_posting as rp
    ref = entry.get("ref") if isinstance(entry.get("ref"), dict) else {}
    sid = ref.get("session_id")
    if str(ref.get("source") or "") != "opname" or not sid:
        return tanpa_jurnal("penyesuaian ini bukan dari sesi opname — tidak ada jurnal asal")
    if abs(float(qty_berubah or 0)) < 1e-9:
        return tanpa_jurnal("stok tidak berubah")
    sess = await db[oe.SESS].find_one({"id": sid}, {"_id": 0})
    if not sess:
        return tanpa_jurnal("sesi opname asal tidak ditemukan")
    opening = oe.is_opening(sess)
    modul = oe.OPENING_EVENT if opening else oe.VARIANCE_EVENT
    if not await rp._find_existing_je(db, modul, f"opname:{sid}"):
        return tanpa_jurnal("sesi opname ini tidak berjurnal (selisih tanpa nilai, atau jurnalnya sudah dibatalkan)")
    ln = baris_sesi(sess, entry.get("material_id"))
    nilai = round(float(qty_berubah) * float((ln or {}).get("unit_cost") or 0), 2)
    if not ln or abs(nilai) < 0.005:
        return tanpa_jurnal("barang ini tidak bernilai di jurnal sesi opname")
    kind = ln.get("kind") or "bahan"
    inv_codes, err = await oe.inventory_codes(db, {kind})
    if err:
        raise HTTPException(400, f"Jurnal persediaan tidak bisa dibuat: {err}")
    if opening:
        from core.opening_balance import retained_earnings_code
        contra = await retained_earnings_code(db)
        role = "subledger_opening_balance.credit_retained_earnings_balancing"
    else:
        # akun lawan dipilih seperti jurnal sesinya (`opname_engine.build_je_lines`): baris beralasan "rusak"
        # yang selisihnya kurang → beban rusak; selain itu akun selisih.
        roles = oe.CONTRA_ROLES[oe.VARIANCE_EVENT]
        asal = ln.get("variance_value")
        asal = float(asal if asal is not None else (entry.get("delta") or 0))
        key = "rusak" if (ln.get("reason") == "rusak" and asal < 0) else "selisih"
        contra = str((await rp.get_mapping(db, oe.VARIANCE_EVENT)).get(roles[key]) or "").strip()
        role = f"{oe.VARIANCE_EVENT}.{roles[key]}"
    if not contra:
        raise HTTPException(400, f"Jurnal persediaan tidak bisa dibuat: akun {role} belum diisi — lengkapi di "
                                 "Profil Posting.")
    kode = ln.get("material_code") or entry.get("material_id")
    memo = (f"{_ARAH_LABEL.get(arah, arah)} penyesuaian stok {kode} · opname {sess.get('session_no') or sid} · "
            f"{float(qty_berubah):g} {ln.get('unit') or ''}").strip()
    return {"perlu": True, "alasan": None, "source_module": modul, "source_ref": f"{arah}:{entry['id']}:{urutan}",
            "je_date": today_wib(), "memo": memo, "nilai": nilai,
            "lines": susun_baris(nilai, inv_codes[kind], contra, memo)}


async def posting(db, plan: dict, user: dict) -> dict:
    from routes import rahaza_posting as rp
    return await rp._create_posted_je(db, plan["je_date"], plan["memo"], plan["source_module"], plan["source_ref"],
                                      plan["lines"], user)


async def batalkan(db, plan: dict, user: dict, alasan: str) -> dict:
    """Batalkan jurnal rencana ini (stok gagal diubah sesudah jurnalnya terbit)."""
    from routes import rahaza_posting as rp
    return await rp._void_je_by_source(db, plan["source_module"], plan["source_ref"], user, reason=alasan)
