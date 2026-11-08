/**
 * StandardRateModule — tab "Tarif standar" di menu HPP (Tahap 9, keputusan owner 7 Nov 2026).
 *
 * Master Proses dihapus; tarif standar per tahap pindah ke sini. Datanya TETAP yang lama (tanpa koleksi baru):
 *   • daftar tahap = master proses produksi (`rahaza_processes`), dibaca lewat GET /api/costing/processes;
 *   • tarif per pcs = setelan costing `process_rates` (PUT /api/costing/settings), dibaca `core/product_costing`
 *     untuk HPP standar per potong bila produk belum punya laporan produksi bertarif.
 * Tahap jahit/CMT tidak diberi tarif di sini — upah CMT diisi per baris di form PO (supaya tidak dihitung dua kali).
 * PANDUAN_UI: PageLayout · tabel · satu tombol utama · tanpa kartu di dalam kartu.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Layers, RefreshCw, Save } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { MoneyInput } from '@/components/ui/money-input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { costingApi } from './costingApi';

const rp = (v) => `Rp ${Math.round(Number(v || 0)).toLocaleString('id-ID')}`;

export default function StandardRateModule({ token }) {
  const [rows, setRows] = useState([]);
  const [saved, setSaved] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await costingApi('GET', '/processes', token);
      const items = (d.items || []).slice().sort((a, b) => (a.is_cmt - b.is_cmt) || String(a.code).localeCompare(String(b.code)));
      setRows(items);
      setSaved(Object.fromEntries(items.map((r) => [r.process_id, Number(r.rate_per_pcs || 0)])));
    } catch (e) {
      toast.error(`Gagal memuat tarif standar: ${e.message}`);
    } finally { setLoading(false); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const setRate = (pid, v) => setRows((prev) => prev.map((r) => (r.process_id === pid ? { ...r, rate_per_pcs: v } : r)));
  const dirty = useMemo(() => rows.some((r) => Number(r.rate_per_pcs || 0) !== Number(saved[r.process_id] || 0)), [rows, saved]);
  const total = useMemo(() => rows.filter((r) => !r.is_cmt && r.active !== false)
    .reduce((s, r) => s + Number(r.rate_per_pcs || 0), 0), [rows]);

  const save = async () => {
    setSaving(true);
    try {
      await costingApi('PUT', '/settings', token, {
        process_rates: rows.filter((r) => !r.is_cmt && Number(r.rate_per_pcs) > 0).map((r) => ({
          process_id: r.process_id, code: r.code, name: r.name, rate_per_pcs: Number(r.rate_per_pcs),
        })),
      });
      toast.success('Tarif standar per tahap disimpan.');
      await load();
    } catch (e) {
      toast.error(`Gagal menyimpan tarif: ${e.message}`);
    } finally { setSaving(false); }
  };

  return (
    <PageLayout
      testId="hpp-standard-rates"
      title="Tarif standar per tahap"
      subtitle="Tarif per pcs tahap internal — dipakai HPP standar per potong bila produk belum punya laporan produksi bertarif."
      actions={<Button type="button" variant="success" onClick={save} disabled={saving || !dirty} data-testid="std-rate-save"><Save className="w-4 h-4" />{saving ? 'Menyimpan…' : 'Simpan tarif'}</Button>}
      tools={<>
        <TombolUnduh namaBerkas="tarif-standar-per-tahap" namaLembar="Tarif" baris={rows} testId="std-rate-unduh" kolom={[
          { label: 'Tahap', nilai: (r) => r.name || r.code }, { label: 'Kode', nilai: (r) => r.code || '' },
          { label: 'Keterangan', nilai: (r) => (r.is_cmt ? 'Upah CMT diisi di form PO' : r.active === false ? 'Nonaktif' : 'Tahap internal') },
          { label: 'Tarif standar per pcs (Rp)', nilai: (r) => (r.is_cmt ? '' : Number(r.rate_per_pcs) || 0) },
        ]} />
        <Button type="button" variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="std-rate-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={!loading && rows.length > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="std-rate-summary">
          Jumlah tarif standar tahap internal: <span className="font-semibold text-foreground tabular-nums">{rp(total)}</span> per pcs.
          {' '}Di HPP standar per potong angka ini tampil sebagai upah internal (informasi) dan tidak masuk HPP.
        </p>
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !rows.length ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
        ) : (
          <Table data-testid="std-rate-table">
            <TableHeader><TableRow>
              <TableHead>Tahap</TableHead><TableHead>Kode</TableHead><TableHead>Keterangan</TableHead>
              <TableHead className="text-right">Tarif standar per pcs</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Layers} title="Belum ada tahap produksi" description="Daftar tahap produksi belum tersedia." />
                  </TableCell>
                </TableRow>
              )}
              {rows.map((r) => (
                <TableRow key={r.process_id} data-testid={`std-rate-row-${r.code}`}>
                  <TableCell className="font-medium">{r.name || r.code}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{r.code}</TableCell>
                  <TableCell>
                    {r.is_cmt
                      ? <StatusBadge tone="warning" label="Upah CMT diisi di form PO" />
                      : r.active === false ? <StatusBadge tone="muted" label="Nonaktif" /> : <StatusBadge tone="info" label="Tahap internal" />}
                  </TableCell>
                  <TableCell className="text-right">
                    {r.is_cmt ? <span className="text-muted-foreground">—</span> : (
                      <MoneyInput glass value={r.rate_per_pcs || ''} onChange={(e) => setRate(r.process_id, e.target.value)}
                        className="h-9 w-36 text-right inline-block" aria-label={`Tarif standar ${r.name || r.code}`}
                        data-testid={`std-rate-${r.code}`} />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayout>
  );
}
