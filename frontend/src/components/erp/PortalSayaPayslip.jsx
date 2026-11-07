/**
 * Portal Saya › Slip Gaji — slip gaji milik karyawan sendiri.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (dulu judul buatan + pembungkus `p-6 max-w-2xl`), daftar slip = TabelData
 * (kartu ringkas di HP) + unduh Excel/CSV, rincian slip dibuka di popup (dulu panel terbuka di dalam kartu),
 * warna token (dulu hijau/biru/merah mentah). Unduh PDF tetap sama.
 */
import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Download, Eye, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { useToast } from '@/hooks/use-toast';
import { formatDateID, formatRupiah } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const fmt = (n) => formatRupiah(n || 0);
const BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const labelPeriode = (slip) => {
  const ym = String(slip.period_from || '').slice(0, 7);
  const [y, m] = ym.split('-').map(Number);
  return y && m ? `${BULAN[m - 1]} ${y}` : 'Periode tidak diketahui';
};
const rentang = (slip) => `${formatDateID(String(slip.period_from || '').slice(0, 10))} – ${formatDateID(String(slip.period_to || '').slice(0, 10))}`;
// FASE 20 — field lama `base_salary`/`total_deductions` tidak ada di payslip baru (backend menulis `earnings_total`
// & `deductions_total`); fallback nama lama dipertahankan untuk payslip lama di DB produksi.
const pokok = (slip) => slip.earnings_total ?? slip.base_salary;
const potongan = (slip) => slip.deductions_total ?? slip.total_deductions;

/** BUG-3 (2026-07-26): karyawan sama sekali TIDAK punya cara mengunduh slip
 *  gajinya sendiri — endpoint PDF menolak 403 "Hubungi HR" dan layar ini tidak
 *  punya tombol apa pun. Slip gaji adalah dokumen milik karyawan (dipakai untuk
 *  pengajuan kredit dsb), jadi unduhan mandiri kini tersedia. */
