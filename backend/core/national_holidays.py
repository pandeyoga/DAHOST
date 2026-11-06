"""core.national_holidays — PRESET hari libur nasional & cuti bersama Indonesia, per tahun.

2026-11-06 (pola P5, Tahap 4): dulu `routes/rahaza_production_calendar.py` memuat SATU daftar
`NATIONAL_HOLIDAYS_2026` berlabel "contoh" dengan tanggal yang salah (mis. Idul Fitri 6–7 April,
Nyepi 14 Maret, Waisak 24 Mei) dan tanpa tahun lain. Tanggal yang salah ikut mengurangi hari kerja
payroll/cuti (`core.workdays`), dan tombol "isi libur nasional" diam-diam tidak menambah apa pun untuk
tahun selain 2026.

Sekarang preset = tabel TAHUN → DAFTAR. Tahun yang belum ada di tabel dikatakan di layar
(`missing_year_message`), bukan diam-diam kosong.

SUMBER (salin persis dari SKB 3 Menteri — Menteri Agama, Menteri Ketenagakerjaan, Menteri PANRB):
  * 2026: SKB Nomor 1497 Tahun 2025, Nomor 2 Tahun 2025, Nomor 5 Tahun 2025, ditetapkan 19 September 2025
          (17 libur nasional + 8 cuti bersama). Rujukan: setneg.go.id "Inilah SKB 3 Menteri Libur Nasional dan
          Cuti Bersama 2026".
  * 2027: SKB Nomor 1205 Tahun 2026, Nomor 3 Tahun 2026, Nomor 2 Tahun 2026, ditetapkan 15 September 2026
          (18 libur nasional + 8 cuti bersama). Rujukan: setneg.go.id "Inilah SKB 3 Menteri Libur Nasional dan
          Cuti Bersama 2027" dan kemenkopmk.go.id "Pemerintah Tetapkan 18 Hari Libur Nasional dan 8 Cuti Bersama
          Tahun 2027" (kedua sumber sama).

Tanggal yang mengikuti kalender keagamaan non-Masehi (Hijriah, Saka, Buddha, Imlek) ditandai
`perkiraan=True` ("perkiraan, cek SKB"): Idulfitri/Iduladha ditetapkan ulang lewat sidang isbat dan SKB bisa
diubah. Tanggal Paskah dihitung dari kalender gereja (pasti), jadi tidak ditandai.

Cuti bersama untuk pekerja swasta bersifat fakultatif (kebijakan perusahaan). Preset tetap memuatnya sebagai
hari libur (seperti preset lama) dengan `kind='cuti_bersama'` supaya bisa dibedakan dan dihapus bila pabrik
tetap bekerja.

Menambah tahun baru: tambahkan satu entri di `_RAW` (salin dari SKB tahun itu) + sumber di `SOURCES`.
"""
from __future__ import annotations

from datetime import date

KIND_LIBUR = "libur_nasional"
KIND_CUTI = "cuti_bersama"
KIND_LABEL = {KIND_LIBUR: "Libur nasional", KIND_CUTI: "Cuti bersama"}

# kalender asal tanggal — yang non-Masehi dianggap perkiraan
CAL_MASEHI, CAL_GEREJA = "masehi", "gereja"
CAL_HIJRIAH, CAL_SAKA, CAL_BUDDHA, CAL_IMLEK = "hijriah", "saka", "buddha", "imlek"
PERKIRAAN_CALENDARS = frozenset({CAL_HIJRIAH, CAL_SAKA, CAL_BUDDHA, CAL_IMLEK})
PERKIRAAN_NOTE = "Perkiraan, cek SKB"

SOURCES = {
    2026: "SKB 3 Menteri No. 1497/2025, 2/2025, 5/2025 (19 Sep 2025)",
    2027: "SKB 3 Menteri No. 1205/2026, 3/2026, 2/2026 (15 Sep 2026)",
}

