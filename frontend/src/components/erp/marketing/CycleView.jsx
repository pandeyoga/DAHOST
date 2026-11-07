/**
 * CycleView — LAYAR SIKLUS MARKETING (F5.5): target → anggaran → omzet dalam SATU layar.
 *
 * KENAPA LAYAR INI ADA
 * --------------------
 * Sebelum F5, satu bulan kerja dibaca dari tiga layar berbeda (Target, Anggaran, Laporan) yang masing-masing
 * menghitung sendiri. Layar ini membaca SATU endpoint (`/api/marketing/cycle/overview`) yang angkanya dihitung
 * `core/marketing_cycle.py`. Total & peringkat dihitung di backend, bukan di browser.
 *
 * Yang WAJIB tetap terlihat (jangan dihapus saat merapikan tampilan):
 *  · DUA angka omzet (produk & order amount) + label "sebelum potongan platform";
 *  · `pace` (bagian bulan yang sudah berjalan) di samping capaian;
 *  · cakupan HPP di samping marjin — marjin tanpa cakupan adalah angka yang menipu;
 *  · **omzet BRUTO dan omzet SETELAH RETUR berdampingan** (keputusan pemilik sesi #9); nilai retur membawa
 *    CAKUPAN: hari yang rekapnya diimpor/diketik tidak tahu soal retur — itu belum diketahui, bukan nol;
 *  · status kunci periode + siapa yang menutup;
 *  · catatan kejujuran data (apa yang TIDAK diketahui angka ini).
 *
 * Standar UI/UX v2 (8 Nov 2026): 4 kartu StatTile + satu kalimat (dulu 7 kartu sebaris), pil "Semua / Perlu
 * perhatian", unduh Excel/CSV (dulu CSV saja), ViewToggle Tabel/Kartu, tabel berisi kolom inti (omzet produk + order
 * amount, setelah retur + nilai retur, capaian + pace, anggaran, marjin + cakupan HPP) — kolom lain (target s.d. hari
 * ini, proyeksi, pesanan, unit, AOV, sisa, ROAS) ada di popup detail dan di unduhan. Aksi baris: Target & Anggaran
 * tampil, Tutup/Buka periode & Detail di menu "Lainnya". Form = FormPopup, detail = DetailPopup, warna lewat token.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Target, Wallet, Loader2, Lock, Unlock, Info, Eye, CheckCircle2, MoreHorizontal, RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { GlassCard } from '@/components/ui/glass';
import FilterChips from '@/components/ui/filter-chips';
import ViewToggle from '@/components/ui/view-toggle';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import { formatRupiah } from '@/lib/format';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmtRp = formatRupiah;
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const pct = (n) => `${Number(n || 0).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const VIEW_KEY = 'marketing_cycle_view';
/** Teks dari server: istilah Inggris / kode program → bahasa biasa (tampilan saja). */
const teks = (s) => String(s || '').replace(/\s*\/\s*Settlement/gi, '').replace(/\bSettlement\b/gi, 'pencairan')
  .replace(/\b([a-z]+(?:_[a-z]+)+)\b/g, (m) => m.replace(/_/g, ' '));
const VIEWS = { table: 'table', grid: 'grid' };

const CAT_LABEL = {
  ads: 'Iklan', kol: 'KOL (fee tetap)', komisi: 'Komisi kreator',
  livehost: 'Host live', sample: 'Sampel', diskon: 'Diskon / promo',
};

// Label PENDEK khusus sel tabel (judul penuh membuat baris tabel tidak seragam tingginya).
const FLAG_SHORT = {
  target_behind: 'tertinggal target',
  target_missing: 'target kosong',
  budget_warning: 'anggaran 80%',
  budget_overrun: 'anggaran lewat',
  budget_overrun_category: 'kategori lewat',
  budget_unplanned_category: 'tanpa rencana',
  budget_missing: 'rencana kosong',
  hpp_coverage_low: 'HPP belum lengkap',
};
const NADA_SEV = { red: 'danger', yellow: 'warning' };

function SevBadge({ severity, children }) {
  return <StatusBadge status={severity} label={children} tone={NADA_SEV[severity] || 'info'} />;
}

function Bar({ value, reference, over }) {
  return (
    <div className="relative mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--glass-bg)]">
      <div className={`h-full ${over ? 'bg-[hsl(var(--destructive))]' : 'bg-primary'}`}
        style={{ width: `${Math.min(Math.max(value || 0, 0), 100)}%` }} />
      {reference != null && (
        <span className="absolute top-0 h-full w-[2px] bg-foreground/60"
          style={{ left: `${Math.min(Math.max(reference, 0), 100)}%` }} title={`pace ${pct(reference)}`} />
      )}
    </div>
  );
}

const Kunci = ({ locked }) => (locked
  ? <StatusBadge status="locked" label="Terkunci" tone="warning" />
  : <StatusBadge status="open" label="Terbuka" tone="muted" />);

