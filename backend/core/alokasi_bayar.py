"""core.alokasi_bayar — pembagian SATU pembayaran ke beberapa dokumen, terlama dulu (16 Nov 2026, owner).

Keputusan owner: pembayaran gabungan (bayar satu CMT untuk beberapa PO/tagihan, atau klien membayar beberapa PO
sekaligus) dibagi OTOMATIS ke dokumen terbuka yang paling lama dulu; Keuangan boleh mengubah pembagiannya sebelum
menyimpan. Satu rumus untuk usulan di layar dan untuk server (bila pembagian tidak dikirim), dan satu pemeriksaan
untuk pembagian yang dikirim layar. Murni — tanpa basis data (kecuali `terbitkan_nomor`).

Bukti pembayaran gabungan (CMT maupun klien) disimpan di SATU koleksi `dewi_pembayaran_gabungan` (`jenis`
membedakan), nomornya lewat kebijakan nomor dokumen (`core.doc_number_policy`).
"""
from __future__ import annotations

TOLERANSI = 0.5     # rupiah: selisih pembulatan dari layar
COLL = 'dewi_pembayaran_gabungan'
JENIS_BAYAR_CMT = 'bayar_cmt'
JENIS_TERIMA_KLIEN = 'terima_klien'
NOMOR_BAYAR_CMT = 'dewi_pembayaran_gabungan.bukti_cmt'
NOMOR_TERIMA_KLIEN = 'dewi_pembayaran_gabungan.bukti_klien'


async def terbitkan_nomor(db, key: str) -> str:
    """Nomor dokumen baru lewat kebijakan penomoran (mode otomatis; format bisa diatur owner)."""
    from core.doc_number_policy import issue_number
    return await issue_number(db, key)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _rp(v) -> str:
    return 'Rp ' + f"{_f(v):,.0f}".replace(',', '.')


def awal(s: str) -> str:
    """Huruf pertama kalimat besar tanpa mengubah sisanya (nomor dokumen tetap utuh)."""
    s = str(s or '')
    return s[:1].upper() + s[1:]


def urutkan(baris: list) -> list:
    """Urutan terlama dulu: (`urut` — tanggal acuan, kosong = paling akhir), lalu `nomor`."""
    return sorted(baris or [], key=lambda b: (str(b.get('urut') or '9999-99-99'), str(b.get('nomor') or ''),
                                              str(b.get('id') or '')))


def alokasi_terlama(jumlah: float, baris: list) -> tuple[list, float]:
    """Bagi `jumlah` ke `baris` ({id, batas, urut, nomor}) terlama dulu, tiap baris paling banyak `batas`-nya.

    → ([{id, jumlah}], sisa yang tidak terbagi). Baris tanpa batas (≤ 0) dilewati."""
    sisa = round(_f(jumlah), 2)
    out = []
    for b in urutkan(baris):
        if sisa <= 0.005:
            break
        batas = round(_f(b.get('batas')), 2)
        if batas <= 0.005:
            continue
        ambil = round(min(sisa, batas), 2)
        out.append({'id': b['id'], 'jumlah': ambil})
        sisa = round(sisa - ambil, 2)
    return out, max(0.0, sisa)


def periksa_alokasi(alokasi: list, batas: dict, *, label: dict | None = None, apa: str = 'dokumen') -> list:
    """Periksa pembagian yang dikirim layar. `batas` = {id: batas bayar dokumen yang SAH untuk pembayaran ini}.

    Ditolak (ValueError, pesan untuk staf): id di luar `batas` (dokumen pihak lain / tidak terbuka), id ganda,
    jumlah ≤ 0, atau jumlah melebihi batas dokumennya. → baris bersih [{id, jumlah}] (urutan kiriman)."""
    label = label or {}
    seen, out = set(), []
    for a in alokasi or []:
        did = str((a or {}).get('id') or '')
        jml = round(_f((a or {}).get('jumlah')), 2)
        if jml <= 0.005:
            continue                     # baris nol di tabel layar = tidak dibayar
        nama = label.get(did) or f"{apa} {did}"
        if did not in batas:
            raise ValueError(f"{awal(nama)} tidak termasuk {apa} terbuka pihak ini — muat ulang lalu ulangi.")
        if did in seen:
            raise ValueError(f"{awal(nama)} muncul dua kali di pembagian.")
        seen.add(did)
        if jml > round(_f(batas[did]), 2) + 0.01:
            raise ValueError(f"Pembagian ke {nama} {_rp(jml)} melebihi batasnya {_rp(batas[did])}.")
        out.append({'id': did, 'jumlah': jml})
    if not out:
        raise ValueError(f"Belum ada {apa} yang dibayar — isi pembagian minimal satu baris.")
    return out
