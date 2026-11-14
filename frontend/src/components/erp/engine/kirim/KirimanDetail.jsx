/**
 * Rincian satu kiriman ke CMT — DI HALAMAN (DetailPanel). Tahap 9, 7 Nov 2026.
 * Isi = dokumen pengeluaran kiriman itu (`GET /kirim-cmt/shipments/{id}`): angka yang SAMA dengan stok yang
 * berkurang dan surat jalan. "Posting ulang jurnal" pindah ke sini dari menu Pengeluaran Material (dinonaktifkan).
 * 2026-11-11: bagian Nota aksesoris (`NotaAksesorisKiriman`) — lihat/cetak/potong/batal, atau buat nota kiriman lama.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BookOpen, Download, Landmark, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiDelete, apiFetch, apiGet, apiPost } from '../../../../lib/api';
import { DetailPanel } from '../../layout/PageLayout';
import { Notice, StatusBadge } from '../../moduleAtoms';
import FileAttachmentPanel from '../FileAttachmentPanel';
import { AksesorisTable, PotonganTable, SectionLabel, ShipStatusBadge, ShipTypeBadge, fmtDate, fmtNum, fmtRp } from './kirimShared';
import NotaAksesorisKiriman from './NotaAksesorisKiriman';
import { punyaCentang } from '@/lib/rbac';

export async function downloadPdf(type, id, filename, label) {
  try {
    const res = await apiFetch(`/export-pdf?type=${type}&id=${id}`);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const err = await res.json(); msg = typeof err?.detail === 'string' ? err.detail : msg; } catch { /* default */ }
      toast.error(`Gagal mencetak ${label}: ${msg}`);
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.style.display = 'none';
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 4000);
    toast.success(`${label} diunduh`);
  } catch (e) { toast.error(e.message || `Gagal mencetak ${label}`); }
}

