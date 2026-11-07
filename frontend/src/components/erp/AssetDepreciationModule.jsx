import { useState, useEffect, useCallback } from 'react';
import { Play, RefreshCw, Calculator } from 'lucide-react';
import { monthOptions } from './finance/PeriodPicker';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Checkbox } from '@/components/ui/checkbox';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState, StatusBadge } from './moduleAtoms';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { useToast } from '@/hooks/use-toast';
import { formatRupiah } from '@/lib/format';
import { thisMonthWIB } from '@/lib/waktu';

const fmt = formatRupiah;
const MONTH_OPTIONS = monthOptions(24);
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const periodLabel = (code) => { const [y, m] = String(code || '').split('-'); return BULAN[Number(m) - 1] ? `${BULAN[Number(m) - 1]} ${y}` : (code || '—'); };
const METHOD_LABEL = { straight_line: 'Garis lurus', double_declining: 'Saldo menurun ganda' };
const catLabel = (c) => (c === 'it' ? 'IT' : c ? c.charAt(0).toUpperCase() + c.slice(1).replace(/-/g, ' ') : '—');
const RESULT_STATUS = {
  posted: { label: 'Tercatat', tone: 'success' },
  error: { label: 'Gagal', tone: 'danger' },
  skipped: { label: 'Dilewati', tone: 'warning' },
  already_posted: { label: 'Sudah tercatat', tone: 'muted' },
};

/**
 * Penyusutan aset (menu Aset Tetap › Penyusutan).
 * 2026-11-05 (PANDUAN_UI G1/G13): cetakan PageLayout — bulan di toolbar, tombol utama di kepala/baris tab,
 * hasil penyusutan dibuka di panel di atas tabel (dulu kartu-kartu angka + tabel terpisah di bawah).
 * 2026-11-08 (Standar UI/UX v2): hasil = popup (tabel ui/table + unduh); daftar aset bisa diunduh; kotak centang aplikasi.
 */
