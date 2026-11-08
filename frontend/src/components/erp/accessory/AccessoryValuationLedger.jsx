/**
 * AccessoryValuationLedger — FASE 8 (bagian dari tab "Valuasi HPP").
 *
 * Dua tabel pendukung:
 *   • Mutasi Bernilai — kartu stok aksesoris beserta HPP, nilai, dan nomor jurnal.
 *     Kolom "Jurnal" menjawab pertanyaan paling sering: "kenapa nilai persediaan
 *     tidak sama dengan buku besar?" — baris tanpa jurnal langsung terlihat.
 *   • Riwayat HPP — jejak perubahan harga satuan (rata-rata bergerak vs koreksi manual).
 *
 * Sumber data: /api/acc/valuation/movements · /api/acc/valuation/cost-history
 *
 * Standar UI/UX v2 (8 Nov 2026): pilihan tampilan = FilterChips (dulu segmen buatan), tabel = TabelData,
 * unduh Excel/CSV, muat ulang = tombol ikon, warna lewat token/StatusBadge (tanpa emoji).
 */

import { useState, useEffect, useCallback } from 'react';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { History, ArrowDownCircle, ArrowUpCircle, Trash2, RefreshCw, Receipt } from 'lucide-react';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

async function api(method, path, token) {
  const r = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });
