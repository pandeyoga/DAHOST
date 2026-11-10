"""core.hapus_master — hapus data master dengan aman (permintaan owner 10 Nov 2026).

Permintaan owner: "pastikan tabel tabel master data bisa dihapus". Hapus permanen hanya boleh bila data itu
BELUM dipakai transaksi/dokumen lain; bila sudah dipakai, server menolak dengan **409** dan kalimat yang
menyebut di mana data itu dipakai, lalu layar menawarkan **Nonaktifkan** (frontend `lib/hapusMaster.js`).

Pola ini sama dengan yang sudah dipakai Vendor CMT sejak Tahap 9 (`routes.vendor_portal.delete_partner`
`?hard=true`: hitung PO/job/kiriman, tolak bila ada). Modul ini hanya menyeragamkan hitungan dan kalimatnya
supaya semua master memakai kode dan pesan yang sama — bukan mekanisme baru di samping yang lama.

    pakai = await hitung_pemakaian(db, [
        ('PO maklon', 'dewi_maklon_pos', {'client_id': cid}),
        ('faktur piutang', 'rahaza_ar_invoices', {'maklon_client_id': cid}),
    ])
    tolak_bila_dipakai('Klien', nama, pakai)        # 409 bila ada pemakaian
"""
from __future__ import annotations

from typing import Iterable

from fastapi import HTTPException

SARAN_NONAKTIF = "Nonaktifkan saja supaya riwayatnya tetap ada."


async def hitung_pemakaian(db, cek: Iterable[tuple]) -> dict:
    """`cek` = deret (label, nama koleksi, filter). → {label: jumlah} hanya untuk yang > 0 (label sama dijumlah)."""
    hasil: dict = {}
    for label, koleksi, filt in cek:
        if not filt:
            continue
        n = await getattr(db, koleksi).count_documents(filt)
        if n:
            hasil[label] = hasil.get(label, 0) + int(n)
    return hasil


def rincian_pemakaian(pemakaian: dict) -> str:
    """{'PO maklon': 3, 'sampel': 1} → '3 PO maklon, 1 sampel'."""
    return ", ".join(f"{n} {label}" for label, n in pemakaian.items() if n)


def tolak_bila_dipakai(jenis: str, nama: str, pemakaian: dict, saran: str = SARAN_NONAKTIF) -> None:
    """409 dengan kalimat staf bila `pemakaian` tidak kosong."""
    if not pemakaian:
        return
    label = f'{jenis} "{nama}"' if nama else jenis
    raise HTTPException(409, f"{label} tidak bisa dihapus karena sudah dipakai di {rincian_pemakaian(pemakaian)}. "
                             f"{saran}".strip())


async def pastikan_tidak_dipakai(db, jenis: str, nama: str, cek: Iterable[tuple], saran: str = SARAN_NONAKTIF) -> None:
    """Gabungan `hitung_pemakaian` + `tolak_bila_dipakai`."""
    tolak_bila_dipakai(jenis, nama, await hitung_pemakaian(db, cek), saran)
