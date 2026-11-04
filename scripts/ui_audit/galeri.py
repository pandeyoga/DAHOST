"""Galeri layar satu portal — potret SEMUA menu & tab, lengkap dengan temuan audit (2026-11-04).

Satu perintah membuka setiap menu portal dan setiap tab hub-nya, menjalankan audit layar
(`dom_audit.js`), memotret isi halaman, lalu menyusun semuanya di SATU halaman HTML berdampingan.
Ketidakcocokan antarlayar (posisi tombol, ruang kosong, gaya tabel, popup) langsung terlihat.

Dijalankan di image resmi Playwright (tidak menambah paket ke aplikasi). Contoh (lokal, PowerShell/Git Bash):

    # 1) token sementara dari backend LOKAL (jangan ditampilkan; hapus setelah dipakai)
    docker exec -i dahost-local-backend-1 python - < scripts/ui_audit/buat_token_lokal.py > "$TEMP/galeri_token.json"
    # 2) galeri — container masuk jaringan app lokal; image tidak membawa paket python playwright
    MSYS_NO_PATHCONV=1 docker run --rm --network dahost-local_default \
      -v "$PWD:/repo:ro" -v "$TEMP:/work" mcr.microsoft.com/playwright/python:v1.49.1-noble sh -c \
      "pip install -q --break-system-packages playwright==1.49.1 >/dev/null 2>&1; \
       python3 /repo/scripts/ui_audit/galeri.py --portal finance --token-file /work/galeri_token.json \
       --base http://localhost:8080 --via http://caddy:80 --out /work/galeri_finance"
    # 3) buka $TEMP/galeri_finance/index.html

Pembanding sebelum/sesudah: tambahkan `--compare /work/galeri_finance_sebelum` (folder galeri lama).
Opsi: --width 1440 --height 900 · --dark · --only fin-ap-hub,fin-cash · --wait 2500
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scan_ui  # noqa: E402  (daftar menu portal & label dari portalNav)

LABEL_RX = re.compile(r"\{\s*id:\s*'([\w-]+)',\s*label:\s*'([^']+)'")

TABS_JS = """() => {
  const main = document.querySelector('main') || document.body;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const tl = [...main.querySelectorAll('[role="tablist"]')].filter(vis)[0];
  return tl ? [...tl.querySelectorAll('[role="tab"]')].map((t) => (t.innerText || '').trim()) : [];
}"""
CLICK_TAB_JS = """(i) => {
  const main = document.querySelector('main') || document.body;
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const tl = [...main.querySelectorAll('[role="tablist"]')].filter(vis)[0];
  const t = tl && tl.querySelectorAll('[role="tab"]')[i];
  if (!t) return false;
  t.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 }));
  t.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
  t.click();
  return true;
}"""
HEIGHT_JS = """() => { const m = document.querySelector('main'); if (!m) return document.body.scrollHeight;
  m.scrollTop = 0; return Math.ceil(m.getBoundingClientRect().top + m.scrollHeight); }"""


def labels_for(portal: str) -> dict[str, str]:
    blocks = scan_ui.portal_blocks(scan_ui.NAV.read_text(encoding="utf-8"))
    return dict(LABEL_RX.findall(blocks.get(portal, "")))


def run(a) -> int:
    from playwright.sync_api import sync_playwright

    ids, _ = scan_ui.portal_files(a.portal)
    if a.only:
        want = [x.strip() for x in a.only.split(",") if x.strip()]
        ids = [i for i in ids if i in want]
    names = labels_for(a.portal)
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    tok = json.loads(Path(a.token_file).read_text(encoding="utf-8"))
    audit_js = (HERE / "dom_audit.js").read_text(encoding="utf-8")
    shots, api_err = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": a.width, "height": a.height}, locale="id-ID",
                                  color_scheme="dark" if a.dark else "light")
        init = (f"localStorage.setItem('erp_token', {json.dumps(tok['token'])});"
                f"localStorage.setItem('erp_user', {json.dumps(json.dumps(tok['user']))});"
                f"localStorage.setItem('erp_portal', {json.dumps(a.portal)});"
                f"localStorage.setItem('rahaza-theme', {json.dumps('dark' if a.dark else 'light')});")
        ctx.add_init_script(init)
        if a.via and a.via != a.base:
            # Halaman tetap "berada" di --base (asal yang sama dengan bundel); setiap permintaan diambil Playwright
            # dari --via lalu diserahkan ke halaman. (Mengganti URL lewat continue_ ditolak Chromium:
            # ERR_BLOCKED_BY_CLIENT.)
            def _proxy(route):
                u = route.request.url
                if not u.startswith(a.base):
                    return route.continue_()
                try:
                    route.fulfill(response=route.fetch(url=a.via + u[len(a.base):], max_redirects=0))
                except Exception:  # noqa: BLE001 — permintaan dibatalkan saat pindah layar
                    route.abort()
            ctx.route("**/*", _proxy)
        page = ctx.new_page()
        current = {"key": ""}
        page.on("response", lambda r: api_err.append({"screen": current["key"], "status": r.status,
                                                      "url": r.url.split("?")[0].replace(a.via or a.base, "")})
                if "/api/" in r.url and r.status >= 400 else None)
        page.on("pageerror", lambda e: api_err.append({"screen": current["key"], "status": "JS", "url": str(e)[:160]}))
        first = ids[0] if ids else ""
        failed = []
        page.on("requestfailed", lambda r: failed.append(f"{r.url[:90]} ({r.failure})"))
        page.goto(f"{a.base}/?portal={a.portal}&module={first}#{first}", wait_until="domcontentloaded")
        page.wait_for_timeout(a.wait)
        if not page.evaluate("() => !!document.querySelector('main')"):
            body = page.evaluate("() => (document.body.innerText || '').trim().slice(0, 200)")
            print("GAGAL: halaman aplikasi tidak tampil (tidak ada <main>). Periksa --base/--via, jaringan, dan token.\n"
                  f"  isi halaman: {body!r}\n  permintaan gagal: {failed[:5]}", file=sys.stderr)
            browser.close()
            return 2
        page.add_script_tag(content=audit_js)

        def capture(menu: str, tab: str, n: int):
            key = f"{menu}|{tab}"
            current["key"] = key
            if not page.evaluate("() => typeof window.uiAudit === 'function'"):
                page.add_script_tag(content=audit_js)   # halaman dimuat ulang → pasang lagi
            res = page.evaluate("() => window.uiAudit()")
            img = f"img/{n:03d}.jpg"
            h = page.evaluate(HEIGHT_JS)
            page.set_viewport_size({"width": a.width, "height": max(a.height, min(int(h) + 24, 6000))})
            page.wait_for_timeout(300)
            loc = page.locator("main").first
            (loc if loc.count() else page).screenshot(path=str(out / img), type="jpeg", quality=72)
            page.set_viewport_size({"width": a.width, "height": a.height})
            shots.append({"key": key, "menu": menu, "menu_label": names.get(menu, menu), "tab": tab, "img": img,
                          "counts": res.get("counts", {}), "samples": res.get("samples", {}),
                          "metrics": res.get("metrics", {})})
            print(f"  {len(shots):3d}  {names.get(menu, menu)}{' › ' + tab if tab else ''}  "
                  f"({sum(res.get('counts', {}).values())} temuan)", flush=True)

        n = 0
        for mid in ids:
            current["key"] = f"{mid}|"
            page.evaluate(f"() => {{ location.hash = '#{mid}'; }}")
            page.wait_for_timeout(a.wait)
            tabs = page.evaluate(TABS_JS)
            if not tabs:
                n += 1
                capture(mid, "", n)
                continue
            for i, label in enumerate(tabs):
                page.evaluate(CLICK_TAB_JS, i)
                page.wait_for_timeout(max(1200, a.wait // 2))
                n += 1
                capture(mid, label, n)
        browser.close()

    total: dict[str, int] = {}
    for s in shots:
        for k, v in s["counts"].items():
            total[k] = total.get(k, 0) + v
    kinds = {k: sorted({x for s in shots for x in s["metrics"].get(m, [])}) for k, m in
             (("KOSONG-GAYA-BEDA", "kosong"), ("TABEL-GAYA-BEDA-PORTAL", "tabel"))}
    for k, v in kinds.items():
        if len(v) > 1:
            total[k] = len(v)
    result = {"portal": a.portal, "dibuat": datetime.now().strftime("%d %b %Y %H:%M"), "lebar": a.width,
              "tema": "gelap" if a.dark else "terang", "total": total, "gaya": kinds, "layar": shots, "api_error": api_err}
    (out / "hasil.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    before = None
    if a.compare:
        bp = Path(a.compare) / "hasil.json"
        if bp.exists():
            before = json.loads(bp.read_text(encoding="utf-8"))
            before["_dir"] = Path(a.compare)
    (out / "index.html").write_text(render(result, before, out), encoding="utf-8")
    print(f"galeri: {out / 'index.html'} · {len(shots)} layar · {sum(total.values())} temuan · {len(api_err)} galat API/JS")
    return 0


CSS = """
:root{--bg:#f6f6fa;--fg:#1d1b2c;--mut:#6b6880;--card:#fff;--line:#e3e1ec;--pri:#6d4ae0;--bad:#c2410c;--ok:#15803d}
@media (prefers-color-scheme:dark){:root{--bg:#14131c;--fg:#ecebf3;--mut:#a4a1b8;--card:#1d1c28;--line:#33314a;--pri:#a78bfa;--bad:#fb923c;--ok:#4ade80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,Inter,sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);background:var(--card);position:sticky;top:0;z-index:2}
h1{font-size:20px;margin:0 0 4px}.mut{color:var(--mut)}main{padding:20px 24px}
.tot{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.chip{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:12px;background:var(--bg);cursor:pointer}
.chip b{color:var(--bad)}.chip.on{border-color:var(--pri);color:var(--pri)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.card h2{font-size:14px;margin:0;padding:10px 12px;border-bottom:1px solid var(--line)}
.shot{display:block;max-height:520px;overflow:hidden;border-bottom:1px solid var(--line);background:var(--bg)}
.shot img{width:100%;display:block}.pair{display:grid;grid-template-columns:1fr 1fr}.pair .lbl{font-size:11px;padding:4px 8px;color:var(--mut)}
.body{padding:8px 12px;font-size:12px}.body .r{display:inline-block;margin:2px 4px 2px 0;padding:1px 7px;border-radius:6px;background:var(--bg);border:1px solid var(--line)}
.r b{color:var(--bad)}details{margin-top:6px}summary{cursor:pointer;color:var(--pri)}li{margin:2px 0;word-break:break-word}
.ok{color:var(--ok)}.bad{color:var(--bad)}table{border-collapse:collapse;font-size:12px;margin-top:8px}td,th{border:1px solid var(--line);padding:4px 8px;text-align:left}
"""
JS = """
const chips=[...document.querySelectorAll('.chip[data-rule]')];let on=null;
chips.forEach(c=>c.onclick=()=>{on=on===c.dataset.rule?null:c.dataset.rule;chips.forEach(x=>x.classList.toggle('on',x.dataset.rule===on));
document.querySelectorAll('.card').forEach(k=>{k.style.display=!on||(k.dataset.rules||'').split(' ').includes(on)?'':'none';});});
"""


def _rules_html(counts: dict, prev: dict | None = None) -> str:
    keys = sorted(set(counts) | set(prev or {}), key=lambda k: -(counts.get(k, 0)))
    parts = []
    for k in keys:
        n, b = counts.get(k, 0), (prev or {}).get(k)
        delta = "" if b is None or b == n else f" <span class='{'ok' if n < b else 'bad'}'>({b}→{n})</span>"
        parts.append(f"<span class='r'>{html.escape(k)} <b>{n}</b>{delta}</span>")
    return "".join(parts) or "<span class='ok'>tidak ada temuan</span>"


def render(res: dict, before: dict | None, out: Path) -> str:
    bmap = {s["key"]: s for s in (before or {}).get("layar", [])}
    rel_before = None
    if before:
        try:
            rel_before = Path("..") / before["_dir"].name
        except Exception:  # noqa: BLE001
            rel_before = None
    tot = sorted(res["total"].items(), key=lambda kv: -kv[1])
    prev_tot = (before or {}).get("total", {})
    head = (f"<h1>Galeri layar — portal {html.escape(res['portal'])}</h1>"
            f"<div class='mut'>{len(res['layar'])} layar · {sum(res['total'].values())} temuan · lebar {res['lebar']} px · "
            f"tema {res['tema']} · {res['dibuat']}"
            + (f" · dibanding galeri {html.escape(before.get('dibuat', ''))}" if before else "") + "</div>"
            "<div class='tot'>" + "".join(
                f"<span class='chip' data-rule='{html.escape(k)}'>{html.escape(k)} <b>{v}</b>"
                + (f" <span class='{'ok' if v < prev_tot.get(k, 0) else 'bad'}'>({prev_tot.get(k, 0)}→{v})</span>"
                   if before and prev_tot.get(k) != v else "") + "</span>" for k, v in tot) + "</div>")
    gaya = "".join(f"<li><b>{html.escape(k)}</b>: {html.escape(' · '.join(v))}</li>" for k, v in res.get("gaya", {}).items() if len(v) > 1)
    errs = res.get("api_error", [])
    err_html = ""
    if errs:
        rows = "".join(f"<tr><td>{html.escape(e['screen'])}</td><td>{e['status']}</td><td>{html.escape(e['url'])}</td></tr>" for e in errs[:200])
        err_html = f"<details open><summary class='bad'>{len(errs)} galat API/JS saat membuka layar</summary><table><tr><th>Layar</th><th>Kode</th><th>Alamat</th></tr>{rows}</table></details>"
    cards = []
    for s in res["layar"]:
        title = html.escape(s["menu_label"] + (f" › {s['tab']}" if s["tab"] else ""))
        samples = "".join(f"<li><b>{html.escape(k)}</b>: {html.escape(' | '.join(v[:4]))}</li>" for k, v in s["samples"].items())
        b = bmap.get(s["key"])
        if b and rel_before is not None:
            shot = (f"<div class='pair'><div><div class='lbl'>Sebelum</div><a class='shot' href='{rel_before / b['img']}' target='_blank'>"
                    f"<img loading='lazy' src='{rel_before / b['img']}'></a></div><div><div class='lbl'>Sesudah</div>"
                    f"<a class='shot' href='{s['img']}' target='_blank'><img loading='lazy' src='{s['img']}'></a></div></div>")
        else:
            shot = f"<a class='shot' href='{s['img']}' target='_blank'><img loading='lazy' src='{s['img']}' alt='{title}'></a>"
        m = s.get("metrics", {})
        meta = (f"<div class='mut'>judul: {html.escape(str(m.get('judul', '—')))} · cetakan: "
                f"{'<span class=ok>ya</span>' if m.get('cetakan') else '<span class=bad>tidak</span>'} · tinggi tombol: "
                f"{html.escape(', '.join(map(str, m.get('tinggiTombol', []))) or '—')}</div>")
        cards.append(f"<section class='card' data-rules='{' '.join(s['counts'])}'><h2>{title}</h2>{shot}<div class='body'>"
                     f"{_rules_html(s['counts'], b['counts'] if b else None)}{meta}"
                     + (f"<details><summary>contoh elemen</summary><ul>{samples}</ul></details>" if samples else "")
                     + "</div></section>")
    return (f"<!doctype html><html lang='id'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Galeri layar {html.escape(res['portal'])}</title><style>{CSS}</style></head><body><header>{head}</header><main>"
            + (f"<p><b>Beda gaya antarlayar:</b></p><ul>{gaya}</ul>" if gaya else "") + err_html
            + f"<div class='grid'>{''.join(cards)}</div></main><script>{JS}</script></body></html>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--portal", required=True)
    ap.add_argument("--token-file", required=True, help="JSON {token, user} dari buat_token_lokal.py")
    ap.add_argument("--base", default="http://localhost:8080", help="alamat aplikasi seperti di peramban")
    ap.add_argument("--via", default="", help="alamat yang benar-benar dihubungi (mis. http://host.docker.internal:8080)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compare", default="", help="folder galeri lama untuk pembanding sebelum/sesudah")
    ap.add_argument("--only", default="", help="id menu dipisah koma (sebagian saja)")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--wait", type=int, default=2500, help="ms menunggu tiap menu dimuat")
    a = ap.parse_args()
    t0 = time.time()
    rc = run(a)
    print(f"selesai dalam {int(time.time() - t0)} detik")
    return rc


if __name__ == "__main__":
    sys.exit(main())
