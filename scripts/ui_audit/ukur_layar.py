"""Ukur layar (Alat 2 rencana UI/UX 8 Nov 2026) — mengukur apa yang BENAR-BENAR tampil, bukan pola kode.

Dijalankan di container Playwright terhadap aplikasi yang berjalan:
    python ukur_layar.py --base http://host --token galeri_token.json --target target.json --out hasil/ --tahap sebelum

target.json: [{"nama": "pengumuman", "portal": "hr", "modul": "hr-announcements",
               "aksi": [{"jenis": "klik", "pilih": "[data-testid=create-announcement-btn]", "nama": "form-baru"}]}]
Setiap "keadaan" (halaman awal + tiap aksi) diukur di lebar 1440 dan 390; tangkapan layar penuh (digulir) disimpan.

Pemeriksaan (V = nomor di rencana):
  V1 kepala_px       tinggi blok kepala (judul + subjudul + tombol) dari atas area konten
  V2 konten_mulai    posisi y elemen utama pertama (tabel/daftar/form/grafik) sebagai % tinggi layar
  V3 terpotong       elemen yang isinya terpotong (scrollWidth > clientWidth) + geser samping halaman
  V4 bertumpuk       pasangan teks yang saling menimpa
  V5 ukuran_huruf    jumlah ukuran huruf berbeda pada teks tampil
  V6 kontras         teks dengan rasio kontras < 4.5 (normal) / < 3 (besar)
  V8 daftar_kartu    kelompok kartu berulang (≥ 6 saudara, tinggi ≥ 70 px) yang seharusnya tabel
  V9 penyaring_lebar kotak cari/pilihan yang lebih lebar dari 420 px (desktop; isian di dalam popup form tidak dihitung)
  V10 tanggal_bawaan isian tanggal bawaan peramban
  V11 istilah        kata Inggris/istilah program yang tampil + label HURUF BESAR
  V12 nilai_aneh     undefined/NaN/null/Invalid Date/[object Object] yang tampil
  V14 galat_konsol, panggilan_api
"""
import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ISTILAH = [
    "announcement", "management", "update", "edit", "priority", "success", "warning", "urgent", "info",
    "submit", "export", "import", "upload", "download", "settlement", "approval", "approve", "reject",
    "template", "assignment", "headcount", "grade", "preview", "draft", "overview", "summary",
    "stock", "catalog", "catalogue", "bulk", "history", "sync", "link", "unlink",
    "listing", "sku master", "default", "fallback", "track", "reimbursement", "per diem", "expense",
    "save", "cancel", "delete", "create", "new", "view", "search", "refresh", "selector",
    "low stock", "out of stock", "in stock", "active", "inactive", "items",
]
# singkatan/nama yang boleh (keputusan 10)
BOLEH = {"PO", "SKU", "CMT", "QC", "HPP", "CV", "DA", "SDM", "RnD", "PIC", "WIB", "PDF", "CSV", "AI", "ID",
         "OKR", "KPI", "NPWP", "PPN", "BOM", "HR", "SMU", "API", "URL", "Rp", "SPP", "PR", "TikTok", "Shopee",
         "Tokopedia", "Lazada", "Blibli", "Instagram", "Website", "Excel"}

