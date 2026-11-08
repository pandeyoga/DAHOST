"""Jelajah semua menu satu atau beberapa portal lalu ukur (Alat 2 rencana UI/UX 8 Nov 2026).

Daftar menu dibaca dari frontend/src/components/erp/portal-shell/portalNav.js (bukan diketik tangan).
Untuk tiap menu, di lebar 1440 dan 390:
  1. keadaan awal;
  2. setiap tab ([role=tab]) diklik satu per satu;
  3. form pertama: tombol berlabel Tambah/Buat/Baru/Input/Ajukan/Catat (bila ada) → diukur sebagai dialog;
  4. detail pertama: tombol Detail/Lihat/Rincian/Buka atau baris tabel pertama → diukur bila membuka dialog.
Keluaran: <out>/<tahap>/hasil.json, ringkas.csv, dan tangkapan layar per keadaan.

Pakai (di container Playwright, dari folder yang berisi skrip ini + ukur_layar.py):
  python jelajah_layar.py --base http://host --token galeri_token.json --portal warehouse,cutting \
      --nav portalNav.js --out hasil --tahap sebelum [--menu wh-stock,wh-opname] [--lebar 1440,390]
"""
import argparse
import csv
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

import ukur_layar as U

TOMBOL_FORM = re.compile(r"^\s*(\+\s*)?(tambah|buat|baru|input|ajukan|catat|rekam)\b", re.I)
TOMBOL_DETAIL = re.compile(r"^\s*(detail|lihat|rincian|buka)\b", re.I)
KOSONG = {"tinggi_layar": 900, "konten_mulai_px": None, "terpotong": [], "geser_samping": False, "bertumpuk": [],
          "ukuran_huruf": [], "jumlah_kontras_rendah": 0, "daftar_kartu": [], "penyaring_lebar": [],
          "tanggal_bawaan": 0, "istilah": [], "huruf_besar": [], "nilai_aneh": []}


def baca_menu(nav_path, portals):
    s = Path(nav_path).read_text(encoding="utf-8")
    hasil, portal = {}, None
    for line in s.splitlines():
        m = re.match(r"\s{2}([a-z_]+):\s*\{", line)
        if m:
            portal = m.group(1)
        for mid, lab in re.findall(r"\{\s*id:\s*'([^']+)',\s*label:\s*'([^']+)'", line):
            if portal in portals:
                hasil.setdefault(portal, []).append((mid, lab))
    return hasil


def ukur_simpan(pg, out, kunci, dialog, meta, hasil, galat, api):
    m = U.ukur(pg, dialog=dialog)
    m.update(meta)
    m.update({"dialog": dialog, "galat_konsol": list(galat), "panggilan_api": len(api)})
    m["ringkas"] = U.ringkas(m)
    hasil.append(m)
    try:
        pg.screenshot(path=str(out / f"{kunci}.png"), full_page=not dialog)
    except Exception:  # noqa: BLE001
        pass


def tutup_dialog(pg):
    for _ in range(3):
        if pg.locator("[role=dialog], [role=alertdialog]").count():
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(400)


