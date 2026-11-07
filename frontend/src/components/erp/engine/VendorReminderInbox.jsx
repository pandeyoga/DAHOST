/**
 * VendorReminderInbox — Pengingat dari admin DA (Portal Vendor CMT; juga di Input atas nama CMT).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, daftar = tabel (dulu kartu berwarna berulang), saringan Menunggu/Dibalas,
 * rincian + balasan dibuka di popup (balasan = FormPopup pendek), bisa diunduh. API sama: GET /reminders,
 * PUT /reminders/{id} { response }.
 */
import { useEffect, useState } from 'react';
import { Bell, MessageSquare } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { PageLayoutSatuBaris } from './DataTable';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { apiGet, apiPut } from '../../../lib/api';

const PRIORITAS = { urgent: ['Mendesak', 'danger'], high: ['Tinggi', 'warning'] };
const prioritas = (p) => PRIORITAS[p] || ['Normal', 'muted'];
const waktu = (d) => (d ? formatDateTimeID(d) : '—');

export default function VendorReminderInbox() {
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saring, setSaring] = useState('');
  const [detail, setDetail] = useState(null);
  const [balas, setBalas] = useState(null);
  const [responseText, setResponseText] = useState('');
  const [mengirim, setMengirim] = useState(false);

  const fetchReminders = async () => {
    try {
      const d = await apiGet('/reminders');
      setReminders(Array.isArray(d) ? d : []);
    } catch (e) { /* tetap tampil kosong */ }
    setLoading(false);
  };
  useEffect(() => { fetchReminders(); }, []);

  const sendResponse = async () => {
    if (!responseText.trim()) { toast.error('Tulis balasan terlebih dahulu'); return; }
    setMengirim(true);
    try {
      await apiPut(`/reminders/${balas.id}`, { response: responseText });
      setBalas(null);
      setResponseText('');
      fetchReminders();
    } catch (e) { toast.error('Gagal mengirim balasan: ' + e.message); }
    finally { setMengirim(false); }
  };

  const pending = reminders.filter((r) => r.status === 'pending');
  const baris = reminders.filter((r) => (saring === 'pending' ? r.status === 'pending' : saring === 'dibalas' ? r.status !== 'pending' : true));

  const kolom = [
    { kunci: 'tgl', label: 'Waktu', isi: (r) => <span className="whitespace-nowrap text-sm">{waktu(r.created_at)}</span> },
    { kunci: 'subjek', label: 'Pengingat', hp: 'judul', isi: (r) => (
      <div className="min-w-0 md:max-w-[26rem]">
        <span className="block truncate font-medium" title={r.subject}>{r.subject}</span>
        <span className="block truncate text-xs text-muted-foreground" title={r.message}>{r.po_number ? `PO ${r.po_number} · ` : ''}{r.message}</span>
      </div>) },
    { kunci: 'prioritas', label: 'Prioritas', isi: (r) => { const [l, t] = prioritas(r.priority); return <StatusBadge status={r.priority || 'normal'} label={l} tone={t} />; } },
    { kunci: 'status', label: 'Status', isi: (r) => (r.status === 'pending'
      ? <StatusBadge status="pending" tone="warning" label="Menunggu balasan" /> : <StatusBadge status="done" tone="success" label="Dibalas" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (r.status === 'pending' && (
      <Button size="sm" onClick={() => { setBalas(r); setResponseText(''); }}><MessageSquare className="w-3.5 h-3.5" />Balas</Button>)) },
  ];

  return (
    <PageLayoutSatuBaris testId="vendor-reminder-inbox" title="Pengingat" subtitle="Pesan dan pengingat dari admin DA."
      filters={<FilterChips value={saring} onChange={setSaring} hideWhenEmpty={false} ariaLabel="Saring pengingat"
        options={[{ key: '', label: 'Semua', count: reminders.length }, { key: 'pending', label: 'Menunggu balasan', count: pending.length },
          { key: 'dibalas', label: 'Dibalas', count: reminders.length - pending.length }]} />}
      tools={<TombolUnduh namaBerkas="pengingat-vendor" baris={baris} kolom={[
        { label: 'Waktu', nilai: (r) => waktu(r.created_at) }, { label: 'Subjek', nilai: (r) => r.subject || '' },
        { label: 'PO', nilai: (r) => r.po_number || '' }, { label: 'Pesan', nilai: (r) => r.message || '' },
        { label: 'Prioritas', nilai: (r) => prioritas(r.priority)[0] }, { label: 'Dari', nilai: (r) => r.created_by || '' },
        { label: 'Balasan', nilai: (r) => r.response || '' }, { label: 'Dibalas', nilai: (r) => (r.response_date ? waktu(r.response_date) : '') },
      ]} />}>
      {loading ? <p className="py-10 text-center text-sm text-muted-foreground">Memuat…</p> : (
        <TabelData kolom={kolom} baris={baris} onKlikBaris={setDetail} testId="vendor-reminder-table"
          kosong={<EmptyState icon={Bell} title={reminders.length ? 'Tidak ada pengingat yang cocok' : 'Belum ada pengingat'}
            description={reminders.length ? 'Ubah saringan.' : 'Pengingat dari admin akan muncul di sini.'} />} />
      )}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.subject || 'Pengingat'} testId="vendor-reminder-detail"
          status={(() => { const [l, t] = prioritas(detail.priority); return <StatusBadge status={detail.priority || 'normal'} label={l} tone={t} />; })()}
          aksi={detail.status === 'pending' && <Button size="sm" onClick={() => { setBalas(detail); setResponseText(''); setDetail(null); }}><MessageSquare className="w-4 h-4" />Balas</Button>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Waktu">{waktu(detail.created_at)}</BarisDetail>
            {detail.po_number && <BarisDetail label="PO">{detail.po_number}</BarisDetail>}
            <BarisDetail label="Dari">{detail.created_by || '—'}</BarisDetail>
            <BarisDetail label="Pesan">{detail.message || '—'}</BarisDetail>
            {detail.status !== 'pending' && <BarisDetail label="Balasan">{detail.response || '—'}</BarisDetail>}
            {detail.status !== 'pending' && <BarisDetail label="Dibalas">{waktu(detail.response_date)}</BarisDetail>}
          </dl>
        </DetailPopup>
      )}
      {balas && (
        <FormPopup open onClose={() => setBalas(null)} ukuran="pendek" judul={`Balas: ${balas.subject || 'pengingat'}`}
          keterangan={balas.message} onSimpan={sendResponse} menyimpan={mengirim} labelSimpan="Kirim balasan" testId="vendor-reminder-reply">
          <Isian label="Balasan" wajib>
            <Textarea rows={4} value={responseText} onChange={(e) => setResponseText(e.target.value)} placeholder="Tulis balasan Anda…" />
          </Isian>
        </FormPopup>
      )}
    </PageLayoutSatuBaris>
  );
}