# (tanggal, nama, jenis, kalender)
_RAW = {
    2026: [
        ("2026-01-01", "Tahun Baru 2026 Masehi", KIND_LIBUR, CAL_MASEHI),
        ("2026-01-16", "Isra Mikraj Nabi Muhammad SAW", KIND_LIBUR, CAL_HIJRIAH),
        ("2026-02-16", "Cuti bersama Tahun Baru Imlek 2577 Kongzili", KIND_CUTI, CAL_IMLEK),
        ("2026-02-17", "Tahun Baru Imlek 2577 Kongzili", KIND_LIBUR, CAL_IMLEK),
        ("2026-03-18", "Cuti bersama Hari Suci Nyepi", KIND_CUTI, CAL_SAKA),
        ("2026-03-19", "Hari Suci Nyepi (Tahun Baru Saka 1948)", KIND_LIBUR, CAL_SAKA),
        ("2026-03-20", "Cuti bersama Idulfitri 1447 H", KIND_CUTI, CAL_HIJRIAH),
        ("2026-03-21", "Idulfitri 1447 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2026-03-22", "Idulfitri 1447 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2026-03-23", "Cuti bersama Idulfitri 1447 H", KIND_CUTI, CAL_HIJRIAH),
        ("2026-03-24", "Cuti bersama Idulfitri 1447 H", KIND_CUTI, CAL_HIJRIAH),
        ("2026-04-03", "Wafat Yesus Kristus", KIND_LIBUR, CAL_GEREJA),
        ("2026-04-05", "Kebangkitan Yesus Kristus (Paskah)", KIND_LIBUR, CAL_GEREJA),
        ("2026-05-01", "Hari Buruh Internasional", KIND_LIBUR, CAL_MASEHI),
        ("2026-05-14", "Kenaikan Yesus Kristus", KIND_LIBUR, CAL_GEREJA),
        ("2026-05-15", "Cuti bersama Kenaikan Yesus Kristus", KIND_CUTI, CAL_GEREJA),
        ("2026-05-27", "Iduladha 1447 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2026-05-28", "Cuti bersama Iduladha 1447 H", KIND_CUTI, CAL_HIJRIAH),
        ("2026-05-31", "Hari Raya Waisak 2570 BE", KIND_LIBUR, CAL_BUDDHA),
        ("2026-06-01", "Hari Lahir Pancasila", KIND_LIBUR, CAL_MASEHI),
        ("2026-06-16", "1 Muharam Tahun Baru Islam 1448 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2026-08-17", "Proklamasi Kemerdekaan", KIND_LIBUR, CAL_MASEHI),
        ("2026-08-25", "Maulid Nabi Muhammad SAW", KIND_LIBUR, CAL_HIJRIAH),
        ("2026-12-24", "Cuti bersama Kelahiran Yesus Kristus", KIND_CUTI, CAL_MASEHI),
        ("2026-12-25", "Kelahiran Yesus Kristus", KIND_LIBUR, CAL_MASEHI),
    ],
    2027: [
        ("2027-01-01", "Tahun Baru 2027 Masehi", KIND_LIBUR, CAL_MASEHI),
        ("2027-01-05", "Isra Mikraj Nabi Muhammad SAW 1448 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2027-02-05", "Cuti bersama Tahun Baru Imlek 2578 Kongzili", KIND_CUTI, CAL_IMLEK),
        ("2027-02-06", "Tahun Baru Imlek 2578 Kongzili", KIND_LIBUR, CAL_IMLEK),
        ("2027-03-08", "Hari Suci Nyepi (Tahun Baru Saka 1949)", KIND_LIBUR, CAL_SAKA),
        ("2027-03-09", "Cuti bersama Idulfitri 1448 H", KIND_CUTI, CAL_HIJRIAH),
        ("2027-03-10", "Idulfitri 1448 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2027-03-11", "Idulfitri 1448 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2027-03-12", "Cuti bersama Idulfitri 1448 H", KIND_CUTI, CAL_HIJRIAH),
        ("2027-03-15", "Cuti bersama Idulfitri 1448 H", KIND_CUTI, CAL_HIJRIAH),
        ("2027-03-25", "Cuti bersama Wafat Yesus Kristus", KIND_CUTI, CAL_GEREJA),
        ("2027-03-26", "Wafat Yesus Kristus", KIND_LIBUR, CAL_GEREJA),
        ("2027-03-28", "Kebangkitan Yesus Kristus (Paskah)", KIND_LIBUR, CAL_GEREJA),
        ("2027-05-01", "Hari Buruh Internasional", KIND_LIBUR, CAL_MASEHI),
        ("2027-05-06", "Kenaikan Yesus Kristus", KIND_LIBUR, CAL_GEREJA),
        ("2027-05-17", "Iduladha 1448 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2027-05-18", "Cuti bersama Iduladha 1448 H", KIND_CUTI, CAL_HIJRIAH),
        ("2027-05-19", "Cuti bersama Hari Raya Waisak 2571 BE", KIND_CUTI, CAL_BUDDHA),
        ("2027-05-20", "Hari Raya Waisak 2571 BE", KIND_LIBUR, CAL_BUDDHA),
        ("2027-06-01", "Hari Lahir Pancasila", KIND_LIBUR, CAL_MASEHI),
        ("2027-06-06", "1 Muharam Tahun Baru Islam 1449 H", KIND_LIBUR, CAL_HIJRIAH),
        ("2027-08-15", "Maulid Nabi Muhammad SAW", KIND_LIBUR, CAL_HIJRIAH),
        ("2027-08-17", "Proklamasi Kemerdekaan", KIND_LIBUR, CAL_MASEHI),
        ("2027-12-24", "Cuti bersama Kelahiran Yesus Kristus", KIND_CUTI, CAL_MASEHI),
        ("2027-12-25", "Kelahiran Yesus Kristus", KIND_LIBUR, CAL_MASEHI),
        ("2027-12-26", "Isra Mikraj Nabi Muhammad SAW 1449 H", KIND_LIBUR, CAL_HIJRIAH),
    ],
}


