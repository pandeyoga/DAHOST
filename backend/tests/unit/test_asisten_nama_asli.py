"""Keputusan owner 9 Nov 2026: owner/superadmin melihat NAMA ASLI vendor/pelanggan di Asisten AI; peran lain tetap
memakai kode samaran (K27). Kontak di teks bebas tetap disamarkan."""
import os
import sys
from datetime import date
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.asisten_ai import alat_base as ab  # noqa: E402
from services.ai.privacy import Pseudonymizer, TanpaSamaran  # noqa: E402


def _ctx(peran):
    return ab.AlatContext(user={"id": "u1", "role": peran}, cv="DA", today=date(2026, 11, 9))


def test_owner_dan_superadmin_melihat_nama_asli():
    for peran in ("owner", "superadmin", "Owner"):
        ps = _ctx(peran).samaran
        assert isinstance(ps, TanpaSamaran)
        assert ps.code("Konveksi Contoh Jaya", "vendor") == "Konveksi Contoh Jaya"
        assert ps.code("  Toko Contoh  ", "pelanggan") == "Toko Contoh"
        assert ps.code("") is None and ps.code(None) is None
        assert ps.real_name("VND-001") is None          # tidak ada kode untuk dipulihkan


def test_peran_lain_tetap_kode_samaran():
    for peran in ("manager", "admin", "hr", "manager_keuangan"):
        ps = _ctx(peran).samaran
        assert type(ps) is Pseudonymizer
        kode = ps.code("Konveksi Contoh Jaya", "vendor")
        assert kode != "Konveksi Contoh Jaya" and ps.real_name(kode) == "Konveksi Contoh Jaya"


def test_samaran_dibagi_dalam_satu_giliran():
    ctx = _ctx("owner")
    assert ctx.untuk_alat("a1", "kode").samaran is ctx.samaran


def test_kontak_tetap_disamarkan_untuk_owner():
    teks = TanpaSamaran().scrub("Hubungi 081234567890 atau kontak@contoh.id")
    assert "081234567890" not in teks and "kontak@contoh.id" not in teks
