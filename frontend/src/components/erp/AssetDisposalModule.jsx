import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, PackageMinus, Trash2 } from 'lucide-react';
import FilterChips from '@/components/ui/filter-chips';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { StatTile, EmptyState } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import Modal from './Modal';
import { useToast } from '@/hooks/use-toast';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { formatRupiah, formatDateID } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import { todayWIB, thisMonthWIB, toWIBDate } from '@/lib/waktu';

const fmt = formatRupiah;
const PAGE_SIZE = 25;
const catLabel = (c) => (c === 'it' ? 'IT' : c ? c.charAt(0).toUpperCase() + c.slice(1).replace(/-/g, ' ') : '—');
const gainClass = (n) => (Number(n) < 0 ? 'text-[hsl(var(--destructive))]' : Number(n) > 0 ? 'text-[hsl(var(--success))]' : 'text-muted-foreground');

/**
 * Pelepasan aset (menu Aset Tetap › Pelepasan).
 * 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout — pil "Aset aktif / Riwayat pelepasan" di toolbar kiri,
 * tombol baris berbentuk garis (dulu merah penuh di tiap baris), formulir di dialog aplikasi.
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
      tools={
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchAssets} data-testid="disposal-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      }
      summary={(activeAssets.length > 0 || disposedAssets.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <StatTile label="Aset aktif" value={activeAssets.length} />
          <StatTile label="Dilepas bulan ini" value={disposedAssets.filter(a => (
            toWIBDate(a.disposal_date).slice(0, 7) === thisMonthWIB()
          )).length} />
          <StatTile
            label="Rata-rata laba/rugi pelepasan"
            value={disposedAssets.length > 0 ? fmt(disposedAssets.reduce((s, a) => s + (a.disposal_gain_loss || 0), 0) / disposedAssets.length) : 'Rp 0'}
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
        <Modal title={`Lepaskan aset ${disposalTarget.name}`} onClose={() => setDisposalTarget(null)} size="md" data-testid="disposal-dialog">
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm rounded-[var(--radius-md)] bg-[hsl(var(--primary)/0.06)] px-3 py-2">
              <dt className="text-muted-foreground">Kode</dt><dd className="text-right">{disposalTarget.code}</dd>
              <dt className="text-muted-foreground">Harga perolehan</dt><dd className="text-right tabular-nums">{fmt(disposalTarget.purchase_cost)}</dd>
              <dt className="text-muted-foreground">Nilai buku saat ini</dt><dd className="text-right tabular-nums font-semibold">{fmt(disposalTarget.book_value_current)}</dd>
            </dl>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Tanggal pelepasan</label>
              <GlassInput
                type="date"
                value={disposalTarget.disposal_date}
                onChange={e => setDisposalTarget(d => ({ ...d, disposal_date: e.target.value }))}
                className="h-9"
                data-testid="disposal-date"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Nilai jual (harga jual atau nilai sisa)</label>
              <MoneyInput
                glass
                value={disposalTarget.disposal_value}
                onChange={e => setDisposalTarget(d => ({ ...d, disposal_value: e.target.value }))}
                data-testid="disposal-value"
              />
              <p className="text-xs text-muted-foreground mt-1">
                Perkiraan laba/rugi: <span className={`tabular-nums ${gainClass(estGain)}`}>{fmt(estGain)}</span>
              </p>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Alasan pelepasan *</label>
              <textarea
                value={disposalTarget.notes}
                onChange={e => setDisposalTarget(d => ({ ...d, notes: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"
                rows={3}
                placeholder="Contoh: dijual karena tidak produktif, rusak berat"
                data-testid="disposal-notes"
              />
            </div>
            <div className="flex gap-2 pt-2 justify-end">
              <Button variant="outline" onClick={() => setDisposalTarget(null)} data-testid="disposal-cancel">
                Batal
              </Button>
              <Button variant="destructive" onClick={dispose} data-testid="disposal-confirm">
                <Trash2 className="w-4 h-4" />
                Lepaskan aset
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </PageLayout>
  );
}
