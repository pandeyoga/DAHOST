"""core.journal_import — format Excel pencatatan/penjurnalan yang bisa DIIMPOR ke sistem.

Permintaan owner 2026-09-24: "data finance tidak bisa sepenuhnya detail dimasukkan ke sistem,
saya butuh format excel pencatatan yang nanti bisa di-import".

Dua sheet yang dibaca (boleh salah satu saja):
  * MUTASI_KAS_BANK — satu baris = satu mutasi rekening (gaya "Lap. Mutasi Rekening" owner):
      tanggal | kode_kas_bank | keterangan | pemasukan | pengeluaran | kode_akun_lawan | referensi
    → jurnal 2 baris: pemasukan = D kas/bank, K akun lawan; pengeluaran = D akun lawan, K kas/bank.
  * JURNAL_UMUM — jurnal bebas banyak baris, dikelompokkan per `no_jurnal`:
      no_jurnal | tanggal | kode_akun | debit | kredit | keterangan | referensi
Setiap baris punya `referensi` opsional.

2026-11-02 (audit No.52) — kunci anti-dobel = ISI baris/jurnal (tanggal + akun + debit + kredit +
keterangan + referensi), BUKAN sidik berkas + nomor baris. Dulu berkas yang ditambah satu baris
(atau sekadar dibuka & disimpan ulang) punya sidik baru → SEMUA baris lama terposting lagi.
Baris kembar yang sah (isi identik, mis. dua parkir Rp5.000 di hari yang sama) dihitung per
kemunculan: kemunculan ke-n hanya diposting bila di buku baru ada < n jurnal impor berisi sama.
`source_ref` = `import:<hash isi>:<n>` (unik → indeks DB menolak dobel saat dua unggahan paralel).
Jurnal impor lama (kunci format lama) tetap dikenali karena hash dihitung dari isi jurnalnya.
"""
from __future__ import annotations

import hashlib
import io
from datetime import date, datetime
from uuid import uuid4

import openpyxl
from openpyxl.styles import Font, PatternFill
from utils.waktu import now_utc

SOURCE_MODULE = "journal_import"
SHEET_MUTASI = "MUTASI_KAS_BANK"
SHEET_UMUM = "JURNAL_UMUM"
COLS_MUTASI = ["tanggal", "kode_kas_bank", "keterangan", "pemasukan", "pengeluaran", "kode_akun_lawan", "referensi"]
COLS_UMUM = ["no_jurnal", "tanggal", "kode_akun", "debit", "kredit", "keterangan", "referensi"]
_HDR = Font(bold=True, color="FFFFFF")
_FILL = PatternFill("solid", fgColor="1F4E78")

PETUNJUK = [
    "FORMAT IMPOR PENCATATAN / PENJURNALAN — CV. Dewi Aditya",
    "1. Sheet MUTASI_KAS_BANK: satu baris = satu mutasi rekening. Isi kode_kas_bank (lihat sheet DAFTAR_AKUN, kelompok kas/bank),",
    "   keterangan, lalu SALAH SATU: pemasukan atau pengeluaran (Rp, tanpa titik), dan kode_akun_lawan (akun biaya/pendapatan/",
    "   hutang/piutang/modal). Contoh: token listrik 1.003.000 dari BCA Dekka → kode_kas_bank 1-1211, pengeluaran 1003000, akun lawan 6-xxxx.",
    "   Transfer antar rekening sendiri: tulis SATU baris pengeluaran dari rekening asal dengan kode_akun_lawan = kode rekening tujuan.",
    "2. Sheet JURNAL_UMUM: untuk jurnal yang lebih dari 2 baris. Baris dengan no_jurnal yang sama menjadi satu jurnal; total debit harus = kredit.",
    "3. tanggal: YYYY-MM-DD atau sel bertipe tanggal Excel. referensi: nomor bukti/nota (opsional).",
    "4. Unggah di Portal Keuangan → Akuntansi → Impor Jurnal (Excel): PRATINJAU dulu (kesalahan ditampilkan per baris), baru Posting.",
    "5. Mengunggah berkas yang sama dua kali AMAN — baris yang sudah masuk dilewati (kunci: isi baris = tanggal, akun, nominal,",
    "   keterangan, referensi). Berkas boleh ditambah baris baru lalu diunggah ulang: hanya baris baru yang diposting.",
    "6. Kode akun hanya boleh akun DETAIL (bukan header) yang aktif — lihat sheet DAFTAR_AKUN.",
]


