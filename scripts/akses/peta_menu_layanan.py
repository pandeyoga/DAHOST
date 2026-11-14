#!/usr/bin/env python3
"""Peta menu → layanan (STATIS, dari kode frontend) — 14 Nov 2026.

Owner: "bisakah dibuatkan sehingga otomatis cek lapisan yang lain untuk semua akses role" dan "apa yang harus di
ceklis di portal lain ikut juga". Untuk tiap menu di `portalNav.js`, skrip ini mencari layar yang dibuka menu itu
(`moduleRegistry.js`, termasuk `makeRedirect`), mengikuti impor relatif di `frontend/src`, lalu mencatat layanan
(METODE + alamat API) yang dipanggil layar itu. Hasilnya dipakai backend:

  * `data/module_catalog.modul_setara` — layanan modul lain yang dipanggil layar sebuah menu ikut terbuka bagi
    pemegang centang aksi yang sama di modul pemilik menu (gerbang + penjaga di kode);
  * `data/module_catalog.menu_access` — tombol layar ikut tampil bila peran punya centang aksi layanan yang dipanggil;
  * `core/cek_akses.py` — Pemeriksaan otomatis di Kontrol Akses › Peran & Hak Akses.

Keluaran (urut, tanpa tanggal, deterministik):
  backend/data/peta_menu_layanan.json   {menu_id: [[METODE, "/api/…"], …]}
  backend/data/peta_menu_label.json     {menu_id: {"label": "…", "portal": ["…"]}}  (nama menu untuk kalimat staf)

Pakai (dari akar repo; Python biasa, tanpa Node):
  python3 scripts/akses/peta_menu_layanan.py           # tulis ulang kedua berkas
  python3 scripts/akses/peta_menu_layanan.py --check   # exit 1 bila berkas tidak mutakhir (dipakai CI)

Pembacaan menu, registry, dan graf impor memakai `scripts/asisten_katalog/peta_layar.py` (satu pembaca layar untuk
katalog Asisten AI dan peta ini).

KETERBATASAN (heuristik statis, sengaja aman: yang tidak terbaca = TIDAK ikut terbuka, bukan sebaliknya)
  * Panggilan yang dikenali: `apiGet/apiPost/apiPut/apiPatch/apiDelete/apiDownload/apiUpload('/x…')` (helper
    `lib/api` & `lib/apiFetch` menambah `/api`), `apiFetch(…)`, `sseFetch(…)` (bawaan POST), `fetch(…)`,
    `axios.get/post/put/patch/delete(…)`, `window.open(…)` dan `href=` templat (unduhan, GET).
  * Pembungkus buatan sendiri dikenali bila berupa fungsi bernama (`function x(path…)`, `const x = (path…) =>`)
    yang meneruskan parameternya ke salah satu panggilan di atas (mis. `cuttingApi(method, path)`, `useApi(path)`),
    di berkas yang sama atau diimpor dengan nama yang sama. Objek/kelas klien (`api.get`) dan hook tanpa nama tidak.
  * Alamat harus berupa literal/templat/penggabungan `+`/ternary, atau konstanta `const|let|var` di berkas yang sama
    (definisi terdekat sebelum panggilan). Alamat dari state, props, `useMemo`, atau objek konfigurasi dilewati.
  * `${…}` di awal segmen → segmen generik `x`; `${…}` di tengah segmen (mis. `accounts${qs}`) dianggap query dan
    dibuang (kecuali didahului `-`/`_`/`.` → `x`). Query string (`?…`) dibuang.
  * Metode dari nama helper, atau `method:` di argumen opsi (semua literal pada ekspresi bersyarat dicatat).
    `method` dinamis tanpa literal → panggilan dilewati. Tanpa `method:` → GET (fetch/apiFetch), POST (sseFetch).
  * Impor diikuti sampai `KEDALAMAN` tingkat; `moduleRegistry.js`/`App.js` tidak diikuti. Berkas yang dicapai
    lebih dari `peta_layar.SHARED_LIMIT` menu dianggap infrastruktur bersama dan tidak diatribusikan ke menu.
  * Satu berkas = satu layar: tab/dialog yang diimpor layar menu itu ikut terhitung walau jarang dibuka.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "asisten_katalog"))
from peta_layar import ENVISH, SHARED_LIMIT, PetaLayar  # noqa: E402

OUT_PETA = os.path.join(ROOT, "backend", "data", "peta_menu_layanan.json")
OUT_LABEL = os.path.join(ROOT, "backend", "data", "peta_menu_label.json")
KEDALAMAN = 8
LEWATI = ("moduleRegistry.js", "App.js")
PH = ""                     # penanda nilai dinamis
PARAM = 0xE100                    # penanda parameter pembungkus ke-i = chr(PARAM + i)

_CALL_NAMA = ("apiGet", "apiPost", "apiPut", "apiPatch", "apiDelete", "apiDownload", "apiUpload", "apiFetch",
              "sseFetch", "fetch", r"axios\.(?:get|post|put|patch|delete)", r"window\.open")
_HREF_RX = re.compile(r"(?:\bhref\s*=\s*\{|\.href\s*=)\s*")
_DEF_RX = re.compile(r"(?<![\w$.])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*")
_FUNGSI_RX = re.compile(
    r"(?<![\w$.])(?:function\s+([A-Za-z_$][\w$]*)\s*\(|(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\()")
_IMPOR_RX = re.compile(r"""(?m)^\s*import\s+([^'";]*?)\s+from\s*['"]([^'"]+)['"]""")
_KOMENTAR_BLOK = re.compile(r"/\*.*?\*/", re.S)
_KOMENTAR_BARIS = re.compile(r"(?m)^([^\n\"'`]*?)//.*$")
_METODE_HELPER = {"apiGet": "GET", "apiDownload": "GET", "apiPost": "POST", "apiUpload": "POST", "apiPut": "PUT",
                  "apiPatch": "PATCH", "apiDelete": "DELETE", "window.open": "GET", "axios.get": "GET",
                  "axios.post": "POST", "axios.put": "PUT", "axios.patch": "PATCH", "axios.delete": "DELETE"}
_TAMBAH_API = {"apiGet", "apiPost", "apiPut", "apiPatch", "apiDelete", "apiDownload", "apiUpload", "apiFetch",
               "sseFetch"}
_METODE = ("GET", "POST", "PUT", "PATCH", "DELETE")
_ID = re.compile(r"[A-Za-z_$][\w$]*")


def tanpa_komentar(teks: str) -> str:
    """Buang komentar JS tanpa menyentuh string (komentar baris hanya bila tidak ada kutip sebelumnya)."""
    teks = _KOMENTAR_BLOK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), teks)
    return _KOMENTAR_BARIS.sub(lambda m: m.group(1), teks)