export default function AssetDepreciationModule({ token }) {
  const [period, setPeriod] = useState(thisMonthWIB());
  const [assets, setAssets] = useState([]);
  const [selectedAssets, setSelectedAssets] = useState([]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const { toast } = useToast();
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/finance/fixed-assets?status=active', { headers });
      if (r.ok) {
        const data = await r.json();
        setAssets(data.filter(a => a.depreciation_method && !['none', 'manual'].includes(a.depreciation_method)));
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal memuat daftar aset', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { fetchAssets(); }, [fetchAssets]);

  const runBatchDepreciation = async () => {
    if (selectedAssets.length === 0 && !(await confirmDialog({
      title: 'Jalankan penyusutan untuk semua aset aktif?', body: 'Tidak ada aset yang dipilih.', confirmLabel: 'Jalankan',
    }))) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await fetch('/api/rahaza/finance/fixed-assets/run-batch-depreciation', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          period,
          asset_ids: selectedAssets.length > 0 ? selectedAssets : [],
          auto_post: true
        })
      });
      if (r.ok) {
        const data = await r.json();
        setResult({ ...data, period });
        toast({ title: 'Berhasil', description: `Penyusutan selesai: ${data.posted_count} aset dicatat ke jurnal` });
      } else {
        const err = await r.json();
        toast({ title: 'Gagal', description: err.detail || 'Penyusutan gagal', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal menjalankan penyusutan', variant: 'destructive' });
    } finally {
      setRunning(false);
    }
  };

  const toggleAsset = (id) => {
    setSelectedAssets(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const selectAll = () => {
    setSelectedAssets(assets.map(a => a.id));
  };

  const clearSelection = () => {
    setSelectedAssets([]);
  };

  const detail = result && (
    <DetailPanel
      title={`Hasil penyusutan ${periodLabel(result.period || period)}`}
      description={`${result.assets_processed} aset diproses · ${result.posted_count} dicatat ke jurnal · total ${fmt(result.total_depreciation)}`}
      onClose={() => setResult(null)}
      testId="depr-result-panel"
      actions={result.results?.length > 0 && (
        <TombolUnduh namaBerkas={`hasil-penyusutan-${result.period || period}`} namaLembar="Hasil penyusutan" baris={result.results} testId="depr-result-unduh"
          kolom={[
            { label: 'Status', nilai: (r) => (RESULT_STATUS[r.status] || { label: r.status }).label },
            { label: 'Kode aset', nilai: (r) => r.asset_code },
            { label: 'Nama aset', nilai: (r) => r.asset_name },
            { label: 'Penyusutan', nilai: (r) => Number(r.depr_amount) || 0 },
            { label: 'No. jurnal', nilai: (r) => r.je_number || '' },
            { label: 'Keterangan', nilai: (r) => (r.reason && r.reason !== 'OK' ? r.reason : '') },
          ]} />
      )}
    >
      {result.results && result.results.length > 0 && (
        <Table data-testid="depr-result-table">
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Kode aset</TableHead>
              <TableHead>Nama aset</TableHead>
              <TableHead className="text-right">Penyusutan</TableHead>
              <TableHead>No. jurnal</TableHead>
              <TableHead>Keterangan</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.results.map((r, idx) => {
              const st = RESULT_STATUS[r.status] || { label: r.status, tone: 'default' };
              return (
                <TableRow key={idx}>
                  <TableCell><StatusBadge tone={st.tone} label={st.label} /></TableCell>
                  <TableCell className="whitespace-nowrap">{r.asset_code}</TableCell>
                  <TableCell>{r.asset_name}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.depr_amount)}</TableCell>
                  <TableCell className="whitespace-nowrap">{r.je_number || '—'}</TableCell>
                  <TableCell className="text-muted-foreground">{r.reason && r.reason !== 'OK' ? r.reason : '—'}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </DetailPanel>
  );

  return (
    <PageLayout
      testId="asset-depreciation-page"
      title="Penyusutan aset"
      subtitle="Hitung penyusutan satu bulan; jurnalnya dicatat otomatis."
      actions={
        <Button onClick={runBatchDepreciation} disabled={running || loading} data-testid="depr-run-batch">
          <Play className="w-4 h-4" />
          {running ? 'Memproses…' : 'Jalankan penyusutan'}
        </Button>
      }
      filters={
        <SmartNativeSelect value={period} onChange={e => setPeriod(e.target.value)} className="h-9 w-48" aria-label="Periode penyusutan" data-testid="depr-period">
          {MONTH_OPTIONS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </SmartNativeSelect>
      }
      tools={<>
        <TombolUnduh namaBerkas="aset-disusutkan" namaLembar="Aset" baris={assets} testId="depr-unduh"
          kolom={[
            { label: 'Kode', nilai: (a) => a.code },
            { label: 'Nama aset', nilai: (a) => a.name },
            { label: 'Kategori', nilai: (a) => catLabel(a.category) },
            { label: 'Metode', nilai: (a) => METHOD_LABEL[a.depreciation_method] || a.depreciation_method },
            { label: 'Harga perolehan', nilai: (a) => Number(a.purchase_cost) || 0 },
            { label: 'Nilai buku', nilai: (a) => Number(a.book_value_current) || 0 },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchAssets} data-testid="depr-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </>}
      summary={assets.length > 0 && (
        <p className="text-sm text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-foreground">
            {selectedAssets.length === 0 ? 'Semua aset aktif akan diproses' : `${selectedAssets.length} dari ${assets.length} aset dipilih`}
          </span>
          <Button variant="link" size="sm" className="h-auto p-0" onClick={selectAll} data-testid="depr-select-all">Pilih semua</Button>
          <Button variant="link" size="sm" className="h-auto p-0" onClick={clearSelection} data-testid="depr-clear-all">Kosongkan</Button>
        </p>
      )}
      detail={detail}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : assets.length === 0 ? (
          <EmptyState icon={Calculator} title="Tidak ada aset yang perlu disusutkan"
            description="Aset aktif dengan metode garis lurus atau saldo menurun muncul di sini." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="depr-asset-table">
              <thead>
                <tr>
                  <th className="w-10">
                    <Checkbox
                      checked={selectedAssets.length === assets.length}
                      onCheckedChange={v => (v ? selectAll() : clearSelection())}
                      aria-label="Pilih semua aset"
                    />
                  </th>
                  <th className="text-left">Kode</th>
                  <th className="text-left">Nama aset</th>
                  <th className="text-left">Kategori</th>
                  <th className="text-left">Metode</th>
                  <th className="text-right">Harga perolehan</th>
                  <th className="text-right">Nilai buku</th>
                </tr>
              </thead>
              <tbody>
                {assets.map(a => (
                  <tr
                    key={a.id}
                    className={`cursor-pointer ${selectedAssets.includes(a.id) ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}
                    onClick={() => toggleAsset(a.id)}
                    data-testid={`depr-asset-row-${a.id}`}
                  >
                    <td>
                      <Checkbox
                        checked={selectedAssets.includes(a.id)}
                        onCheckedChange={() => toggleAsset(a.id)}
                        onClick={e => e.stopPropagation()}
                        aria-label={`Pilih ${a.name}`}
                      />
                    </td>
                    <td className="whitespace-nowrap">{a.code}</td>
                    <td>{a.name}</td>
                    <td>{catLabel(a.category)}</td>
                    <td className="whitespace-nowrap">{METHOD_LABEL[a.depreciation_method] || a.depreciation_method}</td>
                    <td className="text-right tabular-nums">{fmt(a.purchase_cost)}</td>
                    <td className="text-right tabular-nums">{fmt(a.book_value_current)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </PageLayout>
  );
}