JS_UKUR = r"""
(arg) => {
  const ISTILAH = arg.istilah, BOLEH = new Set(arg.boleh);
  const root = document.querySelector('[role=dialog]') && arg.dialog ? document.querySelector('[role=dialog]')
             : (document.querySelector('main') || document.body);
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity||'1') > 0.05; };
  const teksEl = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) { const n = walker.currentNode; const t = n.textContent.trim();
    if (!t || !n.parentElement || !vis(n.parentElement)) continue; teksEl.push(n); }
  const rootR = root.getBoundingClientRect();
  // V1 kepala: judul (h1/h2 atau [data-page-header]) — bawah blok kepala relatif atas root
  let kepala = 0;
  const hdr = root.querySelector('[data-page-header], header, h1, h2');
  if (hdr) { let blk = hdr.closest('[data-page-header]') || hdr.parentElement || hdr; const r = blk.getBoundingClientRect();
    kepala = Math.round(r.bottom - rootR.top); }
  // V2 konten utama pertama
  const utama = root.querySelector('table, [role=table], [data-konten-utama], [role=tabpanel] table, form, .recharts-wrapper, ul li, [data-testid*=list], [data-testid*=card]');
  const kontenY = utama ? Math.round(utama.getBoundingClientRect().top + window.scrollY) : null;
  // V3 terpotong
  const terpotong = [];
  root.querySelectorAll('input, button, label, td, th, span, p, a, [role=combobox], h1, h2, h3').forEach(el => {
    if (!vis(el)) return; const s = getComputedStyle(el);
    if (el.closest('.sr-only') || (el.getBoundingClientRect().width <= 1)) return;  // teks khusus pembaca layar
    if (el.getAttribute('title') && s.textOverflow === 'ellipsis') return;  // dipotong sengaja, teks lengkap di keterangan
    if (el.scrollWidth > el.clientWidth + 2 && (s.overflow.includes('hidden') || s.textOverflow === 'ellipsis' || el.tagName === 'INPUT')) {
      terpotong.push((el.getAttribute('data-testid') || el.tagName.toLowerCase()) + ': ' + (el.value || el.textContent || '').trim().slice(0, 40)); }
  });
  const geserSamping = document.documentElement.scrollWidth > window.innerWidth + 1;
  // V3b terpotong di tepi kanan: elemen tampil yang melewati lebar layar dan TIDAK berada di wadah gulir-samping
  const gulirX = (el) => { let e = el.parentElement; while (e && e !== document.body) { const o = getComputedStyle(e).overflowX;
    if (o === 'auto' || o === 'scroll') return true; e = e.parentElement; } return false; };
  root.querySelectorAll('button, a, input, h1, h2, h3, p, td, th, [role=button]').forEach(el => {
    if (!vis(el) || el.closest('.sr-only')) return; const r = el.getBoundingClientRect();
    if (r.right > window.innerWidth + 1 && r.left < window.innerWidth && !gulirX(el))
      terpotong.push('tepi kanan: ' + (el.getAttribute('aria-label') || el.textContent || el.tagName).trim().slice(0, 30)); });
  // V4 bertumpuk (teks berbeda elemen saling menimpa)
  const kotak = teksEl.slice(0, 700).map(n => { const r = document.createRange(); r.selectNodeContents(n);
    const rb = r.getBoundingClientRect(); const pb = n.parentElement.getBoundingClientRect();
    const b = {left: Math.max(rb.left, pb.left), right: Math.min(rb.right, pb.right), top: Math.max(rb.top, pb.top), bottom: Math.min(rb.bottom, pb.bottom)};
    // potong juga dengan wadah gulir terdekat (isi popup yang tergulir di bawah kaki popup tidak terlihat)
    let e = n.parentElement.parentElement, langkah = 0;
    while (e && e !== document.body && langkah++ < 12) { const o = getComputedStyle(e);
      if (/(auto|scroll|hidden)/.test(o.overflowY + o.overflowX)) { const w = e.getBoundingClientRect();
        b.left = Math.max(b.left, w.left); b.right = Math.min(b.right, w.right); b.top = Math.max(b.top, w.top); b.bottom = Math.min(b.bottom, w.bottom); }
      e = e.parentElement; }
    b.width = b.right - b.left; b.height = b.bottom - b.top;
    return {el: n.parentElement, b, t: n.textContent.trim().slice(0, 30)}; })
    .filter(k => k.b.width > 2 && k.b.height > 2);
  const tumpuk = [];
  for (let i = 0; i < kotak.length && tumpuk.length < 20; i++) for (let j = i + 1; j < kotak.length; j++) {
    const a = kotak[i], c = kotak[j]; if (a.el.contains(c.el) || c.el.contains(a.el)) continue;
    const ox = Math.min(a.b.right, c.b.right) - Math.max(a.b.left, c.b.left);
    const oy = Math.min(a.b.bottom, c.b.bottom) - Math.max(a.b.top, c.b.top);
    if (ox > 4 && oy > 4) { tumpuk.push(a.t + ' ⟂ ' + c.t); if (tumpuk.length >= 20) break; } }
  // V5 ukuran huruf
  const ukuran = new Set(teksEl.map(n => getComputedStyle(n.parentElement).fontSize));
  // V6 kontras
  const lum = (rgb) => { const m = rgb.match(/[\d.]+/g); if (!m) return null; const [r,g,b] = m.slice(0,3).map(Number).map(v => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); }); return 0.2126*r + 0.7152*g + 0.0722*b; };
  const alpha = (c) => { const m = c.match(/[\d.]+/g); return m && m.length > 3 ? Number(m[3]) : 1; };
  const latar = (el) => { let e = el; while (e) { const s = getComputedStyle(e); if (s.backgroundColor && alpha(s.backgroundColor) > 0.6) return s.backgroundColor; e = e.parentElement; } return 'rgb(255,255,255)'; };
  const kontras = [];
  teksEl.slice(0, 700).forEach(n => { const el = n.parentElement; const s = getComputedStyle(el); const a = alpha(s.color);
    const L1 = lum(s.color), L2 = lum(latar(el)); if (L1 == null || L2 == null) return;
    const rasio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05) * (a < 1 ? a : 1);
    const besar = parseFloat(s.fontSize) >= 18.66 || (parseFloat(s.fontSize) >= 14 && parseInt(s.fontWeight) >= 700);
    if (rasio < (besar ? 3 : 4.5)) kontras.push(n.textContent.trim().slice(0, 30) + ' (' + rasio.toFixed(2) + ')'); });
  // V8 daftar sebagai kartu
  const daftarKartu = [];
  if (window.innerWidth >= 768) root.querySelectorAll('*').forEach(p => { const anak = [...p.children].filter(vis); if (anak.length < 6) return;
    const sig = anak.map(a => a.className && typeof a.className === 'string' ? a.className.split(' ').slice(0,4).join('.') : a.tagName);
    const sama = sig.filter(x => x === sig[0]).length; const tinggi = anak.map(a => a.getBoundingClientRect().height);
    if (sama >= 6 && tinggi.filter(h => h >= 70).length >= 6 && !['TBODY','TR','UL','OL','SELECT'].includes(p.tagName)) daftarKartu.push(p.tagName + ' ×' + sama); });
  // V9 penyaring lebar
  const lebar = []; if (window.innerWidth >= 1200 && !arg.dialog) root.querySelectorAll('input[type=search], input[placeholder*=ari], [role=combobox], select').forEach(el => {
    if (!vis(el)) return; const w = el.getBoundingClientRect().width; if (w > 420) lebar.push((el.getAttribute('placeholder') || el.textContent || el.tagName).trim().slice(0, 30) + ' ' + Math.round(w) + 'px'); });
  // V10 tanggal bawaan
  const tglBawaan = [...root.querySelectorAll('input[type=date], input[type=month], input[type=datetime-local]')].filter(vis).length;
  // V11 istilah
  const semuaTeks = teksEl.map(n => n.textContent.trim()).join(' \n ');
  const istilah = new Set();
  ISTILAH.forEach(k => { const re = new RegExp('(^|[^A-Za-z])' + k.replace(/ /g, '\\s+') + '([^A-Za-z]|$)', 'i'); if (re.test(semuaTeks)) istilah.add(k); });
  (semuaTeks.match(/\b[a-z]+_[a-z_]+\b/g) || []).forEach(x => istilah.add(x));
  // huruf besar: (a) gaya uppercase dari CSS pada teks yang aslinya huruf kecil, atau (b) label (th/label/tombol/judul/tab)
  // yang ditulis HURUF BESAR. Isi data (kode barang, nama pemasok di sel tabel) TIDAK dihitung.
  const kapital = new Set(); teksEl.forEach(n => { const t = n.textContent.trim(); const el = n.parentElement; const s = getComputedStyle(el);
    if (t.length <= 4 || BOLEH.has(t) || !/[A-Za-z]{4,}/.test(t)) return;
    const gayaCss = s.textTransform === 'uppercase' && /[a-z]/.test(t);
    const label = el.closest('th, label, button, h1, h2, h3, h4, [role=tab], legend') && t === t.toUpperCase() && !/\d/.test(t);
    if (gayaCss || label) kapital.add(t.toUpperCase().slice(0, 30)); });
  // V12 nilai aneh
  const aneh = (semuaTeks.match(/\b(undefined|NaN|null|Invalid Date)\b|\[object Object\]/g) || []);
  // V16 tabel tanpa unduh: ada tabel berisi, tetapi tidak ada tombol Unduh/Ekspor/CSV/Excel di halaman
  const adaTabel = [...root.querySelectorAll('table')].filter(vis).filter(t => t.querySelectorAll('tbody tr').length > 0).length;
  const adaUnduh = [...document.querySelectorAll('button, a')].filter(vis).some(b => /unduh|ekspor|export|csv|excel|xlsx/i.test((b.textContent || '') + ' ' + (b.getAttribute('aria-label') || '') + ' ' + (b.getAttribute('title') || '')));
  return { tabel_tanpa_unduh: (adaTabel > 0 && !adaUnduh) ? adaTabel : 0,
           kepala_px: kepala, konten_mulai_px: kontenY, tinggi_layar: window.innerHeight,
           terpotong, geser_samping: geserSamping, bertumpuk: tumpuk, ukuran_huruf: [...ukuran],
           kontras_rendah: kontras.slice(0, 25), jumlah_kontras_rendah: kontras.length,
           daftar_kartu: daftarKartu, penyaring_lebar: lebar, tanggal_bawaan: tglBawaan,
           istilah: [...istilah], huruf_besar: [...kapital].slice(0, 15), nilai_aneh: aneh,
           tinggi_halaman: document.documentElement.scrollHeight };
}
"""


