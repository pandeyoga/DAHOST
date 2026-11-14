/**
 * Nota aksesoris SATU kiriman — bagian rincian kiriman (Portal Produksi = Portal Maklon). Owner 10–11 Nov 2026.
 *
 *   • Sudah ada nota: nomor, total, cara bayar, yang sudah dipotong dari tagihan jahit / dibayar langsung, sisa;
 *     Cetak nota · Potong dari tagihan jahit · Batalkan (hanya bila belum dibayar/dipotong).
 *   • Belum ada (kiriman sejak cutoff, kiriman tambahan/pengganti, atau terlewat): "Buat nota aksesoris" →
 *     formulir isian pendek dengan harga per satuan serah (HPP sebagai acuan).
 *   • Tim jahit CV sendiri / saldo awal cutoff: alasan tanpa nota.
 * Server: `GET /kirim-cmt/shipments/{id}` (bagian `nota_aksesoris`), `POST …/nota-aksesoris`, `/kirim-cmt/nota-aksesoris/*`.
 */
import { useState } from 'react';
import { Download, Receipt, Scissors, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import FormPopup from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiFetch, apiPost } from '../../../../lib/api';
import { Notice, StatusBadge } from '../../moduleAtoms';
import NotaAksesorisIsian, { notaGalat, notaPayload, totalNota } from './NotaAksesorisIsian';
import { SectionLabel, fmtRp } from './kirimShared';
import { punyaCentang } from '@/lib/rbac';

const NADA = { issued: 'warning', overdue: 'warning', partial_paid: 'warning', paid: 'success', cancelled: 'muted' };

/** Unduh PDF nota (dipakai juga Portal Vendor). */
export async function unduhNotaPdf(nota) {
  try {
    const res = await apiFetch(`/kirim-cmt/nota-aksesoris/${nota.id}/pdf`);
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try { const e = await res.json(); msg = typeof e?.detail === 'string' ? e.detail : msg; } catch { /* bawaan */ }
      toast.error(`Gagal mencetak nota: ${msg}`);
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url; a.download = `Nota-Aksesoris_${nota.invoice_number}.pdf`; a.style.display = 'none';
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 4000);
  } catch (e) { toast.error(e.message || 'Gagal mencetak nota'); }
}

/** Satu kalimat rincian pelunasan nota. */
export function ringkasBayar(n) {
  const parts = [];
  if (Number(n.jumlah_dipotong) > 0) parts.push(`dipotong dari tagihan jahit ${fmtRp(n.jumlah_dipotong)}`);
  if (Number(n.dibayar_langsung) > 0) parts.push(`dibayar langsung ${fmtRp(n.dibayar_langsung)}`);
  parts.push(`sisa ${fmtRp(n.balance)}`);
  return parts.join(' · ');
}