# ═══════════════ pemindai ekspresi JS sederhana (string, templat, kurung) ═══════════════
def _akhir_string(s: str, i: int) -> int:
    q, j = s[i], i + 1
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == q or c == "\n":
            return j
        j += 1
    return len(s) - 1


def _akhir_templat(s: str, i: int) -> int:
    j = i + 1
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "`":
            return j
        if c == "$" and s[j + 1:j + 2] == "{":
            j = _akhir_kurung(s, j + 1)
        j += 1
    return len(s) - 1


def _akhir_kurung(s: str, i: int, batas: int = 6000) -> int:
    """s[i] = '(' / '[' / '{' → indeks penutupnya (melewati string & templat)."""
    depth, j, n = 0, i, min(len(s), i + batas)
    while j < n:
        c = s[j]
        if c in "'\"":
            j = _akhir_string(s, j)
        elif c == "`":
            j = _akhir_templat(s, j)
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return n - 1


def _pisah(s: str, pemisah: str) -> list[str]:
    """Pisah di tingkat teratas (di luar kurung/string) pada karakter `pemisah`."""
    out, depth, j, awal = [], 0, 0, 0
    while j < len(s):
        c = s[j]
        if c in "'\"":
            j = _akhir_string(s, j)
        elif c == "`":
            j = _akhir_templat(s, j)
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0 and c == pemisah:
            out.append(s[awal:j])
            awal = j + 1
        j += 1
    out.append(s[awal:])
    return out


def _akhir_pernyataan(s: str, i: int, batas: int = 600) -> int:
    depth, j, n = 0, i, min(len(s), i + batas)
    while j < n:
        c = s[j]
        if c in "'\"":
            j = _akhir_string(s, j)
        elif c == "`":
            j = _akhir_templat(s, j)
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                return j
        elif depth == 0 and c in ";\n,":
            return j
        j += 1
    return n


def normal(u: str, tambah_api: bool) -> str | None:
    """Nilai string → '/api/…' (segmen dinamis = 'x', tanpa query) atau None."""
    u = u.split("?")[0].split("#")[0]
    i = u.find("/api/")
    if i >= 0:
        u = u[i:]
    elif tambah_api and u.startswith("/"):
        u = "/api" + u
    else:
        return None
    segs = []
    for seg in u.split("/"):
        if not seg:
            continue
        if seg.startswith(PH):
            segs.append("x")
        elif PH in seg:
            depan = seg.split(PH)[0]
            segs.append("x" if depan[-1:] in "-_." else depan)
        else:
            segs.append(seg)
    if len(segs) < 2 or segs[0] != "api" or segs[1] == "x" or not re.fullmatch(r"[\w.\-/]+", "/".join(segs)):
        return None
    return "/" + "/".join(segs)