export default function KirimanDetail({ id, canDelete, canManage = false, onClose, onOpen, onChanged, onNavigate }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setD(await apiGet(`/kirim-cmt/shipments/${id}`)); }
    catch (e) { toast.error(e.message || 'Rincian kiriman gagal dimuat'); onClose?.(); }
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setD(null); load(); }, [load]);

  if (!d) {
    return <DetailPanel testId="kirim-detail" title="Memuat…" onClose={onClose}><p className="text-sm text-muted-foreground">Memuat…</p></DetailPanel>;
  }
  const s = d.shipment || {};
  const j = d.journal;
  const repost = async () => {
    setBusy(true);
    try {
      const r = await apiPost(`/kirim-cmt/shipments/${s.id}/repost-journal`, {});
      const ok = (r.results || []).filter((x) => x.ok);
      if (r.ok) toast.success(`Jurnal tercatat · ${ok.map((x) => x.je_number).filter(Boolean).join(', ') || 'sudah ada'}`);
      else toast.error(`Jurnal gagal: ${(r.results || []).map((x) => x.error).filter(Boolean).join('; ')}`);
      await load();
    } catch (e) { toast.error(e.message || 'Posting ulang gagal'); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    const ok = await confirmDialog({ title: `Hapus kiriman ${s.shipment_number}?`, danger: true, confirmLabel: 'Hapus kiriman',
      body: 'Kiriman yang bahannya sudah keluar gudang tidak bisa dihapus — kembalikan dulu lewat Retur Material (stok kembali & jurnal dibalik).' });
    if (!ok) return;
    try {
      await apiDelete(`/vendor-shipments/${s.id}`);
      toast.success('Kiriman dihapus');
      onChanged?.(); onClose?.();
    } catch (e) {
      toast.error(e.message || 'Gagal menghapus', /Retur Material/i.test(e.message || '') && onNavigate ? {
        duration: 12000, action: { label: 'Buka Retur Material', onClick: () => onNavigate('prod-material-returns', { vendor_shipment_id: s.id }) },
      } : undefined);
    }
  };
  const pcs = (d.items || []).reduce((t, i) => t + Number(i.qty_sent || 0), 0);

  return (
    <DetailPanel testId="kirim-detail" closeTestId="kirim-detail-close" onClose={onClose}
      title={`${s.shipment_number} · ${s.vendor_name || '—'}`}
      description={`PO ${s.po_number || '—'} · ${fmtDate(s.shipment_date)} · ${fmtNum(pcs)} pcs · nilai keluar gudang ${fmtRp(d.value)}`}
      actions={<>
        <Button type="button" variant="outline" onClick={() => downloadPdf('vendor-shipment', s.id, `SJ-${s.shipment_number}.pdf`, 'Surat jalan')}
          data-testid="kirim-detail-sj"><Download className="w-4 h-4" />Surat jalan</Button>
        <Button type="button" variant="outline" size="icon" title="Panduan produk (PDF)" aria-label="Panduan produk (PDF)"
          onClick={() => downloadPdf('production-guide', s.id, `Panduan-${s.shipment_number}.pdf`, 'Panduan produk')}
          data-testid="kirim-detail-guide"><BookOpen className="w-4 h-4" /></Button>
        <Button type="button" variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" onClick={load}><RefreshCw className="w-4 h-4" /></Button>
        {canDelete && <Button type="button" variant="outline" size="icon" title="Hapus kiriman" aria-label="Hapus kiriman" onClick={remove}
          data-testid="kirim-detail-delete"><Trash2 className="w-4 h-4" /></Button>}
      </>}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <ShipTypeBadge type={s.shipment_type} testId="kirim-detail-type" />
        <ShipStatusBadge status={s.status} testId="kirim-detail-status" />
        <StatusBadge status={s.inspection_status ? 'inspected' : 'pending'} label={s.inspection_status ? 'Sudah diperiksa CMT' : 'Belum diperiksa CMT'}
          tone={s.inspection_status ? 'success' : 'muted'} />
        {d.request?.request_number && <span className="text-muted-foreground">dari permintaan {d.request.request_number}</span>}
        {s.notes && <span className="text-muted-foreground">· {s.notes}</span>}
      </div>
      {d.sample_warning && (
        <Notice tone="warning" icon={AlertTriangle} testId="kirim-detail-sample">{d.sample_warning.message}</Notice>
      )}
      <SectionLabel>Barang dikirim</SectionLabel>
      <Table data-testid="kirim-detail-items">
        <TableHeader><TableRow>
          <TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran / warna</TableHead><TableHead className="text-right">Qty (pcs)</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {(d.items || []).map((i) => (
            <TableRow key={i.id}>
              <TableCell className="whitespace-nowrap">{i.sku || '—'}</TableCell><TableCell>{i.product_name}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{[i.size, i.color].filter(Boolean).join(' / ')}</TableCell>
              <TableCell className="text-right tabular-nums">{fmtNum(i.qty_sent)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <SectionLabel>Potongan</SectionLabel>
      {(d.potongan || []).length ? <PotonganTable rows={d.potongan} testId="kirim-detail-potongan" />
        : <p className="text-xs text-muted-foreground">{s.business_type === 'maklon' ? 'Kain dan potongan disediakan klien.' : 'Tidak ada potongan yang keluar pada kiriman ini.'}</p>}
      <SectionLabel>Aksesoris diserahkan</SectionLabel>
      {(d.aksesoris || []).length ? <AksesorisTable rows={d.aksesoris} mode="detail" testId="kirim-detail-aksesoris" />
        : <p className="text-xs text-muted-foreground">Tidak ada aksesoris dari gudang pada kiriman ini.</p>}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm" data-testid="kirim-detail-journal">
        {j ? (
          <span>
            Dokumen pengeluaran <b className="tabular-nums">{j.mi_number}</b> ·{' '}
            {j.posted ? <span className="text-[hsl(var(--success-text))]">jurnal {j.je_number}</span>
              : <span className="text-[hsl(var(--warning-text))]">belum dijurnal{j.error ? ` — ${j.error}` : ''}</span>}
            {j.negative_lines > 0 && <span className="text-[hsl(var(--warning-text))]"> · {j.negative_lines} baris stok minus</span>}
          </span>
        ) : <span className="text-muted-foreground">{s.opening ? 'Saldo awal cutoff — tanpa pengeluaran gudang.' : 'Belum ada dokumen pengeluaran gudang.'}</span>}
        {/* 14 Nov 2026: server meminta centang Keuangan › Jurnal › Setujui — tanpa itu tombol tidak ditampilkan */}
        {j && j.status === 'issued' && punyaCentang(null, 'mod.fin_journal.approve') && (
          <Button type="button" variant="outline" size="sm" onClick={repost} disabled={busy} data-testid="kirim-detail-repost">
            <Landmark className="w-3.5 h-3.5" />Posting ulang jurnal
          </Button>
        )}
      </div>
      {/* 2026-11-11 (owner): aksesoris yang diserahkan dibeli CMT → nota aksesoris kiriman ini */}
      <NotaAksesorisKiriman shipmentId={s.id} vendorName={s.vendor_name} info={d.nota_aksesoris} canManage={canManage}
        onChanged={load} />
      {(d.children || []).length > 0 && (
        <>
          <SectionLabel>Kiriman tambahan / pengganti</SectionLabel>
          <Table data-testid="kirim-detail-children">
            <TableHeader><TableRow>
              <TableHead>No. kiriman</TableHead><TableHead>Jenis</TableHead><TableHead>Tanggal</TableHead>
              <TableHead className="text-right">Pcs</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {d.children.map((c) => (
                <TableRow key={c.id}>
                  <TableCell><Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => onOpen?.(c.id)}>{c.shipment_number}</Button></TableCell>
                  <TableCell><ShipTypeBadge type={c.shipment_type} /></TableCell>
                  <TableCell className="text-xs">{fmtDate(c.shipment_date)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(c.total_pcs)}</TableCell>
                  <TableCell><ShipStatusBadge status={c.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
      <FileAttachmentPanel entityType="vendor_shipment" entityId={s.id} />
    </DetailPanel>
  );
}
