/**
 * HutangCmtTerjadwal — Keuangan › Hutang Pemasok & CMT › "Hutang CMT terjadwal" (11 Nov 2026, owner).
 *
 * Owner bertanya "kenapa tidak ada hutang CMT": tab Tagihan hanya memuat hutang NYATA (tagihan CMT lahir saat
 * barang lolos QC). Upah jahit untuk barang yang MASIH di penjahit tampil di sini, terpisah dan bertanda
 * "belum jatuh tempo" — bukan hutang yang bisa dibayar, tanpa jurnal:
 *   • CV Sukma        → jadwal hutang PO maklon (disimpan sejak PO dikonfirmasi);
 *   • CV Dewi Aditya  → PERKIRAAN PO DA (sisa pcs di penjahit × upah, dihitung saat dibuka);
 *   • Gabungan        → keduanya.
 * Pilihan CV ikut header `X-CV` (lib/entitas) — layar dipasang ulang saat CV berganti.
 * Sumber: GET /api/production/cmt-billing/schedules?perkiraan_internal=1 (tabel bersama Portal Maklon).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from '../layout/PageLayout';
import { Notice } from '../moduleAtoms';
import JadwalHutangCmtTabel, { JENIS_LABEL, fmtRp, sisaJadwal } from '../engine/JadwalHutangCmtTabel';
import { apiGet } from '../../../lib/api';
import { ownerLabel, useCvOr } from '@/lib/entitas';

export default function HutangCmtTerjadwal() {
  const cv = useCvOr();
  const [data, setData] = useState({ items: [], totals: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [jenis, setJenis] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiGet('/production/cmt-billing/schedules?perkiraan_internal=1');
      setData({ items: Array.isArray(res?.items) ? res.items : [], totals: res?.totals || {} });
    } catch (e) {
      setError(e?.message || 'Gagal memuat hutang CMT terjadwal');
      toast.error(`Gagal memuat hutang CMT terjadwal: ${e?.message || e}`);
      setData({ items: [], totals: {} });
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  // hanya yang masih punya sisa belum jatuh tempo; yang sudah seluruhnya lolos QC ada di tab Tagihan
  const terbuka = useMemo(() => data.items.filter((r) => Number(sisaJadwal(r) || 0) > 0), [data.items]);
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return terbuka.filter((r) => (!jenis || r.jenis === jenis)
      && (!s || [r.po_number, r.vendor_name].filter(Boolean).some((v) => String(v).toLowerCase().includes(s))));
  }, [terbuka, search, jenis]);
  const counts = useMemo(() => ({
    jadwal: terbuka.filter((r) => r.jenis === 'jadwal').length,
    perkiraan: terbuka.filter((r) => r.jenis === 'perkiraan').length,
  }), [terbuka]);
  const sisa = (fn) => rows.filter(fn).reduce((t, r) => t + Number(sisaJadwal(r) || 0), 0);
  const total = sisa(() => true);
  const sisaSmu = sisa((r) => r.jenis === 'jadwal');
  const sisaDa = sisa((r) => r.jenis === 'perkiraan');
  const { page, setPage, totalPages, paged, pageSize } = useClientPagination(rows, 25);

  return (
    <PageLayout
      testId="fin-cmt-terjadwal"
      title="Hutang CMT terjadwal"
      subtitle="Upah jahit untuk barang yang masih di penjahit. Belum jatuh tempo; hutang nyata lahir saat barang lolos QC."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari no. PO atau penjahit"
            className="pl-8" data-testid="fin-cmt-terjadwal-search" />
        </div>
        {counts.jadwal > 0 && counts.perkiraan > 0 && (
          <FilterChips value={jenis} onChange={setJenis} testId="fin-cmt-terjadwal-jenis" ariaLabel="Jenis"
            options={[{ key: '', label: 'Semua', count: terbuka.length },
              { key: 'jadwal', label: JENIS_LABEL.jadwal, count: counts.jadwal },
              { key: 'perkiraan', label: JENIS_LABEL.perkiraan, count: counts.perkiraan }]} />
        )}
      </>}
      tools={<>
        <TombolUnduh namaBerkas="hutang-cmt-terjadwal" namaLembar="Hutang CMT terjadwal" baris={rows} testId="fin-cmt-terjadwal-unduh" kolom={[
          { label: 'PO', nilai: (r) => r.po_number || '' }, { label: 'Vendor CMT', nilai: (r) => r.vendor_name || '' },
          { label: 'CV', nilai: (r) => ownerLabel(r.entity) }, { label: 'Jenis', nilai: (r) => JENIS_LABEL[r.jenis] || '' },
          { label: 'Jadwal (pcs)', nilai: (r) => Number(r.scheduled_qty) || 0 }, { label: 'Jadwal (Rp)', nilai: (r) => Number(r.scheduled_amount) || 0 },
          { label: 'Lolos QC (Rp)', nilai: (r) => Number(r.matured_amount) || 0 },
          { label: 'Belum jatuh tempo (Rp)', nilai: (r) => Number(sisaJadwal(r)) || 0 },
        ]} />
        <Button type="button" variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="fin-cmt-terjadwal-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle} title="Gagal memuat data">{error}</Notice>}
        <p className="text-sm text-muted-foreground" data-testid="fin-cmt-terjadwal-ringkasan">
          Belum jatuh tempo <b className="text-foreground tabular-nums">{fmtRp(total)}</b>
          {cv !== 'DA' && <> · PO maklon (CV Sukma) <span className="tabular-nums">{fmtRp(sisaSmu)}</span></>}
          {cv !== 'SMU' && <> · perkiraan PO DA (CV Dewi Aditya) <span className="tabular-nums">{fmtRp(sisaDa)}</span></>}.
          {' '}Bukan hutang yang bisa dibayar dan tanpa jurnal: hutang nyata lahir saat barang lolos QC dan tampil di tab Tagihan.
        </p>
      </>}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={rows.length} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        <JadwalHutangCmtTabel items={paged} loading={loading} keuangan />
      </GlassCard>
    </PageLayout>
  );
}
