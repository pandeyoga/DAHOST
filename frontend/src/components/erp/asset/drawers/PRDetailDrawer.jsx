/**
 * PRDetailDrawer — detail permintaan pengadaan: data, daftar barang, riwayat persetujuan, tombol keputusan.
 *
 * Standar UI/UX v2 (8 Nov 2026): panel samping (Sheet) → DetailPopup; tombol keputusan di kepala popup
 * (Ajukan · Setujui hijau · Tolak merah · Batalkan); alasan penolakan lewat dialog konfirmasi (server
 * mewajibkan alasan); kode mentah (prioritas, jenis, langkah persetujuan) → label Indonesia; daftar barang =
 * tabel yang bisa diunduh. Endpoint & syarat tombol tidak berubah.
 * 2026-11-08 (keputusan owner): kotak persetujuan juga memuat Request Pembelian Aksesoris (`kind: acc_pr`) dan
 * Purchase Order (`kind: po`). Setujui/Tolak dulu SELALU memanggil `/api/procurement/requests/…` → baris
 * aksesoris/PO gagal. Kini endpoint dipilih per jenis baris (`basisKeputusan`); hak tetap diperiksa server
 * (`eval_approval`). Ajukan/Batalkan hanya untuk Permintaan Pengadaan (jenis lain tidak punya endpoint itu di sini).
 */
