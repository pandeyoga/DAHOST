/**
 * LiveSessionDialog — form input/ubah SESI LIVE (F16).
 *
 * Kenapa layar ini baru ada sekarang: audit 2026-08-11 menemukan
 * `marketing_live_sessions_routes.py` hanya punya endpoint GET — sesi live tidak
 * bisa dicatat lewat aplikasi, padahal di situlah bertemunya omzet toko, jam
 * kerja host, dan performa produk.
 *
 * Dua aturan yang ditegakkan dan terlihat di form:
 *   · TOKO wajib, lalu HOST dipilih dari daftar yang SUDAH di-assign ke toko itu.
 *     Server menolak host yang belum di-assign — supaya jam kerja & bayarannya
 *     tidak dibebankan ke toko yang tidak memakainya.
 *   · Engagement / conversion / AOV dihitung, tidak diketik.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang (dulu Dialog buatan sendiri), tanggal = DatePicker (dulu
 * input type="date"), status = SmartNativeSelect, label Indonesia (Likes/Shares/Revenue/AOV → Suka/Dibagikan/
 * Omzet/Rata-rata per pesanan). Tombol Simpan kini ber-testid live-form-simpan (dulu live-save).
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Calculator } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { useToast } from '@/hooks/use-toast';
import axios from 'axios';
import { MarketingAccountSelect, MarketingHostSelect } from './pickers/MarketingPickers';
import LiveSessionProductsEditor from './LiveSessionProductsEditor';
import { todayWIB } from '@/lib/waktu';

const API = process.env.REACT_APP_BACKEND_URL;
const STATUS_LABEL = {
  scheduled: 'Dijadwalkan', live: 'Sedang live',
  completed: 'Selesai', cancelled: 'Dibatalkan',
};
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;

const EMPTY = {
  account_id: '', host_id: '', session_date: '', title: '', start_time: '',
  duration_minutes: '', peak_viewers: '', total_viewers: '', likes: '',
  comments: '', shares: '', orders: '', revenue: '', units_sold: '',
  products_featured: '', status: 'completed', notes_text: '',
};

export default function LiveSessionDialog({ open, onClose, onSaved, token, session }) {
  const { toast } = useToast();
  const authH = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  // F18#3 — rincian produk ikut satu form/satu simpan.
  const [lines, setLines] = useState([]);

  useEffect(() => {
    if (!open) return;
    if (session) {
      setForm({
        ...EMPTY, ...session,
        session_date: String(session.session_date || '').slice(0, 10),
        notes_text: '',
      });
      // rincian yang sudah ada dimuat supaya menyimpan sesi tidak menghapusnya
      (async () => {
        try {
          const r = await axios.get(
            `${API}/api/marketing/live/sessions/${session.id}/products`, { headers: authH });
          setLines(r.data?.data?.products || []);
        } catch (e) { setLines([]); }
      })();
    } else {
      setForm({ ...EMPTY, session_date: todayWIB() });
      setLines([]);
    }
  }, [open, session, authH]);

  const set = (k) => (e) => setForm((f) => ({
    ...f, [k]: e?.target ? e.target.value : e,
  }));
  const n = (k) => Number(form[k] || 0);
  const derived = {
    engagement: n('total_viewers')
      ? ((n('likes') + n('comments') + n('shares')) / n('total_viewers') * 100) : 0,
    conversion: n('total_viewers') ? (n('orders') / n('total_viewers') * 100) : 0,
    aov: n('orders') ? (n('revenue') / n('orders')) : 0,
    rpm: n('duration_minutes') ? (n('revenue') / n('duration_minutes')) : 0,
  };

  const submit = async () => {
    if (!form.account_id || !form.host_id) {
      toast({ title: 'Toko dan host wajib dipilih', variant: 'destructive' }); return;
    }
    if (!form.session_date || !form.title) {
      toast({ title: 'Tanggal & judul sesi wajib', variant: 'destructive' }); return;
    }
    setSaving(true);
    try {
      const num = ['duration_minutes', 'peak_viewers', 'total_viewers', 'likes',
        'comments', 'shares', 'orders', 'revenue', 'units_sold', 'products_featured'];
      const payload = { ...form };
      num.forEach((k) => { payload[k] = Number(form[k] || 0); });
      // F18#3 — rincian produk dikirim bersama sesinya. Baris tanpa produk
      // (baris kosong yang belum diisi) tidak dikirim, bukan disimpan setengah.
      payload.products = (lines || [])
        .filter((l) => l.catalog_item_id)
        .map((l) => ({
          catalog_item_id: l.catalog_item_id,
          units_sold: Number(l.units_sold || 0),
          revenue: Number(l.revenue || 0),
          orders: Number(l.orders || 0),
          notes: l.notes || '',
        }));
      if (session?.id) {
        await axios.put(`${API}/api/marketing/live/sessions/${session.id}`, payload, { headers: authH });
      } else {
        await axios.post(`${API}/api/marketing/live/sessions`, payload, { headers: authH });
      }
      toast({ title: session?.id ? 'Sesi live diperbarui' : 'Sesi live disimpan' });
      onSaved?.();
      onClose?.();
    } catch (e) {
      toast({
        title: 'Gagal menyimpan',
        description: e.response?.data?.detail || e.message,
        variant: 'destructive',
      });
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="live-form"
      judul={session?.id ? 'Ubah sesi live' : 'Catat sesi live'}
      keterangan="Angka diambil dari dasbor platform sesudah live selesai."
      onSimpan={submit} labelSimpan={session?.id ? 'Simpan perubahan' : 'Simpan'} menyimpan={saving}>
      <div className="grid gap-4 sm:grid-cols-2">
        <MarketingAccountSelect token={token} value={form.account_id}
          onChange={(v) => {
            // Ganti toko ⇒ rincian produk lama (milik katalog toko lain) tidak
            // sah lagi; dibersihkan di sini supaya penolakan server tidak
            // datang sebagai kejutan saat menyimpan.
            setForm((f) => ({ ...f, account_id: v, host_id: '' }));
            setLines([]);
          }}
          testId="live-account-select" />
        <MarketingHostSelect token={token} accountId={form.account_id}
          value={form.host_id} onChange={(v) => setForm((f) => ({ ...f, host_id: v }))}
          testId="live-host-select" />
        <Isian label="Tanggal sesi" wajib>
          <DatePicker value={form.session_date || ''} onChange={(v) => setForm((f) => ({ ...f, session_date: v }))} testId="live-date" />
        </Isian>
        <Isian label="Jam mulai" htmlFor="live-start">
          <Input id="live-start" type="time" value={form.start_time} onChange={set('start_time')} data-testid="live-start" />
        </Isian>
        <Isian label="Judul / tema sesi" wajib htmlFor="live-title" className="sm:col-span-2">
          <Input id="live-title" value={form.title} onChange={set('title')}
            placeholder="Live Gamis Malam — Flash Sale" data-testid="live-title" />
        </Isian>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {/* money=true → nominal Rupiah (MoneyInput, titik ribuan otomatis); sisanya hitungan. */}
        {[['duration_minutes', 'Durasi (menit)'], ['peak_viewers', 'Penonton puncak'],
          ['total_viewers', 'Total penonton'], ['likes', 'Suka'],
          ['comments', 'Komentar'], ['shares', 'Dibagikan'],
          ['orders', 'Jumlah pesanan'], ['revenue', 'Omzet (Rp)', true],
          ['units_sold', 'Item terjual'], ['products_featured', 'Produk dibawakan']]
          .map(([k, l, money]) => (
            <Isian key={k} label={l} htmlFor={`live-${k}`}>
              {money ? (
                <MoneyInput id={`live-${k}`} value={form[k]} onChange={set(k)}
                  className="tabular-nums" data-testid={`live-${k}`} />
              ) : (
                <Input id={`live-${k}`} type="number" min="0" value={form[k]} onChange={set(k)}
                  className="tabular-nums" data-testid={`live-${k}`} />
              )}
            </Isian>
          ))}
        <Isian label="Status">
          <SmartNativeSelect value={form.status} onChange={set('status')} searchable={false} data-testid="live-status">
            {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>

      <div className="rounded-[var(--radius-sm)] border border-[var(--glass-border)] p-3">
        <p className="mb-2 flex items-center gap-1.5 text-sm font-medium">
          <Calculator className="h-4 w-4" /> Dihitung otomatis (tidak bisa diketik)
        </p>
        <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4" data-testid="live-derived">
          <div><span className="text-muted-foreground">Interaksi</span><br /><b className="tabular-nums">{derived.engagement.toFixed(2).replace('.', ',')}%</b></div>
          <div><span className="text-muted-foreground">Konversi</span><br /><b className="tabular-nums">{derived.conversion.toFixed(2).replace('.', ',')}%</b></div>
          <div><span className="text-muted-foreground">Rata-rata per pesanan</span><br /><b className="tabular-nums">{rp(derived.aov.toFixed(0))}</b></div>
          <div><span className="text-muted-foreground">Omzet per menit</span><br /><b className="tabular-nums">{rp(derived.rpm.toFixed(0))}</b></div>
        </div>
      </div>

      <LiveSessionProductsEditor
        token={token} accountId={form.account_id} lines={lines}
        onChange={setLines} sessionRevenue={n('revenue')} disabled={saving}
      />

      <Isian label="Catatan sesi" htmlFor="live-notes">
        <Textarea id="live-notes" value={form.notes_text} onChange={set('notes_text')} rows={2}
          placeholder="mis. kendala jaringan menit 40, produk X paling laku…"
          data-testid="live-notes" />
      </Isian>
    </FormPopup>
  );
}