def _head(ws, cols):
    ws.append(cols)
    for c in ws[1]:
        c.font, c.fill = _HDR, _FILL
    for i in range(len(cols)):
        ws.column_dimensions[chr(65 + i)].width = 22


async def build_template(db) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PETUNJUK"
    for r in PETUNJUK:
        ws.append([r])
    ws.column_dimensions["A"].width = 130
    ws = wb.create_sheet(SHEET_MUTASI)
    _head(ws, COLS_MUTASI)
    ws.append(["2026-09-24", "1-1219", "KR Otomatis DA Store Karanganyar", 191152, None, "4-1100", ""])
    ws.append(["2026-09-24", "1-1211", "Token listrik IDPEL 32177959940", None, 1003000, "6-2200", ""])
    ws.append(["2026-09-24", "1-1211", "Pinjaman modal tanpa bunga → CV DA Official (transfer antar rekening)", None, 9400000, "1-1219", ""])
    ws = wb.create_sheet(SHEET_UMUM)
    _head(ws, COLS_UMUM)
    ws.append(["JU-001", "2026-09-24", "5-1100", 42629400, None, "Pembelian kain rayon RAYONINDO", "INV-123"])
    ws.append(["JU-001", "2026-09-24", "1-1219", None, 42629400, "Bayar via BCA DA Official", "INV-123"])
    ws = wb.create_sheet("DAFTAR_AKUN")
    _head(ws, ["kode_akun", "nama_akun", "tipe", "kelompok"])
    async for a in db.rahaza_coa_accounts.find({"active": True, "is_group": {"$ne": True}}, {"_id": 0}).sort("code", 1):
        kb = "KAS/BANK" if str(a.get("code", "")).startswith(("1-11", "1-12")) else ""
        ws.append([a.get("code"), a.get("name"), a.get("type"), kb])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _num(v) -> float:
    if v in (None, "", "-"):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("Rp", "").replace(".", "").replace(",", ".").replace(" ", "")
    return float(s) if s else 0.0


def _date(v) -> str:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v or "").strip()
    if not s:
        raise ValueError("tanggal kosong")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"tanggal '{s}' tidak dikenal (pakai YYYY-MM-DD)")


def _norm_text(v) -> str:
    return " ".join(str(v or "").split()).casefold()


def content_hash(je_date: str, memo_full: str, lines) -> str:
    """Hash ISI jurnal impor: tanggal + memo (keterangan + [referensi]) + baris (akun, debit, kredit,
    keterangan) tanpa memandang urutan baris. Dipakai untuk baris berkas DAN jurnal yang sudah ada."""
    norm = sorted(
        (str((ln.get("account_code") if isinstance(ln, dict) else ln[0]) or "").strip(),
         round(float((ln.get("debit") if isinstance(ln, dict) else ln[1]) or 0), 2),
         round(float((ln.get("credit") if isinstance(ln, dict) else ln[2]) or 0), 2),
         _norm_text(ln.get("description") if isinstance(ln, dict) else ln[3]))
        for ln in lines or [])
    raw = "|".join([str(je_date)[:10], _norm_text(memo_full)] + [f"{c}~{d:.2f}~{k:.2f}~{t}" for c, d, k, t in norm])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def memo_full(memo: str, reference: str) -> str:
    return memo + (f" [{reference}]" if reference else "")


def assign_import_keys(candidates: list, existing: dict) -> tuple:
    """Murni: pilih kandidat yang BELUM ada di buku. `existing` = {hash: {"count": n, "used": {idx}}}.
    Kemunculan ke-k suatu hash dilewati bila k ≤ jumlah jurnal aktif berisi sama; sisanya diberi
    kunci `import:<hash>:<idx>` dengan idx terkecil yang belum dipakai. → (yang diposting, dilewati)."""
    seen: dict = {}
    fresh, skipped = [], 0
    for c in candidates:
        h = c["content_hash"]
        seen[h] = seen.get(h, 0) + 1
        ex = existing.setdefault(h, {"count": 0, "used": set()})
        if seen[h] <= ex["count"]:
            skipped += 1
            continue
        idx = 1
        while idx in ex["used"]:
            idx += 1
        ex["used"].add(idx)
        fresh.append({**c, "key": f"import:{h}:{idx}"})
    return fresh, skipped


