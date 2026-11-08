/**
 * BudgetAllocationTab — KEPUTUSAN #5 + F5.2
 * Anggaran marketing per TOKO × PERIODE × KATEGORI + realisasi (belanja) + perbandingan + ROI.
 *
 * F5.2 (2026-08-13): realisasi kategori `diskon`, `ads`, `komisi`, `kol`, `livehost` DIHITUNG SISTEM dari data
 * sumbernya; setiap angka otomatis membawa **bukti** (jumlah dokumen sumber).
 *
 * Standar UI/UX v2 (8 Nov 2026): kartu angka StatTile, tabel standar + unduh Excel/CSV, pilihan SmartNativeSelect,
 * isian (rencana anggaran, belanja manual, biaya KOL) dibuka lewat FormPopup — dulu isian langsung di halaman —
 * dengan simpan yang sama; hapus belanja lewat konfirmasi; warna lewat token.
 */
import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, RefreshCw, Lock, Pencil } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { GlassCard } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { todayWIB, addDaysISO } from '@/lib/waktu';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
const BLN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
const tglPendek = (ymd) => { const [y, m, d] = String(ymd || '').split('-').map(Number); return y && m && d ? `${d} ${BLN[m - 1]} ${y}` : String(ymd || ''); };

const CATS = [
  { key: 'ads',      label: 'Iklan',          hint: 'Otomatis: data iklan' },
  { key: 'kol',      label: 'KOL / kreator',  hint: 'Otomatis: fee tetap' },
  { key: 'komisi',   label: 'Komisi kreator', hint: 'Otomatis: % dari omzet' },
  // sesi #34 — host live digaji BULANAN lewat payroll HR (upah per-sesi dihapus)
  { key: 'livehost', label: 'Host live',      hint: 'Otomatis: gaji bulanan SDM' },
  { key: 'sample',   label: 'Sampel',         hint: 'Isi manual' },
  { key: 'diskon',   label: 'Diskon / promo', hint: 'Otomatis: dari pesanan' },
];
const FEE_TYPES = [
  { v: 'none', l: 'Tidak ada' },
  { v: 'fixed', l: 'Fee tetap' },
  { v: 'commission', l: 'Komisi (% penjualan)' },
  { v: 'both', l: 'Fee tetap + komisi' },
];

function Bar({ pct, over }) {
  return (
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--glass-bg)]">
      <div className={`h-full transition-all ${over ? 'bg-[hsl(var(--destructive))]' : 'bg-primary'}`}
        style={{ width: `${Math.min(pct || 0, 100)}%` }} />
    </div>
  );
}

