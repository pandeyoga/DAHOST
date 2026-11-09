"""Uji REGRESI ANGKA payroll (9 Nov 2026, perbaikan HR inti) — HERMETIK (FakeDB), tanpa server/Mongo.

Tujuan: membuktikan perhitungan yang SUDAH BENAR (TER, BPJS, prorata, potongan tidak masuk, lembur dengan absen,
perhitungan setahun Desember, skema mingguan, kasbon) TIDAK berubah oleh perbaikan HR 9 Nov. Angka EXPECTED di bawah
direkam dari mesin hitung SEBELUM perubahan (main 0169ed9) lalu dibekukan. Skenario sengaja tidak memakai perilaku
yang memang DIPUTUSKAN berubah (hari tanpa catatan & bonus kehadiran Q1, lembur tanpa absen Q9, terlambat di hari
cuti/libur H5, plafon JP 2025/2026 M4) — perubahan itu diuji di `test_hr_inti_perbaikan.py`.
"""
import asyncio
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from _fake_mongo import FakeDB  # noqa: E402

import routes.rahaza_payroll_shared as shared  # noqa: E402

run = asyncio.run
OCT = ("2026-10-01", "2026-10-31")
OCT_WD = [date(2026, 10, d) for d in range(1, 32) if date(2026, 10, d).weekday() != 6]
SEMUA_BPJS = {"kes": True, "jht": True, "jp": True, "jkk_jkm": True}


def _prof(**kw):
    p = {"id": "p-a", "employee_id": "emp-a", "pay_scheme": "monthly", "base_rate": 6_000_000, "overtime_rate": 0,
         "active": True}
    p.update(kw)
    return p


def _emp(**kw):
    e = {"id": "emp-a", "name": "Ani", "employee_code": "E01", "tax_ptkp": "TK/0", "ktp_number": "3273011503850001",
         "bpjs_programs": dict(SEMUA_BPJS)}
    e.update(kw)
    return e


def _ev(d, status="hadir", **kw):
    iso = d if isinstance(d, str) else d.isoformat()
    base = {"id": f"ev-{iso}", "employee_id": "emp-a", "date": iso, "status": status, "hours_worked": 8,
            "net_hours_worked": 8, "late_minutes": 0, "overtime_hours": 0}
    base.update(kw)
    return base


def _ringkas(s):
    """Angka slip yang dibekukan (urutan baris dipertahankan)."""
    return {
        "gross": round(s["gross_pay"]), "net": round(s["net_pay"]), "ded_total": round(s["deductions_total"]),
        "earnings": [(e["type"], round(e["amount"])) for e in s["earnings"]],
        "allowances": [(a["name"], round(a["amount"])) for a in s["allowances"]],
        "deductions": [(d.get("type"), round(d["amount"])) for d in s["deductions"]],
        "overtime": (round(s["overtime_amount"]), s["overtime_hours"]),
        "taxable": s["tax"].get("taxable_gross"), "bpjs_er": round(s["bpjs_employer"].get("total") or 0),
    }


def _slip(db, prof=None, emp=None, period=OCT, **kw):
    return run(shared._compute_payslip_for_employee(db, prof or _prof(), period[0], period[1], emp or _emp(), **kw))


def _tunjangan(db):
    db.da_payroll_allowances.docs = [
        {"allowance_id": "al-jab", "name": "Tunjangan Jabatan", "calc_type": "fixed", "amount": 500_000,
         "applicable_to": "all", "is_active": True, "is_fixed_wage": True},
        {"allowance_id": "al-makan", "name": "Insentif Makan", "calc_type": "per_day_attendance", "amount": 10_000,
         "applicable_to": "all", "is_active": True},
        {"allowance_id": "al-bonus", "name": "Bonus Kehadiran", "calc_type": "fixed", "amount": 100_000,
         "applicable_to": "all", "is_active": True}]


def skenario_bulanan_penuh():
    db = FakeDB()
    _tunjangan(db)
    db.rahaza_attendance_events.docs = [_ev(d) for d in OCT_WD]
    return _ringkas(_slip(db))


def skenario_prorata_masuk():
    db = FakeDB()
    _tunjangan(db)
    db.rahaza_attendance_events.docs = [_ev(d) for d in OCT_WD if d.day >= 15]
    return _ringkas(_slip(db, prof=_prof(base_rate=2_700_000), emp=_emp(join_date="2026-10-15",
                                                                          bpjs_programs={"kes": True})))


