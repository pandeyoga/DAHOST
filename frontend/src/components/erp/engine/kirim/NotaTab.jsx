/**
 * Kirim ke CMT › tab "Nota aksesoris" (Portal Produksi = Portal Maklon). Owner 11 Nov 2026: "invoice juga bisa
 * diterbitkan untuk setiap transaksi" → satu nota per penyerahan (Kirim ke CMT, kiriman tambahan/pengganti, serah
 * permintaan vendor di Portal Aksesoris) + REKAP gabungan per CMT per periode (PDF).
 * Nota dari CV Dewi Aditya untuk semua PO, jadi daftar ini tidak disaring per portal.
 * Server: `GET /kirim-cmt/nota-aksesoris`, `/kirim-cmt/nota-aksesoris-rekap/pdf`.
 */
import { useCallback, useEffect, useState } from 'react';
import { Download, FileText, Receipt, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateID } from '@/lib/format';
import PageLayout from '../../layout/PageLayout';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from '../../finance/PeriodPicker';
import { EmptyState, Notice, StatusBadge } from '../../moduleAtoms';
import { apiFetch, apiGet } from '../../../../lib/api';
import { fmtRp } from './kirimShared';
import { ringkasBayar, unduhNotaPdf } from './NotaAksesorisKiriman';

const NADA = { issued: 'warning', overdue: 'warning', partial_paid: 'warning', paid: 'success', cancelled: 'muted' };
const TERBUKA = ['issued', 'overdue', 'partial_paid'];

/** Unduh PDF rekap gabungan nota satu CMT per periode (dipakai juga Portal Vendor). */
export async function unduhRekapPdf({ vendorId = '', from = '', to = '' }) {
  const qs = new URLSearchParams({ vendor_id: vendorId, dari: from || '', sampai: to || '' });
  try {
    const res = await apiFetch(`/kirim-cmt/nota-aksesoris-rekap/pdf?${qs}`);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const e = await res.json(); msg = typeof e?.detail === 'string' ? e.detail : msg; } catch { /* bawaan */ }
      toast.error(`Gagal mencetak rekap: ${msg}`);
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url; a.download = `Rekap-Nota-Aksesoris_${from || 'awal'}_${to || 'kini'}.pdf`; a.style.display = 'none';
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 4000);
  } catch (e) { toast.error(e.message || 'Gagal mencetak rekap'); }
}