const fmtRp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}`;
const fmtDate = (iso) => {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString('id-ID', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return String(iso).slice(0, 16); }
};

const MV_META = {
  receive: { label: 'Terima', icon: ArrowDownCircle, tone: 'success' },
  issue: { label: 'Keluar', icon: ArrowUpCircle, tone: 'warning' },
  scrap: { label: 'Scrap', icon: Trash2, tone: 'danger' },
  opname_adjust: { label: 'Opname', icon: History, tone: 'info' },
  // 2026-11-02 (K9): mutasi mesin opname tunggal bertipe `opname`
  opname: { label: 'Opname', icon: History, tone: 'info' },
  adjust: { label: 'Penyesuaian', icon: History, tone: 'info' },
};
const metaMutasi = (t) => MV_META[t] || { label: 'Mutasi lain', icon: History, tone: 'muted' };

const SOURCE_LABEL = { receive: 'Rata-rata bergerak', manual: 'Koreksi manual' };

export default function AccessoryValuationLedger({ token, refreshKey = 0 }) {
  const [view, setView] = useState('movements');
  const [movements, setMovements] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const [mv, ch] = await Promise.all([
        api('GET', '/api/acc/valuation/movements?limit=200', token).catch(() => []),
        api('GET', '/api/acc/valuation/cost-history?limit=200', token).catch(() => []),
      ]);
      setMovements(Array.isArray(mv) ? mv : []);
      setHistory(Array.isArray(ch) ? ch : []);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const mvPg = useClientPagination(movements, 25);
  const chPg = useClientPagination(history, 25);

  const kolomMutasi = [
    { kunci: 'waktu', label: 'Waktu', hp: 'keterangan', isi: (m) => <span className="whitespace-nowrap text-muted-foreground">{fmtDate(m.created_at)}</span> },
    { kunci: 'aksesoris', label: 'Aksesoris', hp: 'judul', isi: (m) => (
      <div>
        <div className="font-medium">{m.material_name}</div>
        <div className="text-xs text-muted-foreground">{m.material_code}</div>
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (m) => {
      const meta = metaMutasi(m.movement_type);
      return (
        <div>
          <StatusBadge status={m.movement_type} label={meta.label} tone={meta.tone} />
          {m.adjustment_reason && <div className="mt-0.5 text-xs text-muted-foreground">{m.adjustment_reason}</div>}
        </div>
      );
    } },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (m) => (
      <span className={`font-medium tabular-nums ${m.qty_signed < 0 ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--success-text))]'}`}>
        {m.qty_signed > 0 ? '+' : ''}{fmtNum(m.qty_signed)} <span className="text-xs text-muted-foreground">{m.unit}</span>
      </span>) },
    { kunci: 'hpp', label: 'HPP', rata: 'kanan', isi: (m) => (m.unit_cost > 0
      ? <span className="tabular-nums">{fmtRp(m.unit_cost)}</span>
      : <span className="text-[hsl(var(--warning-text))]">belum dinilai</span>) },
    { kunci: 'nilai', label: 'Nilai', rata: 'kanan', isi: (m) => <span className="tabular-nums">{m.value > 0 ? fmtRp(m.value) : '—'}</span> },
    { kunci: 'jurnal', label: 'Jurnal', isi: (m) => (m.je_number
      ? <StatusBadge status="posted" label={m.je_number} tone="success" />
      : m.post_error
        ? <span className="text-[hsl(var(--danger-text))]" title={m.post_error}>Gagal</span>
        : <span className="text-muted-foreground" title="Tidak ada jurnal untuk mutasi ini">—</span>) },
  ];

  const kolomRiwayat = [
    { kunci: 'waktu', label: 'Waktu', hp: 'judul', isi: (h) => <span className="whitespace-nowrap">{fmtDate(h.created_at)}</span> },
    { kunci: 'metode', label: 'Metode', hp: 'keterangan', isi: (h) => SOURCE_LABEL[h.source] || h.method || h.source || '—' },
    { kunci: 'sebelum', label: 'Stok sebelum', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmtNum(h.qty_before)}</span> },
    { kunci: 'masuk', label: 'Qty masuk', rata: 'kanan', isi: (h) => <span className="tabular-nums">{h.qty_in ? fmtNum(h.qty_in) : '—'}</span> },
    { kunci: 'lama', label: 'HPP lama', rata: 'kanan', isi: (h) => <span className="tabular-nums text-muted-foreground">{fmtRp(h.old_unit_cost)}</span> },
    { kunci: 'baru', label: 'HPP baru', rata: 'kanan', isi: (h) => <span className="font-medium tabular-nums">{fmtRp(h.new_unit_cost)}</span> },
    { kunci: 'oleh', label: 'Oleh', isi: (h) => <span className="text-muted-foreground">{h.actor?.name || '—'}</span> },
  ];

  const unduhMutasi = [
    { label: 'Waktu', nilai: (m) => fmtDate(m.created_at) },
    { label: 'Kode', nilai: (m) => m.material_code },
    { label: 'Aksesoris', nilai: (m) => m.material_name },
    { label: 'Jenis', nilai: (m) => metaMutasi(m.movement_type).label },
    { label: 'Alasan', nilai: (m) => m.adjustment_reason || '' },
    { label: 'Qty', nilai: (m) => Number(m.qty_signed || 0) },
    { label: 'Satuan', nilai: (m) => m.unit },
    { label: 'HPP (Rp)', nilai: (m) => Number(m.unit_cost || 0) },
    { label: 'Nilai (Rp)', nilai: (m) => Number(m.value || 0) },
    { label: 'Jurnal', nilai: (m) => m.je_number || (m.post_error ? `Gagal: ${m.post_error}` : '') },
  ];
  const unduhRiwayat = [
    { label: 'Waktu', nilai: (h) => fmtDate(h.created_at) },
    { label: 'Metode', nilai: (h) => SOURCE_LABEL[h.source] || h.method || h.source || '' },
    { label: 'Stok sebelum', nilai: (h) => Number(h.qty_before || 0) },
    { label: 'Qty masuk', nilai: (h) => Number(h.qty_in || 0) },
    { label: 'HPP lama (Rp)', nilai: (h) => Number(h.old_unit_cost || 0) },
    { label: 'HPP baru (Rp)', nilai: (h) => Number(h.new_unit_cost || 0) },
    { label: 'Oleh', nilai: (h) => h.actor?.name || '' },
  ];

  const mutasi = view === 'movements';
  const pg = mutasi ? mvPg : chPg;

  return (
    <div className="space-y-3" data-testid="acc-valuation-ledger">
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-2 text-base font-semibold">Kartu stok bernilai</p>
        <FilterChips value={view} onChange={setView} hideWhenEmpty={false} testId="acc-val-view"
          options={[
            { key: 'movements', label: 'Mutasi bernilai', count: movements.length },
            { key: 'history', label: 'Riwayat HPP', count: history.length },
          ]} />
        <div className="ml-auto flex items-center gap-2">
          <TombolUnduh namaBerkas={mutasi ? 'mutasi-bernilai-aksesoris' : 'riwayat-hpp-aksesoris'}
            namaLembar={mutasi ? 'Mutasi bernilai' : 'Riwayat HPP'} baris={mutasi ? movements : history}
            kolom={mutasi ? unduhMutasi : unduhRiwayat} testId="acc-val-ledger-unduh" />
          <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
            data-testid="acc-val-ledger-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      {err && <Notice tone="danger">{err}</Notice>}

      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat kartu stok…</p>
      ) : mutasi ? (
        <TabelData kolom={kolomMutasi} baris={mvPg.paged} testId="acc-val-mv"
          kosong={<EmptyState icon={Receipt} title="Belum ada mutasi bernilai"
            description="Mutasi akan muncul setelah ada penerimaan, pengeluaran, atau scrap aksesoris." />} />
      ) : (
        <TabelData kolom={kolomRiwayat} baris={chPg.paged} testId="acc-cost-hist"
          kosong={<EmptyState icon={History} title="Belum ada perubahan HPP"
            description="Riwayat terisi saat penerimaan membawa harga beli atau HPP dikoreksi manual." />} />
      )}
      {!loading && (
        <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total}
          pageSize={pg.pageSize} onPageChange={pg.setPage} />
      )}
    </div>
  );
}