class Berkas:
    """Satu berkas sumber: konstanta, pembungkus (fungsi yang meneruskan alamat), dan panggilan layanan."""

    def __init__(self, teks: str):
        self.s = tanpa_komentar(teks)
        self.param: dict = {}
        self.defs = collections.defaultdict(list)          # nama → [(posisi, ekspresi)]
        for m in _DEF_RX.finditer(self.s):
            akhir = _akhir_pernyataan(self.s, m.end())
            self.defs[m.group(1)].append((m.start(), self.s[m.end():akhir].strip()))
        self.impor = {}                                     # nama lokal → (spesifier, nama ekspor)
        for nama, spec in _IMPOR_RX.findall(self.s):
            bawaan, _, sisa = nama.partition("{")
            bawaan = bawaan.strip().rstrip(",").strip()
            if _ID.fullmatch(bawaan or "-"):
                self.impor[bawaan] = (spec, "default")
            for x in sisa.rstrip("}").split(","):
                asal, _, lokal = x.strip().partition(" as ")
                if _ID.fullmatch(asal.strip() or "-"):
                    self.impor[(lokal or asal).strip()] = (spec, asal.strip())
        self.pembungkus: dict = {}                          # nama → spesifikasi (lihat `_analisa_pembungkus`)
        self.pakai_pembungkus: dict = {}                    # pembungkus yang berlaku di berkas ini (lokal + impor)

    # ── nilai ekspresi ──
    def _definisi(self, nama: str, pos: int):
        daftar = self.defs.get(nama) or []
        sebelum = [e for p, e in daftar if p < pos]
        return sebelum[-1] if sebelum else (daftar[0][1] if daftar else None)

    def nilai(self, expr: str, pos: int, depth: int = 0) -> list[str] | None:
        """Kemungkinan nilai string sebuah ekspresi (PH = bagian dinamis); None bila tidak terbaca."""
        e = (expr or "").strip()
        while e.startswith("(") and _akhir_kurung(e, 0) == len(e) - 1:
            e = e[1:-1].strip()
        if not e or depth > 5:
            return None
        if e in self.param:
            return [self.param[e]]
        if e[0] in "'\"" and _akhir_string(e, 0) == len(e) - 1:
            return [e[1:-1]]
        if e[0] == "`" and _akhir_templat(e, 0) == len(e) - 1:
            return self._templat(e[1:-1], pos, depth)
        bagian = _pisah(e, "?")
        if len(bagian) == 2 and not bagian[1].startswith((".", "?")):
            cabang = _pisah(bagian[1], ":")
            if len(cabang) == 2:
                out = (self.nilai(cabang[0], pos, depth + 1) or []) + (self.nilai(cabang[1], pos, depth + 1) or [])
                return out[:6] or None
        plus = _pisah(e, "+")
        if len(plus) > 1:
            hasil = [""]
            for k, p in enumerate(plus):
                v = self.nilai(p, pos, depth + 1)
                if v is None:
                    if k == 0:
                        return None
                    v = [PH]
                hasil = [a + b for a in hasil for b in v][:6]
            return hasil
        if re.fullmatch(r"[A-Za-z_$][\w$.]*", e):
            d = self._definisi(e, pos) if "." not in e else None
            if d is not None:
                v = self.nilai(d, pos, depth + 1)
                if v is not None:
                    return v
                return [""] if ENVISH.search(d) else None
            return [""] if ENVISH.search(e) else None
        if ENVISH.search(e) and "||" in e:
            return [""]
        return None

    def _templat(self, isi: str, pos: int, depth: int) -> list[str]:
        hasil, j, awal = [""], 0, 0
        while j < len(isi):
            if isi[j] == "\\":
                j += 2
                continue
            if isi[j] == "$" and isi[j + 1:j + 2] == "{":
                tutup = _akhir_kurung(isi, j + 1)
                hasil = [h + isi[awal:j] for h in hasil]
                dalam = isi[j + 2:tutup]
                v = self.nilai(dalam, pos, depth + 1)
                if v is None:
                    v = [""] if ENVISH.search(dalam) else [PH]
                hasil = [h + x for h in hasil for x in v][:6]
                j = awal = tutup + 1
                continue
            j += 1
        return [h + isi[awal:] for h in hasil]

    def _metode_opsi(self, opsi: str, pos: int, bawaan: str) -> list[str] | int:
        """Metode dari argumen opsi; int = indeks parameter pembungkus yang membawa metode."""
        o = opsi.strip()
        if _ID.fullmatch(o or "-"):
            if o in self.param:
                return ("opsi", ord(self.param[o]) - PARAM)
            o = self._definisi(o, pos) or ""
        m = re.search(r"(?<![\w$])method\s*(:|,|\})", o)
        if not m:
            return [bawaan]
        if m.group(1) != ":":                               # `{ method }` (singkatan)
            return ("metode", ord(self.param["method"]) - PARAM) if "method" in self.param else []
        ekspr = o[m.end():_akhir_pernyataan(o, m.end())].strip()
        if ekspr in self.param:
            return ("metode", ord(self.param[ekspr]) - PARAM)
        return sorted({x.upper() for x in re.findall(r"['\"`](\w+)['\"`]", ekspr)} & set(_METODE))

    # ── panggilan ──
    def _panggilan_mentah(self, s: str, base: int):
        """[(nama, args, posisi)] untuk panggilan helper bawaan + pembungkus yang berlaku."""
        nama = list(_CALL_NAMA) + [re.escape(n) for n in self.pakai_pembungkus]
        rx = re.compile(r"(?<![\w$.])(" + "|".join(nama) + r")\s*\(")
        for m in rx.finditer(s):
            buka = m.end() - 1
            tutup = _akhir_kurung(s, buka)
            yield m.group(1), _pisah(s[buka + 1:tutup], ","), base + m.start()

    def _urai(self, nama: str, args: list[str], pos: int):
        """[(metode | ('metode'|'opsi', i), nilai URL, tambah_api)] satu panggilan."""
        if nama in self.pakai_pembungkus:
            spec = self.pakai_pembungkus[nama]
            if len(args) <= spec["i"]:
                return []
            urls = self.nilai(args[spec["i"]], pos) or []
            mt = spec["metode"]
            if isinstance(mt, tuple):
                k = mt[1]
                arg = args[k] if len(args) > k else ""
                mt = (sorted({x.upper() for x in re.findall(r"['\"`](\w+)['\"`]", arg)} & set(_METODE))
                      if mt[0] == "metode" else self._metode_opsi(arg, pos, "GET"))
                if isinstance(mt, tuple):
                    mt = []
            return [(mt, spec["awal"] + u + spec["akhir"], spec["api"]) for u in urls]
        urls = self.nilai(args[0], pos) if args else None
        if not urls:
            return []
        if nama in _METODE_HELPER:
            mt = [_METODE_HELPER[nama]]
        else:
            mt = self._metode_opsi(args[1] if len(args) > 1 else "", pos, "POST" if nama == "sseFetch" else "GET")
        return [(mt, u, nama in _TAMBAH_API) for u in urls]

    def analisa_pembungkus(self):
        """Fungsi bernama yang meneruskan parameternya sebagai (bagian) alamat ke helper/fetch."""
        s = self.s
        for m in _FUNGSI_RX.finditer(s):
            nama = m.group(1) or m.group(2)
            buka = m.end() - 1
            tutup = _akhir_kurung(s, buka)
            params = [p.split("=")[0].strip() for p in _pisah(s[buka + 1:tutup], ",")]
            if not any(_ID.fullmatch(p or "-") for p in params):
                continue
            j = tutup + 1
            while j < len(s) and s[j] in " \t\n":
                j += 1
            if m.group(2):                                  # const x = (…) => …  (bukan ekspresi berkurung)
                if s[j:j + 2] != "=>":
                    continue
                j += 2
                while j < len(s) and s[j] in " \t\n":
                    j += 1
            if j >= len(s):
                continue
            akhir = _akhir_kurung(s, j) if s[j] == "{" else _akhir_pernyataan(s, j, 2000)
            badan = s[j:akhir + 1]
            self.param = {p: chr(PARAM + i) for i, p in enumerate(params) if _ID.fullmatch(p or "-")}
            try:
                for n, args, pos in self._panggilan_mentah(badan, j):
                    if n == nama:
                        continue
                    for mt, u, api in self._urai(n, args, pos):
                        tanda = [c for c in u if PARAM <= ord(c) < PARAM + 32]
                        if len(tanda) != 1 or (isinstance(mt, list) and not mt):
                            continue
                        idx = ord(tanda[0]) - PARAM
                        if isinstance(mt, list) and any(PARAM <= ord(c) < PARAM + 32 for x in mt for c in x):
                            continue
                        awal, _, akhir_u = u.partition(tanda[0])
                        self.pembungkus.setdefault(nama, {"i": idx, "awal": awal, "akhir": akhir_u,
                                                          "api": api, "metode": mt})
            finally:
                self.param = {}

    def panggilan(self) -> set[tuple[str, str]]:
        out: set = set()
        for nama, args, pos in self._panggilan_mentah(self.s, 0):
            for mt, u, api in self._urai(nama, args, pos):
                if isinstance(mt, tuple) or any(PARAM <= ord(c) < PARAM + 32 for c in u):
                    continue
                p = normal(u, api)
                if p:
                    out.update((x, p) for x in mt)
        for m in _HREF_RX.finditer(self.s):
            if self.s[m.end():m.end() + 1] != "`":
                continue
            akhir = _akhir_templat(self.s, m.end())
            for u in self.nilai(self.s[m.end():akhir + 1], m.start()) or ():
                p = normal(u, False)
                if p:
                    out.add(("GET", p))
        return out


