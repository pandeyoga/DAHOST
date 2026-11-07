/**
 * MarketingWebhooksModule — Monitor webhook (Portal Toko).
 *
 * Monitor dan kelola event webhook dari marketplace (Tokopedia, Shopee, TikTok).
 * Mendukung pengulangan event yang gagal dan kiriman uji manual.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, daftar = tabel (kartu ringkas di HP),
 * detail = popup, form uji = FormPopup, unduh Excel/CSV (semua baris hasil saringan), bahasa Indonesia.
 * Tampilan "Kartu" lama diganti tabel. Panggilan API & data yang dikirim tidak berubah.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { RefreshCw, RotateCcw, Search, Send, FileJson } from 'lucide-react';
import { Button } from '../../ui/button';
import { Input } from '../../ui/input';
import { Textarea } from '../../ui/textarea';
import SmartNativeSelect from '../../ui/smart-native-select';
import TabelData from '../../ui/tabel-data';
import TombolUnduh from '../../ui/tombol-unduh';
import FormPopup, { Isian } from '../../ui/form-popup';
import DetailPopup, { BarisDetail } from '../../ui/detail-popup';
import PaginationLite from '../../ui/pagination-lite';
import { useToast } from '../../../hooks/use-toast';
import { daysAheadWIB } from '../../../lib/waktu';
import { formatDateTimeID } from '../../../lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import WebhookSecurityPanel from './WebhookSecurityPanel';

const API = process.env.REACT_APP_BACKEND_URL || '';

const PLATFORM_LABELS = { tokopedia: 'Tokopedia', shopee: 'Shopee', tiktok: 'TikTok', manual: 'Manual' };
const labelPlatform = (p) => PLATFORM_LABELS[p] || p || '—';
const waktu = (v) => {
  if (!v) return '—';
  const s = String(v);
  const d = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? '—' : formatDateTimeID(d);
};

function keadaan(evt) {
  if (evt.error === 'duplicate') return { label: 'Duplikat', tone: 'muted' };
  if (evt.error) return { label: 'Galat', tone: 'danger' };
  if (evt.processed) return { label: 'Diproses', tone: 'success' };
  return { label: 'Menunggu', tone: 'warning' };
}
function StatusEvent({ evt }) {
  const k = keadaan(evt);
  return <StatusBadge status={k.label} label={k.label} tone={k.tone} />;
}

const LIMIT = 20;

export default function MarketingWebhooksModule({ user, headers }) {
  const [events, setEvents] = useState([]);
  const [stats, setStats] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filterPlatform, setFilterPlatform] = useState('');
  const [filterProcessed, setFilterProcessed] = useState('');
  const [search, setSearch] = useState('');
  const [skip, setSkip] = useState(0);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [showManualIngest, setShowManualIngest] = useState(false);
  const [manualForm, setManualForm] = useState({ platform: 'tokopedia', payload: '' });
  const [manualSending, setManualSending] = useState(false);
  const [galatUji, setGalatUji] = useState('');
  const { toast } = useToast();
  const authH = useMemo(() => headers || {}, [headers]);

  const paramSaring = useCallback(() => {
    const params = {};
    if (filterPlatform) params.platform = filterPlatform;
    if (filterProcessed !== '') params.processed = filterProcessed === 'true';
    return params;
  }, [filterPlatform, filterProcessed]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = { skip, limit: LIMIT, ...paramSaring() };
      const [evtRes, statsRes] = await Promise.all([
        axios.get(`${API}/api/marketing/webhooks/events`, { headers: authH, params }),
        axios.get(`${API}/api/marketing/webhooks/stats`, { headers: authH }),
      ]);
      setEvents(evtRes.data?.data || []);
      setTotal(evtRes.data?.total || 0);
      setStats(statsRes.data?.data || []);
    } catch (e) {
      toast({ title: 'Gagal memuat event webhook', description: e.response?.data?.detail || 'Coba muat ulang.', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [skip, paramSaring, authH, toast]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleReprocess = async (eventId) => {
    try {
      await axios.post(`${API}/api/marketing/webhooks/events/${eventId}/reprocess`, {}, { headers: authH });
      toast({ title: 'Event diantrekan untuk diproses ulang.' });
      setSelectedEvent(null);
      fetchData();
    } catch (e) {
      toast({ title: 'Gagal memproses ulang', description: e.response?.data?.detail || 'Coba lagi.', variant: 'destructive' });
    }
  };

  const handleManualIngest = async () => {
    setManualSending(true);
    setGalatUji('');
    try {
      let parsedPayload;
      try { parsedPayload = JSON.parse(manualForm.payload); }
      catch { throw new Error('Isi kiriman bukan JSON yang sah.'); }
      const res = await axios.post(
        `${API}/api/marketing/webhooks/manual`,
        { platform: manualForm.platform, event_type: 'order.new', payload: parsedPayload },
        { headers: authH },
      );
      toast({ title: 'Kiriman uji diterima', description: `Nomor event: ${res.data.event_id}` });
      setShowManualIngest(false);
      setManualForm({ platform: 'tokopedia', payload: '' });
      fetchData();
    } catch (e) {
      setGalatUji(e.response?.data?.detail || e.message || 'Gagal mengirim kiriman uji.');
    } finally {
      setManualSending(false);
    }
  };

  const TOKOPEDIA_SAMPLE = JSON.stringify({
    message: "Push Notification Tokopedia",
    message_id: `tokped-test-${Date.now()}`,
    order: {
      order_id: Math.floor(Math.random() * 9000000 + 1000000),
      invoice_ref_num: `INV/TEST/${Date.now()}`,
      order_status: 10,
      buyer: { name: "Test Buyer" },
      total_amount: 150000,
      products: [{ product_id: "SKU-001", name: "Test Product", quantity: 1, subtotal: 150000 }],
      est_start_delivery: daysAheadWIB(2),
    },
  }, null, 2);

  const SHOPEE_SAMPLE = JSON.stringify({
    code: "ORDER_STATUS_UPDATE",
    shop_id: 12345,
    data: {
      ordersn: `TEST${Date.now()}`,
      status: "READY_TO_SHIP",
      buyer_username: "test_buyer",
      total_amount: 200000,
      ship_by_date: daysAheadWIB(2),
      item_list: [{ item_sku: "SKU-002", item_name: "Test Item", model_quantity_purchased: 2, model_discounted_price: 100000 }],
    },
  }, null, 2);

  const cocok = (e, q) => !q
    || (e.platform || '').includes(q.toLowerCase())
    || (e.event_type || '').includes(q.toLowerCase())
    || (e.id || '').includes(q);
  const filtered = events.filter((e) => cocok(e, search));

  /** Unduh: semua event hasil saringan (bukan hanya halaman ini) — memakai API yang sama, per 200 baris. */
  const ambilSemua = async () => {
    const semua = [];
    for (let s = 0; s < 20000; s += 200) {
      const res = await axios.get(`${API}/api/marketing/webhooks/events`, {
        headers: authH, params: { skip: s, limit: 200, ...paramSaring() },
      });
      const d = res.data?.data || [];
      semua.push(...d);
      if (d.length < 200 || semua.length >= (res.data?.total || 0)) break;
    }
    return semua.filter((e) => cocok(e, search));
  };

  const tombolUlangi = (evt) => (evt.error && evt.error !== 'duplicate') && (
    <Button variant="outline" size="sm" onClick={() => handleReprocess(evt.id)} data-testid={`btn-reprocess-${evt.id}`}>
      <RotateCcw />Ulangi
    </Button>
  );

  const kolom = [
    { kunci: 'platform', label: 'Platform', hp: 'judul', isi: (e) => <span className="font-medium">{labelPlatform(e.platform)}</span> },
    { kunci: 'jenis', label: 'Jenis event', hp: 'keterangan', isi: (e) => <code className="text-xs">{e.event_type || '—'}</code> },
    { kunci: 'status', label: 'Status', isi: (e) => <StatusEvent evt={e} /> },
    { kunci: 'pesanan', label: 'Nomor pesanan', isi: (e) => <span className="tabular-nums">{e.normalized_order?.platform_order_id || '—'}</span> },
    { kunci: 'diterima', label: 'Diterima', isi: (e) => <span className="tabular-nums md:whitespace-nowrap">{waktu(e.received_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (e) => tombolUlangi(e) || null },
  ];

  const halaman = Math.floor(skip / LIMIT) + 1;
  const adaSaring = !!(filterPlatform || filterProcessed !== '' || search);

  return (
    <PageLayout testId="marketing-webhooks" title="Monitor webhook"
      subtitle="Event masuk dari Tokopedia, Shopee, dan TikTok Shop; event yang gagal bisa diulang."
      actions={
        <Button variant="outline" onClick={() => { setGalatUji(''); setShowManualIngest(true); }} data-testid="btn-manual-ingest">
          <Send />Uji kirim event
        </Button>
      }
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari platform, jenis event, nomor" value={search} onChange={(e) => setSearch(e.target.value)}
            className="pl-8" data-testid="input-webhook-search" />
        </div>
        <SmartNativeSelect value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setSkip(0); }}
          className="w-40" data-testid="select-platform" searchable={false}>
          <option value="">Semua platform</option>
          <option value="tokopedia">Tokopedia</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
          <option value="manual">Manual</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={filterProcessed} onChange={(e) => { setFilterProcessed(e.target.value); setSkip(0); }}
          className="w-44" data-testid="select-processed" searchable={false}>
          <option value="">Semua status</option>
          <option value="true">Diproses</option>
          <option value="false">Menunggu atau galat</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="event-webhook" namaLembar="Event" baris={filtered} ambilSemua={ambilSemua} testId="webhooks-unduh"
          kolom={[
            { label: 'Platform', nilai: (e) => labelPlatform(e.platform) },
            { label: 'Jenis event', nilai: (e) => e.event_type || '' },
            { label: 'Status', nilai: (e) => keadaan(e).label },
            { label: 'Nomor pesanan', nilai: (e) => e.normalized_order?.platform_order_id || '' },
            { label: 'Diterima', nilai: (e) => waktu(e.received_at) },
            { label: 'Galat', nilai: (e) => (e.error && e.error !== 'duplicate' ? e.error : '') },
            { label: 'Nomor event', nilai: (e) => e.id },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchData} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="btn-refresh-webhooks">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        <WebhookSecurityPanel headers={authH} />
        {stats.length > 0 && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="webhooks-stats">
            {stats.slice(0, 4).map((s) => (
              <StatTile key={s.platform} label={labelPlatform(s.platform)} value={s.total}
                sub={`${s.processed} diproses · ${s.errors} galat · ${String(s.success_rate).replace('.', ',')}% berhasil`}
                subTone={s.errors > 0 ? 'danger' : undefined}
                hint="Semua event yang pernah diterima dari platform ini (tidak ikut penyaring)." />
            ))}
          </div>
        )}
      </>}
      footer={total > LIMIT && (
        <PaginationLite page={halaman} totalPages={Math.ceil(total / LIMIT)} total={total} pageSize={LIMIT}
          onPageChange={(p) => setSkip((p - 1) * LIMIT)} />
      )}>
      {loading && events.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat event…</p>
      ) : (
        <TabelData kolom={kolom} baris={filtered} onKlikBaris={setSelectedEvent} testId="webhooks-table"
          kosong={<EmptyState title={adaSaring ? 'Tidak ada event yang cocok' : 'Belum ada event webhook'}
            description={adaSaring ? 'Ubah saringan atau kata pencarian.' : 'Event muncul saat platform mengirim webhook. Pakai "Uji kirim event" untuk mencoba.'} />} />
      )}

      {selectedEvent && (
        <DetailPopup open onClose={() => setSelectedEvent(null)} testId="webhook-event-detail"
          judul={`Event ${labelPlatform(selectedEvent.platform)}`} status={<StatusEvent evt={selectedEvent} />}
          aksi={tombolUlangi(selectedEvent) || null}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Nomor event"><code className="text-xs">{selectedEvent.id}</code></BarisDetail>
            <BarisDetail label="Jenis event"><code className="text-xs">{selectedEvent.event_type || '—'}</code></BarisDetail>
            <BarisDetail label="Diterima">{waktu(selectedEvent.received_at)}</BarisDetail>
            <BarisDetail label="Nomor pesanan">{selectedEvent.normalized_order?.platform_order_id || '—'}</BarisDetail>
            {selectedEvent.error && <BarisDetail label="Galat"><span className="text-[hsl(var(--danger-text))]">{selectedEvent.error}</span></BarisDetail>}
          </dl>
          {selectedEvent.normalized_order && (
            <div>
              <p className="mb-2 text-sm font-medium text-foreground">Data pesanan yang dibaca</p>
              <pre className="max-h-80 overflow-auto rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3 text-xs text-foreground/80">
                {JSON.stringify(selectedEvent.normalized_order, null, 2)}
              </pre>
            </div>
          )}
        </DetailPopup>
      )}

      <FormPopup open={showManualIngest} onClose={() => setShowManualIngest(false)} ukuran="panjang"
        judul="Uji kirim event webhook" keterangan="Kirim contoh isi webhook untuk mencoba alur penerimaan pesanan."
        onSimpan={handleManualIngest} menyimpan={manualSending} bisaSimpan={!!manualForm.payload} labelSimpan="Kirim"
        galat={galatUji} testId="webhook-manual-form">
        <Isian label="Platform" htmlFor="wh-platform">
          <SmartNativeSelect id="wh-platform" value={manualForm.platform} searchable={false}
            onChange={(e) => setManualForm((f) => ({ ...f, platform: e.target.value }))} data-testid="select-manual-platform">
            <option value="tokopedia">Tokopedia</option>
            <option value="shopee">Shopee</option>
            <option value="tiktok">TikTok</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Isi kiriman (JSON)" wajib htmlFor="wh-payload" petunjuk="Klik Isi contoh untuk memakai contoh pesanan.">
          <Textarea id="wh-payload" value={manualForm.payload} rows={10} placeholder='{"order": {...}}'
            onChange={(e) => setManualForm((f) => ({ ...f, payload: e.target.value }))}
            className="text-xs tabular-nums" data-testid="textarea-webhook-payload" />
        </Isian>
        <Button type="button" variant="outline" size="sm" onClick={() => {
          const sample = manualForm.platform === 'shopee' ? SHOPEE_SAMPLE : TOKOPEDIA_SAMPLE;
          setManualForm((f) => ({ ...f, payload: sample }));
        }} data-testid="btn-load-sample"><FileJson />Isi contoh</Button>
      </FormPopup>
    </PageLayout>
  );
}