/* ─── Form: TARGET (penolakan backend 423 periode tertutup ditahan DI DALAM popup) ─── */
function TargetDialog({ open, onOpenChange, row, period, token, onSaved }) {
  const [form, setForm] = useState({ revenue_target: '', orders_target: '', notes: '', reason: '' });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open && row) {
      setErr('');
      setForm({
        revenue_target: row.target?.revenue || '',
        orders_target: row.target?.orders || '',
        notes: row.target?.notes || '',
        // Alasan TIDAK dibawa dari nilai lama: ia menjelaskan perubahan KALI INI.
        reason: '',
      });
    }
  }, [open, row]);

  const save = async () => {
    setSaving(true); setErr('');
    try {
      const [y, m] = period.split('-');
      const res = await fetch(`${API}/api/marketing/targets`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: row.account.id, year: Number(y), month: Number(m),
          revenue_target: parseFloat(form.revenue_target) || 0,
          orders_target: parseInt(form.orders_target, 10) || 0,
          notes: form.notes || null,
          reason: form.reason || null,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { setErr(body.detail || `Gagal menyimpan (kode ${res.status}).`); return; }
      toast.success(`Target ${row.account.account_name} ${period} disimpan`);
      onOpenChange(false); onSaved();
    } catch (e) { setErr(e.message || 'Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} judul={`Target ${row?.account?.account_name || ''}`}
      keterangan={`Periode ${period}. Capaian dibandingkan dengan pace (bagian bulan yang sudah berjalan), bukan target penuh.`}
      onSimpan={save} menyimpan={saving} galat={err} labelSimpan="Simpan target" testId="cycle-target-dialog">
      <Isian label="Target omzet (Rp)">
        <MoneyInput value={form.revenue_target} data-testid="cycle-target-revenue"
          onChange={(e) => setForm((f) => ({ ...f, revenue_target: e.target.value }))} />
      </Isian>
      <Isian label="Target jumlah pesanan">
        <Input type="number" min={0} value={form.orders_target} data-testid="cycle-target-orders"
          onChange={(e) => setForm((f) => ({ ...f, orders_target: e.target.value }))} />
      </Isian>
      <Isian label="Catatan" petunjuk="Opsional.">
        <Input value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
      </Isian>
      <Isian label="Alasan perubahan"
        petunjuk="Opsional, tampil di Jejak Marketing bersama nilai lama → baru. Tanpa alasan, jejak hanya menjawab 'berapa', bukan 'kenapa'.">
        <Input value={form.reason} placeholder="Mis. target diturunkan karena stok warna utama habis" data-testid="cycle-target-reason"
          onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} />
      </Isian>
    </FormPopup>
  );
}

/* ─── Form: RENCANA ANGGARAN per kategori ───────────────────────────────── */
function BudgetDialog({ open, onOpenChange, row, period, token, onSaved, categories }) {
  const [form, setForm] = useState({});
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open && row) {
      setErr('');
      setReason('');
      const plan = row.budget?.plan || {};
      const f = {};
      (categories || []).forEach((c) => { f[c] = plan[c] || ''; });
      setForm(f);
    }
  }, [open, row, categories]);

  const total = (categories || []).reduce((s, c) => s + (parseFloat(form[c]) || 0), 0);

  const save = async () => {
    setSaving(true); setErr('');
    try {
      const budget_by_category = {};
      (categories || []).forEach((c) => { budget_by_category[c] = parseFloat(form[c]) || 0; });
      const res = await fetch(`${API}/api/marketing/budget`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: row.account.id, period, budget_by_category, reason: reason || '' }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { setErr(body.detail || `Gagal menyimpan (kode ${res.status}).`); return; }
      toast.success(`Rencana anggaran ${row.account.account_name} disimpan`);
      onOpenChange(false); onSaved();
    } catch (e) { setErr(e.message || 'Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} judul={`Rencana anggaran ${row?.account?.account_name || ''}`}
      keterangan={`Periode ${period}. Kategori bertanda otomatis dihitung sistem dari data sumber (pesanan, iklan, shift host live).`}
      onSimpan={save} menyimpan={saving} galat={err} labelSimpan="Simpan rencana" testId="cycle-budget-dialog">
      {(categories || []).map((c) => {
        const cat = (row?.budget?.categories || []).find((x) => x.category === c) || {};
        return (
          <Isian key={c} label={CAT_LABEL[c] || c} petunjuk={`Terpakai ${fmtRp(cat.spend)}${cat.mode === 'auto' ? ' (otomatis)' : ''}`}>
            <MoneyInput value={form[c] ?? ''} data-testid={`cycle-budget-input-${c}`}
              onChange={(e) => setForm((f) => ({ ...f, [c]: e.target.value }))} />
          </Isian>
        );
      })}
      <div className="flex justify-between border-t border-[var(--glass-border)] pt-3 text-sm font-semibold">
        <span>Total rencana</span><span className="tabular-nums" data-testid="cycle-budget-total">{fmtRp(total)}</span>
      </div>
      <Isian label="Alasan perubahan" petunjuk="Opsional, masuk jejak perubahan.">
        <Input value={reason} placeholder="Mis. anggaran iklan ditambah untuk kejar target akhir bulan" data-testid="cycle-budget-reason"
          onChange={(e) => setReason(e.target.value)} />
      </Isian>
    </FormPopup>
  );
}

/* ─── Form: TUTUP / BUKA PERIODE — alasan WAJIB (jejak masuk marketing_change_log) ─── */
function LockDialog({ open, onOpenChange, row, period, token, onSaved }) {
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const locked = !!row?.locked;
  const action = locked ? 'reopen' : 'close';

  useEffect(() => { if (open) { setReason(''); setErr(''); } }, [open]);

  const save = async () => {
    if (!reason.trim()) { setErr('Alasan wajib diisi.'); return; }
    setSaving(true); setErr('');
    try {
      const res = await fetch(`${API}/api/marketing/periods/lock`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: row.account.id, period, action, reason }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { setErr(body.detail || `Gagal (kode ${res.status}).`); return; }
      toast.success(body.message || 'Berhasil');
      onOpenChange(false); onSaved();
    } catch (e) { setErr(e.message || 'Gagal'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)}
      judul={`${locked ? 'Buka periode' : 'Tutup periode'} ${row?.account?.account_name || ''}`} keterangan={`Periode ${period}`}
      onSimpan={save} menyimpan={saving} galat={err} labelSimpan={locked ? 'Buka periode' : 'Tutup periode'} testId="cycle-lock-dialog">
      <Notice tone={locked ? 'warning' : 'info'} icon={locked ? Unlock : Lock}>
        {locked
          ? 'Membuka periode berarti angka yang sudah dirapatkan bisa berubah lagi. Semua perubahan sesudah ini tercatat beserta nama Anda.'
          : 'Menutup periode membekukan target, anggaran, rekap harian, dan impor bulan ini. Ini yang membuat notulen rapat dan sistem tetap sama.'}
      </Notice>
      <Isian label="Alasan" wajib>
        <Input value={reason} data-testid="cycle-lock-reason"
          placeholder={locked ? 'Mis. koreksi pesanan yang terlambat masuk' : 'Mis. sudah dirapatkan 5 Agustus'}
          onChange={(e) => setReason(e.target.value)} />
      </Isian>
      {(row?.lock?.history || []).length > 0 && (
        <div className="space-y-1 text-sm text-muted-foreground" data-testid="cycle-lock-history">
          <p className="font-medium text-foreground">Riwayat kunci</p>
          {(row.lock.history || []).slice(-5).reverse().map((h, i) => (
            <p key={i}>{h.action === 'close' ? 'Ditutup' : 'Dibuka'} oleh {h.by_name} — {h.reason || 'tanpa alasan'}</p>
          ))}
        </div>
      )}
    </FormPopup>
  );
}

/* ─── F6.4 — JEJAK PERUBAHAN (siapa mengubah target, dari berapa ke berapa) ─── */
function ChangeLogPanel({ accountId, period, token }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API}/api/marketing/periods/change-log`
          + `?account_id=${accountId}&period=${period}&limit=20`,
        { headers: { Authorization: `Bearer ${token}` } });
        const j = res.ok ? await res.json() : {};
        if (alive) setRows(j.entries || []);
      } catch { if (alive) setRows([]); }
    })();
    return () => { alive = false; };
  }, [accountId, period, token]);
  const label = (a) => ({
    target_create: 'Target dibuat', target_update: 'Target diubah',
    budget_upsert: 'Rencana anggaran diubah', period_close: 'Periode ditutup',
    period_reopen: 'Periode dibuka',
  }[a] || String(a || '').replace(/_/g, ' '));
  const money = (v) => (typeof v === 'number' ? fmtRp(v) : String(v ?? '—'));
  return (
    <div className="space-y-2" data-testid="cycle-changelog">
      <p className="text-sm font-medium text-foreground">Jejak perubahan bulan ini</p>
      {rows === null ? <p className="text-sm text-muted-foreground">Memuat…</p>
        : rows.length === 0 ? <EmptyState className="py-4" title="Belum ada perubahan tercatat untuk bulan ini" />
          : (
            <Table>
              <TableHeader>
                <TableRow><TableHead>Perubahan</TableHead><TableHead>Oleh</TableHead><TableHead className="hidden sm:table-cell">Omzet target</TableHead><TableHead className="hidden md:table-cell">Alasan</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>{label(r.action)}</TableCell>
                    <TableCell>{r.actor_name || '—'}</TableCell>
                    <TableCell className="hidden whitespace-nowrap tabular-nums sm:table-cell">
                      {(r.before?.revenue_target != null || r.after?.revenue_target != null)
                        ? `${money(r.before?.revenue_target)} → ${money(r.after?.revenue_target)}` : '—'}
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground md:table-cell">{r.reason || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
    </div>
  );
}

/* ─── Detail satu toko (rincian anggaran + bukti + catatan) — popup ───────── */
function DetailDialog({ open, onOpenChange, row, period, token }) {
  if (!row || !open) return null;
  const b = row.budget || {};
  const m = row.margin || {};
  const ach = row.achievement || {};
  const src = {};
  (row.spend_sources || []).forEach((s) => { src[s.category] = s; });
  return (
    <DetailPopup open onClose={() => onOpenChange(false)} testId="cycle-detail-dialog"
      judul={`${row.account.account_name} · ${period}`}
      keterangan={`${row.account.account_code} · ${row.account.platform} · basis omzet: ${teks(row.revenue_basis)}`}
      status={<Kunci locked={row.locked} />}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-konten-utama="">
        <StatTile label="Omzet produk" value={fmtRp(row.actual?.revenue_product)} />
        <StatTile label="Order amount" value={fmtRp(row.actual?.revenue_order_amount)} />
        <StatTile label="Diskon penjual" value={fmtRp(row.actual?.seller_discount)} />
        <StatTile label="Harga coret (bruto)" value={fmtRp(row.actual?.gross_before_discount)} />
      </div>

      <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
        <BarisDetail label="Capaian / pace">{pct(ach.revenue_pct)} / {pct(ach.pace_pct)}</BarisDetail>
        <BarisDetail label="Target s.d. hari ini"><span className="tabular-nums">{fmtRp(ach.prorata_target)}</span></BarisDetail>
        <BarisDetail label="Proyeksi akhir bulan"><span className="tabular-nums">{fmtRp(ach.run_rate)}</span></BarisDetail>
        <BarisDetail label="Pesanan">{fmtNum(row.actual?.orders)}{row.target?.orders ? ` dari target ${fmtNum(row.target.orders)}` : ''} · {fmtNum(row.actual?.units)} unit</BarisDetail>
        <BarisDetail label="Rata-rata per pesanan"><span className="tabular-nums">{fmtRp(row.actual?.aov)}</span></BarisDetail>
        <BarisDetail label="Sisa anggaran"><span className="tabular-nums">{fmtRp(b.total_remaining)} ({pct(b.total_used_pct)} terpakai)</span></BarisDetail>
      </dl>

      {/* ── SESI #9 — RETUR: dua angka omzet berdampingan ──────────────── */}
      <div className="space-y-2" data-testid="cycle-detail-returns">
        <p className="text-sm font-medium text-foreground">Omzet bruto vs omzet setelah retur</p>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Omzet bruto (dipakai target)" value={fmtRp(row.actual?.revenue_gross ?? row.actual?.revenue)} />
          <StatTile label="Pesanan retur" value={fmtNum(row.actual?.returned_orders)} sub={`${fmtNum(row.actual?.returned_units)} pcs`} />
          <StatTile label="Nilai retur" value={fmtRp(row.actual?.returned_amount)} sub={pct(row.actual?.returns_pct)}
            accent={(row.actual?.returned_amount || 0) > 0 ? 'warning' : 'default'} />
          <StatTile label="Omzet setelah retur" value={fmtRp(row.actual?.revenue_net_returns)} />
        </div>
        {row.returns?.label_gross && <p className="text-sm text-muted-foreground">{teks(row.returns.label_gross)}</p>}
        {row.returns?.label_net && <p className="text-sm text-muted-foreground">{teks(row.returns.label_net)}</p>}
        {row.returns?.coverage?.complete === false && (
          <Notice tone="warning">
            Cakupan data retur {pct(row.returns?.coverage?.coverage_pct)} hari ({fmtNum(row.returns?.coverage?.days_known)}/{fmtNum(row.returns?.coverage?.days_total)}) —
            hari yang rekapnya diimpor/diketik tidak membawa informasi retur, jadi nilai retur di atas adalah batas bawah, bukan angka final.
          </Notice>
        )}
        {row.returns?.over_returned && (
          <Notice tone="danger">Nilai retur MELEBIHI omzet bulan ini — biasanya pesanannya dibuat bulan sebelumnya lalu diretur bulan ini.</Notice>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Anggaran per kategori — rencana vs realisasi</p>
          <TombolUnduh namaBerkas={`anggaran-${row.account.account_code}-${period}`} namaLembar="Anggaran per kategori" baris={b.categories || []}
            testId="cycle-detail-budget-unduh"
            kolom={[
              { label: 'Kategori', nilai: (c) => CAT_LABEL[c.category] || c.category },
              { label: 'Sumber', nilai: (c) => (c.mode === 'auto' ? 'Otomatis' : 'Manual') },
              { label: 'Rencana (Rp)', nilai: (c) => c.plan ?? 0 },
              { label: 'Terpakai (Rp)', nilai: (c) => c.spend ?? 0 },
              { label: 'Manual (Rp)', nilai: (c) => c.manual ?? 0 },
              { label: 'Otomatis (Rp)', nilai: (c) => c.auto ?? 0 },
              { label: 'Sisa (Rp)', nilai: (c) => c.variance ?? 0 },
              { label: 'Pakai (%)', nilai: (c) => c.used_pct ?? 0 },
              { label: 'Bukti', nilai: (c) => src[c.category]?.evidence || '' },
            ]} />
        </div>
        <div className="overflow-x-auto">
          <Table data-testid="cycle-detail-budget-table">
            <TableHeader>
              <TableRow>
                <TableHead>Kategori</TableHead>
                <TableHead>Sumber</TableHead>
                <TableHead className="text-right">Rencana</TableHead>
                <TableHead className="text-right">Terpakai</TableHead>
                <TableHead className="hidden text-right md:table-cell">Manual</TableHead>
                <TableHead className="hidden text-right md:table-cell">Otomatis</TableHead>
                <TableHead className="text-right">Sisa</TableHead>
                <TableHead className="text-right">Pakai</TableHead>
                <TableHead className="hidden lg:table-cell">Bukti</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(b.categories || []).map((c) => (
                <TableRow key={c.category} data-testid={`cycle-detail-cat-${c.category}`}>
                  <TableCell>{CAT_LABEL[c.category] || c.category}</TableCell>
                  <TableCell><StatusBadge status={c.mode} label={c.mode === 'auto' ? 'Otomatis' : 'Manual'} tone="muted" /></TableCell>
                  <TableCell className="text-right tabular-nums">{fmtRp(c.plan)}</TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{fmtRp(c.spend)}</TableCell>
                  <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtRp(c.manual)}</TableCell>
                  <TableCell className="hidden text-right tabular-nums md:table-cell">{fmtRp(c.auto)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${c.variance < 0 ? 'text-[hsl(var(--danger-text))]' : ''}`}>{fmtRp(c.variance)}</TableCell>
                  <TableCell className="text-right tabular-nums">{pct(c.used_pct)}</TableCell>
                  <TableCell className="hidden text-muted-foreground lg:table-cell">{src[c.category]?.evidence || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
        <BarisDetail label="Marjin kotor">
          {fmtRp(m.gross_profit)} · {pct(m.gross_margin_pct)}
          <span className="block text-muted-foreground">HPP {fmtRp(m.hpp)} · cakupan HPP {pct(m.hpp_coverage_pct)} ({fmtNum(m.units_covered)}/{fmtNum(m.units_total)} unit)</span>
          {!m.trustworthy && <span className="block text-[hsl(var(--warning-text))]">Cakupan HPP di bawah 80% — marjin ini belum bisa dipercaya untuk keputusan harga.</span>}
        </BarisDetail>
        <BarisDetail label="ROAS / ROI">
          ROAS {Number(row.roi?.roas || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}
          {' · '}{row.roi?.reliable ? `ROI ${pct(row.roi?.roi_pct)}` : <span className="text-muted-foreground">ROI belum bisa dihitung</span>}
          <span className="block text-muted-foreground">Belanja {fmtRp(row.roi?.spend)} = {pct(row.roi?.spend_of_revenue_pct)} dari omzet</span>
          {!row.roi?.reliable && row.roi?.reliability_note && (
            <span className="block text-[hsl(var(--warning-text))]" data-testid="cycle-roi-note">{row.roi.reliability_note}</span>
          )}
        </BarisDetail>
      </dl>

      {(row.flags || []).length > 0 && (
        <div className="space-y-1" data-testid="cycle-detail-flags">
          <p className="text-sm font-medium text-foreground">Peringatan</p>
          {(row.flags || []).map((f, i) => (
            <div key={i} className="flex items-start gap-2 text-sm">
              <SevBadge severity={f.severity}>{FLAG_SHORT[f.code] || f.title}</SevBadge>
              <span className="text-foreground">{teks(f.title)} — {teks(f.message)}</span>
            </div>
          ))}
        </div>
      )}

      <ChangeLogPanel accountId={row.account.id} period={period} token={token} />

      <Notice tone="info" icon={Info} title="Catatan kejujuran data" testId="cycle-detail-notes">
        <ul className="list-disc space-y-0.5 pl-4">
          {(row.data_notes || []).map((n, i) => <li key={i}>{teks(n)}</li>)}
        </ul>
      </Notice>
    </DetailPopup>
  );
}

