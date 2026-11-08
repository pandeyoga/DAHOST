import { useEffect, useState } from 'react';
import { BookOpen, FileDown, History } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateID, formatRupiah } from '@/lib/format';
import { toast } from 'sonner';
import { EmptyState, Notice } from './moduleAtoms';

async function downloadReceipt(token, kind, invoiceId, paymentId) {
  try {
    const r = await fetch(`/api/rahaza/${kind}-invoices/${invoiceId}/payments/${paymentId}/receipt.pdf`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = (r.headers.get('Content-Disposition') || '').match(/filename="(.+)"/)?.[1] || 'Kwitansi.pdf';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { toast.error(`Gagal mengunduh kwitansi: ${e.message}`); }
}

/**
 * Riwayat pembayaran per faktur/tagihan (AR/AP) + nomor jurnal — staf tak perlu buka Buku Jurnal.
 * Dibuka di bawah baris faktur (RowDetail). 2026-11-05 (PANDUAN_UI G7/G8/G10): tanggal formatDateID, angka
 * tabular-nums (bukan font-mono), warna token, tombol PDF = Button, kosong = EmptyState. Popup lama
 * `PaymentHistoryModal` (default export) dihapus — tidak dipakai di mana pun.
 */
export function PaymentHistoryList({ token, kind, invoiceId }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let x = false;
    setRows(null); setErr('');
    fetch(`/api/rahaza/${kind}-invoices/${invoiceId}/payments`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { if (!x) setRows(Array.isArray(d) ? d : []); })
      .catch(e => { if (!x) { setErr(e.message); setRows([]); } });
    return () => { x = true; };
  }, [token, kind, invoiceId]);

  if (rows === null) return <div className="space-y-2">{[0, 1].map(i => <Skeleton key={i} className="h-9 rounded-lg" />)}</div>;
  if (err) return <Notice tone="danger" testId="payment-history-error" className="text-xs">Gagal memuat riwayat: {err}</Notice>;
  if (rows.length === 0) {
    return (
      <EmptyState icon={History} className="py-6" testId="payment-history-empty" title="Belum ada pembayaran"
        description="Pembayaran yang dicatat untuk dokumen ini tampil di sini." />
    );
  }
  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0);
  return (
    <div className="space-y-2">
    <div className="flex justify-end">
      <TombolUnduh namaBerkas="riwayat-pembayaran" namaLembar="Pembayaran" baris={rows} testId="payment-history-unduh"
        kolom={[
          { label: 'Tanggal', nilai: (r) => formatDateID(r.date) },
          { label: 'Rekening', nilai: (r) => (r.account_code ? `${r.account_code} · ${r.account_name}` : 'Tanpa rekening') },
          { label: 'No. jurnal', nilai: (r) => r.gl_je_number || (r.post_error ? 'Jurnal gagal' : 'Belum dijurnal') },
          { label: 'Catatan', nilai: (r) => r.notes || '' },
          { label: 'Jumlah', nilai: (r) => Number(r.amount) || 0 },
        ]} />
    </div>
    <div className="overflow-x-auto" data-testid="payment-history-table">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-2 pr-2">Tanggal</th>
            <th className="py-2 pr-2">Rekening</th>
            <th className="py-2 pr-2">No. jurnal</th>
            <th className="py-2 pr-2">Catatan</th>
            <th className="py-2 text-right">Jumlah</th>
            <th className="py-2 pl-2 text-right">Kwitansi</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id} className="border-t border-[var(--glass-border)]" data-testid={`payment-row-${r.id}`}>
              <td className="py-2 pr-2 whitespace-nowrap">{formatDateID(r.date)}</td>
              <td className="py-2 pr-2">{r.account_code ? `${r.account_code} · ${r.account_name}` : <span className="text-muted-foreground">Tanpa rekening</span>}</td>
              <td className="py-2 pr-2">
                {r.gl_je_number
                  ? <span className="inline-flex items-center gap-1 text-[hsl(var(--success-text))]" data-testid={`payment-je-${r.id}`}><BookOpen size={11} />{r.gl_je_number}</span>
                  : <span className={`text-xs ${r.post_error ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--warning-text))]'}`} title={r.post_error || ''}>{r.post_error ? 'Jurnal gagal' : 'Belum dijurnal'}</span>}
              </td>
              <td className="py-2 pr-2 text-muted-foreground truncate max-w-[180px]" title={r.notes}>{r.notes || '—'}</td>
              <td className="py-2 text-right tabular-nums whitespace-nowrap">{formatRupiah(r.amount)}</td>
              <td className="py-2 pl-2 text-right">
                <Button variant="outline" size="sm" onClick={() => downloadReceipt(token, kind, invoiceId, r.id)}
                  data-testid={`payment-receipt-${r.id}`} title="Unduh kwitansi PDF" aria-label="Unduh kwitansi PDF">
                  <FileDown /> PDF
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-[var(--glass-border)] font-semibold">
            <td colSpan={4} className="py-2 text-right">Total dibayar ({rows.length} pembayaran)</td>
            <td className="py-2 text-right tabular-nums whitespace-nowrap" data-testid="payment-history-total">{formatRupiah(total)}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
    </div>
  );
}
