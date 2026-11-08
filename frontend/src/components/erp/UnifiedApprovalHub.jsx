/**
 * Pusat Persetujuan — ringkasan semua persetujuan yang menunggu (Phase 3.3B):
 *  - Kotak masuk SDM (cuti, lembur, gaji, resignasi, absensi, koreksi absen, perubahan data karyawan)
 *  - Persetujuan bertingkat (multi-level)
 *  - Tugas marketing yang menunggu persetujuan
 *  - Permintaan ubah faktur (keuangan)
 * Pengguna melihat jumlah menunggu di satu tempat, membuka kotak masuk masing-masing, dan melihat permintaan terbaru.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, kartu angka StatTile yang bisa diklik (dulu kartu berwarna
 * beranimasi + kotak total bergradasi + kotak info), daftar terbaru = tabel yang bisa diunduh, tanpa emoji/warna mentah.
 * Angka diperiksa (lihat LAPORAN): `GET /api/approvals/pending` menjawab `{data, total}` (bukan daftar) sehingga
 * hitungan bertingkat dulu SELALU 0 → kini dari `total`/`data`; permintaan ubah faktur dulu diminta `limit=1` lalu
 * dihitung panjang daftarnya (paling banyak 1) → kini batas 500.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { ArrowRight, CheckCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { GlassCard } from '@/components/ui/glass';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

const SUMBER = {
  hr: { label: 'Persetujuan SDM', keterangan: 'Cuti, lembur, gaji, resignasi, absensi', modul: 'hr-inbox', slug: 'hr-approval' },
  multilevel: { label: 'Persetujuan bertingkat', keterangan: 'Alur bertingkat lintas departemen', modul: 'approval-multilevel', slug: 'multi-level-approval' },
  marketing: { label: 'Tugas marketing', keterangan: 'Tugas staf marketing yang menunggu', modul: 'marketing-approvals', slug: 'marketing-task' },
  finance: { label: 'Ubah faktur', keterangan: 'Permintaan ubah faktur (keuangan)', modul: 'fin-approval', slug: 'finance-invoice' },
};
const tgl = (v) => (v ? new Date(v).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }) : '—');
const daftarDari = (v) => (Array.isArray(v) ? v : (Array.isArray(v?.data) ? v.data : (Array.isArray(v?.items) ? v.items : [])));

export default function UnifiedApprovalHub({ token, onNavigate }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const [loading, setLoading] = useState(true);
  const [counts, setCounts] = useState({ hr: 0, multilevel: 0, marketing: 0, finance: 0 });
  const [recentItems, setRecentItems] = useState([]);

  const fetchCounts = useCallback(async () => {
    setLoading(true);
    try {
      const [hrRes, multilevelRes, marketingRes, financeRes] = await Promise.allSettled([
        fetch(`${API}/api/hr/inbox`, { headers }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${API}/api/approvals/pending`, { headers }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${API}/api/marketing/tasks?status=pending_approval&limit=1`, { headers }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${API}/api/invoice-edit-requests?status=Pending&limit=500`, { headers }).then((r) => (r.ok ? r.json() : null)),
      ]);
      const ok = (r) => (r.status === 'fulfilled' ? r.value : null);
      const hr = ok(hrRes);
      const ml = ok(multilevelRes);
      const mk = ok(marketingRes);
      const fn = ok(financeRes);
      const mlList = daftarDari(ml);
      const fnList = daftarDari(fn);

      setCounts({
        // semua jenis di Kotak Masuk SDM (termasuk koreksi absen & perubahan data karyawan, 2026-11-07)
        hr: hr ? (Number(hr.total) || Object.values(hr.counts || {}).reduce((a, n) => a + (Number(n) || 0), 0)) : 0,
        multilevel: ml ? (Number(ml.total) || mlList.length) : 0,
        marketing: mk ? (mk.pagination?.total || mk.tasks?.length || 0) : 0,
        finance: fnList.length,
      });

      const recent = [];
      (hr?.items || []).slice(0, 2).forEach((item) => recent.push({
        id: `hr-${item.id}`, source: 'hr', title: item.title || item.type, requester: item.requester_name, date: item.submitted_at,
      }));
      mlList.slice(0, 2).forEach((item) => recent.push({
        id: `ml-${item.id}`, source: 'multilevel', title: item.subject || item.ref_code, requester: item.requester_name, date: item.created_at,
      }));
      (mk?.tasks || []).slice(0, 2).forEach((item) => recent.push({
        id: `mk-${item.id}`, source: 'marketing', title: item.title, requester: item.assigned_to?.slice(0, 20) || 'Staf', date: item.due_date,
      }));
      fnList.slice(0, 2).forEach((item) => recent.push({
        id: `fn-${item.id}`, source: 'finance', title: `Faktur ${item.invoice_number}`, requester: item.requested_by_name, date: item.requested_at,
      }));
      setRecentItems(recent.slice(0, 6));
    } catch (error) {
      toast.error('Gagal memuat data persetujuan');
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchCounts(); }, [fetchCounts]);

  const totalPending = counts.hr + counts.multilevel + counts.marketing + counts.finance;
  const buka = (modul) => () => onNavigate && onNavigate(modul);

  return (
    <PageLayout
      testId="unified-approval-hub"
      title="Pusat persetujuan"
      subtitle="Persetujuan yang menunggu dari SDM, alur bertingkat, marketing, dan keuangan."
      tools={(
        <Button variant="outline" size="icon" onClick={fetchCounts} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="refresh-hub">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={(
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground" data-testid="total-pending-count">
            {loading ? 'Memuat…' : totalPending === 0
              ? 'Tidak ada permintaan yang menunggu persetujuan.'
              : `${totalPending.toLocaleString('id-ID')} permintaan menunggu persetujuan${totalPending > 10 ? ' — perlu perhatian' : ''}.`}
          </p>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-konten-utama="">
            {Object.entries(SUMBER).map(([k, s]) => (
              <StatTile key={k} testId={`approval-hub-${s.slug}`} label={s.label} value={loading ? '…' : counts[k].toLocaleString('id-ID')}
                accent={counts[k] > 5 ? 'warning' : 'default'}
                sub={counts[k] > 5 ? `Mendesak · ${s.keterangan}` : s.keterangan}
                onClick={buka(s.modul)} hint="Buka kotak masuk" />
            ))}
          </div>
        </div>
      )}
    >
      {recentItems.length > 0 ? (
        <GlassCard className="space-y-3 p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-base font-semibold text-foreground">Permintaan terbaru</p>
              <p className="text-sm text-muted-foreground">Contoh terbaru dari tiap kotak masuk (maks. 2 per jenis).</p>
            </div>
            <TombolUnduh namaBerkas="persetujuan-terbaru" namaLembar="Persetujuan terbaru" baris={recentItems} testId="approval-hub-unduh"
              kolom={[
                { label: 'Jenis', nilai: (r) => SUMBER[r.source]?.label || '' },
                { label: 'Permintaan', nilai: (r) => r.title || '' },
                { label: 'Pengaju', nilai: (r) => r.requester || '' },
                { label: 'Tanggal', nilai: (r) => tgl(r.date) },
              ]} />
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Permintaan</TableHead>
                <TableHead className="hidden sm:table-cell">Jenis</TableHead>
                <TableHead className="hidden md:table-cell">Pengaju</TableHead>
                <TableHead className="hidden sm:table-cell">Tanggal</TableHead>
                <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentItems.map((item) => (
                <TableRow key={item.id} className="cursor-pointer" onClick={buka(SUMBER[item.source]?.modul)} data-testid={`recent-item-${item.id}`}>
                  <TableCell className="font-medium">{item.title || '—'}
                    <span className="block text-xs text-muted-foreground sm:hidden">{SUMBER[item.source]?.label} · {tgl(item.date)}</span></TableCell>
                  <TableCell className="hidden sm:table-cell">{SUMBER[item.source]?.label}</TableCell>
                  <TableCell className="hidden md:table-cell">{item.requester || '—'}</TableCell>
                  <TableCell className="hidden whitespace-nowrap sm:table-cell">{tgl(item.date)}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="link" size="sm" onClick={(e) => { e.stopPropagation(); buka(SUMBER[item.source]?.modul)(); }}>
                      Buka<ArrowRight />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </GlassCard>
      ) : !loading && totalPending === 0 ? (
        <EmptyState icon={CheckCircle} title="Semua persetujuan sudah diproses"
          description="Tidak ada permintaan yang menunggu saat ini." />
      ) : null}
    </PageLayout>
  );
}
