/**
 * Retur Fisik — Portal Gudang (Blueprint §3.7)
 *
 * Tipe 1: Expedition Return   — paket kembali dari ekspedisi
 * Tipe 2: Customer Refund     — pembeli minta refund di marketplace
 *
 * Alur: Menunggu (Pending) → Diterima (unboxing) → Diinspeksi → Selesai (resolusi)
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (dulu kepala buatan + 4 tombol warna-warni + 6 kartu
 * berwarna + 2 kartu tipe besar); tab buatan → pil tampilan; StatTile berketerangan (maks 4); tabel = TabelData
 * + unduhan Excel/CSV; detail = DetailPopup; tiap langkah (terima, inspeksi, selesaikan, batalkan, terima &
 * putuskan) = FormPopup — dulu form menempel di bawah panel detail; window.confirm/prompt/alert → confirmDialog
 * & toast; status/tipe berbahasa Indonesia. Aturan, isian, dan API tidak berubah.
 */

import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import {
  Package, Plus, Search, RefreshCw, CheckCircle, Truck, RotateCcw, ChevronDown,
  PackageOpen, XCircle, Trash2, ClipboardCheck, DownloadCloud, Link2, Zap, MapPin, Undo2, Info,
} from 'lucide-react';
import OnwardCTA from './OnwardCTA';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from './moduleAtoms';
import { formatRupiah } from '@/lib/format';
import { MoneyInput } from '@/components/ui/money-input';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
// W4 (sesi #29) — barang retur WAJIB dipilih dari master produk jadi (INV-F14).
import { FGMaterialSelect } from './masters/MasterSelects';

const API = process.env.REACT_APP_BACKEND_URL || '';

const CHANNELS   = ['Shopee', 'Tokopedia', 'TikTok Shop', 'Lazada', 'Instagram', 'WhatsApp', 'Lainnya'];
// W4 — kondisi 'Rusak' ditambah supaya pilihan pemilik (Baik/Rusak) ada apa adanya.
const CONDITIONS = ['Baik', 'Rusak', 'Rusak Ringan', 'Rusak Berat', 'Tidak Layak Jual'];
const CAUSES     = ['Kesalahan Gudang', 'Kesalahan Customer', 'Kesalahan Ekspedisi', 'Lainnya'];
// 2026-11-02 (K1) — keputusan gudang: Terima → stok jual · Rusak → karantina ·
// Tolak → dikembalikan ke pembeli (tanpa stok/jurnal) · Dibuang.
const REJECT_TO_BUYER = 'Ditolak — Dikembalikan ke Pembeli';
const ACTIONS    = ['Restock ke Gudang', 'Karantina (Rusak)', REJECT_TO_BUYER, 'Reshipment', 'Appeal Platform', 'Dibuang / Dispose', 'Donasi'];
const QTY_ACTIONS = ['Restock ke Gudang', 'Karantina (Rusak)'];
const APPEAL_STATUSES = ['Pending', 'Success', 'Fail'];
// Kondisi yang boleh masuk stok JUAL. Sisanya ditahan di karantina (K-6a).
const SELLABLE_CONDITIONS = ['Baik'];

// Nilai disimpan apa adanya (kontrak backend); yang tampil label staf.
const ACTION_LABEL = {
  'Restock ke Gudang': 'Masuk stok gudang', 'Karantina (Rusak)': 'Karantina (rusak)',
  [REJECT_TO_BUYER]: 'Ditolak — dikembalikan ke pembeli', Reshipment: 'Kirim ulang ke pembeli',
  'Appeal Platform': 'Banding ke platform', 'Dibuang / Dispose': 'Dibuang', Donasi: 'Donasi',
};
const APPEAL_LABEL = { Pending: 'Menunggu', Success: 'Berhasil', Fail: 'Gagal' };
const actionLabel = (a) => ACTION_LABEL[a] || a || '—';

const TYPE_LABELS = {
  expedition_return: 'Tipe 1 — Ekspedisi',
  customer_refund:   'Tipe 2 — Pembeli',
};
const TYPE_TONE = { expedition_return: 'warning', customer_refund: 'primary' };
const STATUS_META = {
  Pending:   { label: 'Menunggu paket', tone: 'warning' },
  Received:  { label: 'Diterima', tone: 'info' },
  Inspected: { label: 'Diinspeksi', tone: 'primary' },
  Resolved:  { label: 'Selesai', tone: 'success' },
  Cancelled: { label: 'Dibatalkan', tone: 'muted' },
  Reversed:  { label: 'Keputusan dibalik', tone: 'warning' },
};
const statusLabel = (s) => STATUS_META[s]?.label || s || '—';
const CONDITION_TONE = {
  Baik: 'text-[hsl(var(--success-text))]', Rusak: 'text-[hsl(var(--danger-text))]',
  'Rusak Ringan': 'text-[hsl(var(--warning-text))]', 'Rusak Berat': 'text-[hsl(var(--warning-text))]',
  'Tidak Layak Jual': 'text-[hsl(var(--danger-text))]',
};

function StatusRetur({ status }) {
  const m = STATUS_META[status] || { label: status || '—', tone: 'default' };
  return <StatusBadge status={status} label={m.label} tone={m.tone} />;
}
function TipeRetur({ type }) {
  return <StatusBadge status={type} label={TYPE_LABELS[type] || type || '—'} tone={TYPE_TONE[type] || 'default'} />;
}

// ─── W4 — LENCANA "APA YANG TERJADI PADA STOK" ────────────────────────────────
// Pemilik harus bisa melihat, tanpa membuka detail, apakah barang retur sudah
// benar-benar masuk stok (dan stok mana: jual atau karantina).
const efekStok = (ret) => {
  if (ret.restocked) {
    const sellable = ret.stock_effect === 'sellable';
    return { label: sellable ? `+${ret.restock_qty} stok jual` : `+${ret.restock_qty} karantina`, tone: sellable ? 'success' : 'warning' };
  }
  if (ret.link_status && ret.link_status !== 'linked') return { label: 'Belum tertaut master', tone: 'danger' };
  return { label: 'Belum masuk stok', tone: 'muted' };
};
function StockBadge({ ret }) {
  const e = efekStok(ret);
  return <span data-testid={`stock-badge-${ret.id}`}><StatusBadge label={e.label} tone={e.tone} /></span>;
}
function SourceBadge({ ret }) {
  const fromMkt = !!ret.source_marketing_return_id;
  return (
    <span data-testid={`source-badge-${ret.id}`}>
      <StatusBadge label={fromMkt ? 'Marketing' : 'Manual'} tone={fromMkt ? 'primary' : 'muted'} />
    </span>
  );
}