function useUnduhPdf(token) {
  const [dl, setDl] = useState('');
  const { toast } = useToast();
  const download = async (slip) => {
    setDl(slip.id);
    try {
      const r = await fetch(`${API}/api/rahaza/payslips/${slip.id}/pdf`, {
        headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) {
        const msg = await r.json().catch(() => ({}));
        throw new Error(msg.detail || `Kode ${r.status}`);
      }
      const blob = await r.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = `slip_gaji_${slip.period_from || ''}_${slip.period_to || ''}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(href);
      toast({ title: 'Slip gaji diunduh', description: 'PDF tersimpan di perangkat Anda.' });
    } catch (err) {
      toast({ title: 'Gagal mengunduh slip', description: String(err.message), variant: 'destructive' });
    } finally { setDl(''); }
  };
  return { dl, download };
}

function RincianSlip({ slip }) {
  const rows = (list, minus = false) => (
    <dl className="divide-y divide-[var(--glass-border)]">
      {list.map((e, i) => (
        <div key={i} className="flex justify-between gap-3 py-1.5 text-sm">
          <dt className="text-muted-foreground">{e.name}</dt>
          <dd className={`tabular-nums ${minus ? 'text-[hsl(var(--danger-text))]' : ''}`}>{minus ? '−' : ''}{fmt(e.amount)}</dd>
        </div>
      ))}
    </dl>
  );
  return (
    <>
      {(slip.days_hadir !== undefined && slip.days_hadir !== null) && (
        <div className="grid grid-cols-3 gap-3">
          <StatTile label="Hari hadir" value={slip.days_hadir ?? '—'} />
          <StatTile label="Total jam" value={slip.total_hours_worked ?? '—'} />
          <StatTile label="Lembur (jam)" value={slip.overtime_hours ?? slip.source_refs?.overtime_hours ?? '—'} />
        </div>
      )}
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Gaji pokok"><span className="tabular-nums">{fmt(pokok(slip))}</span></BarisDetail>
        <BarisDetail label="Total pendapatan"><span className="tabular-nums">{fmt(slip.gross_pay)}</span></BarisDetail>
        <BarisDetail label="Total potongan"><span className="tabular-nums text-[hsl(var(--danger-text))]">−{fmt(potongan(slip))}</span></BarisDetail>
      </dl>
      {slip.earnings?.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium">Pendapatan</p>
          {rows(slip.earnings)}
        </div>
      )}
      {slip.deductions?.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-medium">Potongan</p>
          {rows(slip.deductions, true)}
        </div>
      )}
      <div className="flex justify-between border-t border-[var(--glass-border)] pt-3 text-base font-semibold">
        <span>Gaji bersih (dibawa pulang)</span>
        <span className="tabular-nums">{fmt(slip.net_pay)}</span>
      </div>
    </>
  );
}

export default function PortalSayaPayslip({ user, headers, token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const { dl, download } = useUnduhPdf(token);

  const load = useCallback(async () => {
    try {
      const { data: d } = await axios.get(`${API}/api/portal-saya/me/payslips`, { headers });
      setData(d);
    } catch (e) {
      if (e.response?.status === 409) {
        setData({ error: e.response.data.detail });
      }
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const slips = data?.payslips || data?.items || [];
  const nama = data?.employee_name || data?.employee;

  const kolom = [
    { kunci: 'periode', label: 'Periode', hp: 'judul', isi: (s) => (
      <span className="font-medium" data-testid={`slip-toggle-${s.id}`}>{labelPeriode(s)}</span>) },
    { kunci: 'rentang', label: 'Rentang tanggal', hp: 'keterangan', isi: (s) => <span className="whitespace-nowrap text-sm">{rentang(s)}</span> },
    { kunci: 'bruto', label: 'Pendapatan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmt(s.gross_pay)}</span> },
    { kunci: 'potongan', label: 'Potongan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{fmt(potongan(s))}</span> },
    { kunci: 'bersih', label: 'Gaji bersih', rata: 'kanan', isi: (s) => <span className="font-semibold tabular-nums">{fmt(s.net_pay)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => setDetail(s)}><Eye />Rincian</Button>
        <Button size="sm" variant="outline" onClick={() => download(s)} disabled={dl === s.id} data-testid={`slip-download-${s.id}`}>
          {dl === s.id ? <Loader2 className="animate-spin" /> : <Download />}PDF
        </Button>
      </div>) },
  ];

  return (
    <PageLayout testId="portal-payslip" title="Slip gaji"
      subtitle={nama ? `${nama} — ${slips.length} slip gaji tersedia. Rincian dan PDF bisa dibuka per periode.` : 'Slip gaji Anda per periode, lengkap dengan rincian dan PDF.'}
      tools={slips.length > 0 && (
        <TombolUnduh namaBerkas="slip-gaji-saya" namaLembar="Slip gaji" baris={slips} testId="payslip-unduh" kolom={[
          { label: 'Periode', nilai: (s) => labelPeriode(s) }, { label: 'Dari', nilai: (s) => formatDateID(String(s.period_from || '').slice(0, 10)) },
          { label: 'Sampai', nilai: (s) => formatDateID(String(s.period_to || '').slice(0, 10)) },
          { label: 'Gaji pokok', nilai: (s) => Number(pokok(s)) || 0 }, { label: 'Pendapatan', nilai: (s) => Number(s.gross_pay) || 0 },
          { label: 'Potongan', nilai: (s) => Number(potongan(s)) || 0 }, { label: 'Gaji bersih', nilai: (s) => Number(s.net_pay) || 0 },
        ]} />
      )}>
      {loading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat slip gaji…</p>
      ) : data?.error ? (
        <Notice tone="warning" title="Slip gaji belum bisa ditampilkan">{data.error}</Notice>
      ) : (
        <TabelData kolom={kolom} baris={slips} kunci={(s) => s.id || s.run_id} onKlikBaris={setDetail} testId="payslip-table"
          kosong={<EmptyState title="Belum ada slip gaji" description="Slip muncul di sini setelah gaji periode Anda diproses HR." />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={`Slip gaji ${labelPeriode(detail)}`} keterangan={rentang(detail)}
          testId="payslip-detail"
          aksi={(
            <Button size="sm" variant="outline" onClick={() => download(detail)} disabled={dl === detail.id}>
              {dl === detail.id ? <Loader2 className="animate-spin" /> : <Download />}Unduh PDF
            </Button>
          )}>
          <RincianSlip slip={detail} />
        </DetailPopup>
      )}
    </PageLayout>
  );
}
