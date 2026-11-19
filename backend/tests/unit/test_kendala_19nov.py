"""Uji unit HERMETIK — perbaikan kendala staf 19 Nov 2026.

  · Kesehatan Akun: skor TikTok 0–5 dibaca ×20 (4,1 → sehat, bukan kritis); SES kosong (Shopee) tidak membuat ringkasan
    error dan tidak menilai; ambang lama (60/75, telat kirim 3/5 %, batal 2/3 %) tetap.
  · Kalkulator HPP: baris BOM tech pack per warna/motif hanya dihitung untuk motif yang dipilih.
  · Monitoring Kirim: kapan pesanan terakhir terlihat di berkas impor (dasar tanda "data lama").

Jalankan:  cd backend && python -m pytest tests/unit/test_kendala_19nov.py -q
"""
import os
import sys
from datetime import datetime, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from core import kesehatan_akun as ka  # noqa: E402


@pytest.mark.parametrize("ses,late,cancel,harap", [
    (4.1, None, 0.04, "healthy"),       # TikTok Daluna 19 Nov: dulu "Kritis"
    (3.5, 0, 0, "warning"),             # 70 dari 100
    (2.5, 0, 0, "critical"),            # 50 dari 100
    (None, 0, None, "healthy"),         # Shopee tanpa SES: dulu dibaca 0 → kritis
    (None, 6, 0, "critical"),           # telat kirim tetap menilai
    (None, 0, 2.5, "warning"),
    (85, 0, 0, "healthy"),              # skor 0–100 tetap seperti dulu
    (59, 0, 0, "critical"),
])
def test_status_snapshot_skala_benar(ses, late, cancel, harap):
    assert ka.status_snapshot(ses, late, cancel) == harap


def test_ses_100_dan_rata_lewati_kosong():
    assert ka.ses_100(4.6) == 92.0 and ka.ses_100(None) is None and ka.ses_100(80) == 80
    assert ka.rata([None, 4.0, 6.0]) == 5.0          # dulu sum(None) → error 500 "Gagal memuat ringkasan"
    assert ka.rata([None, None]) is None


def test_pilih_baris_bom_per_motif():
    from routes.dewi_rnd_hpp import _cocok_warna, _warna_baris
    bom = [{"material_code": "A-K22-0006", "color_name": "Ling ling"},
           {"material_code": "A-K22-0027", "color_name": "Sakura Blush"},
           {"material_code": "A-KRT-0002", "color_name": ""}]
    pilih = [b for b in bom if not _warna_baris(b) or _cocok_warna(b, "ling LING")]
    assert [b["material_code"] for b in pilih] == ["A-K22-0006", "A-KRT-0002"]   # kancing 1 motif + karet semua warna


def test_terakhir_terlihat_mengambil_waktu_terbaru():
    from routes.marketing_orders_routes import _terakhir_terlihat
    o = {"created_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
         "updated_at": datetime(2026, 11, 5, tzinfo=timezone.utc),
         "last_seen_import_at": datetime(2026, 11, 18, tzinfo=timezone.utc)}
    assert _terakhir_terlihat(o).day == 18
    assert _terakhir_terlihat({}) is None
