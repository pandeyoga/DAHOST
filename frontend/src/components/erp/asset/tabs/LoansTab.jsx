/**
 * LoansTab — Peminjaman Alat / Aset (ACC-3).
 *
 * Menggantikan menu "Peminjaman" yang dulu salah domain di Portal Aksesoris
 * (lihat memory/PRODUKSI_E9_AKSESORIS.md §ACC-3 & PRODUKSI_E7_ASET.md §AST-3).
 * Di sini yang dipinjam = UNIT ASET ber-nomor, bukan qty barang habis pakai.
 *
 * Standar UI/UX v2 (8 Nov 2026): kepala kedua (judul + ikon + paragraf) dihapus — judul hub sudah cukup;
 * tombol "Pinjamkan aset" di baris tab; 4 StatTile netral; penyaring satu baris; tabel TabelData (kartu
 * ringkas di HP); unduh Excel/CSV; pesan galat = Notice.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, Notice } from '../../moduleAtoms';
import { apicall, fmtDate, useHP } from '../utils';
import { KPICard, BarisKartu } from '../components/KPICard';
import { StatusBadge } from '../components/StatusBadge';
import { LOAN_STATUS_CONFIG, RETURN_CONDITION_LABEL } from '../constants';
import { CreateLoanDialog } from '../dialogs/CreateLoanDialog';
import { ReturnLoanDialog } from '../dialogs/ReturnLoanDialog';

const rowStatus = (l) => (l.is_overdue ? 'overdue' : l.status);

export function LoansTab({ token }) {
  const [loans, setLoans] = useState([]);
  const [summary, setSummary] = useState(null);
  const [status, setStatus] = useState('active');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [returnLoan, setReturnLoan] = useState(null);
  const hp = useHP();

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const [rows, sm] = await Promise.all([
        apicall('GET', `/api/assets/loans?status=${status}`, token),
        apicall('GET', '/api/assets/loans/summary', token),
      ]);
      setLoans(Array.isArray(rows) ? rows : []);
      setSummary(sm || null);
    } catch (e) {
      setErr(e.message || 'Gagal memuat data peminjaman');
    } finally { setLoading(false); }
  }, [token, status]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return loans;
    return loans.filter(l => `${l.loan_number} ${l.asset_number} ${l.asset_name} ${l.borrower_name} ${l.borrower_divisi} ${l.purpose}`
      .toLowerCase().includes(q));
  }, [loans, search]);

  const adaAngka = summary && [summary.active_loans, summary.overdue_loans, summary.returned_this_month, summary.available_assets]
    .some((n) => Number(n) > 0);

  // Alat dibungkus satu kelompok supaya Unduh & muat ulang tidak terpisah baris di HP.
  const alat = (
    <div className="flex items-center gap-2">
      <TombolUnduh namaBerkas="peminjaman-aset" namaLembar="Peminjaman" baris={filtered} testId="asset-loan-unduh"
        kolom={[
          { label: 'No. pinjam', nilai: (l) => l.loan_number },
          { label: 'No. aset', nilai: (l) => l.asset_number },
          { label: 'Aset', nilai: (l) => l.asset_name },
          { label: 'Peminjam', nilai: (l) => l.borrower_name },
          { label: 'Divisi', nilai: (l) => l.borrower_divisi || '' },
          { label: 'Tujuan', nilai: (l) => l.purpose || '' },
          { label: 'Tanggal pinjam', nilai: (l) => fmtDate(l.loan_date) },
          { label: 'Target kembali', nilai: (l) => (l.expected_return_date ? fmtDate(l.expected_return_date) : 'Tidak ditentukan') },
          { label: 'Tanggal kembali', nilai: (l) => (l.return_date ? fmtDate(l.return_date) : '') },
          { label: 'Kondisi kembali', nilai: (l) => (l.condition_in ? RETURN_CONDITION_LABEL[l.condition_in] || l.condition_in : '') },
          { label: 'Status', nilai: (l) => LOAN_STATUS_CONFIG[rowStatus(l)]?.label || l.status },
          { label: 'Hari terlambat', nilai: (l) => (l.is_overdue ? l.days_overdue : 0) },
        ]} />
      <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
        data-testid="asset-loan-refresh">
        <RefreshCw className={loading ? 'animate-spin' : ''} />
      </Button>
    </div>
  );

  return (
    <PageLayout testId="asset-loans-tab" title="Peminjaman"
      subtitle="Alat/aset ber-nomor yang dibawa keluar dan harus dikembalikan."
      actions={<Button onClick={() => setShowCreate(true)} data-testid="asset-loan-new-btn"><Plus />Pinjamkan aset</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari no. pinjam, aset, peminjam" value={search}
            onChange={e => setSearch(e.target.value)} data-testid="asset-loan-search" />
        </div>
        <SmartNativeSelect value={status} onChange={e => setStatus(e.target.value)}
          className="w-44" searchable={false} aria-label="Status peminjaman" data-testid="asset-loan-status-filter">
          <option value="active">Sedang dipinjam</option>
          <option value="returned">Sudah kembali</option>
          <option value="all">Semua</option>
        </SmartNativeSelect>
        {hp && alat}
      </>}
      tools={hp ? null : alat}
      summary={adaAngka ? (
        <div className="space-y-2">
          <BarisKartu testId="asset-loan-kpi">
            <KPICard label="Sedang dipinjam" value={summary.active_loans ?? '—'} testId="asset-loan-kpi-active"
              sub={summary.active_loans ? `Terlama ${summary.longest_out_days || 0} hari` : 'Tidak ada pinjaman aktif'}
              hint="Peminjaman yang belum dikembalikan." />
            <KPICard label="Terlambat" value={summary.overdue_loans ?? '—'} testId="asset-loan-kpi-overdue"
              accent={summary.overdue_loans ? 'danger' : 'default'}
              sub="Melewati target kembali" hint="Peminjaman aktif yang target kembalinya sudah lewat hari ini." />
            <KPICard label="Kembali bulan ini" value={summary.returned_this_month ?? '—'} testId="asset-loan-kpi-returned"
              sub="Sudah dikembalikan" hint="Peminjaman yang tanggal kembalinya di bulan berjalan." />
            <KPICard label="Aset siap dipinjam" value={summary.available_assets ?? '—'} testId="asset-loan-kpi-available"
              sub="Berstatus aktif" hint="Aset berstatus Aktif (tidak dipinjam, tidak dalam pemeliharaan, tidak dilepas)." />
          </BarisKartu>
          {summary.by_divisi?.length > 0 && (
            <p className="text-sm text-muted-foreground" data-testid="asset-loan-per-divisi">
              Dipinjam per divisi: {summary.by_divisi.map((d) => `${d.divisi} ${d.count}`).join(' · ')}
            </p>
          )}
        </div>
      ) : null}
      footer={!loading && filtered.length > 0 ? (
        <p className="text-xs text-muted-foreground">Menampilkan {filtered.length} peminjaman</p>
      ) : null}>
      {err && <Notice tone="danger" title="Data peminjaman gagal dimuat">{err}</Notice>}

      {loading && loans.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat peminjaman…</p>
      ) : (
        <TabelData baris={filtered} testId="asset-loans-table"
          kosong={<EmptyState title={loans.length ? 'Tidak ada peminjaman yang cocok' : 'Belum ada peminjaman'}
            description={loans.length ? 'Ubah kata pencarian atau status.'
              : 'Catat alat/aset yang dibawa keluar lewat tombol "Pinjamkan aset" agar keberadaannya terlacak dan bisa ditagih saat jatuh tempo. Satu pinjaman = satu unit aset ber-nomor; aksesoris memakai jalur permintaan & pengeluaran barang.'} />}
          kolom={[
            { kunci: 'no', label: 'No. pinjam', hp: 'keterangan', isi: (l) => <span className="tabular-nums text-muted-foreground">{l.loan_number}</span> },
            { kunci: 'aset', label: 'Aset', hp: 'judul', isi: (l) => (
              <div className="min-w-0">
                <p className="font-medium">{l.asset_name}</p>
                <p className="text-xs tabular-nums text-muted-foreground">{l.asset_number}</p>
              </div>) },
            { kunci: 'peminjam', label: 'Peminjam', isi: (l) => (
              <span>{l.borrower_name}{l.borrower_divisi && <span className="block text-xs text-muted-foreground">{l.borrower_divisi}</span>}</span>) },
            { kunci: 'tujuan', label: 'Tujuan', isi: (l) => <span className="line-clamp-2 md:max-w-[14rem]">{l.purpose || '—'}</span> },
            { kunci: 'tgl', label: 'Tanggal pinjam', isi: (l) => fmtDate(l.loan_date) },
            { kunci: 'target', label: 'Target kembali', isi: (l) => (
              <span>
                {l.expected_return_date ? fmtDate(l.expected_return_date) : <span className="text-muted-foreground">Tidak ditentukan</span>}
                {l.status === 'returned' && l.return_date && (
                  <span className="block text-xs text-muted-foreground">
                    Kembali {fmtDate(l.return_date)}
                    {l.condition_in ? ` · ${RETURN_CONDITION_LABEL[l.condition_in] || l.condition_in}` : ''}
                  </span>
                )}
              </span>) },
            { kunci: 'status', label: 'Status', isi: (l) => (
              <span className="inline-flex flex-col items-start gap-0.5">
                <StatusBadge status={rowStatus(l)} configMap={LOAN_STATUS_CONFIG} />
                {l.is_overdue && <span className="text-xs text-[hsl(var(--danger-text))]">{l.days_overdue} hari</span>}
              </span>) },
            { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (l) => (l.status === 'active' ? (
              <Button size="sm" variant="outline" onClick={() => setReturnLoan(l)} data-testid={`asset-loan-return-${l.id}`}>
                Kembalikan
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">{l.returned_by_name ? `Diterima ${l.returned_by_name}` : '—'}</span>
            )) },
          ]} />
      )}

      <CreateLoanDialog open={showCreate} onClose={() => setShowCreate(false)} token={token}
        onCreated={() => { load(); }} />
      <ReturnLoanDialog open={!!returnLoan} onClose={() => setReturnLoan(null)} token={token}
        loan={returnLoan}
        onReturned={(d) => {
          load();
          if (d?.maintenance_created) {
            toast.info('Catatan pemeliharaan otomatis dibuat karena aset kembali dalam kondisi rusak.');
          }
        }} />
    </PageLayout>
  );
}