export default function NotaTab() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [vendors, setVendors] = useState([]);
  const [vendorId, setVendorId] = useState('');
  const [period, setPeriod] = useState(() => periodFromPreset('month'));
  const [status, setStatus] = useState('');

  useEffect(() => {
    apiGet('/garments').then((d) => setVendors((Array.isArray(d) ? d : d?.items || []).filter((v) => v.status === 'active')))
      .catch(() => setVendors([]));
  }, []);
  const load = useCallback(async () => {
    setError('');
    const qs = new URLSearchParams({ status: 'aktif' });
    if (vendorId) qs.set('vendor_id', vendorId);
    if (period?.from) qs.set('dari', period.from);
    if (period?.to) qs.set('sampai', period.to);
    try { const d = await apiGet(`/kirim-cmt/nota-aksesoris?${qs}`); setRows(Array.isArray(d) ? d : []); }
    catch (e) { setError(e.message || 'Nota gagal dimuat'); setRows([]); }
  }, [vendorId, period]);
  useEffect(() => { load(); }, [load]);

  const all = rows || [];
  const shown = all.filter((r) => (status === 'terbuka' ? TERBUKA.includes(r.status) : status === 'lunas' ? r.status === 'paid' : true));
  const sum = (k) => shown.reduce((t, r) => t + (Number(r[k]) || 0), 0);
  const vendorName = (vendors.find((v) => v.id === vendorId) || {}).garment_name || '';

  return (
    <PageLayout testId="kirim-nota-tab"
      filters={<>
        <SmartNativeSelect value={vendorId} onChange={(e) => setVendorId(e.target.value)} aria-label="Vendor CMT"
          className="h-9 w-56" data-testid="kirim-nota-vendor">
          <option value="">Semua vendor CMT</option>
          {vendors.map((v) => <option key={v.id} value={v.id}>{v.garment_name}{v.garment_code ? ` (${v.garment_code})` : ''}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={period} onChange={setPeriod} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="kirim-nota-periode" />
        <FilterChips value={status} onChange={setStatus} ariaLabel="Status nota" testId="kirim-nota-status" hideWhenEmpty={false}
          options={[{ key: '', label: 'Semua', count: all.length },
            { key: 'terbuka', label: 'Belum lunas', count: all.filter((r) => TERBUKA.includes(r.status)).length },
            { key: 'lunas', label: 'Lunas', count: all.filter((r) => r.status === 'paid').length }]} />
      </>}
      tools={<>
        <Button type="button" variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" onClick={load}>
          <RefreshCw className="w-4 h-4" /></Button>
        <TombolUnduh namaBerkas="nota-aksesoris-cmt" baris={shown} kolom={[
          { label: 'No. nota', nilai: (r) => r.invoice_number }, { label: 'Tanggal', nilai: (r) => formatDateID(r.issue_date) },
          { label: 'Vendor CMT', nilai: (r) => r.vendor_name }, { label: 'Sumber', nilai: (r) => r.sumber_label },
          { label: 'PO', nilai: (r) => r.po_number || '' }, { label: 'Total', nilai: (r) => Number(r.total) || 0 },
          { label: 'Dipotong tagihan', nilai: (r) => Number(r.jumlah_dipotong) || 0 },
          { label: 'Dibayar langsung', nilai: (r) => Number(r.dibayar_langsung) || 0 },
          { label: 'Sisa', nilai: (r) => Number(r.balance) || 0 }, { label: 'Status', nilai: (r) => r.status_label }]} />
        <Button type="button" variant="outline" disabled={!vendorId} onClick={() => unduhRekapPdf({ vendorId, ...period })}
          title={vendorId ? `Rekap gabungan nota ${vendorName} untuk periode ini` : 'Pilih vendor CMT dulu'}
          data-testid="kirim-nota-rekap"><FileText className="w-4 h-4" />Cetak rekap</Button>
      </>}
      summary={rows && (
        <p className="text-sm" data-testid="kirim-nota-ringkasan">
          {shown.length} nota · total <b className="tabular-nums">{fmtRp(sum('total'))}</b> · dipotong tagihan jahit {fmtRp(sum('jumlah_dipotong'))}
          {' '}· dibayar langsung {fmtRp(sum('dibayar_langsung'))} · sisa <b className="tabular-nums">{fmtRp(sum('balance'))}</b>
          {!vendorId && <span className="text-muted-foreground"> — pilih vendor CMT untuk mencetak rekap gabungannya.</span>}
        </p>
      )}>
      {error && <Notice tone="danger" icon={Receipt}>{error}</Notice>}
      <div className="overflow-x-auto">
        <Table data-testid="kirim-nota-tabel">
          <TableHeader><TableRow>
            <TableHead>No. nota</TableHead><TableHead>Tanggal</TableHead><TableHead>Vendor CMT</TableHead>
            <TableHead>Sumber / PO</TableHead><TableHead className="text-right">Total</TableHead>
            <TableHead>Pembayaran</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Cetak</TableHead>
          </TableRow></TableHeader>
          <TableBody>
            {rows === null && <TableRow><TableCell colSpan={8} className="text-sm text-muted-foreground">Memuat…</TableCell></TableRow>}
            {rows !== null && !shown.length && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={8} className="p-0 [&>div]:py-6">
                  <EmptyState icon={Receipt} title="Belum ada nota aksesoris pada periode ini"
                    description="Nota terbit setiap aksesoris diserahkan ke CMT luar (Kirim ke CMT, kiriman tambahan, atau serah di Portal Aksesoris)." />
                </TableCell>
              </TableRow>
            )}
            {shown.map((r) => (
              <TableRow key={r.id} data-testid={`kirim-nota-row-${r.invoice_number}`}>
                <TableCell className="font-medium whitespace-nowrap">{r.invoice_number}</TableCell>
                <TableCell className="text-sm whitespace-nowrap">{formatDateID(r.issue_date)}</TableCell>
                <TableCell className="text-sm">{r.vendor_name}</TableCell>
                <TableCell className="text-sm">{r.sumber_label}
                  <span className="block text-xs text-muted-foreground">{r.po_number ? `PO ${r.po_number}` : ''}</span></TableCell>
                <TableCell className="text-right tabular-nums">{fmtRp(r.total)}</TableCell>
                <TableCell className="text-sm">{r.cara_bayar_label}
                  <span className="block text-xs text-muted-foreground">{ringkasBayar(r)}</span></TableCell>
                <TableCell><StatusBadge status={r.status} label={r.status_label} tone={NADA[r.status] || 'default'} /></TableCell>
                <TableCell className="text-right">
                  <Button type="button" variant="outline" size="icon" title="Cetak nota" aria-label={`Cetak nota ${r.invoice_number}`}
                    onClick={() => unduhNotaPdf(r)}><Download className="w-4 h-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </PageLayout>
  );
}