def _entry(year: int, d: str, name: str, kind: str, cal: str) -> dict:
    return {"date": d, "name": name, "type": "holiday", "kind": kind, "calendar": cal,
            "perkiraan": cal in PERKIRAAN_CALENDARS, "source": SOURCES[year]}


NATIONAL_HOLIDAYS: dict[int, list[dict]] = {
    y: [_entry(y, *row) for row in rows] for y, rows in _RAW.items()
}


def available_years() -> list[int]:
    return sorted(NATIONAL_HOLIDAYS)


def holidays_for(year: int) -> list[dict] | None:
    """Daftar preset satu tahun (salinan), atau None bila tahun itu belum ada di tabel."""
    rows = NATIONAL_HOLIDAYS.get(int(year))
    return [dict(r) for r in rows] if rows is not None else None


def missing_year_message(year: int) -> str:
    years = ", ".join(str(y) for y in available_years())
    return (f"Data libur nasional tahun {year} belum ada di sistem (tersedia: {years}). "
            f"Tambahkan tanggalnya satu per satu sesuai SKB 3 Menteri tahun {year}.")


def entry_notes(h: dict) -> str:
    """Catatan baris kalender: jenis + sumber SKB (+ tanda perkiraan)."""
    note = f"{KIND_LABEL.get(h.get('kind'), 'Libur nasional')} · {h.get('source') or ''}".strip(" ·")
    if h.get("perkiraan"):
        note += f" · {PERKIRAAN_NOTE} (tanggal mengikuti kalender keagamaan)"
    return note


def calendar_doc(h: dict, *, uid: str, now_iso: str) -> dict:
    """Dokumen `rahaza_production_calendar` untuk satu baris preset (bentuk sama dengan entri manual)."""
    d = date.fromisoformat(h["date"])
    return {
        "id": uid, "date": h["date"], "year": d.year, "month": d.month, "day": d.day,
        "weekday": d.strftime("%A"), "name": h["name"], "type": "holiday",
        "kind": h.get("kind") or KIND_LIBUR, "perkiraan": bool(h.get("perkiraan")),
        "preset_source": h.get("source") or "", "notes": entry_notes(h), "affects_shifts": [],
        "created_at": now_iso, "created_by": "system", "created_by_name": "System",
    }