function fmtDate(iso) {
  if (!iso) return '-';
  try { return new Date(iso).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso?.slice(0, 16) || '-'; }
}
function fmtDateShort(iso) {
  if (!iso) return '-';
  try { return new Date(iso).toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }); }
  catch { return iso?.slice(0, 10) || '-'; }
}
const fmtCurrency = formatRupiah;

async function api(method, path, token, body) {
  const opts = { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
}

// ─── Langkah alur (titik kecil) ───────────────────────────────────────────────
const STEPS = ['Pending', 'Received', 'Inspected', 'Resolved'];
function WorkflowBar({ status }) {
  const idx = STEPS.indexOf(status);
  if (status === 'Cancelled') return <span className="text-xs text-muted-foreground">Dibatalkan</span>;
  return (
    <div className="flex items-center gap-1" aria-label={`Tahap: ${statusLabel(status)}`}>
      {STEPS.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div className={`h-2 w-2 rounded-full ${i <= idx ? 'bg-primary' : 'bg-foreground/10'}`} />
          {i < STEPS.length - 1 && <div className={`h-px w-6 ${i < idx ? 'bg-primary' : 'bg-foreground/10'}`} />}
        </div>
      ))}
    </div>
  );
}

// ─── FORM CATAT RETUR (popup panjang) ─────────────────────────────────────────
function CreateModal({ onClose, onSaved, token, defaultType }) {
  const [form, setForm] = useState({
    return_type: defaultType || 'expedition_return',
    order_number: '', resi_number: '', channel: '',
    customer_name: '', customer_contact: '',
    material_id: '', sku_code: '', product_name: '', qty: 1,
    order_value: 0, initial_reason: '', notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  // SESI #19 — kebijakan penomoran Retur Gudang (Otomatis/Manual).
  const numPolicy = useDocNumberPolicy('wh_returns.return_code', token);
  const [returnCode, setReturnCode] = useState('');

  const submit = async () => {
    if (!form.order_number && !form.resi_number) { setErr('Nomor order atau resi wajib diisi'); return; }
    if (!form.material_id) { setErr('Barang jadi wajib dipilih dari master — tanpa itu stok tidak bisa bertambah.'); return; }
    if (numPolicy?.mode === 'manual' && !returnCode.trim()) {
      setErr(`Nomor retur wajib diisi (pola ${numPolicy.format}).`); return;
    }
    setSaving(true); setErr('');
    try {
      const ret = await api('POST', '/api/wh/returns', token, {
        ...form, ...docNumberPayload(numPolicy, 'return_code', returnCode),
      });
      onSaved(ret);
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="create-return-form"
      judul="Catat retur baru" keterangan="Barang wajib dipilih dari master produk jadi supaya stok bisa bertambah tepat sasaran."
      onSimpan={submit} menyimpan={saving} galat={err} labelSimpan="Catat retur">
      <DocNumberField policy={numPolicy} value={returnCode} onChange={setReturnCode} label="Nomor retur" testId="whret-number" />
      <Isian label="Tipe retur" wajib htmlFor="ret-tipe">
        <SmartNativeSelect id="ret-tipe" value={form.return_type} onChange={e => setForm({ ...form, return_type: e.target.value })}
          data-testid="ret-type">
          {Object.entries(TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SmartNativeSelect>
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="No. order" htmlFor="ret-order" petunjuk="Isi no. order atau no. resi (salah satu wajib).">
          <Input id="ret-order" value={form.order_number} onChange={e => setForm({ ...form, order_number: e.target.value })}
            placeholder="SPX-00001" data-testid="ret-order-number" />
        </Isian>
        <Isian label="No. resi" htmlFor="ret-resi">
          <Input id="ret-resi" value={form.resi_number} onChange={e => setForm({ ...form, resi_number: e.target.value })}
            placeholder="JNE-123456" data-testid="ret-resi-number" />
        </Isian>
        <Isian label="Channel" htmlFor="ret-channel">
          <SmartNativeSelect id="ret-channel" value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })} data-testid="ret-channel">
            <option value="">Pilih channel</option>
            {CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Nama pembeli" htmlFor="ret-customer">
          <Input id="ret-customer" value={form.customer_name} onChange={e => setForm({ ...form, customer_name: e.target.value })}
            placeholder="Nama pembeli" data-testid="ret-customer-name" />
        </Isian>
      </div>
      {/* W4 — BARANG DARI MASTER (bukan ketikan): teks bebas tidak pernah cocok dengan master ⇒ stok tak bergerak. */}
      <Isian label="Barang jadi yang kembali" wajib petunjuk="Wajib dari Master Produk Jadi — inilah yang membuat stok bisa bertambah tepat sasaran.">
        <FGMaterialSelect value={form.material_id} onChange={(v) => setForm({ ...form, material_id: v })}
          label={null} testId="ret-material-select" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Qty retur" htmlFor="ret-qty">
          <Input id="ret-qty" type="number" min="1" value={form.qty} onChange={e => setForm({ ...form, qty: +e.target.value })} data-testid="ret-qty" />
        </Isian>
        <Isian label="Nilai order (Rp)" htmlFor="ret-nilai">
          <MoneyInput id="ret-nilai" value={form.order_value} onChange={e => setForm({ ...form, order_value: +e.target.value })}
            placeholder="0" data-testid="ret-order-value" />
        </Isian>
      </div>
      <Isian label="Alasan retur (awal)" htmlFor="ret-alasan">
        <Textarea id="ret-alasan" rows={2} value={form.initial_reason} onChange={e => setForm({ ...form, initial_reason: e.target.value })}
          placeholder="Barang tidak sampai / ukuran tidak sesuai / dll." data-testid="ret-reason" />
      </Isian>
    </FormPopup>
  );
}

// ─── DETAIL (popup) + FORM LANGKAH (popup) ───────────────────────────────────
function DetailPanel({ ret, token, onClose, onRefresh, onNavigate }) {
  const [data, setData] = useState(ret);
  // Dibuka dari tombol "Terima & putuskan" di tabel → langsung form cepat (tanpa kedip popup detail).
  const [step, setStep] = useState(ret?._openQuick ? 'quick' : null); // 'receive' | 'inspect' | 'resolve' | 'cancel' | 'quick'
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [info, setInfo] = useState('');

  // Aksi cepat dari tabel membuka form "Terima & putuskan" LANGSUNG.
  useEffect(() => {
    if (ret && ret._openQuick) { setStep('quick'); setForm({}); setErr(''); setInfo(''); }
  }, [ret]);

  const openStep = (s) => { setStep(s); setForm({}); setErr(''); setInfo(''); };
  const tutupStep = () => { if (!saving) { setStep(null); setErr(''); } };

  const doReceive = async () => {
    if (!form.unboxing_condition_notes) { setErr('Catatan unboxing wajib diisi'); return; }
    setSaving(true); setErr('');
    try {
      const d = await api('POST', `/api/wh/returns/${data.id}/receive`, token, form);
      setData(d); setStep(null); onRefresh();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const doInspect = async () => {
    if (!form.item_condition || !form.return_cause) { setErr('Kondisi item dan penyebab wajib diisi'); return; }
    setSaving(true); setErr('');
    try {
      const d = await api('POST', `/api/wh/returns/${data.id}/inspect`, token, form);
      setData(d); setStep(null); onRefresh();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const doResolve = async () => {
    if (!form.action_taken) { setErr('Aksi wajib dipilih'); return; }
    setSaving(true); setErr('');
    try {
      const d = await api('POST', `/api/wh/returns/${data.id}/resolve`, token, form);
      setData(d); setStep(null); onRefresh();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  // 2026-11-02 (K1) — keputusan yang SUDAH dibukukan hanya bisa dibalik: stok keluar
  // berjejak + jurnal pembalik; pekerjaan baru dibuka untuk diputuskan ulang.
  const doReverse = async () => {
    const reason = await confirmDialog({
      title: 'Balik keputusan retur ini?',
      body: 'Stok yang sudah masuk dikeluarkan lagi (berjejak) dan jurnal pembalik dibuat; pekerjaan dibuka ulang untuk diputuskan.',
      confirmLabel: 'Balik keputusan', danger: true,
      input: { label: 'Alasan (wajib)', placeholder: 'mis. Marketing menolak retur, barang dikembalikan ke pembeli', minLength: 1 },
    });
    if (!reason || !String(reason).trim()) return;
    setSaving(true); setErr('');
    try {
      const res = await api('POST', `/api/wh/returns/${data.id}/reverse-decision`, token, { reason, reopen: true });
      setData(res.reopened || res.data || data);
      setInfo(res.message || 'Keputusan dibalik');
      toast.success(res.message || 'Keputusan dibalik');
      onRefresh();
    } catch (e) { setErr(e.message); toast.error(e.message); }
    finally { setSaving(false); }
  };

  const doCancel = async () => {
    if (!(await confirmDialog({ title: 'Batalkan retur ini?', body: `${data.return_code} tidak diproses lagi.`, confirmLabel: 'Batalkan retur', danger: true }))) return;
    setSaving(true);
    try {
      const d = await api('POST', `/api/wh/returns/${data.id}/cancel`, token, { reason: form.reason || 'Dibatalkan manual' });
      setData(d); setStep(null); onRefresh();
    } catch (e) { setErr(e.message); toast.error(e.message); }
    finally { setSaving(false); }
  };

  // ── W4 (sesi #29) — SATU KLIK: terima + inspeksi + selesai + masuk stok ────
  // Kondisi menentukan lokasi: Baik → ZNA-FG (ikut stok jual), Rusak → ZNA-KARANTINA.
  const doQuickRestock = async () => {
    setSaving(true); setErr('');
    try {
      const res = await api('POST', `/api/wh/returns/${data.id}/quick-restock`, token, {
        condition: form.condition || 'Baik',
        qty: form.restock_qty ?? data.received_qty ?? data.qty,
        note: form.action_notes || '',
      });
      setData(res.data || data);
      setStep(null);
      setInfo(res.message || 'Stok diperbarui');
      toast.success(res.message || 'Stok diperbarui');
      onRefresh();
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const doRelink = async () => {
    setSaving(true); setErr('');
    try {
      const res = await api('POST', `/api/wh/returns/${data.id}/relink`, token, {});
      setData(res.data || data);
      setInfo(res.link_status === 'linked'
        ? 'Berhasil ditautkan ke master barang — sekarang bisa dimasukkan ke stok.'
        : (res.reason || 'Masih belum bisa ditautkan.'));
    } catch (e) { setErr(e.message); }
    finally { setSaving(false); }
  };

  const linked = !!(data.material_id || data.fg_material_id);
  const isEditable = !['Resolved', 'Cancelled', 'Reversed'].includes(data.status);
  const aksiResolve = form.action_taken || data.recommended_action || '';
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  // Satu popup terbuka pada satu waktu: form langkah menggantikan popup detail; Batal kembali ke detail.
  if (step === 'quick') {
    return (
      <FormPopup open onClose={tutupStep} ukuran="pendek" testId="quick-restock-form"
        judul={`Terima & putuskan · ${data.return_code}`}
        keterangan="Barang diterima (qty aktual), diperiksa, lalu diputuskan dalam satu langkah. Baik → Area Produk Jadi (stok jual); Rusak → Area Karantina. Untuk menolak atau membuang, pakai alur Terima → Inspeksi → Selesaikan."
        onSimpan={doQuickRestock} menyimpan={saving} galat={err} labelSimpan="Masukkan ke stok">
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kondisi barang" wajib htmlFor="q-kondisi">
            <SmartNativeSelect id="q-kondisi" value={form.condition || 'Baik'} onChange={set('condition')} data-testid="quick-condition">
              {CONDITIONS.map(c => <option key={c} value={c}>{c}{SELLABLE_CONDITIONS.includes(c) ? ' — masuk stok jual' : ' — masuk karantina'}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label={`Qty aktual masuk (pengajuan ${data.qty})`} wajib htmlFor="q-qty">
            <Input id="q-qty" type="number" min="1" max={data.received_qty ?? data.qty} value={form.restock_qty ?? data.received_qty ?? data.qty}
              onChange={e => setForm({ ...form, restock_qty: +e.target.value })} data-testid="quick-qty" />
          </Isian>
        </div>
        <Isian label="Catatan" htmlFor="q-catatan">
          <Input id="q-catatan" value={form.action_notes || ''} onChange={set('action_notes')} placeholder="Opsional" data-testid="quick-note" />
        </Isian>
        {err && <span className="sr-only" data-testid="quick-err">{err}</span>}
      </FormPopup>
    );
  }
  if (step === 'receive') {
    return (
      <FormPopup open onClose={tutupStep} ukuran="pendek" testId="receive-form"
        judul={`Terima & unboxing · ${data.return_code}`} onSimpan={doReceive} menyimpan={saving} galat={err} labelSimpan="Konfirmasi terima">
        {/* 2026-11-02 (K1) — qty AKTUAL di paket = batas qty keputusan */}
        <Isian label={`Qty aktual diterima (pengajuan ${data.qty})`} wajib htmlFor="rcv-qty">
          <Input id="rcv-qty" type="number" min="0" value={form.received_qty ?? data.qty}
            onChange={e => setForm({ ...form, received_qty: Math.max(0, parseInt(e.target.value || '0', 10)) })} data-testid="receive-qty" />
        </Isian>
        <Isian label="Kondisi kemasan luar" htmlFor="rcv-kemasan">
          <Input id="rcv-kemasan" value={form.package_condition || ''} onChange={set('package_condition')} placeholder="Segel utuh / basah / sobek / dll." />
        </Isian>
        <Isian label="Kode / tautan bukti foto atau video unboxing" htmlFor="rcv-bukti">
          <Input id="rcv-bukti" value={form.unboxing_photo_notes || ''} onChange={set('unboxing_photo_notes')}
            placeholder="IMG_001 / tautan Google Drive / dll." data-testid="unboxing-photo" />
        </Isian>
        <Isian label="Catatan kondisi saat unboxing" wajib htmlFor="rcv-catatan">
          <Textarea id="rcv-catatan" rows={3} value={form.unboxing_condition_notes || ''} onChange={set('unboxing_condition_notes')}
            placeholder="Barang tampak normal, bungkus dalam sobek, item masih berplastik…" data-testid="unboxing-notes" />
        </Isian>
      </FormPopup>
    );
  }
  if (step === 'inspect') {
    return (
      <FormPopup open onClose={tutupStep} ukuran="pendek" testId="inspect-form"
        judul={`Inspeksi kondisi · ${data.return_code}`} onSimpan={doInspect} menyimpan={saving} galat={err} labelSimpan="Simpan inspeksi">
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Kondisi item" wajib htmlFor="ins-kondisi">
            <SmartNativeSelect id="ins-kondisi" value={form.item_condition || ''} onChange={set('item_condition')} data-testid="inspect-condition">
              <option value="">Pilih kondisi</option>
              {CONDITIONS.map(c => <option key={c} value={c}>{c}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Penyebab retur" wajib htmlFor="ins-penyebab">
            <SmartNativeSelect id="ins-penyebab" value={form.return_cause || ''} onChange={set('return_cause')} data-testid="inspect-cause">
              <option value="">Pilih penyebab</option>
              {CAUSES.map(c => <option key={c} value={c}>{c}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Detail penyebab" htmlFor="ins-detail">
          <Input id="ins-detail" value={form.cause_detail || ''} onChange={set('cause_detail')} placeholder="Jelaskan lebih rinci…" />
        </Isian>
        <Isian label="Rekomendasi tindakan" htmlFor="ins-rekomendasi">
          <SmartNativeSelect id="ins-rekomendasi" value={form.recommended_action || ''} onChange={set('recommended_action')} data-testid="inspect-action">
            <option value="">Otomatis (dari penyebab)</option>
            {ACTIONS.map(a => <option key={a} value={a}>{actionLabel(a)}</option>)}
          </SmartNativeSelect>
        </Isian>
      </FormPopup>
    );
  }
  if (step === 'resolve') {
    return (
      <FormPopup open onClose={tutupStep} ukuran="pendek" testId="resolve-form"
        judul={`Selesaikan retur · ${data.return_code}`} onSimpan={doResolve} menyimpan={saving} galat={err} labelSimpan="Selesaikan">
        <Isian label="Tindakan yang diambil" wajib htmlFor="res-aksi">
          <SmartNativeSelect id="res-aksi" value={aksiResolve} onChange={set('action_taken')} data-testid="resolve-action">
            <option value="">Pilih tindakan</option>
            {ACTIONS.map(a => <option key={a} value={a}>{actionLabel(a)}</option>)}
          </SmartNativeSelect>
        </Isian>
        {aksiResolve === 'Reshipment' && (
          <Isian label="No. resi kirim ulang" htmlFor="res-resi">
            <Input id="res-resi" value={form.reshipment_resi || ''} onChange={set('reshipment_resi')}
              placeholder="Resi pengiriman ulang" data-testid="reshipment-resi" />
          </Isian>
        )}
        {aksiResolve === 'Appeal Platform' && (
          <Isian label="Status banding" htmlFor="res-banding">
            <SmartNativeSelect id="res-banding" value={form.appeal_status || ''} onChange={set('appeal_status')} data-testid="appeal-status">
              <option value="">Pilih status</option>
              {APPEAL_STATUSES.map(s => <option key={s} value={s}>{APPEAL_LABEL[s] || s}</option>)}
            </SmartNativeSelect>
          </Isian>
        )}
        {QTY_ACTIONS.includes(aksiResolve) && (
          <Isian label={`Qty masuk stok / karantina (maks. diterima ${data.received_qty ?? data.qty})`} htmlFor="res-qty">
            <Input id="res-qty" type="number" min="1" max={data.received_qty ?? data.qty} value={form.restock_qty ?? data.received_qty ?? data.qty}
              onChange={e => setForm({ ...form, restock_qty: +e.target.value })} data-testid="restock-qty" />
          </Isian>
        )}
        <Isian label="Catatan resolusi" htmlFor="res-catatan">
          <Textarea id="res-catatan" rows={2} value={form.action_notes || ''} onChange={set('action_notes')}
            placeholder="Catatan tambahan tindakan yang diambil…" />
        </Isian>
      </FormPopup>
    );
  }
  if (step === 'cancel') {
    return (
      <FormPopup open onClose={tutupStep} ukuran="pendek" testId="cancel-form"
        judul={`Batalkan retur · ${data.return_code}`} onSimpan={doCancel} menyimpan={saving} galat={err} labelSimpan="Batalkan retur">
        <Isian label="Alasan pembatalan" htmlFor="btl-alasan">
          <Textarea id="btl-alasan" rows={2} value={form.reason || ''} onChange={set('reason')} placeholder="Kenapa retur ini dibatalkan?" />
        </Isian>
      </FormPopup>
    );
  }

  return (
    <DetailPopup open onClose={onClose} testId="wh-return-detail"
      judul={data.return_code}
      keterangan={`Tahap: ${statusLabel(data.status)}`}
      status={<><TipeRetur type={data.return_type} /><StatusRetur status={data.status} /></>}
      aksi={isEditable ? (
        <>
          {!data.restocked && linked && (
            <Button size="sm" variant="success" onClick={() => openStep('quick')} data-testid="btn-quick-restock"><Zap />Terima &amp; putuskan</Button>
          )}
          {data.status === 'Pending' && (
            <Button size="sm" onClick={() => openStep('receive')} data-testid="btn-receive"><PackageOpen />Terima barang</Button>
          )}
          {data.status === 'Received' && (
            <Button size="sm" onClick={() => openStep('inspect')} data-testid="btn-inspect"><ClipboardCheck />Inspeksi kondisi</Button>
          )}
          {data.status === 'Inspected' && (
            <Button size="sm" variant="success" onClick={() => openStep('resolve')} data-testid="btn-resolve"><CheckCircle />Selesaikan</Button>
          )}
          <Button size="sm" variant="destructive" onClick={() => openStep('cancel')} data-testid="btn-cancel-return"><XCircle />Batalkan</Button>
        </>
      ) : data.status === 'Resolved' ? (
        <Button size="sm" variant="outline" onClick={doReverse} disabled={saving} data-testid="btn-reverse-decision">
          <Undo2 />Balik keputusan
        </Button>
      ) : null}>
      <WorkflowBar status={data.status} />
      {err && <Notice tone="danger" title={err} />}
      {info && <Notice tone="success" icon={CheckCircle} testId="ret-info" title={info} />}
      <dl className="grid gap-x-6 sm:grid-cols-2">
        <BarisDetail label="No. order">{data.order_number || '-'}</BarisDetail>
        <BarisDetail label="No. resi">{data.resi_number || '-'}</BarisDetail>
        <BarisDetail label="Channel">{data.channel || '-'}</BarisDetail>
        <BarisDetail label="Pembeli">{data.customer_name || '-'}</BarisDetail>
        <BarisDetail label="Produk">{data.product_name || data.sku_code || '-'}</BarisDetail>
        <BarisDetail label="Qty">{data.qty} pcs</BarisDetail>
        <BarisDetail label="Nilai order">{fmtCurrency(data.order_value)}</BarisDetail>
        <BarisDetail label="Dicatat">{fmtDateShort(data.created_at)}{data.created_by ? ` · ${data.created_by}` : ''}</BarisDetail>
        {data.initial_reason && <BarisDetail label="Alasan awal">{data.initial_reason}</BarisDetail>}
      </dl>

      {/* ── W4 — TAUTAN MASTER BARANG & EFEK STOK: "barang apa persisnya yang kembali, dan sudah masuk stok?" */}
      <section className="space-y-2" data-testid="ret-master-link">
        <div className="flex flex-wrap items-center gap-2">
          <Link2 className="h-4 w-4 text-primary" />
          <p className="text-sm font-medium">Tautan master barang &amp; stok</p>
          <StockBadge ret={data} />
        </div>
        {linked ? (
          <dl className="grid gap-x-6 sm:grid-cols-2">
            <BarisDetail label="Kode master"><span className="tabular-nums" data-testid="ret-sku-code">{data.sku_code || '—'}</span></BarisDetail>
            <BarisDetail label="Nama">{data.product_name || '—'}</BarisDetail>
            <BarisDetail label="Kategori">{data.material_category || '—'}</BarisDetail>
            <BarisDetail label="Warna / opsi">{[data.material_color, data.material_option].filter(Boolean).join(' · ') || '—'}</BarisDetail>
            {data.restocked && (
              <>
                <BarisDetail label="Masuk lokasi">
                  <span className="inline-flex items-center gap-1" data-testid="ret-restock-location">
                    <MapPin className="h-3 w-3" />{data.restock_location_name || data.restock_location_code || '—'}
                  </span>
                </BarisDetail>
                <BarisDetail label="Kondisi"><span className={`font-medium ${CONDITION_TONE[data.restock_condition] || ''}`}>{data.restock_condition || '—'}</span></BarisDetail>
              </>
            )}
          </dl>
        ) : (
          <Notice tone="warning" title={<span data-testid="ret-link-reason">{data.link_reason || 'Barang retur ini belum tertaut ke master produk jadi, jadi stok tidak bisa ditambah.'}</span>}
            action={data.source_marketing_return_id && (
              <Button size="sm" variant="outline" onClick={doRelink} disabled={saving} data-testid="btn-relink">
                <RefreshCw />Coba tautkan ulang
              </Button>
            )}>
            {(data.link_candidates || []).length > 0 && (
              <>
                Kandidat barang di pesanan ini:
                <ul className="ml-5 mt-1 list-disc space-y-0.5">
                  {data.link_candidates.map((c, i) => (
                    <li key={i}>{c.product_name} {c.variation ? `· ${c.variation}` : ''} ({c.quantity} pcs)</li>
                  ))}
                </ul>
              </>
            )}
          </Notice>
        )}
        {data.restock_error && <p className="text-xs text-[hsl(var(--danger-text))]">Gagal masuk stok: {data.restock_error}</p>}
      </section>

      {data.status !== 'Pending' && data.received_at && (
        <section className="space-y-1">
          <p className="text-sm font-medium">Penerimaan &amp; unboxing <span className="font-normal text-muted-foreground">· {fmtDate(data.received_at)} · {data.received_by}</span></p>
          <dl className="grid gap-x-6 sm:grid-cols-2">
            <BarisDetail label="Kondisi kemasan">{data.package_condition || '-'}</BarisDetail>
            <BarisDetail label="Bukti foto/video">{data.unboxing_photo_notes || '-'}</BarisDetail>
            <BarisDetail label="Catatan unboxing">{data.unboxing_condition_notes || '-'}</BarisDetail>
          </dl>
        </section>
      )}

      {['Inspected', 'Resolved'].includes(data.status) && (
        <section className="space-y-1">
          <p className="text-sm font-medium">Hasil inspeksi <span className="font-normal text-muted-foreground">· {fmtDate(data.inspected_at)} · {data.inspected_by}</span></p>
          <dl className="grid gap-x-6 sm:grid-cols-2">
            <BarisDetail label="Kondisi item"><span className={`font-medium ${CONDITION_TONE[data.item_condition] || ''}`}>{data.item_condition || '-'}</span></BarisDetail>
            <BarisDetail label="Penyebab">{data.return_cause || '-'}</BarisDetail>
            {data.cause_detail && <BarisDetail label="Detail">{data.cause_detail}</BarisDetail>}
            <BarisDetail label="Rekomendasi">{actionLabel(data.recommended_action)}</BarisDetail>
          </dl>
        </section>
      )}

      {data.status === 'Resolved' && (
        <section className="space-y-1">
          <p className="text-sm font-medium">Resolusi <span className="font-normal text-muted-foreground">· {fmtDate(data.resolved_at)} · {data.resolved_by}</span></p>
          <dl className="grid gap-x-6 sm:grid-cols-2">
            <BarisDetail label="Tindakan">{actionLabel(data.action_taken)}</BarisDetail>
            {data.reshipment_resi && <BarisDetail label="Resi kirim ulang"><span className="tabular-nums">{data.reshipment_resi}</span></BarisDetail>}
            {data.appeal_status && <BarisDetail label="Status banding">{APPEAL_LABEL[data.appeal_status] || data.appeal_status}</BarisDetail>}
            {data.received_qty != null && <BarisDetail label="Qty diterima">{data.received_qty} pcs</BarisDetail>}
            {data.restock_qty > 0 && <BarisDetail label="Qty masuk stok">{data.restock_qty} pcs</BarisDetail>}
            {data.action_notes && <BarisDetail label="Catatan">{data.action_notes}</BarisDetail>}
            {data.source_marketing_return_id && (
              <BarisDetail label="Retur Toko asal"><span className="tabular-nums">{data.source_marketing_return_id.slice(0, 8)}…</span></BarisDetail>
            )}
          </dl>
          {data.marketing_rejected_after_decision && (
            <Notice tone="warning" testId="wh-mkt-rejected-after" title="Marketing menolak/menghapus retur ini setelah keputusan gudang">
              Bila barang harus keluar lagi, tekan <b>Balik keputusan</b> (stok keluar berjejak + jurnal pembalik).
            </Notice>
          )}
          {/* RC-FLOW-UX-11b: retur asal Toko selesai → kembali ke Marketing untuk credit note */}
          {data.source_marketing_return_id && onNavigate && (
            <OnwardCTA
              onNavigate={onNavigate}
              title="Barang sudah masuk stok — langkah berikutnya"
              actions={[
                { module: 'marketing-after-sales', params: { tab: 'returns', return_id: data.source_marketing_return_id },
                  label: 'Terbitkan credit note & refund', primary: true,
                  hint: 'Kembali ke portal Toko untuk menerbitkan credit note', testId: 'onward-issue-credit-note' },
                { module: 'wms-stock-hub', params: { tab: 'stock' }, label: 'Cek stok barang jadi',
                  hint: 'Periksa stok setelah barang masuk', testId: 'onward-check-stock' },
              ]}
            />
          )}
        </section>
      )}

      {(data.timeline || []).length > 0 && (
        <section className="space-y-2">
          <p className="text-sm font-medium">Riwayat</p>
          <ol className="space-y-2 border-l border-[var(--glass-border)] pl-4">
            {[...(data.timeline || [])].reverse().map((t, i) => (
              <li key={i} className="text-sm">
                <span className="inline-flex flex-wrap items-center gap-2">
                  <StatusRetur status={t.status} />
                  <span className="text-xs text-muted-foreground">oleh {t.by} · {fmtDate(t.at)}</span>
                </span>
                {t.note && <p className="mt-0.5 text-xs text-muted-foreground">{t.note}</p>}
              </li>
            ))}
          </ol>
        </section>
      )}
    </DetailPopup>
  );
}

// ─── TABEL RETUR ──────────────────────────────────────────────────────────────
const KOLOM_UNDUH = [
  { label: 'Kode', nilai: (r) => r.return_code },
  { label: 'Asal', nilai: (r) => (r.source_marketing_return_id ? 'Marketing' : 'Manual') },
  { label: 'Tipe', nilai: (r) => TYPE_LABELS[r.return_type] || r.return_type },
  { label: 'No. order', nilai: (r) => r.order_number || '' },
  { label: 'No. resi', nilai: (r) => r.resi_number || '' },
  { label: 'Channel', nilai: (r) => r.channel || '' },
  { label: 'Pembeli', nilai: (r) => r.customer_name || '' },
  { label: 'Barang', nilai: (r) => r.product_name || '' },
  { label: 'Kode master', nilai: (r) => r.sku_code || '' },
  { label: 'Qty', nilai: (r) => Number(r.qty || 0) },
  { label: 'Status', nilai: (r) => statusLabel(r.status) },
  { label: 'Efek stok', nilai: (r) => efekStok(r).label },
  { label: 'Tanggal', nilai: (r) => fmtDateShort(r.created_at) },
];

function ReturnsTable({ returns, loading, onView, onDelete, onQuickRestock, kosong }) {
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(returns, 25);
  if (loading && !returns.length) return <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>;
  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'judul', isi: (r) => <span className="font-medium tabular-nums" data-testid={`ret-row-${r.id}`}>{r.return_code}</span> },
    { kunci: 'asal', label: 'Asal', isi: (r) => <SourceBadge ret={r} /> },
    { kunci: 'order', label: 'No. order / resi', hp: 'keterangan', isi: (r) => r.order_number || r.resi_number || '-' },
    { kunci: 'barang', label: 'Barang (master)', isi: (r) => (
      <div className="min-w-0">
        <p className="font-medium">{r.product_name || '-'}</p>
        <p className="text-xs tabular-nums text-muted-foreground">{r.sku_code || '—'}</p>
      </div>) },
    { kunci: 'qty', label: 'Qty', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.qty || 0}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusRetur status={r.status} /> },
    { kunci: 'stok', label: 'Efek stok', isi: (r) => <StockBadge ret={r} /> },
    { kunci: 'tgl', label: 'Tanggal', isi: (r) => <span className="whitespace-nowrap">{fmtDateShort(r.created_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => {
      // 2026-11-02 (K1) — hanya pekerjaan yang BELUM diputuskan
      const canQuick = !r.restocked && ['Pending', 'Received', 'Inspected'].includes(r.status) && (r.material_id || r.fg_material_id);
      return (
        <div className="flex items-center justify-end gap-1.5">
          {canQuick && onQuickRestock && (
            <Button size="sm" variant="success" onClick={() => onQuickRestock(r)} title="Terima (qty aktual) & putuskan masuk stok"
              data-testid={`quick-restock-${r.id}`}>
              <Zap />Terima &amp; putuskan
            </Button>
          )}
          {r.status === 'Pending' && !r.restocked && (
            <Button size="icon-sm" variant="ghost" onClick={() => onDelete(r)} aria-label={`Hapus retur ${r.return_code}`}
              title="Hapus retur" data-testid={`del-ret-${r.id}`}>
              <Trash2 className="text-[hsl(var(--danger-text))]" />
            </Button>
          )}
        </div>
      );
    } },
  ];
  return (
    <div className="space-y-3">
      <TabelData kolom={kolom} baris={paged} onKlikBaris={onView} testId="wh-returns-table" kosong={kosong} />
      {total > 0 && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}
    </div>
  );
}

const TAMPILAN = [
  { key: 'dashboard', label: 'Ringkasan' },
  { key: 'expedition', label: 'Tipe 1 — Ekspedisi' },
  { key: 'customer', label: 'Tipe 2 — Pembeli' },
  { key: 'all', label: 'Semua retur' },
];

// ─── ROOT ─────────────────────────────────────────────────────────────────────
export default function WHReturnsModule({ token, onNavigate }) {
  const [tab, setTab]         = useState('dashboard');
  const [returns, setReturns] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch]   = useState('');
  const [statusF, setStatusF] = useState('');
  const [selected, setSelected] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createType, setCreateType] = useState(null);
  // W4 (sesi #29) — jembatan Marketing → Gudang
  const [gap, setGap] = useState(null);
  const [pulling, setPulling] = useState(false);
  const [pullMsg, setPullMsg] = useState('');
  // Ringkasan (dulu komponen tab sendiri) — diangkat ke sini supaya bisa dimuat ulang & diunduh dari toolbar.
  const [summary, setSummary] = useState(null);
  const [actionItems, setActionItems] = useState([]);
  const [dashLoading, setDashLoading] = useState(true);

  const loadGap = useCallback(async () => {
    try { setGap(await api('GET', '/api/wh/returns/marketing-gap', token)); }
    catch (e) { /* ringkasan jembatan bersifat informatif — jangan matikan layar */ }
  }, [token]);
  useEffect(() => { loadGap(); }, [loadGap]);

  const loadDashboard = useCallback(async () => {
    setDashLoading(true);
    try {
      const [s, items] = await Promise.all([
        api('GET', '/api/wh/returns/summary', token),
        // Item yang perlu aksi (Menunggu + Diterima + Diinspeksi)
        Promise.all(['Pending', 'Received', 'Inspected'].map((st) => api('GET', `/api/wh/returns?status=${st}`, token)))
          .then((ls) => ls.flatMap((d) => (Array.isArray(d) ? d : []))),
      ]);
      setSummary(s);
      setActionItems(items.sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 20));
    } catch (e) { console.error(e); }
    finally { setDashLoading(false); }
  }, [token]);

  const load = useCallback(async (type, extra = {}) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (type)           params.set('return_type', type);
      if (extra.status)   params.set('status', extra.status);
      if (extra.search)   params.set('search', extra.search);
      const data = await api('GET', `/api/wh/returns?${params}`, token);
      setReturns(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => {
    if (tab === 'dashboard')  loadDashboard();
    if (tab === 'expedition') load('expedition_return', { status: statusF, search });
    if (tab === 'customer')   load('customer_refund',   { status: statusF, search });
    if (tab === 'all')        load('', { status: statusF, search });
  }, [tab, statusF, search, load, loadDashboard]);

  const refreshCurrent = () => {
    loadGap();
    if (tab === 'dashboard')  loadDashboard();
    if (tab === 'expedition') load('expedition_return', { status: statusF, search });
    if (tab === 'customer')   load('customer_refund',   { status: statusF, search });
    if (tab === 'all')        load('', { status: statusF, search });
  };

  const onView = (ret) => setSelected(ret);
  const onDelete = async (ret) => {
    if (!(await confirmDialog({ title: `Hapus retur ${ret.return_code}?`, body: 'Pekerjaan retur yang belum diterima ini dihapus.', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      await api('DELETE', `/api/wh/returns/${ret.id}`, token);
      toast.success(`Retur ${ret.return_code} dihapus.`);
      refreshCurrent();
    } catch (e) { toast.error(e.message); }
  };

  // Aksi cepat dari baris tabel: langsung ke form "Terima & putuskan" supaya kondisi (Baik/Rusak) & qty
  // tetap DIPILIH manusia — bukan diam-diam ditebak.
  const onQuickRestock = (ret) => setSelected({ ...ret, _openQuick: true });

  // Tarik retur pembeli dari Marketing (idempoten; aman ditekan berulang).
  const pullFromMarketing = async () => {
    setPulling(true); setPullMsg('');
    try {
      const res = await api('POST', '/api/wh/returns/sync-marketing', token, { dry_run: false });
      const d = res.data || {};
      // 2026-11-02 (K1) — tarik HANYA membuat pekerjaan Menunggu; stok menunggu keputusan.
      setPullMsg(`Diperiksa ${d.scanned} retur Marketing · ${d.created} pekerjaan baru (menunggu paket) · `
        + `${d.skipped} perlu dipilih produknya`
        + (d.failed ? ` · ${d.failed} gagal` : ''));
      refreshCurrent();
    } catch (e) { setPullMsg(`Gagal menarik retur: ${e.message}`); }
    finally { setPulling(false); }
  };

  const quickCreate = (type) => { setCreateType(type); setShowCreate(true); };
  const ringkasan = tab === 'dashboard';
  const barisUnduh = ringkasan ? actionItems : returns;
  const kosongDaftar = (
    <EmptyState icon={RotateCcw} testId="wh-ret-empty" title="Belum ada retur fisik di daftar ini"
      description='Retur pembeli dari Marketing masuk ke sini otomatis. Bila ada yang tertinggal, tekan "Tarik retur dari Marketing".' />
  );

  return (
    <PageLayout testId="wh-returns-module" title="Retur Fisik"
      subtitle="Terima, periksa, dan putuskan barang retur: masuk stok, karantina, kirim ulang, atau dibuang."
      actions={<>
        <Button variant="outline" onClick={pullFromMarketing} disabled={pulling} data-testid="btn-pull-marketing">
          <DownloadCloud className={pulling ? 'animate-pulse' : ''} />{pulling ? 'Menarik…' : 'Tarik retur dari Marketing'}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" data-testid="btn-add-typed">Catat per tipe<ChevronDown /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => quickCreate('expedition_return')} data-testid="btn-add-expedition">
              <Truck className="mr-2 h-4 w-4" />Tipe 1 — paket kembali dari ekspedisi
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => quickCreate('customer_refund')} data-testid="btn-add-customer">
              <RotateCcw className="mr-2 h-4 w-4" />Tipe 2 — pembeli minta refund
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button onClick={() => { setCreateType(null); setShowCreate(true); }} data-testid="btn-add-return"><Plus />Catat retur</Button>
      </>}
      filters={<>
        <FilterChips className="w-full sm:w-auto" options={TAMPILAN} value={tab} onChange={setTab} hideWhenEmpty={false} testId="wh-ret-tab" />
        {!ringkasan && (
          <>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari kode, no. order, resi, pembeli"
                className="pl-8" data-testid="wh-ret-search" />
            </div>
            <SmartNativeSelect value={statusF} onChange={e => setStatusF(e.target.value)} aria-label="Status retur"
              className="w-full sm:w-44" wrapperClassName="w-full sm:w-44" data-testid="wh-ret-status-filter">
              <option value="">Semua status</option>
              {Object.entries(STATUS_META).map(([s, m]) => <option key={s} value={s}>{m.label}</option>)}
            </SmartNativeSelect>
          </>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas={ringkasan ? 'retur-perlu-tindakan' : 'retur-fisik'} namaLembar="Retur fisik"
            baris={barisUnduh} kolom={KOLOM_UNDUH} testId="wh-ret-unduh" />
          <Button variant="outline" size="icon" onClick={refreshCurrent} disabled={loading || (ringkasan && dashLoading)}
            title="Muat ulang" aria-label="Muat ulang" data-testid="wh-ret-refresh">
            <RefreshCw className={loading || (ringkasan && dashLoading) ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      summary={<>
        {/* W4 — jembatan Marketing → Gudang: retur pembeli yang belum punya pekerjaan fisik di sini. */}
        {gap && (
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" data-testid="mkt-bridge-banner">
            <span className="font-medium">Retur dari Marketing</span>
            <span><span className="text-muted-foreground">Retur pembeli </span><strong className="tabular-nums" data-testid="gap-mkt-total">{gap.marketing_returns_total}</strong></span>
            <span><span className="text-muted-foreground">Sudah terhubung </span><strong className="tabular-nums" data-testid="gap-bridged">{gap.already_bridged}</strong></span>
            <span><span className="text-muted-foreground">Belum ditarik </span>
              <strong className={`tabular-nums ${gap.pending_bridge > 0 ? 'text-[hsl(var(--warning-text))]' : ''}`} data-testid="gap-pending">{gap.pending_bridge}</strong>
            </span>
            <span><span className="text-muted-foreground">Sudah masuk stok </span><strong className="tabular-nums" data-testid="gap-restocked">{gap.restocked}</strong></span>
            {gap.needs_link > 0 && (
              <span><span className="text-muted-foreground">Perlu dipilih produknya </span><strong className="tabular-nums text-[hsl(var(--danger-text))]" data-testid="gap-needs-link">{gap.needs_link}</strong></span>
            )}
          </p>
        )}
        {pullMsg && <Notice tone="info" icon={Info} testId="pull-msg" title={pullMsg} />}
        {ringkasan && summary && summary.total > 0 && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="wh-ret-stats">
            <StatTile label="Total retur" value={summary.total}
              sub={`Tipe 1 ekspedisi ${summary.expedition_returns} · tipe 2 pembeli ${summary.customer_refunds}`} />
            <StatTile label="Perlu tindakan" value={summary.action_needed} accent={summary.action_needed > 0 ? 'warning' : 'default'}
              sub={`Menunggu ${summary.pending} · diterima ${summary.received} · diinspeksi ${summary.inspected}`} />
            <StatTile label="Selesai" value={summary.resolved} sub="Sudah diputuskan (masuk stok, karantina, kirim ulang, dll.)" />
            <StatTile label="Lainnya" value={Math.max(0, summary.total - summary.action_needed - summary.resolved)}
              sub="Dibatalkan atau keputusan dibalik" />
          </div>
        )}
      </>}
      footer={(
        // RC-FLOW-UX — setelah barang retur diterima → cek/perbarui stok (Alur 8 selesai)
        <OnwardCTA
          onNavigate={onNavigate}
          title="Setelah barang retur diterima"
          actions={[
            { module: 'wms-stock-hub', label: 'Lihat & sesuaikan stok', icon: Package, primary: true, hint: 'Barang retur layak jual masuk kembali ke stok' },
          ]}
        />
      )}>
      {ringkasan ? (
        dashLoading && !summary ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat ringkasan…</p>
        ) : actionItems.length > 0 ? (
          <section className="space-y-2">
            {/* Daftar dibatasi 20 terbaru — judul menyebut jumlah sebenarnya (dulu jumlah yang ditampilkan saja). */}
            <p className="text-sm font-medium">
              Perlu tindakan ({summary?.action_needed ?? actionItems.length})
              {(summary?.action_needed ?? 0) > actionItems.length && <span className="font-normal text-muted-foreground"> · menampilkan {actionItems.length} terbaru</span>}
            </p>
            <ReturnsTable returns={actionItems} loading={dashLoading} onView={onView} onDelete={onDelete} onQuickRestock={onQuickRestock} kosong={kosongDaftar} />
          </section>
        ) : (
          <EmptyState icon={CheckCircle} title="Semua retur sudah ditangani"
            description={gap?.pending_bridge > 0
              ? `Tidak ada pekerjaan di gudang, tetapi ${gap.pending_bridge} retur pembeli di Marketing belum ditarik.`
              : 'Tidak ada yang perlu tindakan saat ini.'}
            action={gap?.pending_bridge > 0 ? <Button variant="outline" onClick={pullFromMarketing} disabled={pulling}><DownloadCloud />Tarik retur dari Marketing</Button> : null} />
        )
      ) : (
        <ReturnsTable returns={returns} loading={loading} onView={onView} onDelete={onDelete} onQuickRestock={onQuickRestock} kosong={kosongDaftar} />
      )}

      {selected && (
        <DetailPanel ret={selected} token={token} onClose={() => setSelected(null)}
          onRefresh={() => { setSelected(null); refreshCurrent(); }} onNavigate={onNavigate} />
      )}

      {showCreate && (
        <CreateModal token={token} defaultType={createType}
          onClose={() => setShowCreate(false)}
          onSaved={(ret) => { setShowCreate(false); setSelected(ret); refreshCurrent(); }} />
      )}
    </PageLayout>
  );
}
