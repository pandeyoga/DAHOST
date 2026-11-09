"""Waktu & batas waktu kewajiban — hari kerja dari SSOT `core.workdays` (6 hari/minggu, libur Kalender SDM).

Semua instan disimpan AWARE UTC; batas hari & jam tetap ("pukul 10.00") dihitung dalam WIB (`utils.waktu`).
Nilai tersimpan di koleksi lain bercampur (datetime naif UTC, teks ISO, teks 'YYYY-MM-DD') → `ts()` menormalkan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from utils.waktu import WIB, now_utc, to_wib


def ts(v) -> datetime | None:
    """Nilai waktu tersimpan apa pun → datetime AWARE UTC (None bila kosong/tak terbaca).

    datetime naif = UTC (aturan penyimpanan); 'YYYY-MM-DD' = awal hari itu WIB; teks ISO tanpa zona = UTC."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)
    if isinstance(v, date):
        return datetime.combine(v, time.min, tzinfo=WIB).astimezone(timezone.utc)
    s = str(v).strip()
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime.combine(date.fromisoformat(s), time.min, tzinfo=WIB).astimezone(timezone.utc)
        except ValueError:
            return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def tanggal_wib(v) -> date | None:
    t = ts(v)
    return to_wib(t).date() if t else None


def jam_wib(d: date, hhmm: str) -> datetime:
    """Instan UTC untuk tanggal WIB `d` pukul 'HH:MM' WIB."""
    try:
        h, m = (int(x) for x in (hhmm or "00:00").split(":")[:2])
    except ValueError:
        h, m = 0, 0
    return datetime.combine(d, time(min(max(h, 0), 23), min(max(m, 0), 59)), tzinfo=WIB).astimezone(timezone.utc)


@dataclass
class Kalender:
    """Hari kerja (murni, tanpa DB): hari libur mingguan + set tanggal libur 'YYYY-MM-DD'."""
    off_weekdays: frozenset = frozenset({6})
    libur: set = field(default_factory=set)

    def kerja(self, d: date) -> bool:
        return d.weekday() not in self.off_weekdays and d.isoformat() not in self.libur

    def hari_kerja_berikut(self, d: date, k: int) -> date:
        """Hari kerja ke-k sesudah `d` (k=0 → `d` bila hari kerja, kalau tidak hari kerja berikutnya)."""
        cur = d
        if k <= 0:
            for _ in range(400):
                if self.kerja(cur):
                    return cur
                cur += timedelta(days=1)
            return d
        n = 0
        for _ in range(800):
            cur += timedelta(days=1)
            if self.kerja(cur):
                n += 1
                if n >= k:
                    return cur
        return cur

    def tambah_hari_kerja(self, mulai: datetime, n: int) -> datetime:
        """`mulai` + n hari kerja, jam yang sama (WIB). Mulai di hari libur dihitung dari hari kerja berikutnya."""
        w = to_wib(mulai)
        d = w.date()
        if not self.kerja(d):
            d = self.hari_kerja_berikut(d, 0)
            w = datetime.combine(d, time(8, 0), tzinfo=WIB)
        tujuan = self.hari_kerja_berikut(d, max(int(n or 0), 0))
        return datetime.combine(tujuan, w.timetz().replace(tzinfo=None), tzinfo=WIB).astimezone(timezone.utc)

    def tambah_jam(self, mulai: datetime, jam: float) -> datetime:
        """`mulai` + N jam; bila jatuh di hari libur digeser ke hari kerja berikutnya (jam yang sama)."""
        t = to_wib(mulai + timedelta(hours=float(jam or 0)))
        d = t.date()
        if self.kerja(d):
            return t.astimezone(timezone.utc)
        d2 = self.hari_kerja_berikut(d, 0)
        return datetime.combine(d2, t.timetz().replace(tzinfo=None), tzinfo=WIB).astimezone(timezone.utc)

    def hari_kerja_lewat(self, dari: datetime, sampai: datetime) -> int:
        """Jumlah hari kerja WIB sesudah tanggal `dari` s.d. tanggal `sampai` (0 bila hari yang sama/sebelum)."""
        a, b = to_wib(dari).date(), to_wib(sampai).date()
        if b <= a:
            return 0
        n, cur = 0, a
        while cur < b:
            cur += timedelta(days=1)
            if self.kerja(cur):
                n += 1
        return n


async def muat_kalender(db, dari: date | None = None, sampai: date | None = None) -> Kalender:
    from core.workdays import get_work_calendar, holiday_set
    hari_ini = to_wib(now_utc()).date()
    dari = dari or (hari_ini - timedelta(days=120))
    sampai = sampai or (hari_ini + timedelta(days=60))
    cal = await get_work_calendar(db)
    try:
        libur = await holiday_set(db, dari, sampai)
    except Exception:  # noqa: BLE001 — kalender libur kosong tidak boleh mematikan pemindai
        libur = set()
    return Kalender(off_weekdays=frozenset(cal["off_weekdays"]), libur=set(libur))


def hitung_tenggat(tenggat: dict, *, kal: Kalender, mulai: datetime | None, periode: str | None = None,
                   tenggat_dokumen: datetime | None = None) -> datetime | None:
    """Batas waktu satu kejadian dari bentuk tenggat aturan.

    jenis:
      hari_kerja  {nilai: n}                 mulai + n hari kerja (jam yang sama)
      jam         {nilai: h}                 mulai + h jam (digeser bila jatuh di hari libur)
      jam_tetap   {hari: k, jam: 'HH:MM'}    kewajiban berkala periode tanggal D: hari kerja ke-k sesudah D, pukul jam
      dokumen     {}                         tanggal dari dokumen (mis. jatuh tempo tagihan) — akhir hari itu WIB
    """
    jenis = (tenggat or {}).get("jenis") or "hari_kerja"
    if jenis == "dokumen":
        if tenggat_dokumen is None:
            return None
        d = to_wib(tenggat_dokumen).date()
        return jam_wib(d, "23:59")
    if jenis == "jam_tetap":
        if not periode:
            return None
        try:
            d = date.fromisoformat(periode[:10])
        except ValueError:
            return None
        k = int(tenggat.get("hari") or 0)
        hari = kal.hari_kerja_berikut(d, k) if k > 0 else d
        return jam_wib(hari, tenggat.get("jam") or "23:59")
    if mulai is None:
        return None
    if jenis == "jam":
        return kal.tambah_jam(mulai, float(tenggat.get("nilai") or 0))
    return kal.tambah_hari_kerja(mulai, int(tenggat.get("nilai") or 1))


def label_tenggat(tenggat: dict) -> str:
    """Kalimat tenggat untuk layar (bahasa staf)."""
    jenis = (tenggat or {}).get("jenis") or "hari_kerja"
    if jenis == "jam":
        return f"{tenggat.get('nilai') or 0} jam"
    if jenis == "jam_tetap":
        k = int(tenggat.get("hari") or 0)
        jam = (tenggat.get("jam") or "23:59").replace(":", ".")
        if k <= 0:
            return f"hari itu pukul {jam}"
        return f"hari kerja berikutnya pukul {jam}" if k == 1 else f"{k} hari kerja kemudian pukul {jam}"
    if jenis == "dokumen":
        return "tanggal jatuh tempo dokumen"
    return f"{int(tenggat.get('nilai') or 1)} hari kerja"
