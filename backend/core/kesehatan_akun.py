"""core.kesehatan_akun — SATU aturan status snapshot Kesehatan Akun marketplace (19 Nov 2026).

Kendala staf 19 Nov: "Kesehatan akun Shopee tidak bisa tersimpan" — sebenarnya tersimpan, tetapi:
  * ringkasan halaman error 500 bila Skor SES kosong (Shopee memang tidak punya SES) → pesan "Gagal memuat ringkasan";
  * SEMUA snapshot berstatus Kritis: aturan lama mengira skor berskala 0–100 (kritis < 60), padahal skor kinerja
    toko TikTok berskala 0–5 (mis. 4,1) dan SES kosong dibaca 0.

Aturan (ambang lama dipertahankan, hanya skalanya dibetulkan):
  * Skor SES 0–5 dibaca sebagai skala 5 → dikali 20 (4,1 → 82). Skor > 5 dianggap sudah berskala 0–100.
  * SES kosong TIDAK ikut menilai; status dari telat kirim & pembatalan saja.
  * Kritis   : SES < 60, telat kirim > 5 %, atau pembatalan > 3 %.
    Perhatian: SES < 75, telat kirim > 3 %, atau pembatalan > 2 %.
    Sehat    : selain itu.
Status dihitung ulang SAAT DIBACA (ringkasan & riwayat), jadi snapshot lama ikut benar tanpa migrasi.
"""
from __future__ import annotations

SEHAT, PERHATIAN, KRITIS = "healthy", "warning", "critical"


def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def ses_100(ses) -> float | None:
    """Skor SES dalam skala 0–100 (skor 0–5 dikali 20); kosong → None."""
    s = _num(ses)
    if s is None:
        return None
    return round(s * 20, 2) if 0 <= s <= 5 else s


def status_snapshot(ses=None, late=None, cancel=None) -> str:
    s = ses_100(ses)
    late = _num(late) or 0.0
    cancel = _num(cancel) or 0.0
    if (s is not None and s < 60) or late > 5 or cancel > 3:
        return KRITIS
    if (s is not None and s < 75) or late > 3 or cancel > 2:
        return PERHATIAN
    return SEHAT


def status_dok(doc: dict) -> str:
    d = doc or {}
    return status_snapshot(d.get("ses_score"), d.get("late_shipment_rate"), d.get("cancellation_rate"))


def rata(values) -> float | None:
    """Rata-rata nilai yang terisi saja (kosong tidak dihitung sebagai 0)."""
    xs = [x for x in (_num(v) for v in values) if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None