import { useState } from 'react';
import { Ban, Check, Send, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { cn } from '@/lib/utils';
import { angka, apicall, fmtCurrency, fmtDate, fmtDateTime } from '../utils';
import { StatusBadge } from '../components/StatusBadge';
import { Bagian } from '../components/KPICard';
import { PR_STATUS_CONFIG, PR_PRIORITY_LABEL, PR_TYPE_LABEL, PR_STEP_LABEL } from '../constants';

/** Endpoint keputusan per jenis baris kotak persetujuan (`kind` dari `/api/procurement/inbox`). */
export const BASIS_KEPUTUSAN = {
  pr: '/api/procurement/requests',
  acc_pr: '/api/acc/purchase-requests',
  po: '/api/rahaza/purchase-orders',
};
/** Baris tanpa `kind` (daftar "Semua permintaan") = Permintaan Pengadaan. */
export const basisKeputusan = (pr) => BASIS_KEPUTUSAN[pr?.kind || 'pr'] || pr?.api_base || BASIS_KEPUTUSAN.pr;
const PESAN_BERHASIL = {
  submit: 'Permintaan diajukan untuk persetujuan', approve: 'Permintaan disetujui',
  reject: 'Permintaan ditolak', cancel: 'Permintaan dibatalkan',
};

export function PRDetailDrawer({ pr, token, open, onClose, onRefresh, currentUser }) {
  const [loading, setLoading] = useState(false);
  const [comment] = useState('');

  if (!pr) return null;

  const jenisPengadaan = (pr.kind || 'pr') === 'pr';
  const canApprove = ['submitted', 'dept_approved', 'finance_approved'].includes(pr.status);
  const canSubmit = jenisPengadaan && pr.status === 'draft';
  const canCancel = jenisPengadaan && ['draft', 'submitted'].includes(pr.status) &&
    (pr.requested_by === currentUser?.id || currentUser?.role === 'superadmin' || currentUser?.role === 'admin');

  // Gagal = HTTP bukan 2xx (apicall melempar) atau `ok: false`. PO menjawab dokumen PO tanpa `ok`.
  const action = async (endpoint, body = {}) => {
    setLoading(true);
    try {
      const d = await apicall('POST', `${basisKeputusan(pr)}/${pr.id}/${endpoint}`, token, body);
      if (d?.ok === false) toast.error(d.detail || 'Gagal');
      else {
        toast.success(endpoint === 'approve' && d?.next_stage_label
          ? `Disetujui — lanjut ke ${d.next_stage_label}` : PESAN_BERHASIL[endpoint] || 'Berhasil');
        onRefresh(); onClose();
      }
    } catch (e) { toast.error(e.message || 'Gagal'); }
    finally { setLoading(false); }
  };

  const tolak = async () => {
    const reason = await confirmDialog({
      title: 'Tolak permintaan ini?', body: `${pr.request_number} — ${pr.title}. Tulis alasan agar pemohon tahu.`,
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan (wajib)', placeholder: 'Alasan penolakan…' },
    });
    if (reason) action('reject', { reason });
  };
  const batalkan = async () => {
    const ok = await confirmDialog({
      title: 'Batalkan permintaan ini?', body: `${pr.request_number} — ${pr.title} tidak akan diproses lagi.`,
      confirmLabel: 'Batalkan permintaan', danger: true,
    });
    if (ok) action('cancel');
  };

  const items = (pr.items || []).map((it, i) => ({ ...it, _baris: i }));
  const steps = pr.approval_steps || [];

  return (
    <DetailPopup open={open} onClose={onClose} judul={pr.title} testId="pr-detail"
      keterangan={[pr.request_number, pr.requested_by_name].filter(Boolean).join(' · ')}
      status={<StatusBadge status={pr.status} configMap={PR_STATUS_CONFIG} />}
      aksi={(canSubmit || canApprove || canCancel) ? (
        <>
          {canSubmit && (
            <Button size="sm" onClick={() => action('submit')} disabled={loading} data-testid="pr-submit-btn">
              <Send />Ajukan persetujuan
            </Button>
          )}
          {canApprove && (
            <>
              <Button size="sm" variant="success" onClick={() => action('approve', { comment })} disabled={loading}
                data-testid="pr-approve-btn">
                <Check />Setujui
              </Button>
              <Button size="sm" variant="destructive" onClick={tolak} disabled={loading} data-testid="pr-reject-btn">
                <X />Tolak
              </Button>
            </>
          )}
          {canCancel && (
            <Button size="sm" variant="outline" onClick={batalkan} disabled={loading} data-testid="pr-cancel-btn">
              <Ban />Batalkan permintaan
            </Button>
          )}
        </>
      ) : null}>
      <dl className="divide-y divide-[var(--glass-border)]">
        <BarisDetail label="Pemohon">{pr.requested_by_name || '—'}</BarisDetail>
        <BarisDetail label="Departemen">{pr.department || '—'}</BarisDetail>
        <BarisDetail label="Prioritas">{PR_PRIORITY_LABEL[pr.priority] || pr.priority || '—'}</BarisDetail>
        <BarisDetail label="Jenis">{PR_TYPE_LABEL[pr.request_type] || pr.request_type || '—'}</BarisDetail>
        <BarisDetail label="Tanggal dibuat">{fmtDate(pr.created_at)}</BarisDetail>
        <BarisDetail label="Perkiraan total"><span className="tabular-nums">{fmtCurrency(pr.total_estimated)}</span></BarisDetail>
        {pr.justification && <BarisDetail label="Justifikasi">{pr.justification}</BarisDetail>}
      </dl>

      <Bagian judul={`Daftar barang (${items.length})`} testId="pr-detail-items"
        alat={<TombolUnduh namaBerkas={`barang-${pr.request_number || 'permintaan'}`} namaLembar="Barang" baris={items}
          testId="pr-items-unduh" kolom={[
            { label: 'Barang', nilai: (it) => it.name },
            { label: 'Spesifikasi', nilai: (it) => it.specification || '' },
            { label: 'Jumlah', nilai: (it) => Number(it.qty) || 0 },
            { label: 'Satuan', nilai: (it) => it.unit || '' },
            { label: 'Perkiraan total', nilai: (it) => angka(it.total_price) },
          ]} />}>
        <TabelData baris={items} kunci={(it) => it._baris} testId="pr-items-table"
          kosong={<p className="py-4 text-center text-sm text-muted-foreground">Tidak ada barang.</p>}
          kolom={[
            { kunci: 'nama', label: 'Barang', hp: 'judul', isi: (it) => <span className="font-medium">{it.name}</span> },
            { kunci: 'spek', label: 'Spesifikasi', hp: 'keterangan', isi: (it) => it.specification || '—' },
            { kunci: 'qty', label: 'Jumlah', rata: 'kanan', isi: (it) => <span className="tabular-nums">{Number(it.qty || 0).toLocaleString('id-ID')} {it.unit}</span> },
            { kunci: 'total', label: 'Perkiraan total', rata: 'kanan', isi: (it) => <span className="tabular-nums">{fmtCurrency(it.total_price)}</span> },
          ]} />
      </Bagian>

      {steps.length > 0 && (
        <Bagian judul="Riwayat persetujuan" testId="pr-detail-steps">
          <ol className="space-y-3 border-l border-[var(--glass-border)] pl-4">
            {steps.map((s, i) => (
              <li key={s.id || i} className="relative">
                <span aria-hidden="true" className={cn('absolute -left-[1.4rem] top-1.5 h-2.5 w-2.5 rounded-full',
                  s.action === 'approved' ? 'bg-[hsl(var(--success))]' : s.action === 'rejected' ? 'bg-[hsl(var(--destructive))]' : 'bg-primary')} />
                <p className="text-sm">
                  <span className="font-medium">{s.actor_name}</span>{' '}
                  <span className="text-muted-foreground">{PR_STEP_LABEL[s.action] || 'memperbarui'}</span>
                </p>
                {s.comment && <p className="text-sm text-muted-foreground">{s.comment}</p>}
                {s.timestamp && <p className="text-xs text-muted-foreground">{fmtDateTime(s.timestamp)}</p>}
              </li>
            ))}
          </ol>
        </Bagian>
      )}
    </DetailPopup>
  );
}