export default function BudgetAllocationTab({ token, accounts, period: periodProp, monthLabel }) {
  const authH = { Authorization: `Bearer ${token}` };
  /* SESI #34 — PERIODE ANGGARAN 7 HARI (default) tanpa membuang mode bulanan.
     Keputusan pemilik: "periode budget menjadi 7 hari yang sebelumnya satu bulan…
     yang saat ini satu bulan jangan dihapus namun bisa dikonfigurasi balik".
     Setelan dibaca dari `/api/marketing/budget/period-settings`; kalau mode
     `weekly`, layar memakai periode 7-hari (kunci = tanggal MULAI) alih-alih
     periode bulanan yang dikirim halaman induk. */
  const [pSettings, setPSettings] = useState(null);
  const [weekStart, setWeekStart] = useState('');
  const weekly = (pSettings?.period_mode || 'weekly') === 'weekly';
  const period = weekly ? (weekStart || pSettings?.current_period || '') : periodProp;

  useEffect(() => {
    fetch(`${API}/api/marketing/budget/period-settings`, { headers: authH })
      .then((r) => r.json())
      .then((d) => {
        if (!d?.settings) return;
        setPSettings(d.settings);
        setWeekStart((w) => w || d.settings.current_period);
      })
      .catch(() => {});
  }, [token]); // eslint-disable-line

  // Pilihan 8 periode 7-hari terakhir, dihitung dari tanggal mulai periode kini.
  const weekOptions = (() => {
    const days = pSettings?.period_days || 7;
    const base = pSettings?.current_period || todayWIB();
    const out = [];
    for (let i = 0; i < 8; i += 1) {
      const start = addDaysISO(base, -i * days);
      out.push({ start, label: `${tglPendek(start)} – ${tglPendek(addDaysISO(start, days - 1))}` });
    }
    return out;
  })();

  const jsonH = { ...authH, 'Content-Type': 'application/json' };

  const [accountId, setAccountId] = useState('');
  const [budgetForm, setBudgetForm] = useState({ ads: '', kol: '', komisi: '', livehost: '', sample: '', diskon: '' });
  // F6.5 — alasan perubahan angka ikut tercatat di jejak (opsional).
  const [budgetReason, setBudgetReason] = useState('');
  const [summary, setSummary] = useState(null);
  const [spendEntries, setSpendEntries] = useState([]);
  const [kolList, setKolList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [savingBudget, setSavingBudget] = useState(false);
  const [newSpend, setNewSpend] = useState({ category: 'ads', amount: '', description: '' });
  const [addingSpend, setAddingSpend] = useState(false);
  // Standar UI/UX v2: isian dibuka lewat popup form (dulu isian langsung di halaman).
  const [bukaRencana, setBukaRencana] = useState(false);
  const [bukaBelanja, setBukaBelanja] = useState(false);
  const [kolEdit, setKolEdit] = useState(null);

  // default account
  useEffect(() => {
    if (!accountId && accounts?.length) setAccountId(accounts[0].id);
  }, [accounts, accountId]);

  const load = useCallback(async () => {
    if (!accountId || !period) return;
    setLoading(true);
    try {
      const [bRes, sRes, spRes, kRes] = await Promise.all([
        fetch(`${API}/api/marketing/budget?account_id=${accountId}&period=${period}`, { headers: authH }),
        fetch(`${API}/api/marketing/budget/summary?account_id=${accountId}&period=${period}`, { headers: authH }),
        fetch(`${API}/api/marketing/budget/spend?account_id=${accountId}&period=${period}`, { headers: authH }),
        fetch(`${API}/api/marketing/budget/kol-cost?account_id=${accountId}`, { headers: authH }),
      ]);
      if (bRes.ok) {
        const b = await bRes.json();
        const bbc = b.budget_by_category || {};
        const next = {};
        CATS.forEach(c => { next[c.key] = bbc[c.key] || ''; });
        setBudgetForm(next);
      }
      if (sRes.ok) setSummary(await sRes.json());
      if (spRes.ok) setSpendEntries((await spRes.json()).entries || []);
      if (kRes.ok) setKolList((await kRes.json()).creators || []);
    } catch { toast.error('Gagal memuat data budget'); }
    finally { setLoading(false); }
  }, [accountId, period, token]); // eslint-disable-line

  useEffect(() => { load(); }, [load]);

  const saveBudget = async () => {
    setSavingBudget(true);
    try {
      const budget_by_category = {};
      CATS.forEach(c => { budget_by_category[c.key] = parseFloat(budgetForm[c.key]) || 0; });
      const res = await fetch(`${API}/api/marketing/budget`, {
        method: 'PUT', headers: jsonH,
        body: JSON.stringify({ account_id: accountId, period, budget_by_category,
          reason: budgetReason || '' }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Gagal simpan budget');
      toast.success('Rencana anggaran disimpan');
      setBudgetReason('');
      load();
      return true;
    } catch (e) { toast.error(e.message); return false; }
    finally { setSavingBudget(false); }
  };

  const addSpend = async () => {
    if (!(parseFloat(newSpend.amount) > 0)) { toast.error('Jumlah belanja harus lebih dari 0'); return false; }
    setAddingSpend(true);
    try {
      const res = await fetch(`${API}/api/marketing/budget/spend`, {
        method: 'POST', headers: jsonH,
        body: JSON.stringify({
          account_id: accountId, period, category: newSpend.category,
          amount: parseFloat(newSpend.amount) || 0, description: newSpend.description || '',
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Gagal catat spend');
      toast.success('Belanja dicatat');
      setNewSpend({ category: 'ads', amount: '', description: '' });
      load();
      return true;
    } catch (e) { toast.error(e.message); return false; }
    finally { setAddingSpend(false); }
  };

  const delSpend = async (id) => {
    try {
      const res = await fetch(`${API}/api/marketing/budget/spend/${id}`, { method: 'DELETE', headers: authH });
      if (!res.ok) throw new Error('Gagal hapus');
      toast.success('Catatan belanja dihapus');
      load();
    } catch (e) { toast.error(e.message); }
  };

  const saveKolCost = async (creator) => {
    try {
      const cfg = creator.cost_config || {};
      const res = await fetch(`${API}/api/marketing/budget/kol-cost/${creator.creator_id}`, {
        method: 'PUT', headers: jsonH,
        body: JSON.stringify({
          fee_type: cfg.fee_type || 'none',
          fixed_fee: parseFloat(cfg.fixed_fee) || 0,
          commission_pct: parseFloat(cfg.commission_pct) || 0,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Gagal simpan');
      toast.success(`Konfigurasi biaya "${creator.name}" disimpan`);
      load();
    } catch (e) { toast.error(e.message); }
  };

  const catMap = {};
  (summary?.categories || []).forEach(c => { catMap[c.category] = c; });
  const srcMap = {};
  (summary?.spend_sources || []).forEach(s => { srcMap[s.category] = s; });
  const labelCat = (k) => CATS.find((c) => c.key === k)?.label || k;
  const kunciTerkunci = !!summary?.locked;

  const simpanRencana = async () => { await saveBudget(); setBukaRencana(false); };
  const simpanBelanja = async () => { const ok = await addSpend(); if (ok) setBukaBelanja(false); };
  const simpanKol = async () => {
    if (!kolEdit) return;
    await saveKolCost(kolEdit);
    setKolEdit(null);
  };
  const hapusBelanja = async (e) => {
    const ok = await confirmDialog({
      title: 'Hapus catatan belanja ini?', body: `${labelCat(e.category)} ${fmtRp(e.amount)}${e.description ? ` — ${e.description}` : ''}`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (ok) delSpend(e.id);
  };

  return (
    <div className="space-y-4" data-testid="budget-allocation-tab">
      {/* Periode terkunci: tombol Simpan akan ditolak 423 — katakan SEBELUM diklik */}
      {kunciTerkunci && (
        <Notice tone="warning" icon={Lock} testId="budget-locked-banner">
          Periode <b>{period}</b> untuk toko ini sudah <b>ditutup</b>
          {summary.lock?.closed_by_name ? ` oleh ${summary.lock.closed_by_name}` : ''}
          {summary.lock?.reason ? ` — alasan: ${summary.lock.reason}` : ''}.
          Rencana anggaran & catatan belanja tidak bisa diubah sampai periode dibuka kembali (Siklus bulan ini → Lainnya → Buka periode).
        </Notice>
      )}

      {/* Pilihan periode & toko — satu baris */}
      <div className="flex flex-wrap items-center gap-2">
        {/* SESI #34 — pemilih PERIODE 7 HARI (default). Mode bulanan tetap ada (Setelan); kalau bulanan, pemilih
            ini tidak muncul dan periode diambil dari halaman induk. */}
        {weekly && (
          <SmartNativeSelect value={weekStart} onChange={(e) => setWeekStart(e.target.value)} searchable={false}
            className="h-9 w-64" aria-label={`Periode ${pSettings?.period_days || 7} hari`} data-testid="budget-week-select">
            {weekOptions.map((w) => <option key={w.start} value={w.start}>{w.label}</option>)}
          </SmartNativeSelect>
        )}
        <SmartNativeSelect value={accountId} onChange={(e) => setAccountId(e.target.value)} className="h-9 w-56"
          aria-label="Akun toko" data-testid="budget-account-select">
          {(accounts || []).map((a) => <option key={a.id} value={a.id}>{a.account_name} · {a.platform}</option>)}
        </SmartNativeSelect>
        {!weekly && <span className="text-sm text-muted-foreground">{monthLabel}</span>}
        <Button variant="outline" size="icon" className="ml-auto" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </div>

      {summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="budget-summary-cards" data-konten-utama="">
          <StatTile label="Total anggaran" value={fmtRp(summary.total_budget)} />
          <StatTile label="Total terpakai" value={fmtRp(summary.total_spend)} />
          <StatTile label="Sisa anggaran" value={fmtRp(summary.total_remaining)} accent={summary.total_remaining < 0 ? 'danger' : 'default'}
            sub={summary.total_remaining < 0 ? 'Melebihi rencana' : undefined} />
          <StatTile label="ROI" value={`${summary.roi_pct}%`} sub={`Penjualan ${fmtRp(summary.sales)}`} />
        </div>
      )}

      {/* Rencana vs realisasi per kategori */}
      <GlassCard className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-base font-semibold text-foreground">Rencana vs realisasi per kategori</p>
            <p className="text-sm text-muted-foreground">Kategori otomatis dihitung sistem dari data sumbernya; buktinya di kolom terakhir.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <TombolUnduh namaBerkas={`anggaran-${period}`} namaLembar="Anggaran per kategori" baris={CATS} testId="budget-category-unduh"
              kolom={[
                { label: 'Kategori', nilai: (c) => c.label },
                { label: 'Sumber', nilai: (c) => (catMap[c.key]?.mode === 'auto' ? 'Otomatis' : catMap[c.key]?.mode ? 'Manual' : '') },
                { label: 'Rencana (Rp)', nilai: (c) => parseFloat(budgetForm[c.key]) || 0 },
                { label: 'Realisasi (Rp)', nilai: (c) => catMap[c.key]?.spend ?? 0 },
                { label: 'Manual (Rp)', nilai: (c) => catMap[c.key]?.manual ?? 0 },
                { label: 'Otomatis (Rp)', nilai: (c) => catMap[c.key]?.auto ?? 0 },
                { label: 'Sisa (Rp)', nilai: (c) => catMap[c.key]?.remaining ?? 0 },
                { label: 'Pemakaian (%)', nilai: (c) => catMap[c.key]?.used_pct ?? 0 },
                { label: 'Bukti', nilai: (c) => srcMap[c.key]?.evidence || '' },
              ]} />
            <Button onClick={() => setBukaRencana(true)} disabled={!accountId} data-testid="budget-edit-btn"><Pencil />Ubah rencana</Button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <Table data-testid="budget-category-table">
            <TableHeader>
              <TableRow>
                <TableHead>Kategori</TableHead>
                <TableHead className="text-right">Rencana</TableHead>
                <TableHead className="text-right">Realisasi</TableHead>
                <TableHead className="hidden text-right md:table-cell">Manual</TableHead>
                <TableHead className="hidden text-right md:table-cell">Otomatis</TableHead>
                <TableHead className="text-right">Sisa</TableHead>
                <TableHead className="w-[150px]">Pemakaian</TableHead>
                <TableHead className="hidden lg:table-cell">Bukti angka otomatis</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {CATS.map((c) => {
                const row = catMap[c.key] || {};
                const src = srcMap[c.key] || {};
                const over = row.status === 'over';
                return (
                  <TableRow key={c.key} data-testid={`budget-cat-${c.key}`}>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{c.label}</span>
                        {row.mode && <span data-testid={`budget-mode-${c.key}`}><StatusBadge status={row.mode} label={row.mode === 'auto' ? 'Otomatis' : 'Manual'} tone="muted" /></span>}
                      </div>
                      <span className="text-xs text-muted-foreground">{c.hint}</span>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">{fmtRp(parseFloat(budgetForm[c.key]) || 0)}</TableCell>
                    <TableCell className="whitespace-nowrap text-right font-medium tabular-nums" data-testid={`spend-${c.key}`}>{fmtRp(row.spend)}</TableCell>
                    <TableCell className="hidden whitespace-nowrap text-right tabular-nums text-muted-foreground md:table-cell">{fmtRp(row.manual)}</TableCell>
                    <TableCell className="hidden whitespace-nowrap text-right tabular-nums text-muted-foreground md:table-cell" data-testid={`spend-auto-${c.key}`}>{fmtRp(row.auto)}</TableCell>
                    <TableCell className={`whitespace-nowrap text-right tabular-nums ${row.remaining < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>{fmtRp(row.remaining)}</TableCell>
                    <TableCell>
                      <div className="flex items-center justify-between text-xs">
                        <span className={over ? 'font-medium text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}>{row.used_pct || 0}%</span>
                        {over && <StatusBadge status="over" label="Lewat" tone="danger" />}
                      </div>
                      <Bar pct={row.used_pct} over={over} />
                    </TableCell>
                    <TableCell className="hidden max-w-[240px] whitespace-normal text-xs text-muted-foreground lg:table-cell" data-testid={`budget-evidence-${c.key}`}>
                      {src.evidence || (row.mode === 'manual' ? 'hanya dari entri manual' : '—')}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </GlassCard>

      {/* Realisasi manual */}
      <GlassCard className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-base font-semibold text-foreground">Realisasi manual</p>
            <p className="text-sm text-muted-foreground" data-testid="spend-manual-note">
              Hanya untuk biaya yang tidak terbaca sistem (mis. sampel). Kategori otomatis (diskon, iklan, komisi, KOL, host live) sudah dihitung
              dari data sumbernya — mencatatnya lagi di sini membuat biaya yang sama dihitung dua kali.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <TombolUnduh namaBerkas={`belanja-manual-${period}`} namaLembar="Belanja manual" baris={spendEntries} testId="spend-unduh"
              kolom={[
                { label: 'Kategori', nilai: (e) => labelCat(e.category) },
                { label: 'Jumlah (Rp)', nilai: (e) => e.amount ?? 0 },
                { label: 'Keterangan', nilai: (e) => e.description || '' },
              ]} />
            <Button variant="outline" onClick={() => setBukaBelanja(true)} disabled={!accountId} data-testid="spend-open-btn"><Plus />Catat belanja</Button>
          </div>
        </div>
        <Table data-testid="spend-list">
          <TableHeader>
            <TableRow><TableHead>Kategori</TableHead><TableHead className="text-right">Jumlah</TableHead><TableHead>Keterangan</TableHead><TableHead><span className="sr-only">Aksi</span></TableHead></TableRow>
          </TableHeader>
          <TableBody>
            {spendEntries.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={4} className="p-0 [&>div]:py-8"><EmptyState title="Belum ada catatan realisasi manual" /></TableCell>
              </TableRow>
            )}
            {spendEntries.map((e) => (
              <TableRow key={e.id}>
                <TableCell>{labelCat(e.category)}</TableCell>
                <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">{fmtRp(e.amount)}</TableCell>
                <TableCell className="text-muted-foreground">{e.description || '—'}</TableCell>
                <TableCell className="text-right">
                  <Button size="icon-sm" variant="ghost" onClick={() => hapusBelanja(e)} title="Hapus catatan" aria-label="Hapus catatan" data-testid={`spend-del-${e.id}`}>
                    <Trash2 />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </GlassCard>

      {/* Konfigurasi biaya KOL */}
      <GlassCard className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-base font-semibold text-foreground">Biaya KOL / kreator</p>
            <p className="text-sm text-muted-foreground">Skema bayar tiap kreator yang ditugaskan ke toko ini (fee tetap dan/atau komisi).</p>
          </div>
          <TombolUnduh namaBerkas="biaya-kol" namaLembar="Biaya KOL" baris={kolList} testId="kol-cost-unduh"
            kolom={[
              { label: 'Kreator', nilai: (k) => k.name },
              { label: 'Kode', nilai: (k) => k.creator_code || '' },
              { label: 'Skema bayar', nilai: (k) => FEE_TYPES.find((f) => f.v === (k.cost_config?.fee_type || 'none'))?.l || '' },
              { label: 'Fee tetap (Rp)', nilai: (k) => parseFloat(k.cost_config?.fixed_fee) || 0 },
              { label: 'Komisi (%)', nilai: (k) => parseFloat(k.cost_config?.commission_pct) || 0 },
            ]} />
        </div>
        <div className="overflow-x-auto">
          <Table data-testid="kol-cost-table">
            <TableHeader>
              <TableRow>
                <TableHead>Kreator</TableHead>
                <TableHead>Skema bayar</TableHead>
                <TableHead className="text-right">Fee tetap</TableHead>
                <TableHead className="text-right">Komisi</TableHead>
                <TableHead><span className="sr-only">Aksi</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {kolList.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={5} className="p-0 [&>div]:py-8"><EmptyState title="Belum ada kreator yang ditugaskan ke akun ini" /></TableCell>
                </TableRow>
              )}
              {kolList.map((k, idx) => {
                const cfg = k.cost_config || {};
                const ft = cfg.fee_type || 'none';
                return (
                  <TableRow key={k.creator_id} data-testid={`kol-cost-row-${idx}`}>
                    <TableCell><div className="font-medium">{k.name}</div><div className="text-xs text-muted-foreground">{k.creator_code}</div></TableCell>
                    <TableCell>{FEE_TYPES.find((f) => f.v === ft)?.l || ft}</TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">{ft === 'fixed' || ft === 'both' ? fmtRp(parseFloat(cfg.fixed_fee) || 0) : '—'}</TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">{ft === 'commission' || ft === 'both' ? `${parseFloat(cfg.commission_pct) || 0}%` : '—'}</TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" onClick={() => setKolEdit({ ...k, idx, cost_config: { ...cfg } })} data-testid={`kol-save-${idx}`}>
                        <Pencil />Ubah
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {summary?.kol_detail?.length > 0 && (
          <p className="text-sm text-muted-foreground">
            Biaya KOL terhitung periode ini: {summary.kol_detail.map((d) => `${d.creator_name} ${fmtRp(d.cost)}`).join(' · ')}
          </p>
        )}
      </GlassCard>

      {/* ── Popup: ubah rencana anggaran ── */}
      <FormPopup open={bukaRencana} onClose={() => setBukaRencana(false)} judul="Ubah rencana anggaran"
        keterangan={`Periode ${period}${kunciTerkunci ? ' — periode ini ditutup, penyimpanan akan ditolak' : ''}.`}
        onSimpan={simpanRencana} menyimpan={savingBudget} bisaSimpan={!!accountId} labelSimpan="Simpan rencana" testId="budget-form">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {CATS.map((c) => (
            <Isian key={c.key} label={c.label} petunjuk={c.hint}>
              <MoneyInput value={budgetForm[c.key]} data-testid={`budget-input-${c.key}`} placeholder="0"
                onChange={(e) => setBudgetForm((f) => ({ ...f, [c.key]: e.target.value }))} />
            </Isian>
          ))}
        </div>
        <Isian label="Alasan perubahan" petunjuk="Opsional, masuk jejak perubahan.">
          <Input value={budgetReason} onChange={(e) => setBudgetReason(e.target.value)}
            placeholder="Mis. anggaran iklan ditambah untuk kejar target" data-testid="budget-reason-input" />
        </Isian>
      </FormPopup>

      {/* ── Popup: catat belanja manual ── */}
      <FormPopup open={bukaBelanja} onClose={() => setBukaBelanja(false)} judul="Catat belanja manual"
        keterangan="Hanya untuk biaya yang tidak terbaca sistem." onSimpan={simpanBelanja} menyimpan={addingSpend}
        bisaSimpan={!!accountId} labelSimpan="Simpan" testId="spend-form">
        <Isian label="Kategori">
          <SmartNativeSelect value={newSpend.category} onChange={(e) => setNewSpend((s) => ({ ...s, category: e.target.value }))}
            searchable={false} className="h-9 w-full sm:w-56" data-testid="spend-category-select">
            {CATS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Jumlah (Rp)" wajib>
          <MoneyInput value={newSpend.amount} data-testid="spend-amount-input" placeholder="0"
            onChange={(e) => setNewSpend((s) => ({ ...s, amount: e.target.value }))} />
        </Isian>
        <Isian label="Keterangan">
          <Input value={newSpend.description} data-testid="spend-desc-input" placeholder="Mis. sampel untuk kreator baru"
            onChange={(e) => setNewSpend((s) => ({ ...s, description: e.target.value }))} />
        </Isian>
      </FormPopup>

      {/* ── Popup: biaya KOL ── */}
      <FormPopup open={!!kolEdit} onClose={() => setKolEdit(null)} judul={`Biaya ${kolEdit?.name || 'kreator'}`}
        keterangan={kolEdit?.creator_code} onSimpan={simpanKol} labelSimpan="Simpan" testId="kol-form">
        <Isian label="Skema bayar">
          <SmartNativeSelect value={kolEdit?.cost_config?.fee_type || 'none'} searchable={false} className="h-9 w-full sm:w-64"
            data-testid={`kol-feetype-${kolEdit?.idx}`}
            onChange={(e) => setKolEdit((k) => ({ ...k, cost_config: { ...(k.cost_config || {}), fee_type: e.target.value } }))}>
            {FEE_TYPES.map((f) => <option key={f.v} value={f.v}>{f.l}</option>)}
          </SmartNativeSelect>
        </Isian>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Fee tetap (Rp)">
            <MoneyInput value={kolEdit?.cost_config?.fixed_fee ?? ''} placeholder="0" data-testid={`kol-fixedfee-${kolEdit?.idx}`}
              disabled={['none', 'commission'].includes(kolEdit?.cost_config?.fee_type || 'none')}
              onChange={(e) => setKolEdit((k) => ({ ...k, cost_config: { ...(k.cost_config || {}), fixed_fee: e.target.value } }))} />
          </Isian>
          <Isian label="Komisi (%)">
            <Input type="number" min={0} max={100} value={kolEdit?.cost_config?.commission_pct ?? ''} placeholder="0"
              data-testid={`kol-commission-${kolEdit?.idx}`}
              disabled={['none', 'fixed'].includes(kolEdit?.cost_config?.fee_type || 'none')}
              onChange={(e) => setKolEdit((k) => ({ ...k, cost_config: { ...(k.cost_config || {}), commission_pct: e.target.value } }))} />
          </Isian>
        </div>
      </FormPopup>
    </div>
  );
}