/* ══════════════════════════════════════════════════════════════════════════ */
export default function CycleView({ token, period, monthLabel, scope = 'marketing' }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState(() => {
    try { return VIEWS[localStorage.getItem(VIEW_KEY)] || 'table'; } catch { return 'table'; }
  });
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [target, setTarget] = useState(null);
  const [budget, setBudget] = useState(null);
  const [lockRow, setLockRow] = useState(null);
  const [detail, setDetail] = useState(null);

  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view); } catch { /* storage diblokir */ } }, [view]);

  const load = useCallback(async () => {
    if (!period) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/marketing/cycle/overview?period=${period}`,
        { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`kode ${res.status}`);
      setData(await res.json());
    } catch (e) {
      toast.error(`Gagal memuat siklus: ${e.message}`);
      setData(null);
    } finally { setLoading(false); }
  }, [period, token]);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => {
    const all = data?.rows || [];
    if (!onlyAttention) return all;
    return all.filter((r) => (r.flags || []).some((f) => f.severity === 'red' || f.severity === 'yellow'));
  }, [data, onlyAttention]);

  const t = data?.totals || {};
  const prog = data?.progress || {};
  const diAtasPace = (t.revenue_pct || 0) >= (t.pace_pct || 0);

  // Kolom unduhan = semua kolom tabel lama (CSV lama) — kini Excel & CSV.
  const kolomUnduh = [
    ['Toko', (r) => r.account.account_name], ['Kode', (r) => r.account.account_code], ['Platform', (r) => r.account.platform],
    ['Kunci', (r) => (r.locked ? 'Terkunci' : 'Terbuka')], ['Target omzet', (r) => r.target?.revenue ?? ''],
    ['Omzet produk', (r) => r.actual?.revenue_product ?? 0], ['Omzet order amount', (r) => r.actual?.revenue_order_amount ?? 0],
    ['Nilai retur', (r) => r.actual?.returned_amount ?? 0], ['Pesanan retur', (r) => r.actual?.returned_orders ?? 0],
    ['Omzet setelah retur', (r) => r.actual?.revenue_net_returns ?? 0], ['Capaian %', (r) => r.achievement?.revenue_pct ?? 0],
    ['Pace %', (r) => r.achievement?.pace_pct ?? 0], ['Target prorata', (r) => r.achievement?.prorata_target ?? 0],
    ['Proyeksi akhir bulan', (r) => r.achievement?.run_rate ?? 0], ['Pesanan', (r) => r.actual?.orders ?? 0],
    ['Target pesanan', (r) => r.target?.orders ?? ''], ['Unit', (r) => r.actual?.units ?? 0], ['AOV', (r) => r.actual?.aov ?? 0],
    ['Rencana anggaran', (r) => r.budget?.total_plan ?? 0], ['Terpakai', (r) => r.budget?.total_spend ?? 0],
    ['Sisa', (r) => r.budget?.total_remaining ?? 0], ['Pakai %', (r) => r.budget?.total_used_pct ?? 0],
    ['Marjin %', (r) => r.margin?.gross_margin_pct ?? 0], ['Cakupan HPP %', (r) => r.margin?.hpp_coverage_pct ?? 0],
    ['ROAS', (r) => r.roi?.roas ?? 0], ['Peringatan', (r) => (r.flags || []).map((f) => FLAG_SHORT[f.code] || f.title).join(' | ')],
  ].map(([label, nilai]) => ({ label, nilai }));

  const aksiBaris = (r) => (
    <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
      <Button size="sm" variant="outline" onClick={() => setTarget(r)} data-testid={`cycle-set-target-${r.account.account_code}`}>
        <Target />Target
      </Button>
      <Button size="sm" variant="outline" onClick={() => setBudget(r)} data-testid={`cycle-set-budget-${r.account.account_code}`}>
        <Wallet />Anggaran
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" title="Lainnya" aria-label="Lainnya" data-testid={`cycle-more-${r.account.account_code}`}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setLockRow(r)} data-testid={`cycle-lock-${r.account.account_code}`}>
            {r.locked ? <Unlock className="mr-2 h-4 w-4" /> : <Lock className="mr-2 h-4 w-4" />}{r.locked ? 'Buka periode' : 'Tutup periode'}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setDetail(r)} data-testid={`cycle-detail-${r.account.account_code}`}>
            <Eye className="mr-2 h-4 w-4" />Lihat detail
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );

  const bendera = (r, maks = 2) => ((r.flags || []).length === 0
    ? <span className="inline-flex items-center gap-1 whitespace-nowrap text-sm text-[hsl(var(--success-text))]"><CheckCircle2 className="h-3.5 w-3.5" />aman</span>
    : (
      <span className="flex flex-wrap gap-1">
        {(r.flags || []).slice(0, maks).map((f, i) => (
          <span key={i} title={`${f.title} — ${f.message}`} className="whitespace-nowrap">
            <SevBadge severity={f.severity}>{FLAG_SHORT[f.code] || f.title}</SevBadge>
          </span>
        ))}
        {(r.flags || []).length > maks && (
          <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={(e) => { e.stopPropagation(); setDetail(r); }}
            title={(r.flags || []).slice(maks).map((f) => f.title).join(' · ')} data-testid={`cycle-flags-more-${r.account.account_code}`}>
            +{(r.flags || []).length - maks} lagi
          </Button>
        )}
      </span>
    ));

  return (
    <div className="space-y-4" data-testid="cycle-view">
      {/* ── KPI gabungan: 4 kartu + 1 kalimat ─────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="cycle-kpi" data-konten-utama="">
        <StatTile label="Omzet produk" value={fmtRp(t.revenue_product)}
          sub={`Order amount ${fmtRp(t.revenue_order_amount)} · target ${fmtRp(t.target_revenue)} (${t.accounts_with_target || 0}/${t.accounts || 0} toko punya target)`} />
        {/* SESI #9 — omzet sesudah retur berdampingan dengan bruto */}
        <StatTile testId="cycle-kpi-returns" label="Setelah retur" value={fmtRp(t.revenue_net_returns)}
          sub={t.returns_coverage_complete === false
            ? 'Ada hari yang rekapnya diimpor/diketik ⇒ retur BELUM DIKETAHUI (bukan nol)'
            : (t.returned_orders || 0) > 0
              ? `Retur ${fmtNum(t.returned_orders)} pesanan · ${fmtRp(t.returned_amount)} (${pct(t.returns_pct)})`
              : 'Tidak ada retur bulan ini'}
          subTone={t.returns_coverage_complete === false ? 'warning' : undefined} />
        <StatTile label="Capaian vs pace" value={`${pct(t.revenue_pct)} / ${pct(t.pace_pct)}`}
          accent={t.target_revenue ? (diAtasPace ? 'success' : 'warning') : 'default'}
          sub={t.target_revenue ? (diAtasPace ? 'Di atas pace target' : 'Di bawah pace target') : 'Belum ada target omzet'} />
        <StatTile label="Anggaran terpakai" value={fmtRp(t.total_spend)} sub={`dari rencana ${fmtRp(t.total_plan)} · ${pct(t.total_used_pct)}`} />
      </div>
      <p className="text-sm text-muted-foreground" data-testid="cycle-label">
        Marjin kotor {fmtRp(t.gross_profit)} (cakupan HPP {pct(t.hpp_coverage_pct)}) · sisa {Math.max((prog.days_total || 0) - (prog.days_elapsed || 0), 0)} hari
        ({prog.days_elapsed || 0}/{prog.days_total || 0} hari berjalan, {monthLabel}).{data?.label ? ` ${teks(data.label)}` : ''}
      </p>

      {/* ── baris alat ──────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterChips testId="cycle-filter" hideWhenEmpty={false} value={onlyAttention ? 'perhatian' : ''}
          onChange={(k) => setOnlyAttention(k === 'perhatian')} ariaLabel="Saring toko"
          options={[{ key: '', label: 'Semua toko', count: (data?.rows || []).length },
            { key: 'perhatian', label: 'Perlu perhatian', count: (data?.attention || []).length }]} />
        <div className="ml-auto flex items-center gap-2">
          <TombolUnduh namaBerkas={`siklus-marketing-${period}`} namaLembar="Siklus marketing" baris={data?.rows || []} kolom={kolomUnduh}
            testId="cycle-export-csv" />
          <ViewToggle value={view} onChange={setView} testId="cycle-view" />
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang" data-testid="cycle-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      {/* papan perlu perhatian — diurutkan backend (merah dulu) */}
      {(data?.attention || []).length > 0 && (
        <GlassCard className="space-y-2 p-4" data-testid="cycle-attention-board">
          <p className="text-base font-semibold text-foreground">
            Perlu perhatian — {t.flags_red || 0} merah · {t.flags_yellow || 0} kuning
          </p>
          <Table>
            <TableBody>
              {(data.attention || []).slice(0, 8).map((a) => (
                <TableRow key={a.account_id} className="cursor-pointer" data-testid={`cycle-attention-${a.account_code}`}
                  onClick={() => setDetail((data.rows || []).find((r) => r.account.id === a.account_id))}>
                  <TableCell className="font-medium">{a.account_name}</TableCell>
                  <TableCell>
                    <span className="flex flex-wrap gap-1">{a.flags.map((f, i) => <SevBadge key={i} severity={f.severity}>{f.title}</SevBadge>)}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </GlassCard>
      )}

      {/* ── TABEL / KARTU ────────────────────────────────────────────────── */}
      {loading ? (
        <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Menghitung siklus semua toko…
        </p>
      ) : !rows.length ? (
        <EmptyState testId="cycle-empty" title={onlyAttention ? 'Tidak ada toko yang perlu perhatian bulan ini' : 'Belum ada toko aktif untuk periode ini'} />
      ) : view === 'table' ? (
        <GlassCard className="overflow-x-auto p-0">
          <Table data-testid="cycle-table">
            <TableHeader>
              <TableRow>
                <TableHead>Toko</TableHead>
                <TableHead className="text-right">Target omzet</TableHead>
                <TableHead className="text-right">Omzet produk</TableHead>
                <TableHead className="text-right">Setelah retur</TableHead>
                <TableHead className="min-w-[110px]">Capaian / pace</TableHead>
                <TableHead className="hidden text-right lg:table-cell">Anggaran</TableHead>
                <TableHead className="hidden text-right xl:table-cell">Marjin (cakupan HPP)</TableHead>
                <TableHead className="hidden md:table-cell">Peringatan</TableHead>
                <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => {
                const ach = r.achievement || {};
                const b = r.budget || {};
                const m = r.margin || {};
                const behind = (r.flags || []).some((f) => f.code === 'target_behind');
                const over = (b.total_spend || 0) > (b.total_plan || 0) && (b.total_plan || 0) > 0;
                return (
                  <TableRow key={r.account.id} className="cursor-pointer" onClick={() => setDetail(r)}
                    data-testid={`cycle-row-${r.account.account_code}`}>
                    <TableCell>
                      <div className="font-medium text-foreground">{r.account.account_name}</div>
                      <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                        {r.account.account_code} · {r.account.platform} <Kunci locked={r.locked} />
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      {r.target?.exists ? fmtRp(r.target.revenue) : <span className="text-muted-foreground">belum diisi</span>}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums">
                      <div className="font-medium">{fmtRp(r.actual?.revenue_product)}</div>
                      <div className="text-xs text-muted-foreground">order {fmtRp(r.actual?.revenue_order_amount)}</div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right tabular-nums" data-testid={`cycle-net-${r.account.account_code}`}>
                      <div className="font-medium">{fmtRp(r.actual?.revenue_net_returns)}</div>
                      <div className="text-xs text-muted-foreground" data-testid={`cycle-returned-${r.account.account_code}`}>
                        {(r.actual?.returned_orders || 0) > 0
                          ? `retur ${fmtRp(r.actual?.returned_amount)} · ${fmtNum(r.actual?.returned_orders)} pesanan`
                          : 'tanpa retur'}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className={behind ? 'font-medium text-[hsl(var(--danger-text))]' : 'font-medium'}>{pct(ach.revenue_pct)}</span>
                      <span className="text-xs text-muted-foreground"> / {pct(ach.pace_pct)}</span>
                      <Bar value={ach.revenue_pct} reference={ach.pace_pct} over={behind} />
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap text-right tabular-nums lg:table-cell">
                      <div className={over ? 'font-medium text-[hsl(var(--danger-text))]' : ''}>{fmtRp(b.total_spend)}</div>
                      <div className="text-xs text-muted-foreground">dari {fmtRp(b.total_plan)}</div>
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap text-right tabular-nums xl:table-cell">
                      {pct(m.gross_margin_pct)}
                      <span className={`ml-1 text-xs ${m.trustworthy ? 'text-muted-foreground' : 'text-[hsl(var(--warning-text))]'}`}>({pct(m.hpp_coverage_pct)})</span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">{bendera(r)}</TableCell>
                    <TableCell className="text-right">{aksiBaris(r)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </GlassCard>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="cycle-grid">
          {rows.map((r) => {
            const ach = r.achievement || {};
            const b = r.budget || {};
            const behind = (r.flags || []).some((f) => f.code === 'target_behind');
            return (
              <GlassCard key={r.account.id} className="space-y-2 p-4" data-testid={`cycle-card-${r.account.account_code}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-medium text-foreground">{r.account.account_name}</p>
                    <p className="text-xs text-muted-foreground">{r.account.account_code} · {r.account.platform}</p>
                  </div>
                  <Kunci locked={r.locked} />
                </div>
                <dl className="space-y-1 text-sm">
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Target</dt>
                    <dd className="tabular-nums">{r.target?.exists ? fmtRp(r.target.revenue) : 'belum diisi'}</dd></div>
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Omzet produk</dt>
                    <dd className="font-medium tabular-nums">{fmtRp(r.actual?.revenue_product)}</dd></div>
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Order amount</dt>
                    <dd className="tabular-nums">{fmtRp(r.actual?.revenue_order_amount)}</dd></div>
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Setelah retur</dt>
                    <dd className="font-medium tabular-nums">{fmtRp(r.actual?.revenue_net_returns)}</dd></div>
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Capaian / pace</dt>
                    <dd className={behind ? 'font-medium text-[hsl(var(--danger-text))]' : ''}>{pct(ach.revenue_pct)} / {pct(ach.pace_pct)}</dd></div>
                  <Bar value={ach.revenue_pct} reference={ach.pace_pct} over={behind} />
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Anggaran</dt>
                    <dd className="tabular-nums">{fmtRp(b.total_spend)} / {fmtRp(b.total_plan)}</dd></div>
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Marjin (cakupan HPP)</dt>
                    <dd>{pct(r.margin?.gross_margin_pct)} ({pct(r.margin?.hpp_coverage_pct)})</dd></div>
                  <div className="flex justify-between gap-2"><dt className="text-muted-foreground">ROAS</dt>
                    <dd>{Number(r.roi?.roas || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}</dd></div>
                </dl>
                <div>{bendera(r, 3)}</div>
                {aksiBaris(r)}
              </GlassCard>
            );
          })}
        </div>
      )}

      {/* ringkasan bawah — arah yang harus dibaca sebelum keluar layar */}
      {!loading && rows.length > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="cycle-footer-note">
          <span className={diAtasPace ? 'font-medium text-[hsl(var(--success-text))]' : 'font-medium text-[hsl(var(--warning-text))]'}>
            {diAtasPace ? 'Gabungan semua toko sedang di atas pace target. ' : 'Gabungan semua toko sedang di bawah pace target. '}
          </span>
          Angka dihitung backend dari satu sumber (rekap harian + pesanan + data iklan + shift host live). Realisasi anggaran otomatis
          tidak ditulis sebagai entri belanja, jadi tidak dobel dengan catatan manual.{scope === 'management' ? ' Tampilan Manajemen: semua toko.' : ''}
        </p>
      )}

      <TargetDialog open={!!target} onOpenChange={(v) => !v && setTarget(null)}
        row={target} period={period} token={token} onSaved={load} />
      <BudgetDialog open={!!budget} onOpenChange={(v) => !v && setBudget(null)}
        row={budget} period={period} token={token} onSaved={load} categories={data?.categories || []} />
      <LockDialog open={!!lockRow} onOpenChange={(v) => !v && setLockRow(null)}
        row={lockRow} period={period} token={token} onSaved={load} />
      <DetailDialog open={!!detail} onOpenChange={(v) => !v && setDetail(null)}
        row={detail} period={period} token={token} />
    </div>
  );
}
