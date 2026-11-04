/*
 * Audit tampilan (DOM) — pasangan scripts/ui_audit/scan_ui.py (2026-11-04).
 *
 * Memeriksa layar yang BENAR-BENAR tampil (hasil CSS akhir), jadi menangkap hal yang tidak terlihat dari
 * kode: tombol tanpa latar, kartu di dalam kartu, baris laporan yang dibuat kartu, angka nol merah,
 * isi tertutup tombol chat, dll. Kode aturan sama dengan docs/design/PANDUAN_UI.md.
 *
 * Cara pakai (lihat docs/design/CARA_AUDIT_UI.md):
 *   1. Buka app (sudah masuk), buka DevTools › Console, tempel isi berkas ini, Enter.
 *   2. Satu layar:        await uiAudit()                         → ringkasan layar yang sedang tampil
 *   3. Semua menu portal: await uiAuditMenus(['fin-cash', ...])   → buka tiap menu + tiap tab hub-nya
 *      Hasil lengkap tersimpan di window.__uiAuditResult (salin dengan copy(window.__uiAuditResult)).
 */
(function () {
  const ENGLISH = ['Export CSV', 'Export Excel', 'Export', 'Refresh', 'Settlement', 'Outstanding', 'Overview', 'Submit',
    'Approve', 'Reject', 'Retry', 'Statement', 'Invoice', 'Print', 'Save', 'Cancel', 'Delete', 'Upload', 'Download',
    'Unposted', 'Pending', 'Gross Profit', 'Operating Income', 'Net Income', 'Dashboard', 'Overdue', 'Aging', 'Actual',
    'Analysis', 'Client', 'Internal WO', 'Total Budget', 'Variance', 'Debtors', 'Customer', 'Supplier', 'request'];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0.05;
  };
  const rgba = (c) => {
    const m = String(c).match(/rgba?\(([^)]+)\)/);
    if (!m) return [0, 0, 0, 0];
    const p = m[1].split(',').map((x) => parseFloat(x));
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const hasBg = (el) => {
    const cs = getComputedStyle(el);
    return rgba(cs.backgroundColor)[3] > 0.05 || (cs.backgroundImage && cs.backgroundImage !== 'none');
  };
  const hasBorder = (el) => {
    const cs = getComputedStyle(el);
    return parseFloat(cs.borderTopWidth) > 0 && rgba(cs.borderTopColor)[3] > 0.05;
  };
  const isCard = (el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (r.height < 44 || r.width < 120) return false;
    if (/^(BUTTON|INPUT|SELECT|TEXTAREA|A|TD|TH|TR|TABLE|THEAD|TBODY|LABEL|SPAN)$/.test(el.tagName)) return false;
    if (el.getAttribute('role') === 'tab' || el.getAttribute('role') === 'tablist') return false;
    return parseFloat(cs.borderTopLeftRadius) >= 10 && hasBorder(el) && hasBg(el);
  };
  const short = (el) => {
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').trim().replace(/\s+/g, ' ');
    return `${el.tagName.toLowerCase()}${el.dataset.testid ? `[${el.dataset.testid}]` : ''} "${t.slice(0, 50)}"`;
  };
  const isRed = (c) => { const [r, g, b] = rgba(c); return r > 170 && g < 110 && b < 120; };

  function auditScreen() {
    const main = document.querySelector('main') || document.body;
    const mr = main.getBoundingClientRect();
    const all = [...main.querySelectorAll('*')].filter(visible);
    const out = {};
    const add = (code, el, extra) => {
      (out[code] = out[code] || []).push(extra || (el ? short(el) : ''));
    };

    // Layar gagal dimuat (ErrorBoundary) — semua temuan lain tidak berarti; catat dan berhenti
    if (/mengalami error|Minified React error|Coba Lagi/.test((main.innerText || '').slice(0, 600))) {
      return { url: location.hash, counts: { 'LAYAR-ERROR': 1 }, samples: { 'LAYAR-ERROR': [(main.innerText || '').slice(0, 160)] }, metrics: { judul: '—', tinggiTombol: [], jumlahKartu: 0, tabel: [] } };
    }

    // ── G3 Tombol ───────────────────────────────────────────────────────────
    const btns = all.filter((el) => (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') &&
      el.getAttribute('role') !== 'tab' && !el.closest('[role="tablist"]'));
    const heights = new Map();
    for (const b of btns) {
      const txt = (b.innerText || '').trim();
      const r = b.getBoundingClientRect();
      // tombol biasa saja (bukan kartu yang bisa diklik, bukan tautan teks)
      if (txt.length >= 2 && !b.closest('table') && r.height >= 24 && r.height <= 56) heights.set(Math.round(r.height), (heights.get(Math.round(r.height)) || 0) + 1);
      if (txt.length < 2 || b.closest('table') || b.disabled || r.height > 56) continue;
      const cs = getComputedStyle(b);
      const padX = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
      if (!hasBg(b) && hasBorder(b)) add('TOMBOL-TANPA-LATAR', b);
      else if (!hasBg(b) && !hasBorder(b) && padX >= 20 && r.height >= 30 && !/underline/.test(cs.textDecorationLine)) add('TOMBOL-HANTU', b);
    }
    const hs = [...heights.keys()].sort((a, b) => a - b);
    if (hs.length > 2) add('TOMBOL-TINGGI-BEDA', null, `tinggi tombol: ${hs.map((h) => `${h}px×${heights.get(h)}`).join(', ')}`);
    if (btns.filter((b) => getComputedStyle(b).backgroundColor === getComputedStyle(document.querySelector('button.bg-primary') || b).backgroundColor && hasBg(b) && (b.innerText || '').trim().length > 2 && !b.closest('table')).length > 2) {
      add('TOMBOL-UTAMA-BANYAK', null, 'lebih dari 2 tombol berwarna utama di satu layar');
    }

    // ── G4 Tab ──────────────────────────────────────────────────────────────
    const lists = all.filter((el) => el.getAttribute('role') === 'tablist');
    // tab bersarang yang tampil sebagai pil penyaring (tanpa latar segmen) = standar G4, bukan pelanggaran
    for (const l of lists) if (l.parentElement && l.parentElement.closest('[role="tabpanel"]') && hasBg(l)) add('TAB-DI-DALAM-TAB', l);
    const groups = new Set();
    const tabButtons = new Set();
    for (const el of all) {
      const kids = [...el.children].filter((c) => c.tagName === 'BUTTON' && visible(c));
      if (kids.length < 2 || kids.length !== el.children.length || el.getAttribute('role') === 'tablist' || el.closest('table')) continue;
      if (kids.every((k) => k.hasAttribute('aria-pressed')) && el.getAttribute('role') === 'group') continue;   // FilterChips standar
      // tab = semua tombol berteks (bukan ikon / nomor halaman), tinggi sama
      const texts = kids.map((k) => (k.innerText || '').trim());
      if (texts.some((t) => t.length < 2 || /^\d+$/.test(t))) continue;
      if (new Set(kids.map((k) => Math.round(k.getBoundingClientRect().height))).size > 1) continue;
      const bgs = kids.map((k) => getComputedStyle(k).backgroundColor + getComputedStyle(k).color);
      const uniq = new Set(bgs);
      if (uniq.size === 2 && bgs.filter((x) => x === bgs.find((y) => bgs.indexOf(y) === bgs.lastIndexOf(y))).length === 1 &&
          kids.every((k) => (k.innerText || '').trim().length < 40)) {
        const cs = getComputedStyle(el);
        groups.add(`radius ${cs.borderTopLeftRadius} · latar ${cs.backgroundColor} · garis ${cs.borderTopWidth}`);
        add('TAB-BUATAN', el, `tab buatan: ${texts.join(' | ').slice(0, 80)}`);
        kids.forEach((k) => tabButtons.add(k));
      }
    }
    for (const l of lists) {
      if (l.parentElement && l.parentElement.closest('[role="tabpanel"]') && !hasBg(l)) continue;   // pil penyaring bersarang
      const cs = getComputedStyle(l);
      groups.add(`[tablist] radius ${cs.borderTopLeftRadius} · latar ${cs.backgroundColor} · rata ${cs.justifyContent}`);
    }
    if (groups.size > 1) add('TAB-GAYA-BEDA', null, `${groups.size} gaya tab: ${[...groups].join(' / ')}`);

    if (out['TOMBOL-HANTU']) {
      const tabTexts = new Set([...tabButtons].map(short));
      out['TOMBOL-HANTU'] = out['TOMBOL-HANTU'].filter((x) => !tabTexts.has(x));
      if (!out['TOMBOL-HANTU'].length) delete out['TOMBOL-HANTU'];
    }

    // ── G5 Kartu ────────────────────────────────────────────────────────────
    const cards = all.filter(isCard);
    for (const c of cards) {
      const parentCard = c.parentElement && c.parentElement.closest('*') && [...cards].find((p) => p !== c && p.contains(c));
      if (parentCard) add('KARTU-DI-DALAM-KARTU', c);
      const r = c.getBoundingClientRect();
      const words = (c.innerText || '').trim().split(/\s+/).length;
      if (r.width > mr.width * 0.6 && r.height < 130 && words <= 8 && /\d/.test(c.innerText || '')) add('KARTU-SATU-ANGKA-LEBAR', c);
    }
    const rowParents = new Set();
    for (const c of cards) {
      const p = c.parentElement;
      if (!p || rowParents.has(p)) continue;
      const sib = [...p.children].filter((x) => cards.includes(x));
      const pr = p.getBoundingClientRect();
      const rows = sib.filter((x) => { const r = x.getBoundingClientRect(); return r.width > pr.width * 0.8 && r.height < 100; });
      if (rows.length >= 3) { rowParents.add(p); add('BARIS-JADI-KARTU', p, `${rows.length} baris kartu: ${rows.slice(0, 3).map((x) => (x.innerText || '').trim().split('\n')[0]).join(' | ')}`); }
      const row = sib.filter((x) => Math.abs(x.getBoundingClientRect().top - c.getBoundingClientRect().top) < 4);
      if (row.length >= 3) {
        const colors = new Set(row.map((x) => getComputedStyle(x).backgroundColor + getComputedStyle(x).borderTopColor));
        if (colors.size >= 3 && !rowParents.has(p)) { rowParents.add(p); add('KARTU-WARNA-WARNI', p, `${row.length} kartu sejajar, ${colors.size} warna latar`); }
      }
    }
    const kpiZero = cards.filter((c) => /\b(Rp\s?)?0\b/.test(c.innerText || '') && (c.innerText || '').trim().split(/\s+/).length <= 6);
    if (kpiZero.length >= 3) add('KARTU-NOL-BERJEJER', null, `${kpiZero.length} kartu bernilai 0 (pakai tampilan kosong)`);

    // ── G7 Angka & tabel ────────────────────────────────────────────────────
    for (const el of all) {
      if (el.children.length) continue;
      const t = (el.textContent || '').trim();
      if (!t) continue;
      const cs = getComputedStyle(el);
      if (/^(Rp\s?)?-?[\d.,]+$/.test(t) && /mono/i.test(cs.fontFamily)) add('ANGKA-MONO', el);
      if (/^(Rp\s?)?0$/.test(t) && isRed(cs.color)) add('NOL-MERAH', el);
      if (/\b\d{4}-\d{2}-\d{2}\b/.test(t) && el.tagName !== 'INPUT' && t.length < 40) add('TANGGAL-MENTAH', el);
      if (/\b\d+\.\d+\s?(%|hari)/.test(t)) add('DESIMAL-TITIK', el);
      if (/\b[a-z]{2,}_[a-z_]{2,}\b/.test(t) && t.length < 60) add('KODE-MENTAH', el);
      for (const w of ENGLISH) if (new RegExp(`(^|[^\\w])${w}([^\\w]|$)`).test(t) && t.length < 60) { add('TEKS-INGGRIS', el); break; }
    }
    for (const o of main.querySelectorAll('select option')) {
      if (/\b[a-z]{2,}_[a-z_]{2,}\b/.test(o.textContent || '')) { add('KODE-MENTAH', o, `pilihan: ${o.textContent.trim()}`); }
    }
    const tableSigs = new Set();
    for (const tb of main.querySelectorAll('table')) {
      if (!visible(tb)) continue;
      const th = tb.querySelector('thead th'); const td = tb.querySelector('tbody td'); const tr = tb.querySelector('tbody tr');
      if (th && td && tr) {
        const a = getComputedStyle(th); const b = getComputedStyle(td);
        tableSigs.add(`judul ${a.fontSize} ${a.textTransform === 'uppercase' ? 'KAPITAL' : 'biasa'} ${a.fontWeight} latar ${rgba(a.backgroundColor)[3] > 0.05 ? 'ada' : 'tidak'} · sel ${b.fontSize} pad ${b.paddingTop}/${b.paddingLeft} · baris ${Math.round(tr.getBoundingClientRect().height)}px`);
      }
      if (!tb.querySelector('thead')) add('TABEL-TANPA-KEPALA', tb, 'tabel tanpa baris judul kolom');
      let misaligned = 0;
      for (const td of tb.querySelectorAll('tbody td')) {
        const t = (td.innerText || '').trim();
        if (/^(Rp\s?)?-?[\d.,]{4,}$/.test(t) && getComputedStyle(td).textAlign !== 'right' && getComputedStyle(td).textAlign !== 'end') misaligned++;
      }
      if (misaligned) add('ANGKA-TIDAK-RATA-KANAN', tb, `${misaligned} sel angka tidak rata kanan`);
    }

    // ── G6 Filter & periode ─────────────────────────────────────────────────
    const dateInputs = all.filter((el) => el.tagName === 'INPUT' && /date|month/.test(el.type));
    for (const d of dateInputs) if (d.type === 'month' && !d.value) add('BULAN-KOSONG', d, 'kotak bulan kosong tampil "--------- ----"');
    const hasPeriodPicker = !!main.querySelector('[data-testid$="-period"], [data-testid$="period-picker"], select[aria-label="Periode"]');
    if ((hasPeriodPicker && dateInputs.length) || dateInputs.filter((d) => d.type === 'month').length && dateInputs.filter((d) => d.type === 'date').length) {
      add('PERIODE-GANDA', null, `${dateInputs.length} kotak tanggal/bulan${hasPeriodPicker ? ' + pemilih periode' : ''}`);
    }
    const fields = all.filter((el) => /^(INPUT|SELECT)$/.test(el.tagName) && !/checkbox|radio|hidden/.test(el.type));
    const stacked = fields.filter((f) => f.getBoundingClientRect().width > mr.width * 0.85);
    if (stacked.length >= 2) add('FILTER-BERTUMPUK', null, `${stacked.length} kotak isian selebar layar (seharusnya satu baris toolbar)`);

    // ── G1 Tata letak & G12 tombol mengambang ──────────────────────────────
    const first = [...main.children].find(visible);
    if (first) {
      const inner = first.querySelector(':scope > *') || first;
      const ratio = inner.getBoundingClientRect().width / mr.width;
      if (ratio < 0.85) add('LEBAR-HALAMAN-BEDA', inner, `isi hanya ${Math.round(ratio * 100)}% lebar area`);
    }
    const floating = [...document.querySelectorAll('body *')].filter((el) => {
      const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
      return cs.position === 'fixed' && r.width >= 40 && r.width <= 90 && r.height >= 40 && r.height <= 90 && r.right > innerWidth - 120 && r.bottom > innerHeight - 140 && visible(el);
    });
    // periksa di posisi gulir paling bawah: yang penting baris/tombol terakhir tidak tertutup
    const prevScroll = main.scrollTop;
    main.scrollTop = main.scrollHeight;
    for (const f of floating) {
      const fr = f.getBoundingClientRect();
      for (const el of main.querySelectorAll('button, a, input, select, td')) {
        if (!visible(el) || f.contains(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.left < fr.right && r.right > fr.left && r.top < fr.bottom && r.bottom > fr.top) { add('TERTUTUP-CHAT', el); }
      }
    }
    main.scrollTop = prevScroll;

    // ── G2 Judul ────────────────────────────────────────────────────────────
    const h = [...main.querySelectorAll('h1, h2')].find(visible);
    const metrics = { judul: h ? `${h.tagName} ${getComputedStyle(h).fontSize} ${(h.innerText || '').trim().slice(0, 40)}` : '—',
      tinggiTombol: hs, jumlahKartu: cards.length, tabel: [...tableSigs] };
    if (tableSigs.size > 1) add('TABEL-GAYA-BEDA', null, `${tableSigs.size} gaya tabel di satu layar`);
    const counts = Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.length]));
    const samples = Object.fromEntries(Object.entries(out).map(([k, v]) => [k, [...new Set(v)].slice(0, 6)]));
    return { url: location.hash, counts, samples, metrics };
  }

  async function clickTab(el) {
    el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0 }));
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
    el.click();
    await sleep(1800);
  }

  window.uiAudit = async () => auditScreen();
  window.uiAuditMenus = async (ids, waitMs = 2500) => {
    const res = [];
    for (const id of ids) {
      location.hash = `#${id}`;
      await sleep(waitMs);
      const main = document.querySelector('main') || document.body;
      const tabs = [...main.querySelectorAll('[role="tablist"]')].filter(visible)[0];
      const triggers = tabs ? [...tabs.querySelectorAll('[role="tab"]')] : [];
      if (!triggers.length) { res.push({ menu: id, tab: '', ...auditScreen() }); continue; }
      for (const t of triggers) {
        await clickTab(t);
        res.push({ menu: id, tab: (t.innerText || '').trim(), ...auditScreen() });
      }
    }
    const total = {};
    for (const r of res) for (const [k, n] of Object.entries(r.counts)) total[k] = (total[k] || 0) + n;
    window.__uiAuditResult = { layar: res.length, total, per_layar: res };
    return { layar: res.length, total };
  };
})();