def ukur(pg, dialog=False):
    return pg.evaluate(JS_UKUR, {"istilah": ISTILAH, "boleh": sorted(BOLEH), "dialog": dialog})


def ringkas(m):
    """Skor sederhana: jumlah temuan per pemeriksaan (untuk tabel sebelum/sesudah)."""
    t = m.get("tinggi_layar") or 900
    km = m.get("konten_mulai_px")
    return {
        "V1 kepala >96px": 0 if m.get("dialog") else int((m.get("kepala_px") or 0) > (140 if m.get("lebar", 1440) < 768 else 96)),
        "V2 konten utama >40% layar": int(km is not None and km > 0.4 * t),
        "V3 terpotong": len(m["terpotong"]) + int(m["geser_samping"]),
        "V4 bertumpuk": len(m["bertumpuk"]),
        "V5 ukuran huruf >5": max(0, len(m["ukuran_huruf"]) - 5),
        "V6 kontras rendah": m["jumlah_kontras_rendah"],
        "V8 daftar-kartu": len(m["daftar_kartu"]),
        "V9 penyaring lebar": len(m["penyaring_lebar"]),
        "V10 tanggal bawaan": m["tanggal_bawaan"],
        "V11 istilah/huruf besar": len(m["istilah"]) + len(m["huruf_besar"]),
        "V16 tabel tanpa unduh": 0 if m.get("dialog") else int(bool(m.get("tabel_tanpa_unduh"))),
        "V12 nilai aneh": len(m["nilai_aneh"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tahap", default="sebelum")
    a = ap.parse_args()
    tok = json.loads(Path(a.token).read_text(encoding="utf-8"))
    targets = json.loads(Path(a.target).read_text(encoding="utf-8"))
    out = Path(a.out) / a.tahap
    out.mkdir(parents=True, exist_ok=True)
    hasil = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for lebar, tinggi, hp in ((1440, 900, False), (390, 844, True)):
            ctx = b.new_context(viewport={"width": lebar, "height": tinggi}, locale="id-ID", is_mobile=hp,
                                has_touch=hp, device_scale_factor=1)
            ctx.add_init_script(f"localStorage.setItem('erp_token', {json.dumps(tok['token'])});"
                                f"localStorage.setItem('erp_user', {json.dumps(json.dumps(tok['user']))});")
            for t in targets:
                pg = ctx.new_page()
                galat, api = [], []
                pg.on("console", lambda m, g=galat: g.append(m.text[:200]) if m.type == "error" else None)
                pg.on("pageerror", lambda e, g=galat: g.append("PAGEERROR " + str(e)[:200]))
                pg.on("request", lambda r, c=api: c.append(r.url) if "/api/" in r.url else None)
                pg.goto(f"{a.base}/?portal={t['portal']}&module={t['modul']}#{t['modul']}", wait_until="domcontentloaded")
                pg.wait_for_timeout(t.get("tunggu", 3500))
                keadaan = [("awal", None)] + [(x["nama"], x) for x in t.get("aksi", [])]
                for nama, aksi in keadaan:
                    if aksi:
                        try:
                            if aksi.get("muat_ulang"):
                                pg.goto(f"{a.base}/?portal={t['portal']}&module={t['modul']}#{t['modul']}",
                                        wait_until="domcontentloaded")
                                pg.wait_for_timeout(t.get("tunggu", 3500))
                            for langkah in aksi.get("langkah", [aksi]):
                                pg.locator(langkah["pilih"]).first.click(timeout=8000)
                                pg.wait_for_timeout(langkah.get("tunggu", 1200))
                        except Exception as e:  # noqa: BLE001
                            hasil.append({"target": t["nama"], "keadaan": nama, "lebar": lebar, "galat_aksi": str(e)[:200]})
                            continue
                    dialog = bool(aksi and aksi.get("dialog"))
                    m = ukur(pg, dialog=dialog)
                    m.update({"target": t["nama"], "keadaan": nama, "lebar": lebar, "dialog": dialog,
                              "galat_konsol": list(galat), "panggilan_api": len(api)})
                    m["ringkas"] = ringkas(m)
                    hasil.append(m)
                    pg.screenshot(path=str(out / f"{t['nama']}__{nama}__{lebar}.png"), full_page=not dialog)
                    if aksi and aksi.get("tutup"):
                        try:
                            pg.keyboard.press("Escape")
                            pg.wait_for_timeout(600)
                        except Exception:  # noqa: BLE001
                            pass
                pg.close()
            ctx.close()
        b.close()
    (out / "hasil.json").write_text(json.dumps(hasil, ensure_ascii=False, indent=1), encoding="utf-8")
    for h in hasil:
        if "ringkas" in h:
            tot = sum(h["ringkas"].values())
            print(f"{h['target']:12s} {h['keadaan']:16s} {h['lebar']:5d}  total temuan={tot:3d}  "
                  + "  ".join(f"{k.split()[0]}={v}" for k, v in h["ringkas"].items() if v))
        else:
            print(f"{h['target']:12s} {h['keadaan']:16s} {h['lebar']:5d}  GALAT AKSI: {h.get('galat_aksi')}")


if __name__ == "__main__":
    main()
