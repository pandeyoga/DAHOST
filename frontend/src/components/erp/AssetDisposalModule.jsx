import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, PackageMinus, Trash2 } from 'lucide-react';
import FilterChips from '@/components/ui/filter-chips';
import { GlassCard } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import { useToast } from '@/hooks/use-toast';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah, formatDateID } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB, thisMonthWIB, toWIBDate } from '@/lib/waktu';

const fmt = formatRupiah;
const PAGE_SIZE = 25;
const catLabel = (c) => (c === 'it' ? 'IT' : c ? c.charAt(0).toUpperCase() + c.slice(1).replace(/-/g, ' ') : '—');
const gainClass = (n) => (Number(n) < 0 ? 'text-[hsl(var(--danger-text))]' : Number(n) > 0 ? 'text-[hsl(var(--success-text))]' : 'text-muted-foreground');

/**
 * Pelepasan aset (menu Aset Tetap › Pelepasan).
 * 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout — pil "Aset aktif / Riwayat pelepasan" di toolbar kiri,
 * tombol baris berbentuk garis (dulu merah penuh di tiap baris), formulir di dialog aplikasi.
 * 2026-11-08 (Standar UI/UX v2): form = FormPopup pendek + DatePicker; daftar bisa diunduh Excel/CSV; rata-rata
 * laba/rugi tanpa riwayat = "—" (dulu "Rp 0").
 */
