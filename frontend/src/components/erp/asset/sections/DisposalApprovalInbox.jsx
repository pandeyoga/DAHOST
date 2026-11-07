/**
 * DisposalApprovalInbox — permintaan pelepasan aset (disposal) untuk Admin/Keuangan/Manajer.
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • kartu bergaris warna per permintaan → tabel TabelData; klik baris membuka detail popup;
 *  • pil buatan sendiri → FilterChips; unduh Excel/CSV;
 *  • Setujui (hijau) → popup form pendek dengan catatan opsional; Tolak (merah) → konfirmasi dengan alasan
 *    wajib (aturan lama: catatan wajib saat menolak). Tanpa emoji.
 */
import { useState, useEffect, useCallback } from 'react';
import { Check, RefreshCw, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from '../../layout/PageLayout';
import { EmptyState, Notice } from '../../moduleAtoms';
import { DISPOSAL_STATUS_CONFIG } from '../constants';
import { angka, apicall, fmtCurrency, fmtDate } from '../utils';
import { StatusBadge } from '../components/StatusBadge';

const SARINGAN = [
  { key: 'pending', label: 'Menunggu' },
  { key: 'approved', label: 'Disetujui' },
  { key: 'rejected', label: 'Ditolak' },
  { key: 'all', label: 'Semua' },
];

export function DisposalApprovalInbox({ token, userRole, onRefresh }) {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState('pending');
  const [setujui, setSetujui] = useState(null);   // permintaan yang sedang disetujui (popup form)
  const [notes, setNotes] = useState('');
  const [processing, setProcessing] = useState(false);
  const [detail, setDetail] = useState(null);
  const canReview = ['admin', 'superadmin', 'finance', 'manager'].includes(userRole);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apicall('GET', `/api/assets/disposal-requests?status=${filterStatus}`, token);
      if (Array.isArray(data)) setRequests(data);
    } catch { toast.error('Gagal memuat permintaan pelepasan'); }
    finally { setLoading(false); }
  }, [token, filterStatus]);

  useEffect(() => { load(); }, [load]);

  const kirimKeputusan = async (req, action, catatan) => {
    setProcessing(true);
    try {
      const data = await apicall('PATCH', `/api/assets/disposal-requests/${req.id}/${action}`, token, { notes: catatan });
      if (data?.ok !== undefined) {
        toast.success(action === 'approve' ? 'Pelepasan disetujui dan jurnal dibuat' : 'Pelepasan ditolak');
        setSetujui(null); setNotes(''); setDetail(null);
        load(); onRefresh?.();
        return true;
      }
      toast.error(data?.detail || 'Gagal memproses');
    } catch (e) { toast.error(e.message || 'Gagal memproses'); }
    finally { setProcessing(false); }
    return false;
  };

  const tolak = async (req) => {
    const alasan = await confirmDialog({
      title: 'Tolak pelepasan aset?',
      body: `${req.asset_name} (${req.asset_number}) tetap tercatat aktif. Tulis alasan agar pemohon tahu.`,
      confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan (wajib)', placeholder: 'Alasan penolakan…' },
    });
    if (!alasan) return;
    await kirimKeputusan(req, 'reject', alasan);
  };
  const bukaSetujui = (req) => { setNotes(''); setSetujui(req); };

  const tombolKeputusan = (req, ukuran = 'sm') => (canReview && req.status === 'pending' ? (
    <>
      <Button size={ukuran} variant="success" onClick={() => bukaSetujui(req)} data-testid={`approve-disposal-${req.id}`}>
        <Check />Setujui
      </Button>
      <Button size={ukuran} variant="destructive" onClick={() => tolak(req)} disabled={processing}
        data-testid={`reject-disposal-${req.id}`}>
        <X />Tolak
      </Button>
    </>
  ) : null);

  const labelSaringan = SARINGAN.find((s) => s.key === filterStatus)?.label.toLowerCase();

  return (
    <PageLayout testId="disposal-requests-tab" title="Pelepasan"
      subtitle="Permintaan pelepasan aset bernilai tinggi yang perlu persetujuan."
      filters={<FilterChips options={SARINGAN} value={filterStatus} onChange={setFilterStatus} hideWhenEmpty={false}
        testId="disposal-filter" ariaLabel="Status permintaan" />}
      tools={<>
        <TombolUnduh namaBerkas="permintaan-pelepasan-aset" namaLembar="Pelepasan" baris={requests} testId="disposal-unduh"
          kolom={[
            { label: 'Aset', nilai: (r) => r.asset_name },
            { label: 'No. aset', nilai: (r) => r.asset_number },
            { label: 'Nilai buku', nilai: (r) => angka(r.nbv || 0) },
            { label: 'Nilai jual', nilai: (r) => angka(r.disposal_value || 0) },
            { label: 'Tanggal pelepasan', nilai: (r) => fmtDate(r.disposal_date) },
            { label: 'Alasan', nilai: (r) => r.reason || '' },
            { label: 'Diminta oleh', nilai: (r) => r.requested_by_name || '' },
            { label: 'Tanggal diminta', nilai: (r) => fmtDate(r.requested_at) },
            { label: 'Status', nilai: (r) => DISPOSAL_STATUS_CONFIG[r.status]?.label || r.status },
            { label: 'Catatan peninjau', nilai: (r) => r.review_notes || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && requests.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat permintaan…</p>
      ) : (
        <TabelData baris={requests} onKlikBaris={setDetail} testId="disposal-table"
          kosong={<EmptyState title="Tidak ada permintaan pelepasan"
            description={filterStatus !== 'all' ? `Tidak ada permintaan berstatus "${labelSaringan}".`
              : 'Permintaan muncul di sini saat aset bernilai buku di atas Rp 5 juta diajukan untuk dilepas.'} />}
          kolom={[
            { kunci: 'aset', label: 'Aset', hp: 'judul', isi: (r) => (
              <div className="min-w-0">
                <p className="font-medium">{r.asset_name}</p>
                <p className="text-xs tabular-nums text-muted-foreground">{r.asset_number}</p>
              </div>) },
            { kunci: 'nbv', label: 'Nilai buku', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtCurrency(r.nbv || 0)}</span> },
            { kunci: 'jual', label: 'Nilai jual', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmtCurrency(r.disposal_value || 0)}</span> },
            { kunci: 'tgl', label: 'Tanggal pelepasan', isi: (r) => fmtDate(r.disposal_date) },
            { kunci: 'oleh', label: 'Diminta', isi: (r) => (
              <span>{r.requested_by_name || '—'}<span className="block text-xs text-muted-foreground">{fmtDate(r.requested_at)}</span></span>) },
            { kunci: 'alasan', label: 'Alasan', hp: 'keterangan', isi: (r) => (
              <span className="line-clamp-2 md:max-w-[16rem]" title={r.reason}>{r.reason || '—'}</span>) },
            { kunci: 'status', label: 'Status', isi: (r) => <StatusBadge status={r.status} configMap={DISPOSAL_STATUS_CONFIG} /> },
            ...(canReview ? [{ kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
              <div className="flex justify-end gap-2">{tombolKeputusan(r)}</div>) }] : []),
          ]} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.asset_name} testId="disposal-detail"
          keterangan={detail.asset_number}
          status={<StatusBadge status={detail.status} configMap={DISPOSAL_STATUS_CONFIG} />}
          aksi={tombolKeputusan(detail)}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Nilai buku">{fmtCurrency(detail.nbv || 0)}</BarisDetail>
            <BarisDetail label="Nilai jual">{fmtCurrency(detail.disposal_value || 0)}</BarisDetail>
            <BarisDetail label="Tanggal pelepasan">{fmtDate(detail.disposal_date)}</BarisDetail>
            <BarisDetail label="Alasan">{detail.reason || '—'}</BarisDetail>
            <BarisDetail label="Diminta">{detail.requested_by_name || '—'} · {fmtDate(detail.requested_at)}</BarisDetail>
            {detail.review_notes && <BarisDetail label="Catatan peninjau">{detail.review_notes}</BarisDetail>}
          </dl>
        </DetailPopup>
      )}

      <FormPopup open={!!setujui} onClose={() => setSetujui(null)} ukuran="pendek" testId="disposal-approve-form"
        judul="Setujui pelepasan aset" labelSimpan="Setujui" menyimpan={processing}
        keterangan={setujui ? `${setujui.asset_name} · nilai buku ${fmtCurrency(setujui.nbv || 0)}` : undefined}
        onSimpan={() => kirimKeputusan(setujui, 'approve', notes)}>
        <Notice tone="warning" title="Aset langsung dilepas">
          Menyetujui akan langsung melepas aset ini dan membuat jurnal Keuangan.
        </Notice>
        <Isian label="Catatan" petunjuk="Opsional." htmlFor="disposal-approve-notes">
          <Textarea id="disposal-approve-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="Catatan persetujuan…" />
        </Isian>
      </FormPopup>
    </PageLayout>
  );
}