# ═══════════════ menu → berkas → layanan ═══════════════
def susun(root: str = ROOT) -> tuple[dict, dict]:
    pl = PetaLayar(root)
    menus = sorted(pl.mod_label)

    def berkas_menu(mid: str):
        seen = set()
        while mid in pl.redir and mid not in seen:
            seen.add(mid)
            mid = pl.redir[mid]
        return pl.mod_file.get(mid)

    def jangkau(start: str) -> set:
        seen, antre = {start: 0}, [start]
        while antre:
            f = antre.pop(0)
            if seen[f] >= KEDALAMAN:
                continue
            for g in sorted(pl.graph.get(f, ())):
                if g not in seen and os.path.basename(g) not in LEWATI:
                    seen[g] = seen[f] + 1
                    antre.append(g)
        return set(seen)

    jangkauan = {m: jangkau(f) for m in menus if (f := berkas_menu(m))}
    pakai = collections.Counter(f for fs in jangkauan.values() for f in fs)
    berkas: dict = {}

    def baca(f: str) -> Berkas:
        if f not in berkas:
            with open(f, encoding="utf-8", errors="replace") as fh:
                b = berkas[f] = Berkas(fh.read())
            b.analisa_pembungkus()
        return berkas[f]

    def siapkan(f: str) -> Berkas:
        b = baca(f)
        if not b.pakai_pembungkus:
            b.pakai_pembungkus = dict(b.pembungkus)
            for lokal, (spec, asal) in b.impor.items():
                src = pl.resolve_impor(f, spec)
                if src and lokal not in b.pakai_pembungkus:
                    spek = baca(src).pembungkus.get(asal)
                    if spek:
                        b.pakai_pembungkus[lokal] = spek
        return b

    hasil_berkas: dict = {}
    peta = {}
    for m, fs in sorted(jangkauan.items()):
        semua = set()
        for f in sorted(fs):
            if pakai[f] > SHARED_LIMIT:
                continue
            if f not in hasil_berkas:
                hasil_berkas[f] = siapkan(f).panggilan()
            semua |= hasil_berkas[f]
        if semua:
            peta[m] = [list(x) for x in sorted(semua, key=lambda t: (t[1], t[0]))]
    label = {m: {"label": pl.mod_label[m], "portal": sorted(pl.mod_portal.get(m, ()))} for m in menus}
    return peta, label


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    peta, label = susun()
    keluaran = {OUT_PETA: _json(peta), OUT_LABEL: _json(label)}
    jumlah = sum(len(v) for v in peta.values())
    if "--check" in argv:
        basi = []
        for path, isi in keluaran.items():
            try:
                with open(path, encoding="utf-8") as fh:
                    lama = fh.read()
            except FileNotFoundError:
                lama = None
            if lama != isi:
                basi.append(os.path.relpath(path, ROOT).replace("\\", "/"))
        if basi:
            print("GAGAL: peta menu -> layanan tidak mutakhir:", ", ".join(basi))
            print("       jalankan `python3 scripts/akses/peta_menu_layanan.py` lalu commit hasilnya.")
            return 1
        print(f"OK: peta menu -> layanan mutakhir ({len(peta)} menu, {jumlah} pasangan menu-layanan)")
        return 0
    for path, isi in keluaran.items():
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(isi)
    print(f"ditulis: {len(peta)} menu, {jumlah} pasangan menu-layanan -> backend/data/peta_menu_layanan.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