async def _existing_content(db, dates, entity=None) -> dict:
    """Tahap 8: anti-dobel per buku CV (`entity`); None = semua buku (perilaku lama)."""
    from core.entities import entity_match
    out: dict = {}
    if not dates:
        return out
    async for je in db.rahaza_journal_entries.find(
            {"source_module": SOURCE_MODULE, "status": {"$ne": "voided"}, "date": {"$in": sorted(dates)},
             **(entity_match(entity) if entity else {})},
            {"_id": 0, "date": 1, "memo": 1, "lines": 1, "source_ref": 1, "import_content_hash": 1}):
        h = je.get("import_content_hash") or content_hash(je.get("date"), je.get("memo") or "", je.get("lines") or [])
        e = out.setdefault(h, {"count": 0, "used": set()})
        e["count"] += 1
        parts = str(je.get("source_ref") or "").split(":")
        if len(parts) == 3 and parts[0] == "import" and parts[1] == h and parts[2].isdigit():
            e["used"].add(int(parts[2]))
    return out


async def parse_workbook(db, data: bytes, entity=None) -> dict:
    sha = hashlib.sha1(data).hexdigest()[:8]
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    acc = {a["code"]: a async for a in db.rahaza_coa_accounts.find({"active": True}, {"_id": 0, "code": 1, "name": 1, "type": 1, "is_group": 1})}
    errors: list = []
    cands: list = []   # kandidat jurnal (belum dicek akun) — urutan berkas dipertahankan

    def _acc(code, where):
        code = str(code or "").strip()
        a = acc.get(code)
        if not a:
            errors.append(f"{where}: kode akun '{code}' tidak ada / nonaktif")
            return None
        if a.get("is_group"):
            errors.append(f"{where}: akun '{code}' adalah header — pakai akun anaknya")
            return None
        return a

    def _line(a, d, c, desc):
        return {"account_code": a["code"], "account_name": a.get("name", ""), "account_type": a.get("type", ""),
                "debit": round(float(d), 2), "credit": round(float(c), 2), "description": desc}

    # ── Tahap 1: baca isi (tanggal, angka, kode) — tanpa cek akun ──────────────
    if SHEET_MUTASI in wb.sheetnames:
        ws = wb[SHEET_MUTASI]
        for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not r or all(v in (None, "") for v in r[:6]):
                continue
            where = f"{SHEET_MUTASI} baris {i}"
            r = list(r) + [None] * (7 - len(r))
            try:
                tgl = _date(r[0])
            except ValueError as e:
                errors.append(f"{where}: {e}")
                continue
            masuk, keluar = _num(r[3]), _num(r[4])
            if (masuk > 0) == (keluar > 0):
                errors.append(f"{where}: isi SALAH SATU pemasukan atau pengeluaran (> 0)")
                continue
            desc = str(r[2] or "").strip() or "Mutasi kas/bank"
            amt = masuk or keluar
            bank, lawan = str(r[1] or "").strip(), str(r[5] or "").strip()
            raw = ([(bank, amt, 0, desc, where), (lawan, 0, amt, desc, where)] if masuk
                   else [(lawan, amt, 0, desc, where), (bank, 0, amt, desc, where)])
            ref = str(r[6] or "").strip()
            cands.append({"sheet": SHEET_MUTASI, "row": i, "date": tgl, "memo": desc, "reference": ref,
                          "raw": raw, "total": amt,
                          "content_hash": content_hash(tgl, memo_full(desc, ref), raw)})

    if SHEET_UMUM in wb.sheetnames:
        ws = wb[SHEET_UMUM]
        groups: dict = {}
        for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not r or all(v in (None, "") for v in r[:5]):
                continue
            r = list(r) + [None] * (7 - len(r))
            no = str(r[0] or "").strip()
            if not no:
                errors.append(f"{SHEET_UMUM} baris {i}: no_jurnal kosong")
                continue
            groups.setdefault(no, []).append((i, r))
        for no, rows in groups.items():
            first = rows[0][0]
            raw, memo, refno, tgl = [], "", "", None
            ok = True
            for i, r in rows:
                where = f"{SHEET_UMUM} baris {i} ({no})"
                try:
                    tgl = tgl or _date(r[1])
                except ValueError as e:
                    errors.append(f"{where}: {e}")
                    ok = False
                    continue
                d, c = _num(r[3]), _num(r[4])
                if (d > 0) == (c > 0):
                    errors.append(f"{where}: isi SALAH SATU debit atau kredit (> 0)")
                    ok = False
                    continue
                desc = str(r[5] or "").strip()
                memo = memo or desc
                refno = refno or str(r[6] or "").strip()
                raw.append((str(r[2] or "").strip(), d, c, desc, where))
            if not ok:
                continue
            td, tc = sum(x[1] for x in raw), sum(x[2] for x in raw)
            if abs(td - tc) > 0.5:
                errors.append(f"{SHEET_UMUM} {no}: Debit Rp {td:,.0f} ≠ Kredit Rp {tc:,.0f}")
                continue
            if len(raw) < 2:
                errors.append(f"{SHEET_UMUM} {no}: minimal 2 baris")
                continue
            memo = memo or no
            cands.append({"sheet": SHEET_UMUM, "row": first, "date": tgl, "memo": memo, "reference": refno,
                          "raw": raw, "total": td, "no_jurnal": no,
                          "content_hash": content_hash(tgl, memo_full(memo, refno), raw)})

    # ── Tahap 2: anti-dobel berdasarkan ISI terhadap jurnal impor yang sudah ada ─
    existing = await _existing_content(db, {c["date"] for c in cands}, entity)
    fresh, skipped = assign_import_keys(cands, existing)

    # ── Tahap 3: cek akun hanya untuk yang akan diposting ───────────────────────
    journals = []
    for c in fresh:
        lines, ok = [], True
        for code, d, k, desc, where in c["raw"]:
            a = _acc(code, where)
            if not a:
                ok = False
                continue
            lines.append(_line(a, d, k, desc))
        if not ok:
            continue
        j = {k: v for k, v in c.items() if k != "raw"}
        j["lines"] = lines
        journals.append(j)

    if SHEET_MUTASI not in wb.sheetnames and SHEET_UMUM not in wb.sheetnames:
        errors.append(f"Berkas tidak punya sheet {SHEET_MUTASI} maupun {SHEET_UMUM} — unduh template dulu.")
    return {"ok": not errors, "file_sha": sha, "errors": errors, "journals": journals, "skipped_existing": skipped,
            "totals": {"journals": len(journals), "amount": round(sum(j["total"] for j in journals), 2)}}