def skenario_alpa_dan_terlambat():
    db = FakeDB()
    _tunjangan(db)
    db.rahaza_payroll_settings.docs = [{"key": "late_penalty", "enabled": True, "mode": "per_minute",
                                        "amount_per_minute": 1_000},
                                       {"key": "attendance_bonus", "max_alpa_days": 5, "forfeit_if_late": False}]
    db.rahaza_attendance_events.docs = [_ev(d) for d in OCT_WD if d.day not in (5, 6, 7)]
    db.rahaza_attendance_events.docs += [_ev(f"2026-10-0{d}", "alpa") for d in (5, 6, 7)]
    db.rahaza_attendance_events.docs[0]["late_minutes"] = 20
    db.rahaza_attendance_events.docs[1]["late_minutes"] = 15
    return _ringkas(_slip(db, prof=_prof(base_rate=2_700_000)))


def skenario_lembur_dengan_absen():
    db = FakeDB()
    db.rahaza_attendance_events.docs = [_ev(d) for d in OCT_WD]
    by = {e["date"]: e for e in db.rahaza_attendance_events.docs}
    by["2026-10-06"].update(overtime_hours=2, overtime_paid=True)       # ditandai HR → 1,5 + 2
    by["2026-10-07"].update(overtime_hours=2)                           # pengajuan 1 jam → 1,5
    by["2026-10-08"].update(overtime_hours=3)                           # tanpa pengajuan → tidak dibayar
    db.rahaza_attendance_events.docs.append(_ev("2026-10-11", hours_worked=9, net_hours_worked=9,
                                                overtime_hours=9))      # Minggu, kerja 9 jam
    db.rahaza_overtime_requests.docs = [
        {"employee_id": "emp-a", "date": "2026-10-07", "status": "approved", "hours": 1},
        {"employee_id": "emp-a", "date": "2026-10-11", "status": "approved", "hours": 9}]
    return _ringkas(_slip(db, prof=_prof(base_rate=3_460_000), emp=_emp(bpjs_programs={})))


def skenario_ter_b_plafon_jp_2024():
    db = FakeDB()
    wd = [date(2024, 10, d) for d in range(1, 32) if date(2024, 10, d).weekday() != 6]
    db.rahaza_attendance_events.docs = [_ev(d) for d in wd]
    return _ringkas(_slip(db, prof=_prof(base_rate=15_200_000), emp=_emp(tax_ptkp="K/1"),
                          period=("2024-10-01", "2024-10-31")))


def skenario_desember_setahun():
    db = FakeDB()
    db.rahaza_payroll_runs.docs = [{"id": "r-prev", "status": "finalized"}]
    for m in range(1, 12):
        db.rahaza_payslips.docs.append({
            "id": f"s{m}", "run_id": "r-prev", "employee_id": "emp-a", "period_to": f"2026-{m:02d}-28",
            "gross_pay": 10_000_000, "tax": {"tax_month": f"2026-{m:02d}", "taxable_gross": 10_054_000},
            "deductions": [{"type": "pph21", "amount": 226_215}, {"type": "bpjs_jht", "amount": 200_000},
                           {"type": "bpjs_jp", "amount": 100_000}]})
    dec = [date(2026, 12, d) for d in range(1, 32) if date(2026, 12, d).weekday() != 6]
    db.rahaza_attendance_events.docs = [_ev(d) for d in dec]
    emp = _emp(bpjs_programs={"jht": True, "jp": True, "jkk_jkm": True})
    return _ringkas(_slip(db, prof=_prof(base_rate=10_000_000), emp=emp, period=("2026-12-01", "2026-12-31")))


def skenario_mingguan():
    db = FakeDB()
    db.rahaza_attendance_events.docs = [_ev(f"2026-10-{d:02d}") for d in (12, 13, 14, 15, 16, 17)]
    return _ringkas(_slip(db, prof=_prof(pay_scheme="weekly", base_rate=900_000), emp=_emp(bpjs_programs={"kes": True}),
                          period=("2026-10-12", "2026-10-18")))


def skenario_kasbon():
    db = FakeDB()
    db.rahaza_attendance_events.docs = [_ev(d) for d in OCT_WD]
    db.dewi_kasbon_requests.docs = [
        {"id": "k1", "employee_id": "emp-a", "status": "disbursed", "deduction_start_period": "2026-10",
         "type": "kasbon", "type_label": "Kasbon", "request_number": "KB-1", "outstanding_balance": 400_000,
         "disbursed_at": "2026-10-02"},
        {"id": "k2", "employee_id": "emp-a", "status": "disbursed", "deduction_start_period": "2026-09",
         "type": "loan", "type_label": "Pinjaman", "request_number": "PJ-1", "outstanding_balance": 900_000,
         "installment_amount": 300_000, "disbursed_at": "2026-09-02"}]
    return _ringkas(_slip(db, prof=_prof(base_rate=3_000_000), emp=_emp(bpjs_programs={})))


