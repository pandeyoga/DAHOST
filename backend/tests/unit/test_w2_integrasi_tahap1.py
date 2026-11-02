"""Uji regresi tindak lanjut integrasi gelombang 2 tahap 1 (2026-11-02).

1. Keuangan ikut memegang modul run gaji (K34: setujui pembatalan; K25: bayar).
2. Kotak masuk HR menolak persetujuan klaim/dinas milik sendiri (K25), sama seperti layar asalnya.
3. Total gaji Laporan Eksekutif dihitung dari periode run, bukan `created_at` (dulu selalu 0).
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi import HTTPException  # noqa: E402


def test_keuangan_ikut_portal_run_gaji():
    from data.module_catalog import ALSO_PORTALS
    assert "finance" in ALSO_PORTALS.get("hr_payroll", [])


def test_inbox_tolak_klaim_milik_sendiri():
    from routes.hr_approval_inbox import _tolak_ajuan_sendiri
    me = {"id": "u-hr", "email": "hr@contoh.id"}
    with pytest.raises(HTTPException) as e:
        _tolak_ajuan_sendiri({"employee_id": "u-hr"}, me, "klaim biaya")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        _tolak_ajuan_sendiri({"submitted_by": "HR@contoh.id"}, me, "perjalanan dinas")


def test_inbox_boleh_klaim_orang_lain():
    from routes.hr_approval_inbox import _tolak_ajuan_sendiri
    _tolak_ajuan_sendiri({"employee_id": "u-lain", "submitted_by": "lain@contoh.id"},
                         {"id": "u-hr", "email": "hr@contoh.id"}, "klaim biaya")


def test_laporan_eksekutif_total_gaji_pakai_periode_run():
    from routes import dewi_executive_report as rep
    src = inspect.getsource(rep._hr_kpis)
    blok = src[src.index("payroll_pipeline"):]
    assert '"period_to": {"$gte": start, "$lte": end}' in blok
    assert '"created_at": {"$gte": start' not in blok