async def post_journals(db, user: dict, journals: list, filename: str, entity: str = "DA") -> dict:
    """Tahap 8: semua jurnal satu berkas masuk ke buku SATU CV (`entity`, dari layar); akun/rekening yang
    tidak berlaku untuk CV itu membuat jurnalnya gagal (masuk daftar gagal, sisanya tetap diposting)."""
    from core.entities import validate_manual_lines
    from routes.rahaza_journals import _check_period_open, _gen_je_number, _mirror_lines, _validate_lines
    posted, failed = [], []
    for j in journals:
        try:
            d = date.fromisoformat(j["date"])
            total_d, total_c = await _validate_lines(db, j["lines"])
            await validate_manual_lines(db, j["lines"], entity, what="Jurnal impor")
            await _check_period_open(db, d, entity)
            now = now_utc()   # stempel simpan = UTC aware (dulu UTC naif)
            doc = {"id": str(uuid4()), "je_number": await _gen_je_number(db, d, "", entity), "entity": entity,
                   "date": d.isoformat(),
                   "memo": j["memo"] + (f" [{j['reference']}]" if j.get("reference") else ""),
                   "source_module": SOURCE_MODULE, "source_ref": j["key"], "import_file": filename,
                   "import_content_hash": j.get("content_hash"),  # 2026-11-02: kunci anti-dobel per isi
                   "status": "posted", "total_debit": total_d, "total_credit": total_c,
                   "created_at": now, "updated_at": now, "created_by": user["id"], "created_by_name": user.get("name", ""),
                   "posted_at": now, "posted_by": user["id"], "voided_at": None, "voided_by": None,
                   "flags": {"imported": True},
                   "lines": [{"line_id": str(uuid4()), **ln, "cost_center_id": None} for ln in j["lines"]]}
            await db.rahaza_journal_entries.insert_one(doc)
            await _mirror_lines(db, doc)
            posted.append({"je_number": doc["je_number"], "date": doc["date"], "memo": doc["memo"], "total": total_d})
        except Exception as e:  # noqa: BLE001 — satu baris gagal tidak menghentikan sisanya
            detail = getattr(e, "detail", None) or str(e)
            failed.append({"sheet": j["sheet"], "row": j["row"], "memo": j["memo"], "error": str(detail)})
    return {"posted": posted, "failed": failed, "posted_count": len(posted), "failed_count": len(failed)}