SKENARIO = {
    "bulanan_penuh": skenario_bulanan_penuh,
    "prorata_masuk": skenario_prorata_masuk,
    "alpa_dan_terlambat": skenario_alpa_dan_terlambat,
    "lembur_dengan_absen": skenario_lembur_dengan_absen,
    "ter_b_plafon_jp_2024": skenario_ter_b_plafon_jp_2024,
    "desember_setahun": skenario_desember_setahun,
    "mingguan": skenario_mingguan,
    "kasbon": skenario_kasbon,
}

# Direkam dari main 0169ed9 (sebelum perbaikan HR 9 Nov). JANGAN diubah tanpa keputusan owner.
EXPECTED = {'bulanan_penuh': {'gross': 6870000,
                   'net': 6520436,
                   'ded_total': 349564,
                   'earnings': [('monthly', 6000000)],
                   'allowances': [('Tunjangan Jabatan', 500000),
                                  ('Insentif Makan', 270000),
                                  ('Bonus Kehadiran', 100000)],
                   'deductions': [('bpjs_kesehatan', 65000),
                                  ('bpjs_jht', 130000),
                                  ('bpjs_jp', 65000),
                                  ('pph21', 89564)],
                   'overtime': (0, 0),
                   'taxable': 7165100,
                   'bpjs_er': 665600},
 'prorata_masuk': {'gross': 1983334,
                   'net': 1951334,
                   'ded_total': 32000,
                   'earnings': [('monthly', 1500000)],
                   'allowances': [('Tunjangan Jabatan', 277778),
                                  ('Insentif Makan', 150000),
                                  ('Bonus Kehadiran', 55556)],
                   'deductions': [('bpjs_kesehatan', 32000)],
                   'overtime': (0, 0),
                   'taxable': 2111334,
                   'bpjs_er': 128000},
 'alpa_dan_terlambat': {'gross': 3540000,
                        'net': 3077000,
                        'ded_total': 463000,
                        'earnings': [('monthly', 2700000)],
                        'allowances': [('Tunjangan Jabatan', 500000),
                                       ('Insentif Makan', 240000),
                                       ('Bonus Kehadiran', 100000)],
                        'deductions': [('late', 35000),
                                       ('absence', 300000),
                                       ('bpjs_kesehatan', 32000),
                                       ('bpjs_jht', 64000),
                                       ('bpjs_jp', 32000)],
                        'overtime': (0, 0),
                        'taxable': 3350280,
                        'bpjs_er': 327680},
 'lembur_dengan_absen': {'gross': 3980000,
                         'net': 3980000,
                         'ded_total': 0,
                         'earnings': [('monthly', 3460000)],
                         'allowances': [],
                         'deductions': [],
                         'overtime': (520000, 12.0),
                         'taxable': 3980000,
                         'bpjs_er': 0},
 'ter_b_plafon_jp_2024': {'gross': 15200000,
                          'net': 13729852,
                          'ded_total': 1470148,
                          'earnings': [('monthly', 15200000)],
                          'allowances': [],
                          'deductions': [('bpjs_kesehatan', 120000),
                                         ('bpjs_jht', 304000),
                                         ('bpjs_jp', 100423),
                                         ('pph21', 945725)],
                          'overtime': (0, 0),
                          'taxable': 15762080,
                          'bpjs_er': 1325326},
 'desember_setahun': {'gross': 10000000,
                      'net': 9335965,
                      'ded_total': 664035,
                      'earnings': [('monthly', 10000000)],
                      'allowances': [],
                      'deductions': [('bpjs_jht', 200000), ('bpjs_jp', 100000), ('pph21', 364035)],
                      'overtime': (0, 0),
                      'taxable': 10054000,
                      'bpjs_er': 624000},
 'mingguan': {'gross': 900000,
              'net': 891000,
              'ded_total': 9000,
              'earnings': [('weekly', 900000)],
              'allowances': [],
              'deductions': [('bpjs_kesehatan', 9000)],
              'overtime': (0, 0),
              'taxable': 936000,
              'bpjs_er': 36000},
 'kasbon': {'gross': 3000000,
            'net': 2300000,
            'ded_total': 700000,
            'earnings': [('monthly', 3000000)],
            'allowances': [],
            'deductions': [('kasbon', 300000), ('kasbon', 400000)],
            'overtime': (0, 0),
            'taxable': 3000000,
            'bpjs_er': 0}}


def test_angka_payroll_tidak_berubah():
    hasil = {k: fn() for k, fn in SKENARIO.items()}
    if not EXPECTED:   # pragma: no cover — perekaman awal
        import json
        print(json.dumps(hasil, indent=1, default=str))
        raise AssertionError("EXPECTED belum direkam")
    for k, want in EXPECTED.items():
        got = hasil[k]
        got = {kk: [tuple(x) if isinstance(x, list) else x for x in v] if isinstance(v, list) else v
               for kk, v in got.items()}
        assert got == want, f"skenario {k} berubah:\n{got}\n!=\n{want}"
