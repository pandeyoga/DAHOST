"""Alat Asisten AI — PERSETUJUAN (Tahap C, 8 Nov 2026; agen setuju). Kontrak D, risiko MENENGAH.

  daftar_persetujuan_menunggu  (baca) yang bisa DIPUTUSKAN pengguna ini sekarang: cuti/izin/sakit, lembur,
                               permintaan pembelian (PR + Request Aksesoris lama), PO pembelian. Sumbernya daftar
                               layar yang sama: Kotak Masuk SDM (`GET /api/hr/inbox`) dan kotak persetujuan
                               Pengadaan (`GET /api/procurement/inbox`, mesin `core.pr_approval`).
  putuskan_cuti                Kotak Masuk SDM › Cuti  `POST /api/hr/inbox/leave/{id}/approve|reject`
  putuskan_lembur              Kotak Masuk SDM › Lembur `POST /api/hr/inbox/overtime/{id}/approve|reject`
  putuskan_pr                  Permintaan Pengadaan `POST /api/procurement/requests/{id}/approve|reject`
                               (Request Aksesoris lama: `/api/acc/purchase-requests/{id}/approve|reject`)
  putuskan_po_pembelian        Purchase Order pembelian `POST /api/rahaza/purchase-orders/{id}/approve|reject`.
                               BUKAN konfirmasi PO maklon (dilarang untuk AI; alat ini tidak menyentuh PO maklon).

Aturan yang dipegang:
  * semua tulisan lewat endpoint layar dengan token pengguna (`ctx.api`); tidak ada tulis DB langsung;
  * aturan siapa yang boleh memutus (peran/tahap, pemisahan tugas "bukan ajuan sendiri", tahap 2 oleh orang lain,
    "satu orang tidak menyetujui dua tahap", batas departemen, override admin yang tercatat) DITEGAKKAN endpoint.
    `siapkan` hanya membaca flag server (`can_approve`/`blocked_reason`) dan mencerminkan aturan mesin cuti/lembur
    supaya kartu yang pasti ditolak tidak ditawarkan — endpoint tetap penentu terakhir;
  * alasan keputusan (wajib, ≥ 10 karakter, diminta kartu risiko menengah) diteruskan inti sebagai `ctx.alasan` dan
    dikirim sebagai catatan persetujuan / alasan penolakan;
  * `jalankan` membaca ulang keadaan dan menolak (409) bila pengajuan sudah berubah sejak kartu dibuat;
  * mode CV Gabungan ditolak (lihat saja); dokumen pembelian & SDM dibukukan di CV Dewi Aditya;
  * TANPA `batalkan`: persetujuan/penolakan tidak punya jalan balik yang bersih (cuti disetujui hanya bisa
    DIBATALKAN lewat Portal Saya/SDM; PR/PO/lembur tidak bisa "dibatal-setujui").
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from core.asisten_ai.alat_base import AlatError, alat, tindakan
from core.asisten_ai.alat._bantu_laporan import boleh_sdm_penuh, coba, hari_ini, pangkas, samaran

log = logging.getLogger(__name__)

# ── Endpoint layar ───────────────────────────────────────────────────────────────────────────────────────
P_SDM = "/api/hr/inbox"
P_CUTI = "/api/rahaza/leaves"
P_LEMBUR = "/api/rahaza/overtime"
P_PROFIL = "/api/portal/profile"
P_PINBOX = "/api/procurement/inbox"
P_PR = "/api/procurement/requests"
P_ACC = "/api/acc/purchase-requests"
P_PO = "/api/rahaza/purchase-orders"

_ID_RX = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
_NOMOR_RX = r"^[A-Za-z0-9][A-Za-z0-9/_. -]{0,63}$"
_KOSONG = "—"
_HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
_BULAN = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
          "Oktober", "November", "Desember")
LABEL_TAHAP = "Tahap persetujuan"     # baris kartu yang dibandingkan ulang di `jalankan`

STATUS_CUTI = {"draft": "Draf", "pending_approval": "Menunggu atasan", "pending_hr_approval": "Menunggu SDM",
               "approved": "Disetujui", "rejected": "Ditolak", "cancelled": "Dibatalkan"}
CUTI_MENUNGGU = ("pending_approval", "pending_hr_approval")
JENIS_CUTI = {"cuti": "Cuti", "izin": "Izin", "sakit": "Sakit"}
BAYAR = {"paid": "Dibayar", "unpaid": "Tidak dibayar"}
BAYAR_ISIAN = {"dibayar": "paid", "tidak_dibayar": "unpaid"}
STATUS_LEMBUR = {"pending": "Menunggu persetujuan", "approved": "Disetujui", "rejected": "Ditolak",
                 "cancelled": "Dibatalkan"}
STATUS_PR = {"draft": "Draf", "submitted": "Menunggu persetujuan departemen",
             "dept_approved": "Menunggu persetujuan keuangan", "finance_approved": "Menunggu persetujuan final",
             "approved": "Disetujui", "in_procurement": "Sedang pengadaan", "completed": "Selesai",
             "rejected": "Ditolak", "cancelled": "Dibatalkan"}
PR_MENUNGGU = ("submitted", "dept_approved", "finance_approved")
STATUS_ACC = {"Draft": "Draf", "Submitted": "Menunggu persetujuan", "Approved": "Disetujui", "Rejected": "Ditolak",
              "Forwarded": "Sudah diteruskan ke Permintaan Pengadaan", "Ordered": "Sudah dipesan",
              "Received": "Sudah diterima", "Cancelled": "Dibatalkan"}
STATUS_PO = {"draft": "Draf", "pending_approval": "Menunggu persetujuan", "approved": "Disetujui",
             "partially_received": "Diterima sebagian", "fully_received": "Diterima penuh", "rejected": "Ditolak",
             "cancelled": "Dibatalkan"}
ALASAN_OVERRIDE = {"stage_role": "Anda bukan peran tahap ini", "self_approval": "Anda pembuat dokumen ini",
                   "double_stage": "Anda sudah menyetujui tahap sebelumnya",
                   "department": "departemen dokumen berbeda dengan departemen Anda"}

PESAN_BUKAN_SDM = ("Akun ini bukan penyetuju Kotak Masuk SDM (butuh hak persetujuan SDM: HR, manajer, atau owner), "
                   "jadi tidak bisa memutus cuti/izin atau lembur. Keputusan ini dilakukan penyetuju yang berhak.")
PESAN_K25_CUTI = ("Pemisahan tugas: Anda tidak boleh memutus pengajuan cuti/izin milik Anda sendiri. "
                  "Minta penyetuju lain.")
PESAN_K25_LEMBUR = ("Pemisahan tugas: Anda tidak boleh memutus pengajuan lembur milik/ajuan Anda sendiri. "
                    "Minta penyetuju lain.")
PESAN_TINGKAT2 = ("Persetujuan tingkat 2 harus oleh orang lain: Anda sudah menyetujui tingkat 1 pengajuan ini. "
                  "Minta penyetuju SDM lain.")
CATATAN_ALASAN_SETUJU = "Alasan yang Anda tulis saat menyetujui kartu ini dikirim sebagai catatan persetujuan."
CATATAN_ALASAN_TOLAK = ("Kartu ini MENOLAK pengajuan: tekan Setujui untuk menjalankan penolakan, atau Batal bila tidak "
                        "jadi. Alasan yang Anda tulis dikirim ke pemohon sebagai alasan penolakan.")
CATATAN_TANPA_BALIK = "Keputusan ini tidak bisa dibalikkan otomatis lewat Asisten AI."


# ── Bantuan tampilan ─────────────────────────────────────────────────────────────────────────────────────
def _angka(v: Any, desimal: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return _KOSONG
    s = f"{x:,.{desimal}f}".rstrip("0").rstrip(".") if desimal else f"{x:,.0f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _rp(v: Any) -> str:
    try:
        return "Rp " + _angka(round(float(v)), 0)
    except (TypeError, ValueError):
        return _KOSONG


def _tgl(s: Any) -> str:
    try:
        d = date.fromisoformat(str(s)[:10])
    except ValueError:
        return str(s or _KOSONG)
    return f"{_HARI[d.weekday()]}, {d.day} {_BULAN[d.month - 1]} {d.year}"


def _tgl_pendek(s: Any) -> str:
    try:
        d = date.fromisoformat(str(s)[:10])
    except ValueError:
        return str(s or _KOSONG)
    return f"{d.day} {_BULAN[d.month - 1][:3]} {d.year}"


def _rentang(dari: Any, sampai: Any) -> str:
    if not sampai or str(sampai)[:10] == str(dari)[:10]:
        return _tgl(dari)
    return f"{_tgl(dari)} s.d. {_tgl(sampai)}"


def _daftar_tgl(hari: list) -> str:
    """'6, 7, 9 Nov 2026' (maks. 8 tanggal, sisanya diringkas)."""
    try:
        ds = [date.fromisoformat(str(x)[:10]) for x in hari or []]
    except ValueError:
        return ", ".join(str(x) for x in hari or [])
    if not ds:
        return _KOSONG
    potong = ds[:8]
    teks = ", ".join(_tgl_pendek(d.isoformat()) if (i == len(potong) - 1 or d.month != potong[i + 1].month)
                     else str(d.day) for i, d in enumerate(potong))
    return teks + (f", dan {len(ds) - 8} hari lain" if len(ds) > 8 else "")


def _teks(v: Any, batas: int = 160) -> str:
    t = " ".join(str(v or "").split())
    return t if len(t) <= batas else t[: batas - 1] + "…"


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split())


def _uid(ctx) -> Optional[str]:
    return (getattr(ctx, "user", None) or {}).get("id")


def _tolak_gabungan(ctx) -> None:
    """Mode CV Gabungan = lihat saja (keputusan owner Tahap 8). Keputusan diambil di CV satu buku."""
    if str(getattr(ctx, "cv", "") or "").upper() == "ALL":
        from core.entities import READONLY_ALL_MSG
        raise AlatError(400, READONLY_ALL_MSG + " Setelah itu minta keputusan ini lagi.")


def _keputusan(args: dict) -> str:
    k = str((args or {}).get("keputusan") or "")
    if k not in ("setujui", "tolak"):
        raise AlatError(400, "Keputusan harus 'setujui' atau 'tolak'.")
    return k


def _alasan(ctx) -> str:
    """Alasan dari kartu (inti mengisinya sebagai `ctx.alasan`; wajib untuk risiko menengah)."""
    a = _norm(getattr(ctx, "alasan", ""))
    if not a:
        raise AlatError(400, "Alasan keputusan wajib diisi saat menyetujui kartu ini.")
    return a[:500]


def _peringatan_cv(ctx, doc: dict) -> list:
    """Dokumen pembelian dibukukan di CV pemiliknya (tanpa field `entity` = CV Dewi Aditya)."""
    from core.entities import entity_of_doc, entity_short
    milik = entity_of_doc(doc)
    cv = str(getattr(ctx, "cv", "") or "DA").upper()
    if cv in ("DA", "SMU") and cv != milik:
        return [f"Dokumen ini milik buku {entity_short(milik)}, sedangkan pilihan CV Anda {entity_short(cv)}. "
                "Keputusan tetap berlaku untuk dokumen ini."]
    return []


def _cek_tidak_berubah(rencana: dict, sekarang: str) -> None:
    """Kartu dibuat untuk tahap tertentu; bila tahap sudah bergeser (diputus orang lain), jangan jalankan."""
    for p in (rencana or {}).get("perubahan") or []:
        if p.get("label") == LABEL_TAHAP:
            if _norm(p.get("sebelum")) != _norm(sekarang):
                raise AlatError(409, f"Pengajuan ini sudah berubah sejak kartu dibuat (sekarang: {sekarang}). "
                                     "Tidak ada yang diubah; minta Asisten AI menyiapkan kartu baru.")
            return


async def _karyawan_saya(ctx) -> Optional[str]:
    """Id karyawan milik akun ini (SSOT identitas lewat Portal Saya › Profil)."""
    d, _ = await coba(ctx, "GET", P_PROFIL)
    if not isinstance(d, dict):
        return None
    return ((d.get("employee") or {}).get("id")) or d.get("employee_id") or None


async def _kotak_sdm(ctx, jenis: str) -> list:
    """Isi Kotak Masuk SDM untuk satu jenis (leave | overtime). 403 = bukan penyetuju SDM."""
    try:
        d = await ctx.api("GET", P_SDM, params={"type": jenis, "limit_per_type": 200})
    except AlatError as e:
        if e.status == 403:
            raise AlatError(403, PESAN_BUKAN_SDM) from None
        raise
    return [i for i in (d or {}).get("items") or [] if isinstance(i, dict) and i.get("type") == jenis]


def _label_override(alasan: list) -> str:
    return ", ".join(ALASAN_OVERRIDE.get(a, a) for a in alasan or []) or "aturan pemisahan wewenang"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1. Cuti / izin / sakit — Kotak Masuk SDM (mesin `core.leave_engine`)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def _tingkat(raw: dict) -> tuple[int, int]:
    try:
        req = int(raw.get("approval_level_required") or 1)
    except (TypeError, ValueError):
        req = 1
    try:
        cur = int(raw.get("current_approval_level") or 1)
    except (TypeError, ValueError):
        cur = 1
    return req, cur


def _tahap_cuti(raw: dict) -> str:
    req, cur = _tingkat(raw)
    label = STATUS_CUTI.get(raw.get("status"), "Menunggu persetujuan")
    return f"{label} (tingkat {min(cur, req)} dari {req})" if req > 1 else label


def _cuti_final(raw: dict) -> bool:
    req, cur = _tingkat(raw)
    return not (req > 1 and cur == 1)


async def _cari_cuti(ctx, lid: str) -> dict:
    for it in await _kotak_sdm(ctx, "leave"):
        if it.get("id") == lid:
            return it
    d, _ = await coba(ctx, "GET", f"{P_CUTI}/{lid}")
    if isinstance(d, dict) and d.get("status") and d["status"] not in CUTI_MENUNGGU:
        raise AlatError(409, f"Pengajuan cuti/izin ini sudah berstatus {STATUS_CUTI.get(d['status'], d['status'])}, "
                             "jadi tidak perlu diputuskan lagi.")
    raise AlatError(404, "Pengajuan cuti/izin itu tidak ada di Kotak Masuk SDM Anda. Lihat daftar_persetujuan_menunggu "
                         "untuk pengajuan yang menunggu.")


async def _cuti_sudah_diputus(ctx, lid: str, e: AlatError) -> AlatError:
    """Endpoint menolak dengan 400 karena status sudah bukan menunggu → 409 ramah; galat lain apa adanya."""
    if e.status != 400:
        return e
    try:
        await _cari_cuti(ctx, lid)
    except AlatError as e2:
        if e2.status == 409:
            return e2
    return e


@tindakan(
    name="putuskan_cuti",
    label="Menyiapkan keputusan cuti/izin",
    description=(
        "Menyiapkan kartu untuk MENYETUJUI atau MENOLAK satu pengajuan cuti/izin/sakit lewat Kotak Masuk SDM (jalur "
        "yang sama dengan tombol Setujui/Tolak di Portal SDM › Inbox SDM). Isian: `id` pengajuan (dari "
        "daftar_persetujuan_menunggu) dan `keputusan` setujui|tolak. Hanya penyetuju SDM (HR, manajer, owner) yang "
        "bisa; pengajuan milik sendiri ditolak; tingkat 2 (SDM) harus oleh orang lain selain penyetuju tingkat 1. "
        "Persetujuan akhir memotong saldo cuti dalam hari kerja (bila dibayar), menulis absensi per hari kerja, dan "
        "mengabari pemohon; persetujuan tingkat 1 pengajuan > 7 hari kerja hanya meneruskan ke SDM. `pembayaran` "
        "(dibayar|tidak_dibayar) hanya untuk persetujuan akhir: isi sesuai usulan sistem dari daftar bila pengguna "
        "tidak menyebut, supaya pengguna bisa mengubahnya di kartu; saldo tidak cukup untuk 'dibayar' = ditolak. "
        "Alasan yang ditulis pengguna di kartu dikirim sebagai catatan persetujuan/alasan penolakan. Tidak bisa "
        "dibalikkan otomatis (cuti yang sudah disetujui dibatalkan lewat Portal Saya/SDM)."),
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "pattern": _ID_RX, "description": "Id pengajuan cuti/izin/sakit."},
            "keputusan": {"type": "string", "enum": ["setujui", "tolak"]},
            "pembayaran": {"type": "string", "enum": list(BAYAR_ISIAN),
                           "description": "Persetujuan akhir: dibayar atau tidak_dibayar (bawaan usulan sistem)."},
        },
        "required": ["id", "keputusan"],
        "additionalProperties": False,
    },
    domain="sdm",
    risiko="menengah",
    menu="hr-inbox",
)
class PutuskanCuti:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        lid = str(args.get("id") or "")
        if kep == "tolak" and "pembayaran" in args:
            raise AlatError(400, "Isian pembayaran hanya untuk persetujuan, bukan penolakan.")
        it = await _cari_cuti(ctx, lid)
        raw, meta = it.get("raw") or {}, it.get("meta") or {}
        if await _karyawan_saya(ctx) == raw.get("employee_id") and raw.get("employee_id"):
            raise AlatError(403, PESAN_K25_CUTI)
        req, cur = _tingkat(raw)
        final = _cuti_final(raw)
        step1 = raw.get("approval_step_1") or {}
        if kep == "setujui" and req > 1 and cur >= 2 and step1.get("approver_id") and \
                step1.get("approver_id") == _uid(ctx):
            raise AlatError(409, PESAN_TINGKAT2)
        if not final and "pembayaran" in args:
            raise AlatError(400, "Ini persetujuan tingkat 1 (atasan); keputusan pembayaran diambil SDM di tingkat 2. "
                                 "Panggil lagi tanpa isian pembayaran.")

        nama = it.get("requester_name") or "karyawan"
        kode = it.get("requester_code")
        jenis = JENIS_CUTI.get(meta.get("leave_kind") or meta.get("request_type"), "Cuti")
        jenis_cuti = meta.get("leave_type") or jenis
        dari, sampai = meta.get("from_date") or raw.get("from_date"), meta.get("to_date") or raw.get("to_date")
        hari = meta.get("total_days")
        setengah = bool(meta.get("half_day"))
        sebelum = _tahap_cuti(raw)
        if kep == "tolak":
            sesudah = "Ditolak"
        else:
            sesudah = "Disetujui" if final else "Menunggu SDM (tingkat 2 dari 2)"
        perubahan = [{"label": LABEL_TAHAP, "sebelum": sebelum, "sesudah": sesudah}]
        catatan = [f"Karyawan: {nama}" + (f" ({kode})" if kode else "") +
                   (f", {it['requester_dept']}" if it.get("requester_dept") else "") + ".",
                   f"Alasan karyawan: {_teks(raw.get('reason') or it.get('reason'), 200) or _KOSONG}.",
                   "Lampiran bukti: " + ("ada (lihat di Inbox SDM)." if meta.get("attachment_url") else "tidak ada.")]
        peringatan: list = []
        ubah: list = []
        if kep == "setujui" and final:
            prev, _err = await coba(ctx, "GET", f"{P_CUTI}/{lid}/approval-preview")
            prev = prev if isinstance(prev, dict) else None
            usul = (prev or {}).get("suggestion") or meta.get("pay_decision_suggestion") or {}
            usul_kode = usul.get("decision") if usul.get("decision") in BAYAR else "paid"
            putus = BAYAR_ISIAN.get(args.get("pembayaran")) or usul_kode
            if prev:
                tipe_tak_dibayar = bool(prev.get("type_unpaid"))
                potong = tipe_tak_dibayar or putus == "paid"
                per_tahun = [b for b in prev.get("balance_by_year") or [] if isinstance(b, dict)]
                if putus == "paid" and not tipe_tak_dibayar:
                    kurang = [b for b in per_tahun if float(b.get("remaining") or 0) < float(b.get("days") or 0)]
                    if kurang:
                        rinci = "; ".join(f"tahun {b.get('year')}: sisa {_angka(b.get('remaining'))} hari, diminta "
                                          f"{_angka(b.get('days'))} hari" for b in kurang)
                        raise AlatError(400, f"Sisa cuti tidak cukup untuk disetujui sebagai cuti dibayar ({rinci}). "
                                             "Tanyakan ke pengguna; bila tetap disetujui, panggil lagi dengan "
                                             "pembayaran='tidak_dibayar'.")
                if potong:
                    for b in per_tahun:
                        sisa = float(b.get("remaining") or 0)
                        perubahan.append({"label": f"Saldo {jenis_cuti} {b.get('year')}",
                                          "sebelum": f"{_angka(sisa)} hari",
                                          "sesudah": f"{_angka(sisa - float(b.get('days') or 0))} hari"})
                hari = prev.get("working_days", hari)
                perubahan.append({"label": "Absensi", "sebelum": _KOSONG,
                                  "sesudah": f"{jenis} di {_angka(hari)} hari kerja ({_daftar_tgl(prev.get('days'))})"})
                efek = ("Saldo dipotong, absensi ditulis per hari kerja, dan pemohon dikabari." if potong else
                        "Absensi ditulis per hari kerja tanpa memakai jatah saldo, dan pemohon dikabari.")
            else:
                catatan.append("Saldo dan hari kerja tidak bisa dibaca dengan akun ini; sistem tetap memeriksa saldo "
                               "saat menyetujui.")
                efek = "Saldo dan absensi diperbarui sistem, dan pemohon dikabari."
            perubahan.append({"label": "Pembayaran", "sebelum": _KOSONG,
                              "sesudah": BAYAR[putus] + (" (usulan sistem)" if putus == usul_kode else "")})
            if usul.get("reason"):
                catatan.append(f"Usulan sistem: {BAYAR[usul_kode].lower()} — {_teks(usul.get('reason'), 160)}")
            if "pembayaran" in args:
                ubah.append({"kunci": "pembayaran", "label": "Pembayaran", "jenis": "pilihan",
                             "nilai": args["pembayaran"],
                             "pilihan": [{"nilai": k, "label": BAYAR[v]} for k, v in BAYAR_ISIAN.items()]})
        elif kep == "setujui":
            efek = ("Tingkat 1 selesai; pengajuan diteruskan ke persetujuan SDM (tingkat 2). Saldo dan absensi belum "
                    "berubah.")
        else:
            efek = "Pengajuan ditolak dan pemohon dikabari beserta alasan Anda. Saldo dan absensi tidak berubah."
        catatan += [f"Akibat: {efek}", CATATAN_ALASAN_SETUJU if kep == "setujui" else CATATAN_ALASAN_TOLAK,
                    CATATAN_TANPA_BALIK]
        aksi = "Setujui" if kep == "setujui" else "Tolak"
        return {"judul": f"{aksi} {jenis.lower()} {nama}",
                "ringkas": f"{jenis_cuti} · {_rentang(dari, sampai)} · {_angka(hari)} hari kerja"
                           + (" · setengah hari" if setengah else "") + ".",
                "perubahan": perubahan, "catatan": catatan, "peringatan": peringatan, "ubah": ubah,
                "tautan": {"label": "Buka Inbox SDM", "menu": "hr-inbox"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        alasan = _alasan(ctx)
        lid = str(args.get("id") or "")
        it = await _cari_cuti(ctx, lid)
        raw = it.get("raw") or {}
        _cek_tidak_berubah(rencana, _tahap_cuti(raw))
        if kep == "setujui":
            body: dict = {"note": alasan}
            if _cuti_final(raw) and args.get("pembayaran") in BAYAR_ISIAN:
                body["pay_decision"] = BAYAR_ISIAN[args["pembayaran"]]
            path = f"{P_SDM}/leave/{lid}/approve"
        else:
            body, path = {"reason": alasan}, f"{P_SDM}/leave/{lid}/reject"
        try:
            out = await ctx.api("POST", path, json=body)
        except AlatError as e:
            raise await _cuti_sudah_diputus(ctx, lid, e) from None
        baru = (out or {}).get("new_status") or ("rejected" if kep == "tolak" else "approved")
        meta = it.get("meta") or {}
        apa = f"Pengajuan {JENIS_CUTI.get(meta.get('leave_kind'), 'cuti').lower()} " \
              f"{_rentang(meta.get('from_date'), meta.get('to_date'))}"
        if baru == "pending_hr_approval":
            ringkas = f"{apa} disetujui di tingkat 1 dan diteruskan ke SDM (tingkat 2)."
        elif baru == "approved":
            ringkas = f"{apa} disetujui; saldo & absensi diperbarui, pemohon dikabari."
        else:
            ringkas = f"{apa} ditolak; pemohon dikabari beserta alasannya."
        return {"ringkas": ringkas, "hasil": {"cuti_id": lid, "status_baru": STATUS_CUTI.get(baru, baru)},
                "pembatalan": None}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 2. Lembur — Kotak Masuk SDM (fungsi persetujuan `routes.rahaza_overtime.approve_overtime_request`)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
async def _cari_lembur(ctx, oid: str) -> dict:
    for it in await _kotak_sdm(ctx, "overtime"):
        if it.get("id") == oid:
            return it
    d, _ = await coba(ctx, "GET", P_LEMBUR, {"limit": 1000})
    semua = (d.get("overtime") or []) if isinstance(d, dict) else []
    for r in semua:
        if isinstance(r, dict) and r.get("id") == oid and r.get("status") != "pending":
            raise AlatError(409, f"Pengajuan lembur ini sudah berstatus {STATUS_LEMBUR.get(r['status'], r['status'])}, "
                                 "jadi tidak perlu diputuskan lagi.")
    raise AlatError(404, "Pengajuan lembur itu tidak ada di Kotak Masuk SDM Anda. Lihat daftar_persetujuan_menunggu "
                         "untuk pengajuan yang menunggu.")


@tindakan(
    name="putuskan_lembur",
    label="Menyiapkan keputusan lembur",
    description=(
        "Menyiapkan kartu untuk MENYETUJUI atau MENOLAK satu pengajuan lembur lewat Kotak Masuk SDM (fungsi "
        "persetujuan yang sama dengan layar Lembur dan Inbox SDM). Isian: `id` pengajuan (dari "
        "daftar_persetujuan_menunggu) dan `keputusan` setujui|tolak. Hanya penyetuju SDM (HR, manajer, owner); "
        "lembur milik/ajuan sendiri ditolak. Lembur yang disetujui ikut dihitung di payroll (jam × pengali dari "
        "Pengaturan Payroll); pemohon dikabari. Alasan yang ditulis pengguna di kartu dikirim sebagai catatan "
        "persetujuan/alasan penolakan. Tidak bisa dibalikkan otomatis."),
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "pattern": _ID_RX, "description": "Id pengajuan lembur."},
            "keputusan": {"type": "string", "enum": ["setujui", "tolak"]},
        },
        "required": ["id", "keputusan"],
        "additionalProperties": False,
    },
    domain="sdm",
    risiko="menengah",
    menu="hr-inbox",
)
class PutuskanLembur:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        oid = str(args.get("id") or "")
        it = await _cari_lembur(ctx, oid)
        raw, meta = it.get("raw") or {}, it.get("meta") or {}
        saya = await _karyawan_saya(ctx)
        if raw.get("submitted_by") == _uid(ctx) or (saya and saya == raw.get("employee_id")):
            raise AlatError(403, PESAN_K25_LEMBUR)
        nama = it.get("requester_name") or "karyawan"
        kode = it.get("requester_code")
        jam = meta.get("hours") if meta.get("hours") is not None else raw.get("hours")
        mulai, akhir = meta.get("start_time") or raw.get("start_time"), meta.get("end_time") or raw.get("end_time")
        pengali = meta.get("rate_multiplier") or raw.get("rate_multiplier") or 1.5
        tgl = meta.get("date") or raw.get("date")
        perubahan = [{"label": LABEL_TAHAP, "sebelum": STATUS_LEMBUR["pending"],
                      "sesudah": "Disetujui" if kep == "setujui" else "Ditolak"}]
        if kep == "setujui":
            perubahan.append({"label": "Payroll", "sebelum": _KOSONG,
                              "sesudah": f"{_angka(jam)} jam lembur × pengali {_angka(pengali)} ikut dihitung"})
            efek = "Lembur masuk perhitungan upah lembur payroll periode itu, dan pemohon dikabari."
        else:
            efek = "Pengajuan ditolak dan pemohon dikabari beserta alasan Anda. Payroll tidak berubah."
        catatan = [f"Karyawan: {nama}" + (f" ({kode})" if kode else "") +
                   (f", {it['requester_dept']}" if it.get("requester_dept") else "") + ".",
                   f"Alasan karyawan: {_teks(raw.get('reason') or it.get('reason'), 200) or _KOSONG}.",
                   f"Akibat: {efek}", CATATAN_ALASAN_SETUJU if kep == "setujui" else CATATAN_ALASAN_TOLAK,
                   CATATAN_TANPA_BALIK]
        aksi = "Setujui" if kep == "setujui" else "Tolak"
        waktu = f" · {mulai}–{akhir}" if mulai and akhir else ""
        return {"judul": f"{aksi} lembur {nama}",
                "ringkas": f"{_tgl(tgl)}{waktu} · {_angka(jam)} jam.",
                "perubahan": perubahan, "catatan": catatan, "peringatan": [], "ubah": [],
                "tautan": {"label": "Buka Inbox SDM", "menu": "hr-inbox"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        alasan = _alasan(ctx)
        oid = str(args.get("id") or "")
        it = await _cari_lembur(ctx, oid)
        meta = it.get("meta") or {}
        if kep == "setujui":
            path, body = f"{P_SDM}/overtime/{oid}/approve", {"note": alasan}
        else:
            path, body = f"{P_SDM}/overtime/{oid}/reject", {"reason": alasan}
        try:
            await ctx.api("POST", path, json=body)
        except AlatError as e:
            if e.status == 400:
                try:
                    await _cari_lembur(ctx, oid)
                except AlatError as e2:
                    if e2.status == 409:
                        raise e2 from None
            raise
        apa = f"Lembur {_tgl(meta.get('date'))} ({_angka(meta.get('hours'))} jam)"
        ringkas = (f"{apa} disetujui; ikut dihitung di payroll, pemohon dikabari." if kep == "setujui" else
                   f"{apa} ditolak; pemohon dikabari beserta alasannya.")
        return {"ringkas": ringkas,
                "hasil": {"lembur_id": oid, "status_baru": "Disetujui" if kep == "setujui" else "Ditolak"},
                "pembatalan": None}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 3 & 4. Pembelian — mesin `core.pr_approval` (PR, Request Aksesoris lama, Purchase Order)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
def _sama_nomor(a: Any, b: Any) -> bool:
    return bool(a) and bool(b) and _norm(a).upper() == _norm(b).upper()


def _tahap_teks(d: dict) -> str:
    """'Persetujuan Departemen (tahap 1 dari 2)' dari flag server (`eval_approval`)."""
    lab = d.get("stage_label") or "Persetujuan"
    if d.get("stage_order") and d.get("total_stages"):
        return f"{lab} (tahap {d['stage_order']} dari {d['total_stages']})"
    return lab


def _tahap_berikut(d: dict) -> Optional[str]:
    nxt = d.get("next_stage")
    if not nxt:
        return None
    for c in d.get("chain") or []:
        if isinstance(c, dict) and c.get("stage") == nxt:
            return f"{c.get('label') or nxt} (tahap {c.get('order')} dari {d.get('total_stages') or len(d['chain'])})"
    return str(nxt)


def _cek_hak(d: dict, kep: str, apa: str) -> None:
    boleh = d.get("can_approve") if kep == "setujui" else d.get("can_reject")
    if not boleh:
        raise AlatError(403, _teks(d.get("blocked_reason"), 300) or
                        f"Akun ini tidak berhak {'menyetujui' if kep == 'setujui' else 'menolak'} {apa} ini.")


def _peringatan_override(d: dict, apa: str) -> list:
    if not d.get("is_override"):
        return []
    return [f"Anda memutus sebagai admin/owner dengan MENEMBUS aturan ({_label_override(d.get('override_reasons'))}). "
            f"Tindakan ini tercatat sebagai override di riwayat {apa}."]


def _baris_barang(items: list, nama_k: str = "name") -> Optional[str]:
    rows = [i for i in items or [] if isinstance(i, dict)]
    if not rows:
        return None
    bagian = []
    for i in rows[:5]:
        nama = _teks(i.get(nama_k) or i.get("material_name") or i.get("description") or i.get("name"), 50)
        qty = i.get("qty_label") or f"{_angka(i.get('qty'))} {i.get('uom') or i.get('unit') or ''}".strip()
        nilai = i.get("subtotal") if i.get("subtotal") is not None else i.get("total_price")
        bagian.append(f"{nama} {qty} ({_rp(nilai)})")
    sisa = len(rows) - 5
    return "Barang: " + "; ".join(bagian) + (f"; dan {sisa} barang lain" if sisa > 0 else "") + "."


async def _inbox_pengadaan(ctx) -> list:
    d, _ = await coba(ctx, "GET", P_PINBOX, {"scope": "relevant"})
    return [i for i in d if isinstance(i, dict)] if isinstance(d, list) else []


def _wajib_rujukan(args: dict) -> tuple[str, str]:
    pid, nomor = str(args.get("id") or ""), str(args.get("nomor") or "")
    if not pid and not nomor:
        raise AlatError(400, "Sebutkan id atau nomor dokumen (lihat daftar_persetujuan_menunggu).")
    return pid, nomor


async def _cari_pr(ctx, args: dict) -> tuple[dict, str]:
    """(detail dengan flag server, basis endpoint) untuk PR pengadaan atau Request Aksesoris lama."""
    pid, nomor = _wajib_rujukan(args)
    for i in await _inbox_pengadaan(ctx):
        if i.get("kind") in ("pr", "acc_pr") and (i.get("id") == pid or _sama_nomor(i.get("request_number"), nomor)):
            base = i.get("api_base") if i.get("api_base") in (P_PR, P_ACC) else P_PR
            return await ctx.api("GET", f"{base}/{i['id']}"), base
    if pid:
        try:
            return await ctx.api("GET", f"{P_PR}/{pid}"), P_PR
        except AlatError as e:
            if e.status != 404:
                raise
        try:
            return await ctx.api("GET", f"{P_ACC}/{pid}"), P_ACC
        except AlatError as e:
            if e.status != 404:
                raise
        raise AlatError(404, "Permintaan pembelian itu tidak ditemukan.")
    d = await ctx.api("GET", P_PR, params={"search": nomor, "limit": 20})
    for r in (d or {}).get("items") or []:
        if _sama_nomor(r.get("request_number"), nomor):
            return await ctx.api("GET", f"{P_PR}/{r['id']}"), P_PR
    rows, _ = await coba(ctx, "GET", P_ACC)
    for r in rows if isinstance(rows, list) else []:
        if _sama_nomor(r.get("pr_number"), nomor):
            return await ctx.api("GET", f"{P_ACC}/{r['id']}"), P_ACC
    raise AlatError(404, f"Permintaan pembelian bernomor {_teks(nomor, 40)} tidak ditemukan.")


def _status_pr(d: dict, base: str) -> tuple[bool, str]:
    """(masih menunggu?, label status)."""
    if base == P_ACC:
        raw = d.get("raw_status") or d.get("status")
        return raw == "Submitted", STATUS_ACC.get(raw, str(raw))
    return d.get("status") in PR_MENUNGGU, STATUS_PR.get(d.get("status"), str(d.get("status")))


async def _pr_menunggu(ctx, args: dict, kep: str, rencana: Optional[dict] = None) -> tuple[dict, str]:
    """Dokumen yang MASIH menunggu, belum bergeser dari tahap di kartu (`rencana`, saat jalankan), dan boleh diputus
    pengguna ini menurut flag server. Urutan pesan: sudah diputus (409) → berubah sejak kartu (409) → hak (403)."""
    d, base = await _cari_pr(ctx, args)
    menunggu, label = _status_pr(d, base)
    if not menunggu:
        nomor = f" {d['request_number']}" if d.get("request_number") else ""
        raise AlatError(409, f"Permintaan{nomor} sudah berstatus {label}, jadi tidak perlu diputuskan lagi.")
    if rencana is not None:
        _cek_tidak_berubah(rencana, _tahap_teks(d))
    _cek_hak(d, kep, "permintaan pembelian")
    return d, base


@tindakan(
    name="putuskan_pr",
    label="Menyiapkan keputusan permintaan pembelian",
    description=(
        "Menyiapkan kartu untuk MENYETUJUI (meneruskan ke tahap berikutnya / menyetujui penuh) atau MENOLAK satu "
        "Permintaan Pengadaan (PR) — termasuk Request Pembelian Aksesoris lama yang masih menunggu — lewat endpoint "
        "yang sama dengan tombol Setujui/Tolak di Portal Pengadaan. Isian: `id` atau `nomor` (dari "
        "daftar_persetujuan_menunggu) dan `keputusan` setujui|tolak. Aturan tahap (departemen → keuangan → final "
        "menurut nilai), peran tiap tahap, larangan pembuat menyetujui sendiri, larangan satu orang menyetujui dua "
        "tahap, dan batas departemen ditegakkan sistem; admin/owner boleh menembus aturan itu tetapi tercatat sebagai "
        "override (kartu memberi peringatan). Disetujui penuh = PR siap dijadikan PO; ditolak = pemohon dikabari. "
        "Alasan yang ditulis pengguna di kartu dikirim sebagai komentar persetujuan/alasan penolakan. Tidak bisa "
        "dibalikkan otomatis."),
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "pattern": _ID_RX, "description": "Id permintaan."},
            "nomor": {"type": "string", "pattern": _NOMOR_RX, "description": "Nomor permintaan, mis. PR-…"},
            "keputusan": {"type": "string", "enum": ["setujui", "tolak"]},
        },
        "required": ["keputusan"],
        "additionalProperties": False,
    },
    domain="stok",
    risiko="menengah",
    menu="proc-requests",
)
class PutuskanPr:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        d, base = await _pr_menunggu(ctx, args, kep)
        nomor = d.get("request_number") or _KOSONG
        jenis = "Request Aksesoris" if base == P_ACC else "Permintaan Pengadaan"
        lanjut = _tahap_berikut(d) if kep == "setujui" else None
        if kep == "tolak":
            sesudah, efek = "Ditolak", "Permintaan berhenti di status Ditolak dan pemohon dikabari beserta alasan Anda."
        elif lanjut:
            sesudah = lanjut
            efek = f"Diteruskan ke {lanjut.split(' (')[0]}; penyetuju tahap itu mendapat notifikasi."
        else:
            sesudah, efek = "Disetujui penuh", "Disetujui penuh; permintaan siap dijadikan Purchase Order dan pemohon dikabari."
        catatan = [c for c in (
            f"{jenis} {nomor}: {_teks(d.get('title'), 120)}.",
            f"Pemohon: {d.get('requested_by_name') or _KOSONG}; departemen: {d.get('department') or 'tanpa departemen'}.",
            _baris_barang(d.get("items")),
            f"Dibutuhkan: {_tgl(d['needed_by'])}." if d.get("needed_by") else None,
            f"Alasan pengajuan: {_teks(d.get('justification'), 160)}." if d.get("justification") else None,
            f"Akibat: {efek}",
            CATATAN_ALASAN_SETUJU if kep == "setujui" else CATATAN_ALASAN_TOLAK,
            CATATAN_TANPA_BALIK) if c]
        aksi = "Setujui" if kep == "setujui" else "Tolak"
        menu = "proc-accessory-pr" if base == P_ACC else "proc-requests"
        return {"judul": f"{aksi} permintaan pembelian {nomor}",
                "ringkas": f"{_teks(d.get('title'), 80)} · {_rp(d.get('total_estimated'))} · {_tahap_teks(d)}.",
                "perubahan": [{"label": LABEL_TAHAP, "sebelum": _tahap_teks(d), "sesudah": sesudah},
                              {"label": "Nilai", "sebelum": _rp(d.get("total_estimated")),
                               "sesudah": _rp(d.get("total_estimated"))}],
                "catatan": catatan,
                "peringatan": _peringatan_override(d, "permintaan") + _peringatan_cv(ctx, d),
                "ubah": [],
                "tautan": {"label": "Buka " + ("Request Aksesoris" if base == P_ACC else "Permintaan Pengadaan"),
                           "menu": menu}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        alasan = _alasan(ctx)
        d, base = await _pr_menunggu(ctx, args, kep, rencana)
        aksi, body = ("approve", {"comment": alasan}) if kep == "setujui" else ("reject", {"reason": alasan})
        try:
            out = await ctx.api("POST", f"{base}/{d['id']}/{aksi}", json=body)
        except AlatError as e:
            if e.status == 400:
                await _pr_menunggu(ctx, {"id": d["id"]}, kep)   # → 409 ramah bila sudah diputus orang lain
            raise
        out = out or {}
        nomor = d.get("request_number") or "Permintaan"
        tahap = d.get("stage_label") or "tahap ini"
        if kep == "tolak":
            ringkas = f"{nomor} ditolak di {tahap}; pemohon dikabari beserta alasannya."
        elif out.get("next_stage"):
            ringkas = f"{nomor} disetujui di {tahap}; diteruskan ke {out.get('next_stage_label') or 'tahap berikutnya'}."
        else:
            ringkas = f"{nomor} disetujui penuh; siap dijadikan Purchase Order."
        if out.get("override"):
            ringkas += " Tercatat sebagai override admin."
        return {"ringkas": ringkas,
                "hasil": {"pr_id": d["id"], "nomor": d.get("request_number"),
                          "status_baru": out.get("new_status"), "override": bool(out.get("override"))},
                "pembatalan": None}


async def _cari_po(ctx, args: dict) -> dict:
    pid, nomor = _wajib_rujukan(args)
    for i in await _inbox_pengadaan(ctx):
        if i.get("kind") == "po" and (i.get("id") == pid or _sama_nomor(i.get("request_number"), nomor)):
            return await ctx.api("GET", f"{P_PO}/{i['id']}")
    if pid:
        return await ctx.api("GET", f"{P_PO}/{pid}")
    rows = await ctx.api("GET", P_PO, params={"search": nomor})
    if not isinstance(rows, list):
        rows = (rows or {}).get("items") or []
    for r in rows:
        if isinstance(r, dict) and _sama_nomor(r.get("po_number"), nomor):
            return await ctx.api("GET", f"{P_PO}/{r['id']}")
    raise AlatError(404, f"Purchase Order bernomor {_teks(nomor, 40)} tidak ditemukan.")


async def _po_menunggu(ctx, args: dict, kep: str, rencana: Optional[dict] = None) -> dict:
    """Sama dengan `_pr_menunggu`, untuk PO pembelian; PO maklon selalu ditolak."""
    from core.entities import is_maklon_po
    d = await _cari_po(ctx, args)
    if is_maklon_po(d):
        raise AlatError(403, "Ini PO maklon. Konfirmasi PO maklon tidak tersedia untuk Asisten AI; lakukan di layar "
                             "Portal Maklon.")
    if d.get("status") != "pending_approval":
        nomor = f" {d['po_number']}" if d.get("po_number") else ""
        raise AlatError(409, f"PO{nomor} sudah berstatus {STATUS_PO.get(d.get('status'), d.get('status'))}, jadi "
                             "tidak perlu diputuskan lagi.")
    if rencana is not None:
        _cek_tidak_berubah(rencana, _tahap_teks(d))
    _cek_hak(d, kep, "Purchase Order")
    return d


@tindakan(
    name="putuskan_po_pembelian",
    label="Menyiapkan keputusan PO pembelian",
    description=(
        "Menyiapkan kartu untuk MENYETUJUI (satu tahap: pengadaan → keuangan → final menurut nilai) atau MENOLAK satu "
        "Purchase Order PEMBELIAN ke supplier (Portal Pengadaan › Purchase Order), lewat endpoint yang sama dengan "
        "layar. BUKAN untuk PO produksi/maklon: konfirmasi PO maklon tidak tersedia untuk AI. Isian: `id` atau "
        "`nomor` PO (dari daftar_persetujuan_menunggu) dan `keputusan` setujui|tolak. Peran tiap tahap, larangan "
        "pembuat menyetujui PO sendiri, dan larangan satu orang menyetujui dua tahap ditegakkan sistem; admin/owner "
        "boleh menembus tetapi tercatat sebagai override (kartu memberi peringatan). Disetujui penuh = PO siap "
        "dikirim ke supplier; persetujuan tidak membuat jurnal atau pembayaran. Ditolak = pembuat PO dikabari dan "
        "bisa mengajukan ulang. Alasan yang ditulis pengguna di kartu dikirim sebagai komentar/alasan penolakan. "
        "Tidak bisa dibalikkan otomatis."),
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "pattern": _ID_RX, "description": "Id PO pembelian."},
            "nomor": {"type": "string", "pattern": _NOMOR_RX, "description": "Nomor PO, mis. PO-…"},
            "keputusan": {"type": "string", "enum": ["setujui", "tolak"]},
        },
        "required": ["keputusan"],
        "additionalProperties": False,
    },
    domain="stok",
    risiko="menengah",
    menu="proc-purchase-orders",
)
class PutuskanPoPembelian:
    @staticmethod
    async def siapkan(ctx, args: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        d = await _po_menunggu(ctx, args, kep)
        nomor = d.get("po_number") or _KOSONG
        supplier = d.get("supplier_name") or d.get("vendor_name") or "supplier"
        lanjut = _tahap_berikut(d) if kep == "setujui" else None
        if kep == "tolak":
            sesudah = "Ditolak"
            efek = "PO ditolak; pembuat PO dikabari beserta alasan Anda dan bisa memperbaiki lalu mengajukan ulang."
        elif lanjut:
            sesudah = lanjut
            efek = f"Diteruskan ke {lanjut.split(' (')[0]}; penyetuju tahap itu mendapat notifikasi."
        else:
            sesudah = "Disetujui penuh"
            efek = ("PO disetujui penuh dan siap dikirim ke supplier; penerimaan barang dicatat di Penerimaan Barang. "
                    "Persetujuan ini tidak membuat jurnal atau pembayaran.")
        peringatan = _peringatan_override(d, "PO") + _peringatan_cv(ctx, d)
        if d.get("exceeds_pr_value"):
            peringatan.insert(0, f"Nilai PO melebihi nilai PR yang disetujui ({_rp(d.get('pr_approved_value'))}).")
        catatan = [c for c in (
            f"Purchase Order {nomor} ke {_teks(supplier, 80)}"
            + (f", dari permintaan {d['from_pr_number']}" if d.get("from_pr_number") else "") + ".",
            f"Dibuat oleh: {d.get('created_by_name') or _KOSONG}; tanggal PO {_tgl(d.get('po_date'))}"
            + (f"; perkiraan kirim {_tgl(d['expected_delivery_date'])}" if d.get("expected_delivery_date") else "")
            + ".",
            _baris_barang(d.get("items"), "material_name"),
            f"Akibat: {efek}",
            CATATAN_ALASAN_SETUJU if kep == "setujui" else CATATAN_ALASAN_TOLAK,
            CATATAN_TANPA_BALIK) if c]
        aksi = "Setujui" if kep == "setujui" else "Tolak"
        return {"judul": f"{aksi} PO pembelian {nomor}",
                "ringkas": f"{_teks(supplier, 60)} · {_rp(d.get('total_value'))} · {_tahap_teks(d)}.",
                "perubahan": [{"label": LABEL_TAHAP, "sebelum": _tahap_teks(d), "sesudah": sesudah},
                              {"label": "Nilai PO", "sebelum": _rp(d.get("total_value")),
                               "sesudah": _rp(d.get("total_value"))}],
                "catatan": catatan, "peringatan": peringatan, "ubah": [],
                "tautan": {"label": "Buka Purchase Order", "menu": "proc-purchase-orders"}}

    @staticmethod
    async def jalankan(ctx, args: dict, rencana: dict) -> dict:
        _tolak_gabungan(ctx)
        kep = _keputusan(args)
        alasan = _alasan(ctx)
        d = await _po_menunggu(ctx, args, kep, rencana)
        aksi, body = ("approve", {"comment": alasan}) if kep == "setujui" else ("reject", {"reason": alasan})
        try:
            out = await ctx.api("POST", f"{P_PO}/{d['id']}/{aksi}", json=body)
        except AlatError as e:
            if e.status == 400:
                await _po_menunggu(ctx, {"id": d["id"]}, kep)   # → 409 ramah bila sudah diputus orang lain
            raise
        out = out or {}
        nomor = d.get("po_number") or "PO"
        tahap = d.get("stage_label") or "tahap ini"
        if kep == "tolak":
            ringkas = f"{nomor} ditolak di {tahap}; pembuat PO dikabari beserta alasannya."
        elif out.get("next_stage"):
            ringkas = f"{nomor} disetujui di {tahap}; diteruskan ke {out.get('next_stage_label') or 'tahap berikutnya'}."
        else:
            ringkas = f"{nomor} disetujui penuh; siap dikirim ke supplier."
        if out.get("override"):
            ringkas += " Tercatat sebagai override admin."
        return {"ringkas": ringkas,
                "hasil": {"po_id": d["id"], "nomor": d.get("po_number"), "status_baru": out.get("status"),
                          "override": bool(out.get("override"))},
                "pembatalan": None}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
# 5. Baca: persetujuan yang menunggu keputusan pengguna ini
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════
JENIS_DAFTAR = ("cuti", "lembur", "pr", "po")


def _nama(ctx, ps, nama: Optional[str]) -> Optional[str]:
    """K27: nama karyawan asli hanya untuk owner/superadmin/SDM; peran lain kode samaran."""
    if not nama:
        return None
    return nama if boleh_sdm_penuh(ctx) else ps.code(nama, "karyawan")


def _teks_aman(v: Any, batas: int) -> str:
    from services.ai.privacy import mask_pii
    return mask_pii(_teks(v, batas))


def _override_item(i: dict) -> Optional[str]:
    return _label_override(i.get("override_reasons")) if i.get("is_override") else None


@alat(
    name="daftar_persetujuan_menunggu",
    kind="read",
    label="Membaca persetujuan yang menunggu Anda",
    description=(
        "Daftar pengajuan yang bisa DIPUTUSKAN pengguna ini sekarang, dari daftar layar yang sama: Kotak Masuk SDM "
        "(cuti/izin/sakit dan lembur; ajuan milik sendiri dan tingkat 2 yang tingkat 1-nya Anda setujui sendiri "
        "dikeluarkan dan dihitung di `tidak_bisa_anda_putuskan`) dan kotak persetujuan Pengadaan (Permintaan "
        "Pengadaan, Request Aksesoris lama, Purchase Order pembelian — hanya yang lolos aturan tahap/peran/"
        "departemen; `override` terisi bila hanya bisa diputus sebagai admin/owner dengan menembus aturan, tercatat). "
        "Isian opsional `jenis` (cuti, lembur, pr, po) dan `batas` per jenis (bawaan 20). Setiap baris punya `id` "
        "untuk putuskan_cuti / putuskan_lembur / putuskan_pr / putuskan_po_pembelian. Nilai dalam rupiah bulat. "
        "Nama karyawan asli hanya untuk owner/SDM; peran lain mendapat kode samaran."),
    input_schema={
        "type": "object",
        "properties": {
            "jenis": {"type": "array", "maxItems": 4, "items": {"type": "string", "enum": list(JENIS_DAFTAR)}},
            "batas": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "additionalProperties": False,
    },
    domain="umum",
)
async def daftar_persetujuan_menunggu(ctx, args: dict) -> dict:
    jenis = [j for j in JENIS_DAFTAR if j in set(args.get("jenis") or JENIS_DAFTAR)]
    batas = int(args.get("batas") or 20)
    ps = samaran(ctx)
    uid = _uid(ctx)
    hasil: dict = {"per_tanggal": hari_ini(ctx).isoformat(), "jumlah": {}, "tidak_bisa_anda_putuskan": {},
                   "catatan": []}
    sumber = []
    saya = await _karyawan_saya(ctx) if {"cuti", "lembur"} & set(jenis) else None
    sdm_penuh = boleh_sdm_penuh(ctx)

    for j, tipe in (("cuti", "leave"), ("lembur", "overtime")):
        if j not in jenis:
            continue
        try:
            items = await _kotak_sdm(ctx, tipe)
        except AlatError as e:
            hasil["catatan"].append(f"{j.capitalize()}: {e.pesan}")
            continue
        if "Kotak Masuk SDM" not in sumber:
            sumber.append("Kotak Masuk SDM")
        rows, sendiri, tingkat2 = [], 0, 0
        for it in items:
            raw, meta = it.get("raw") or {}, it.get("meta") or {}
            milik = bool(saya) and saya == raw.get("employee_id")
            if tipe == "overtime":
                milik = milik or raw.get("submitted_by") == uid
            if milik:
                sendiri += 1
                continue
            if tipe == "leave":
                req, cur = _tingkat(raw)
                if req > 1 and cur >= 2 and uid and (raw.get("approval_step_1") or {}).get("approver_id") == uid:
                    tingkat2 += 1
                    continue
                row = {"id": it.get("id"), "pemohon": _nama(ctx, ps, it.get("requester_name")),
                       "kode_karyawan": it.get("requester_code"), "departemen": it.get("requester_dept"),
                       "jenis": meta.get("leave_type") or JENIS_CUTI.get(meta.get("leave_kind"), "Cuti"),
                       "dari": meta.get("from_date"), "sampai": meta.get("to_date"),
                       "hari_kerja": meta.get("total_days"), "tahap": _tahap_cuti(raw),
                       "persetujuan_akhir": _cuti_final(raw)}
                usul = (meta.get("pay_decision_suggestion") or {}).get("decision")
                if row["persetujuan_akhir"] and usul in BAYAR:
                    row["usulan_pembayaran"] = "dibayar" if usul == "paid" else "tidak_dibayar"
            else:
                row = {"id": it.get("id"), "pemohon": _nama(ctx, ps, it.get("requester_name")),
                       "kode_karyawan": it.get("requester_code"), "departemen": it.get("requester_dept"),
                       "tanggal": meta.get("date"), "jam": meta.get("hours"),
                       "mulai": meta.get("start_time"), "selesai": meta.get("end_time")}
            if sdm_penuh and (it.get("reason") or raw.get("reason")):
                row["alasan"] = _teks_aman(it.get("reason") or raw.get("reason"), 120)
            row["diajukan"] = str(it.get("submitted_at") or it.get("created_at") or "")[:10] or None
            rows.append({k: v for k, v in row.items() if v not in (None, "")})
        hasil["jumlah"][j] = len(rows)
        hasil[j] = rows[:batas]
        if sendiri or tingkat2:
            hasil["tidak_bisa_anda_putuskan"][j] = {k: v for k, v in (("ajuan_sendiri", sendiri),
                                                                       ("tingkat_1_sudah_anda_setujui", tingkat2)) if v}

    if {"pr", "po"} & set(jenis):
        d, err = await coba(ctx, "GET", P_PINBOX, {"scope": "relevant"})
        if err:
            hasil["catatan"].append(f"Pembelian: {err}")
        else:
            sumber.append("Kotak persetujuan Pengadaan")
            items = [i for i in d if isinstance(i, dict)] if isinstance(d, list) else []
            prs, pos = [], []
            for i in items:
                base = {"id": i.get("id"), "nomor": i.get("request_number"),
                        "nilai_rp": int(round(float(i.get("total_estimated") or 0))), "tahap": _tahap_teks(i),
                        "override": _override_item(i)}
                if i.get("kind") == "po":
                    base.update({"supplier": _teks(i.get("supplier"), 80) or None,
                                 "dari_pr": i.get("from_pr_number") or None,
                                 "melebihi_nilai_pr": bool(i.get("exceeds_pr_value")) or None})
                    pos.append(base)
                elif i.get("kind") in ("pr", "acc_pr"):
                    base.update({"jenis": "Request Aksesoris" if i.get("kind") == "acc_pr" else "Pengadaan",
                                 "judul": _teks_aman(i.get("title"), 80), "departemen": i.get("department") or None,
                                 "jumlah_barang": len(i.get("items") or [])})
                    prs.append(base)
            for j, rows in (("pr", prs), ("po", pos)):
                if j in jenis:
                    rows = [{k: v for k, v in r.items() if v not in (None, "")} for r in rows]
                    hasil["jumlah"][j] = len(rows)
                    hasil[j] = rows[:batas]
    if not any(hasil["jumlah"].values()):
        hasil["catatan"].append("Tidak ada pengajuan yang menunggu keputusan Anda pada jenis yang diminta.")
    if not hasil["tidak_bisa_anda_putuskan"]:
        hasil.pop("tidak_bisa_anda_putuskan")
    if not hasil["catatan"]:
        hasil.pop("catatan")
    for j in jenis:
        if j in hasil and hasil["jumlah"].get(j, 0) > batas:
            hasil.setdefault("catatan", []).append(f"{j}: hanya {batas} dari {hasil['jumlah'][j]} yang ditampilkan.")
    if not sdm_penuh and ({"cuti", "lembur"} & set(jenis)):
        hasil["catatan_nama"] = "Nama karyawan disamarkan (kode KRY-xxx) sesuai hak akses Anda."
    mask = getattr(ctx, "mask", None)
    if callable(mask):
        hasil = mask(hasil, teks=False)   # buang kunci data pribadi; teks bebas sudah disamarkan per kolom
    hasil = pangkas(hasil, ("cuti", "lembur", "pr", "po"))
    hasil["_sumber"] = sumber or ["Kotak persetujuan"]
    return hasil