export default function NotaAksesorisKiriman({ shipmentId, vendorName, info, canManage, onChanged }) {
  const [buka, setBuka] = useState(false);
  const [harga, setHarga] = useState({});
  const [cara, setCara] = useState(info?.cara_bawaan || 'potong_tagihan');
  const [busy, setBusy] = useState(false);
  if (!info) return null;
  const n = info.nota;
  const rows = info.baris || [];

  const buat = async () => {
    setBusy(true);
    try {
      const r = await apiPost(`/kirim-cmt/shipments/${shipmentId}/nota-aksesoris`, notaPayload(rows, harga, cara));
      if (r.gratis) toast.info('Semua aksesoris gratis — tidak ada nota.');
      else toast.success(`Nota ${r.nota.invoice_number} ${fmtRp(r.nota.total)} terbit`);
      setBuka(false); onChanged?.();
    } catch (e) { toast.error(e.message || 'Nota gagal dibuat'); }
    finally { setBusy(false); }
  };
  const potong = async () => {
    setBusy(true);
    try {
      const r = await apiPost(`/kirim-cmt/nota-aksesoris/${n.id}/potong`, {});
      const dipotong = Number(r.jumlah_dipotong || 0) - Number(n.jumlah_dipotong || 0);
      if (dipotong <= 0) toast.info(`Belum ada tagihan jahit terbuka — sisa ${fmtRp(r.balance)} otomatis memotong tagihan berikutnya.`);
      else toast.success(Number(r.balance) > 0 ? `Dipotong ${fmtRp(dipotong)} · sisa ${fmtRp(r.balance)} menunggu tagihan jahit berikutnya`
        : `Dipotong ${fmtRp(dipotong)} · nota lunas`);
      onChanged?.();
    } catch (e) { toast.error(e.message || 'Potong tagihan gagal'); }
    finally { setBusy(false); }
  };
  const batal = async () => {
    const alasan = await confirmDialog({ title: `Batalkan nota ${n.invoice_number}?`, confirmLabel: 'Batalkan nota', danger: true,
      body: 'Jurnal nota dibalik. Setelah itu nota baru bisa dibuat untuk kiriman ini.', input: { label: 'Alasan pembatalan', minLength: 3 } });
    if (!alasan) return;
    try {
      await apiPost(`/kirim-cmt/nota-aksesoris/${n.id}/batal`, { alasan });
      toast.info(`Nota ${n.invoice_number} dibatalkan`);
      onChanged?.();
    } catch (e) { toast.error(e.message || 'Pembatalan gagal'); }
  };

  return (
    <div className="space-y-2" data-testid="kirim-detail-nota">
      <SectionLabel>Nota aksesoris</SectionLabel>
      {n ? (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex flex-wrap items-center gap-2">
              <b className="tabular-nums" data-testid="kirim-detail-nota-nomor">{n.invoice_number}</b>
              <StatusBadge status={n.status} label={n.status_label} tone={NADA[n.status] || 'default'} />
              <span className="tabular-nums">{fmtRp(n.total)}</span>
              <span className="text-muted-foreground">· {n.cara_bayar_label}</span>
            </span>
            <span className="flex flex-wrap items-center gap-1">
              <Button type="button" variant="outline" size="sm" onClick={() => unduhNotaPdf(n)} data-testid="kirim-detail-nota-pdf">
                <Download className="w-3.5 h-3.5" />Cetak nota</Button>
              {/* 14 Nov 2026: memotong tagihan jahit = centang Produksi › Tagihan CMT › Setujui (aturan server) */}
              {canManage && punyaCentang(null, 'mod.prod_cmt_billing.approve') && ['issued', 'partial_paid', 'overdue'].includes(n.status) && Number(n.balance) > 0 && (
                <Button type="button" variant="outline" size="sm" onClick={potong} disabled={busy} data-testid="kirim-detail-nota-potong">
                  <Scissors className="w-3.5 h-3.5" />Potong dari tagihan jahit</Button>
              )}
              {canManage && n.status !== 'cancelled' && !Number(n.paid_amount) && !(n.potongan || []).length && (
                <Button type="button" variant="outline" size="icon" title="Batalkan nota" aria-label="Batalkan nota" onClick={batal}
                  data-testid="kirim-detail-nota-batal"><XCircle className="w-4 h-4" /></Button>
              )}
            </span>
          </div>
          <p className="text-muted-foreground" data-testid="kirim-detail-nota-bayar">{ringkasBayar(n)}
            {n.status !== 'paid' && n.cara_bayar === 'potong_tagihan' && Number(n.balance) > 0
              && ' — sisa otomatis memotong tagihan jahit berikutnya.'}</p>
          {(n.potongan || []).length > 0 && (
            <ul className="text-xs text-muted-foreground list-disc pl-4">
              {n.potongan.map((p) => (
                <li key={p.id}>Tagihan {p.nomor}{p.po_number ? ` PO ${p.po_number}` : ''}: {fmtRp(p.jumlah)}
                  {p.antar_cv ? ' (tagihan CV Sukma, lewat antar CV)' : ''}</li>
              ))}
            </ul>
          )}
          {n.potong_error && <Notice tone="warning" icon={Receipt}>Potong tagihan tertunda: {n.potong_error}</Notice>}
        </div>
      ) : info.bisa_dibuat ? (
        <Notice tone="info" icon={Receipt} testId="kirim-detail-nota-belum" title="Belum ada nota aksesoris"
          action={canManage && <Button type="button" variant="outline" size="sm" onClick={() => setBuka(true)}
            data-testid="kirim-detail-nota-buat">Buat nota aksesoris</Button>}>
          Aksesoris kiriman ini dibeli CMT. Ketik harga jualnya untuk menerbitkan nota.
        </Notice>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="kirim-detail-nota-tidak">
          {info.status_kiriman === 'gratis' ? 'Semua aksesoris diberikan gratis — tanpa nota.'
            : info.alasan || 'Tidak ada aksesoris dari gudang pada kiriman ini.'}
        </p>
      )}
      {buka && (
        <FormPopup open onClose={() => setBuka(false)} ukuran="panjang" testId="kirim-nota-form"
          judul="Buat nota aksesoris" keterangan={`Aksesoris yang sudah diserahkan ke ${vendorName || 'CMT'} — harga per satuan serah.`}
          onSimpan={buat} bisaSimpan={!notaGalat(rows, harga) && !busy} menyimpan={busy}
          labelSimpan={totalNota(rows, harga) > 0 ? 'Terbitkan nota' : 'Simpan'}>
          <NotaAksesorisIsian rows={rows} harga={harga} onHarga={(k, v) => setHarga((h) => ({ ...h, [k]: v }))}
            caraBayar={cara} onCaraBayar={setCara} vendorName={vendorName} testId="kirim-nota-buat" />
        </FormPopup>
      )}
    </div>
  );
}