def teks(el):
    try:
        return (el.inner_text() or el.get_attribute("aria-label") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def jelajah_menu(pg, a, out, portal, mid, lab, lebar, hasil):
    galat, api = [], []
    pg.on("console", lambda m: galat.append(m.text[:200]) if m.type == "error" else None)
    pg.on("pageerror", lambda e: galat.append("PAGEERROR " + str(e)[:200]))
    pg.on("request", lambda r: api.append(r.url) if "/api/" in r.url else None)
    meta = {"portal": portal, "menu": mid, "label": lab, "lebar": lebar}
    pg.goto(f"{a.base}/?portal={portal}&module={mid}#{mid}", wait_until="domcontentloaded")
    pg.wait_for_timeout(a.tunggu)
    ukur_simpan(pg, out, f"{portal}__{mid}__awal__{lebar}", False, {**meta, "keadaan": "awal"}, hasil, galat, api)
    tabs = pg.locator("main [role=tab]")
    n = min(tabs.count(), 12)
    for i in range(1, n):
        try:
            t = tabs.nth(i)
            if t.is_disabled():
                continue
            nama = (teks(t) or f"tab{i}").split("\n")[0][:30]
            t.click(timeout=3000)
            pg.wait_for_timeout(1500)
            ukur_simpan(pg, out, f"{portal}__{mid}__tab{i}__{lebar}", False, {**meta, "keadaan": f"tab: {nama}"},
                        hasil, galat, api)
        except Exception:  # noqa: BLE001
            continue
    if n > 1:
        try:
            tabs.nth(0).click(timeout=3000)
            pg.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass
    try:
        tombol = [x for x in pg.locator("main button:visible").all() if TOMBOL_FORM.match(teks(x))]
        if tombol:
            label_t = teks(tombol[0])[:30]
            tombol[0].click(timeout=3000)
            pg.wait_for_timeout(1200)
            if pg.locator("[role=dialog]").count():
                ukur_simpan(pg, out, f"{portal}__{mid}__form__{lebar}", True, {**meta, "keadaan": "form: " + label_t},
                            hasil, galat, api)
            tutup_dialog(pg)
    except Exception:  # noqa: BLE001
        tutup_dialog(pg)
    try:
        cand = [x for x in pg.locator("main button:visible").all() if TOMBOL_DETAIL.match(teks(x))]
        target = cand[0] if cand else None
        # baris tabel (layar lebar) atau kartu ringkas TabelData (HP)
        for sel in ("main tbody tr:visible", "main [data-testid$='-kartu']:visible"):
            if target is None and pg.locator(sel).count():
                target = pg.locator(sel).first
        if target is not None:
            target.click(timeout=3000)
            pg.wait_for_timeout(1200)
            if pg.locator("[role=dialog]").count():
                ukur_simpan(pg, out, f"{portal}__{mid}__detail__{lebar}", True, {**meta, "keadaan": "detail"},
                            hasil, galat, api)
            tutup_dialog(pg)
    except Exception:  # noqa: BLE001
        tutup_dialog(pg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--portal", required=True)
    ap.add_argument("--nav", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tahap", default="sebelum")
    ap.add_argument("--menu", default="")
    ap.add_argument("--lebar", default="1440,390")
    ap.add_argument("--tunggu", type=int, default=3000)
    a = ap.parse_args()
    tok = json.loads(Path(a.token).read_text(encoding="utf-8"))
    portals = [p.strip() for p in a.portal.split(",") if p.strip()]
    hanya = {m.strip() for m in a.menu.split(",") if m.strip()}
    menu = baca_menu(a.nav, portals)
    out = Path(a.out) / a.tahap
    out.mkdir(parents=True, exist_ok=True)
    hasil = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for lebar in [int(x) for x in a.lebar.split(",")]:
            hp = lebar < 768
            ctx = b.new_context(viewport={"width": lebar, "height": 844 if hp else 900}, locale="id-ID",
                                is_mobile=hp, has_touch=hp, device_scale_factor=1, accept_downloads=True)
            ctx.add_init_script(f"localStorage.setItem('erp_token', {json.dumps(tok['token'])});"
                                f"localStorage.setItem('erp_user', {json.dumps(json.dumps(tok['user']))});")
            for portal, items in menu.items():
                for mid, lab in items:
                    if hanya and mid not in hanya:
                        continue
                    pg = ctx.new_page()
                    pg.set_default_timeout(6000)
                    try:
                        jelajah_menu(pg, a, out, portal, mid, lab, lebar, hasil)
                    except Exception as e:  # noqa: BLE001
                        hasil.append({"portal": portal, "menu": mid, "label": lab, "lebar": lebar,
                                      "keadaan": "awal", "galat_aksi": str(e)[:200]})
                    pg.close()
            ctx.close()
        b.close()
    (out / "hasil.json").write_text(json.dumps(hasil, ensure_ascii=False, indent=1), encoding="utf-8")
    kunci_v = list(U.ringkas(dict(KOSONG)).keys())
    with open(out / "ringkas.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["portal", "menu", "label", "keadaan", "lebar", "total"] + kunci_v + ["galat_konsol"])
        for h in hasil:
            r = h.get("ringkas") or {}
            w.writerow([h.get("portal"), h.get("menu"), h.get("label"), h.get("keadaan"), h.get("lebar"),
                        sum(r.values()) if r else "GALAT"] + [r.get(k, "") for k in kunci_v]
                       + [len(h.get("galat_konsol") or [])])
    tot = sum(sum((h.get("ringkas") or {}).values()) for h in hasil)
    print(f"RINGKAS {len(hasil)} keadaan diukur, total temuan {tot}")


if __name__ == "__main__":
    main()
