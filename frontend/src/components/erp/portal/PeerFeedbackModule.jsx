/**
 * Portal Saya › Peer Feedback — beri dan terima masukan dari rekan kerja.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (dulu kepala berikon gradien + `p-6`), 3 kartu angka StatTile (dulu
 * kotak berwarna hex), tab buatan → pil penyaring berangka, daftar masukan = TabelData + unduh Excel/CSV (dulu kartu
 * besar per masukan), isi lengkap di popup, form kirim = FormPopup. Endpoint & isi yang dikirim tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { toast } from 'sonner';
import { Send, Star } from 'lucide-react';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';

const CATEGORY_LABEL = {
  teamwork: 'Kerja sama tim',
  communication: 'Komunikasi',
  quality: 'Kualitas kerja',
  leadership: 'Kepemimpinan',
  general: 'Umum',
};
const kategori = (k) => CATEGORY_LABEL[k] || CATEGORY_LABEL.general;
const tgl = (v) => (v ? formatDateID(v) : '—');

function Bintang({ rating, besar = false }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`${rating} dari 5`}>
      {Array.from({ length: 5 }).map((_, i) => (
        <Star key={i} className={`${besar ? 'h-6 w-6' : 'h-3.5 w-3.5'} ${i < rating ? 'fill-[hsl(var(--warning))] text-[hsl(var(--warning))]' : 'text-muted-foreground/50'}`} />
      ))}
    </span>
  );
}

export default function PeerFeedbackModule({ token }) {
  const [activeTab, setActiveTab] = useState('received');
  const [receivedFeedback, setReceivedFeedback] = useState([]);
  const [givenFeedback, setGivenFeedback] = useState([]);
  const [peers, setPeers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [showSendDialog, setShowSendDialog] = useState(false);
  const [formData, setFormData] = useState({ to_employee_id: '', rating: 5, category: 'general', message: '', is_anonymous: false });
  const [avgRating, setAvgRating] = useState(0);
  const [detail, setDetail] = useState(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchReceived = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/peer-feedback/received`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setReceivedFeedback(data?.data || []);
      setAvgRating(data?.metadata?.avg_rating || 0);
    } catch (e) {
      toast.error(`Gagal memuat masukan: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const fetchGiven = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/peer-feedback/given`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setGivenFeedback(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat masukan: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const fetchPeers = useCallback(async () => {
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/peers`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setPeers(data?.data || []);
    } catch (e) {
      console.error('Peers fetch failed:', e);
    }
  }, [headers]);

  useEffect(() => {
    fetchReceived();
    fetchGiven();
    fetchPeers();
  }, [fetchReceived, fetchGiven, fetchPeers]);

  const handleSend = async () => {
    if (!formData.to_employee_id || !formData.message.trim()) {
      toast.error('Pilih penerima dan tulis pesan');
      return;
    }
    setSending(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/peer-feedback`, {
        method: 'POST',
        headers,
        body: JSON.stringify(formData),
      });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      toast.success('Masukan berhasil dikirim.');
      setShowSendDialog(false);
      setFormData({ to_employee_id: '', rating: 5, category: 'general', message: '', is_anonymous: false });
      fetchGiven();
      fetchReceived();
    } catch (e) {
      toast.error(`Gagal mengirim masukan: ${e.message}`);
    } finally {
      setSending(false);
    }
  };

  const diterima = activeTab === 'received';
  const baris = diterima ? receivedFeedback : givenFeedback;
  const siapa = (fb) => (diterima ? (fb.from_employee_name || (fb.is_anonymous ? 'Anonim' : '—')) : fb.to_employee_name);

  const kolom = [
    { kunci: 'siapa', label: diterima ? 'Dari' : 'Untuk', hp: 'judul', isi: (fb) => (
      <span className="font-medium">{siapa(fb)}{!diterima && fb.is_anonymous && <span className="text-muted-foreground"> · anonim</span>}</span>) },
    { kunci: 'kategori', label: 'Kategori', isi: (fb) => <StatusBadge status={fb.category} label={kategori(fb.category)} tone="default" /> },
    { kunci: 'rating', label: 'Nilai', isi: (fb) => <Bintang rating={fb.rating} /> },
    { kunci: 'pesan', label: 'Pesan', isi: (fb) => <p className="line-clamp-2 text-sm text-muted-foreground md:max-w-[26rem]">{fb.message}</p> },
    { kunci: 'tanggal', label: 'Tanggal', isi: (fb) => <span className="whitespace-nowrap text-sm">{tgl(fb.created_at)}</span> },
  ];

  return (
    <PageLayout testId="peer-feedback-module" title="Peer feedback"
      subtitle="Beri dan terima masukan dari rekan kerja."
      actions={<Button onClick={() => setShowSendDialog(true)} data-testid="peer-send-btn"><Send />Kirim masukan</Button>}
      filters={(
        <FilterChips className="w-full min-w-0 sm:w-auto" value={activeTab} onChange={(k) => setActiveTab(k || 'received')} hideWhenEmpty={false} testId="peer-tab"
          options={[
            { key: 'received', label: 'Diterima', count: receivedFeedback.length },
            { key: 'given', label: 'Diberikan', count: givenFeedback.length },
          ]} />
      )}
      tools={(
        <TombolUnduh namaBerkas={diterima ? 'masukan-diterima' : 'masukan-diberikan'} namaLembar="Masukan" baris={baris} testId="peer-unduh" kolom={[
          { label: diterima ? 'Dari' : 'Untuk', nilai: (fb) => siapa(fb) || '' }, { label: 'Kategori', nilai: (fb) => kategori(fb.category) },
          { label: 'Nilai (1–5)', nilai: (fb) => fb.rating }, { label: 'Pesan', nilai: (fb) => fb.message || '' },
          { label: 'Anonim', nilai: (fb) => (fb.is_anonymous ? 'Ya' : 'Tidak') }, { label: 'Tanggal', nilai: (fb) => tgl(fb.created_at) },
        ]} />
      )}
      summary={(
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Masukan diterima" value={receivedFeedback.length} testId="peer-stat-received" />
          <StatTile label="Rata-rata nilai" value={receivedFeedback.length ? Number(avgRating).toFixed(1).replace('.', ',') : '—'}
            sub={receivedFeedback.length ? 'Dari masukan yang diterima (skala 1–5)' : 'Belum ada masukan'} testId="peer-stat-avg" />
          <StatTile label="Masukan diberikan" value={givenFeedback.length} testId="peer-stat-given" />
        </div>
      )}>
      {loading && baris.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat masukan…</p>
      ) : (
        <TabelData kolom={kolom} baris={baris} onKlikBaris={setDetail} testId="peer-table"
          kosong={<EmptyState title={diterima ? 'Belum ada masukan yang diterima' : 'Belum ada masukan yang diberikan'}
            description={diterima ? 'Masukan dari rekan akan muncul di sini.' : 'Tekan Kirim masukan untuk memberi masukan ke rekan.'} />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="peer-detail"
          judul={diterima ? `Masukan dari ${siapa(detail)}` : `Masukan untuk ${siapa(detail)}`}
          keterangan={tgl(detail.created_at)}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kategori">{kategori(detail.category)}</BarisDetail>
            <BarisDetail label="Nilai"><Bintang rating={detail.rating} /></BarisDetail>
            <BarisDetail label="Anonim">{detail.is_anonymous ? 'Ya' : 'Tidak'}</BarisDetail>
            <BarisDetail label="Pesan"><span className="whitespace-pre-line">{detail.message}</span></BarisDetail>
          </dl>
        </DetailPopup>
      )}

      <FormPopup open={showSendDialog} onClose={() => setShowSendDialog(false)} ukuran="pendek" testId="peer-send-form"
        judul="Kirim masukan" keterangan="Masukan yang membangun membantu rekan berkembang."
        onSimpan={handleSend} menyimpan={sending} labelSimpan="Kirim">
        <Isian label="Kepada" wajib>
          <SmartNativeSelect value={formData.to_employee_id} onChange={(e) => setFormData({ ...formData, to_employee_id: e.target.value })}
            className="w-full" data-testid="peer-to">
            <option value="">— Pilih rekan kerja —</option>
            {peers.map(p => (
              <option key={p.id || p.employee_code} value={p.id || p.employee_code}>
                {`${p.name}${p.department ? ` - ${p.department}` : ''}${p.job_title ? ` (${p.job_title})` : ''}`}
              </option>
            ))}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Nilai" wajib>
          <div className="flex items-center gap-1" role="radiogroup" aria-label="Nilai">
            {[1, 2, 3, 4, 5].map(r => (
              <Button key={r} type="button" variant="ghost" size="icon" role="radio" aria-checked={formData.rating === r}
                title={`${r} bintang`} aria-label={`${r} bintang`} onClick={() => setFormData({ ...formData, rating: r })}>
                <Star className={`!h-6 !w-6 ${r <= formData.rating ? 'fill-[hsl(var(--warning))] text-[hsl(var(--warning))]' : 'text-muted-foreground/50'}`} />
              </Button>
            ))}
          </div>
        </Isian>
        <Isian label="Kategori">
          <SmartNativeSelect value={formData.category} onChange={(e) => setFormData({ ...formData, category: e.target.value })}
            searchable={false} className="w-full">
            {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Pesan" wajib htmlFor="peer-message">
          <Textarea id="peer-message" placeholder="Tulis masukan yang konstruktif dan membangun…" rows={4}
            value={formData.message} onChange={e => setFormData({ ...formData, message: e.target.value })} />
        </Isian>
        <label className="flex items-center gap-3 text-sm">
          <Switch checked={formData.is_anonymous} onCheckedChange={v => setFormData({ ...formData, is_anonymous: v })} />
          Kirim sebagai anonim
        </label>
      </FormPopup>
    </PageLayout>
  );
}