export default function AssetDisposalModule({ token }) {
  const [activeAssets, setActiveAssets] = useState([]);
  const [disposedAssets, setDisposedAssets] = useState([]);
  const [tab, setTab] = useState('active');
  const [loading, setLoading] = useState(true);
  const [disposalTarget, setDisposalTarget] = useState(null);
  const { toast } = useToast();
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    try {
      const [activeR, disposedR] = await Promise.all([
        fetch('/api/rahaza/finance/fixed-assets?status=active', { headers }),
        fetch('/api/rahaza/finance/fixed-assets?status=disposed', { headers })
      ]);
      if (activeR.ok) setActiveAssets(await activeR.json());
      if (disposedR.ok) setDisposedAssets(await disposedR.json());
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal memuat daftar aset', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { fetchAssets(); }, [fetchAssets]);

  const dispose = async () => {
    if (!disposalTarget) return;
    if (!disposalTarget.notes || disposalTarget.notes.trim().length < 5) {
      toast({ title: 'Gagal', description: 'Alasan pelepasan minimal 5 huruf', variant: 'destructive' });
      return;
    }
    try {
      const r = await fetch(`/api/rahaza/finance/fixed-assets/${disposalTarget.id}/dispose`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          disposal_date: disposalTarget.disposal_date || todayWIB(),
          disposal_value: Number(disposalTarget.disposal_value) || 0,
          notes: disposalTarget.notes
        })
      });
      if (r.ok) {
        const result = await r.json();
        toast({
          title: 'Berhasil',
          description: `Aset ${disposalTarget.name} dilepas. Laba/rugi pelepasan: ${fmt(result.gain_loss)}`
        });
        setDisposalTarget(null);
        fetchAssets();
      } else {
        const err = await r.json();
        toast({ title: 'Gagal', description: err.detail || 'Gagal melepas aset', variant: 'destructive' });
      }
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal melepas aset', variant: 'destructive' });
    }
  };

  const assets = tab === 'active' ? activeAssets : disposedAssets;
  const estGain = disposalTarget ? Number(disposalTarget.disposal_value) - disposalTarget.book_value_current : 0;

  const { page, setPage, totalPages, total, paged } = useClientPagination(assets, PAGE_SIZE);
  return (
    <PageLayout
      testId="asset-disposal-page"
      title="Pelepasan aset"
      subtitle="Jual atau hapus aset tetap; jurnal laba/rugi pelepasan dicatat otomatis."
      filters={
        <FilterChips value={tab} onChange={setTab} testId="disposal-tab" ariaLabel="Tampilan" hideWhenEmpty={false}
          options={[{ key: 'active', label: 'Aset aktif', count: activeAssets.length }, { key: 'disposed', label: 'Riwayat pelepasan', count: disposedAssets.length }]} />
      }
      tools={<>
        <TombolUnduh namaBerkas={tab === 'active' ? 'aset-aktif' : 'riwayat-pelepasan-aset'} namaLembar={tab === 'active' ? 'Aset aktif' : 'Pelepasan'} baris={assets} testId="disposal-unduh"
          kolom={tab === 'active' ? [
            { label: 'Kode', nilai: (a) => a.code },
            { label: 'Nama aset', nilai: (a) => a.name },
            { label: 'Kategori', nilai: (a) => catLabel(a.category) },
            { label: 'Harga perolehan', nilai: (a) => Number(a.purchase_cost) || 0 },
            { label: 'Nilai buku', nilai: (a) => Number(a.book_value_current) || 0 },
          ] : [
            { label: 'Kode', nilai: (a) => a.code },
            { label: 'Nama aset', nilai: (a) => a.name },
            { label: 'Kategori', nilai: (a) => catLabel(a.category) },
            { label: 'Tanggal pelepasan', nilai: (a) => formatDateID(a.disposal_date) },
            { label: 'Nilai buku saat dilepas', nilai: (a) => Number(a.nbv_at_disposal) || 0 },
            { label: 'Nilai jual', nilai: (a) => Number(a.disposal_value) || 0 },
            { label: 'Laba/rugi', nilai: (a) => Number(a.disposal_gain_loss) || 0 },
            { label: 'Alasan', nilai: (a) => a.disposal_notes || a.notes || '' },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchAssets} data-testid="disposal-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </>}
      summary={(activeAssets.length > 0 || disposedAssets.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <StatTile label="Aset aktif" value={activeAssets.length} sub="Bisa dilepas" />
          <StatTile label="Dilepas bulan ini" value={disposedAssets.filter(a => (
            toWIBDate(a.disposal_date).slice(0, 7) === thisMonthWIB()
          )).length} sub="Menurut tanggal pelepasan" />
          <StatTile
            label="Rata-rata laba/rugi pelepasan"
            value={disposedAssets.length > 0 ? fmt(disposedAssets.reduce((s, a) => s + (a.disposal_gain_loss || 0), 0) / disposedAssets.length) : '—'}
            sub={disposedAssets.length > 0 ? `Dari ${disposedAssets.length} pelepasan` : 'Belum ada pelepasan'}
          />
        </div>
      )}
      footer={!loading && assets.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : assets.length === 0 ? (
          tab === 'active'
            ? <EmptyState icon={PackageMinus} title="Tidak ada aset aktif" description="Aset yang didaftarkan di Daftar aset muncul di sini dan bisa dilepas." />
            : <EmptyState icon={PackageMinus} title="Belum ada riwayat pelepasan" description="Aset yang dijual atau dihapus tercatat di sini." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="disposal-table">
              <thead>
                <tr>
                  <th className="text-left">Kode</th>
                  <th className="text-left">Nama aset</th>
                  <th className="text-left">Kategori</th>
                  {tab === 'active' ? (
                    <>
                      <th className="text-right">Harga perolehan</th>
                      <th className="text-right">Nilai buku</th>
                      <th className="text-right">Aksi</th>
                    </>
                  ) : (
                    <>
                      <th className="text-left">Tanggal pelepasan</th>
                      <th className="text-right">Nilai buku saat dilepas</th>
                      <th className="text-right">Nilai jual</th>
                      <th className="text-right">Laba/rugi</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {paged.map(a => (
                  <tr key={a.id} data-testid={`disposal-row-${a.id}`}>
                    <td className="whitespace-nowrap">{a.code}</td>
                    <td>{a.name}</td>
                    <td>{catLabel(a.category)}</td>
                    {tab === 'active' ? (
                      <>
                        <td className="text-right tabular-nums">{fmt(a.purchase_cost)}</td>
                        <td className="text-right tabular-nums">{fmt(a.book_value_current)}</td>
                        <td className="text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setDisposalTarget({ ...a, disposal_date: todayWIB(), disposal_value: 0, notes: '' })}
                            data-testid={`disposal-btn-${a.id}`}
                          >
                            <Trash2 className="w-4 h-4" />
                            Lepaskan
                          </Button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="whitespace-nowrap">{formatDateID(a.disposal_date)}</td>
                        <td className="text-right tabular-nums">{fmt(a.nbv_at_disposal)}</td>
                        <td className="text-right tabular-nums">{fmt(a.disposal_value)}</td>
                        <td className={`text-right tabular-nums ${gainClass(a.disposal_gain_loss)}`}>
                          {a.disposal_gain_loss > 0 ? '+' : ''}{fmt(a.disposal_gain_loss)}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      {disposalTarget && (
        <FormPopup open onClose={() => setDisposalTarget(null)} ukuran="pendek" testId="disposal-dialog"
          judul={`Lepaskan aset ${disposalTarget.name}`} keterangan="Jurnal laba/rugi pelepasan dicatat otomatis."
          onSimpan={dispose} labelSimpan="Lepaskan aset">
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kode">{disposalTarget.code}</BarisDetail>
            <BarisDetail label="Harga perolehan"><span className="tabular-nums">{fmt(disposalTarget.purchase_cost)}</span></BarisDetail>
            <BarisDetail label="Nilai buku saat ini"><span className="tabular-nums font-semibold">{fmt(disposalTarget.book_value_current)}</span></BarisDetail>
          </dl>
          <Isian label="Tanggal pelepasan">
            <DatePicker value={disposalTarget.disposal_date} onChange={v => setDisposalTarget(d => ({ ...d, disposal_date: v }))} testId="disposal-date" />
          </Isian>
          <Isian label="Nilai jual (harga jual atau nilai sisa)">
            <MoneyInput glass value={disposalTarget.disposal_value}
              onChange={e => setDisposalTarget(d => ({ ...d, disposal_value: e.target.value }))} data-testid="disposal-value" />
            <p className="text-xs text-muted-foreground">
              Perkiraan laba/rugi: <span className={`tabular-nums ${gainClass(estGain)}`}>{fmt(estGain)}</span>
            </p>
          </Isian>
          <Isian label="Alasan pelepasan" wajib petunjuk="Minimal 5 huruf." htmlFor="disposal-notes">
            <Textarea id="disposal-notes" value={disposalTarget.notes} rows={3}
              onChange={e => setDisposalTarget(d => ({ ...d, notes: e.target.value }))}
              placeholder="Contoh: dijual karena tidak produktif, rusak berat" data-testid="disposal-notes" />
          </Isian>
        </FormPopup>
      )}
    </PageLayout>
  );
}
