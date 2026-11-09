/**
 * CatalogItemsView — TAB "ITEM" KATALOG (F4.4).
 *
 * KENAPA LAYAR INI ADA
 * --------------------
 * Pertanyaan marketing di layar ini: produk mana yang belum tayang, mana yang ditolak platform dan kenapa,
 * marjinnya berapa dan HPP-nya dari mana, harga kita beda berapa dari harga resmi master, fotonya ada?
 * Semua data itu dikirim endpoint item katalog.
 *
 * Standar UI/UX v2 (8 Nov 2026, keluhan owner): tabel 20 kolom + 11 ikon aksi per baris diganti tabel berisi
 * kolom penting saja; kolom lain dan SEMUA aksi ada di popup detail (klik baris). Per baris tampil paling banyak
 * 2 aksi (aksi penayangan + "Lainnya"). Penyaring satu baris; popup form standar; unduh Excel/CSV.
 * Tampilan kartu (grid foto) tetap ada, bawaan = tabel.
 *
 * AKSI CEPAT (klarifikasi owner 9 Nov 2026 §D): centang banyak baris → satu baris tombol: Isi harga dari master
 * (kosong saja / timpa) · Tayangkan yang ber-URL · Jadikan draf · Arsipkan · Kembalikan · Lainnya. Setiap aksi
 * massal menampilkan pratinjau (berapa berubah, berapa dilewati & alasannya) lalu bisa DIBATALKAN dari toast atau
 * Alat katalog › Riwayat aksi massal. "Tayangkan" massal hanya untuk item yang SUDAH punya URL sah sendiri — tidak
 * ada satu URL yang diisikan ke banyak produk, jadi bukti tayang per item tetap benar.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import {
  ExternalLink, Image as ImageIcon, Upload, Trash2, Pencil, Rocket, Loader2, AlertTriangle,
  XCircle, Archive, RotateCcw, Clock, Link2, ChevronUp, ChevronDown, Coins, ArrowRightLeft,
  MoreHorizontal, Search, SlidersHorizontal, Eye, FileSpreadsheet, Tags,
} from 'lucide-react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { PRODUCT_STATUS_OPTIONS, PRODUCT_STATUS_UNSET, productStatusLabel, productStatusTone } from '@/lib/productStatus';
import { alatUrl, batalkanAksi, panggil, ringkasLewati } from './catalogToolsApi';
import CatalogPriceUrlDialog from './CatalogPriceUrlDialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup,
  DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { CHIP_CLASS, CHIP_ACTIVE_CLASS } from '@/components/ui/tabs';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import ViewToggle from '@/components/ui/view-toggle';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { cn } from '@/lib/utils';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import { Toolbar } from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL || '';
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const angka = (n) => Number(n || 0).toLocaleString('id-ID');
const jam = (v) => formatDateTimeID(parseServerTime(v), { fallback: '—' });
const VIEW_KEY = 'catalog_items_view';   // pilihan tampilan bertahan antar sesi
const PER_HALAMAN = 25;

// Status katalog (dihitung server: penayangan + stok jual) → label & warna
const STATUS_CFG = {
  DRAFT: { label: 'Draf', tone: 'muted' },
  PRE_ORDER: { label: 'Pra-pesan', tone: 'primary' },
  ACTIVE: { label: 'Aktif', tone: 'success' },
  HABIS: { label: 'Habis', tone: 'warning' },
  NONAKTIF: { label: 'Nonaktif', tone: 'muted' },
  DITOLAK: { label: 'Ditolak', tone: 'danger' },
};
const PUBLISH_LABEL = { draft: 'Belum tayang', published: 'Tayang', rejected: 'Ditolak', archived: 'Diarsipkan' };
const SORT_OPTIONS = [
  ['name:asc', 'Nama A–Z'], ['status:asc', 'Status'], ['price:desc', 'Harga tertinggi'],
  ['margin:desc', 'Marjin tertinggi'], ['margin:asc', 'Marjin terendah'], ['stock:asc', 'Stok paling sedikit'],
  ['updated:desc', 'Terakhir diubah'],
];
const statusLabel = (r) => (STATUS_CFG[r.catalog_status] || STATUS_CFG.DRAFT).label;
const publishLabel = (r) => r.publish_state_label || PUBLISH_LABEL[r.publish_state] || r.publish_state || '—';
const belumTerukur = (r) => r.margin_status === 'belum_bisa_diukur';
// Sumber harga resmi master (backend core.product_master.official_price)
const SUMBER_HARGA = { sku: 'harga per SKU', model: 'harga model (cadangan)', none: 'belum ada' };
// Penyaring status produk: satu pilihan gabungan Stop & Dead (dipakai untuk "arsipkan yang Stop/Dead")
const OPSI_STATUS_PRODUK = [
  { value: 'stop,dead', label: 'Stop & Dead', kode: ['stop', 'dead'] },
  ...PRODUCT_STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label, kode: [o.value] })),
  { value: PRODUCT_STATUS_UNSET, label: 'Status belum diisi', kode: [PRODUCT_STATUS_UNSET] },
];
// Aksi massal penayangan (backend bulk-transition) — label tombol & judul konfirmasi
const AKSI_MASSAL = {
  publish: { judul: 'Tayangkan yang ber-URL', tombol: 'Tayangkan' },
  unpublish: { judul: 'Jadikan draf', tombol: 'Jadikan draf' },
  archive: { judul: 'Arsipkan', tombol: 'Arsipkan', alasan: true },
  restore: { judul: 'Kembalikan dari arsip', tombol: 'Kembalikan' },
  preorder: { judul: 'Tandai pra-pesan', tombol: 'Tandai pra-pesan' },
  unpreorder: { judul: 'Lepas tanda pra-pesan', tombol: 'Lepas pra-pesan' },
  reject: { judul: 'Tandai ditolak platform', tombol: 'Tandai ditolak', alasan: true, wajib: true },
};

function Thumb({ url, alt, besar = false }) {
  const ukuran = besar ? 'w-16 h-16' : 'w-10 h-10';
  if (!url) {
    return (
      <div className={cn(ukuran, 'shrink-0 rounded-[var(--radius-sm)] border border-border flex items-center justify-center')}
        title="Belum ada foto">
        <ImageIcon className="w-4 h-4 text-muted-foreground" />
      </div>
    );
  }
  return (
    <img src={`${API}${url.startsWith('/') ? url : `/${url}`}`} alt={alt || ''}
      className={cn(ukuran, 'shrink-0 rounded-[var(--radius-sm)] border border-border object-cover')}
      onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }} />
  );
}

function ItemStatus({ row }) {
  const cfg = STATUS_CFG[row.catalog_status] || STATUS_CFG.DRAFT;
  return (
    <span title={row.catalog_status_reason || ''} data-testid={`item-status-${row.sku}`}>
      <StatusBadge status={row.catalog_status} label={cfg.label} tone={cfg.tone} />
    </span>
  );
}

function Marjin({ r }) {
  // SESI #37 — HPP tidak diketahui ⇒ lencana, BUKAN 0%/100%.
  if (belumTerukur(r)) {
    return (
      <span title={r.margin_reason} data-testid={`catalog-margin-unknown-${r.sku || r.id}`}>
        <StatusBadge status="belum" label="Belum bisa diukur" tone="warning" />
      </span>
    );
  }
  return (
    <span className={cn('inline-flex flex-col items-end tabular-nums', Number(r.margin_pct) < 0 && 'font-medium text-[hsl(var(--danger-text))]')}>
      <span>{rp(r.margin)}</span>
      <span className="text-xs text-muted-foreground">{Number(r.margin_pct || 0).toLocaleString('id-ID')}%</span>
    </span>
  );
}

function StokJual({ r }) {
  if (r.available === null || r.available === undefined) return <span className="text-muted-foreground">—</span>;
  return (
    <span className={cn('tabular-nums', Number(r.available) <= 0 && 'font-medium text-[hsl(var(--warning-text))]')}>
      {angka(r.available)}
    </span>
  );
}

/* ── Popup: tayangkan (butuh URL sebagai bukti) ──────────────────────────────── */
function PublishDialog({ open, onOpenChange, item, catalogId, headers, onDone }) {
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (open) { setUrl(item?.platform_url || ''); setErr(''); }
  }, [open, item]);

  const save = async () => {
    setBusy(true); setErr('');
    try {
      const r = await fetch(
        `${API}/api/marketing/catalogs/${catalogId}/items/${item.id}/publish`,
        { method: 'POST', headers, body: JSON.stringify({ platform_url: url }) });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal menandai tayang');
      toast.success(b.message, { duration: 8000 });
      onOpenChange(false);
      onDone?.();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="pendek" onSimpan={save} menyimpan={busy}
      galat={err} labelSimpan="Tandai tayang" judul="Tandai tayang" testId="publish-dialog"
      keterangan={`${item?.name || ''} — tempel URL produk di marketplace sebagai bukti tayang.`}>
      <Isian label="URL produk" wajib htmlFor="publish-url"
        petunjuk="Tanpa tautan, status tayang tidak bisa diperiksa dan produk sulit dibuka saat ada komplain.">
        <Input id="publish-url" value={url} onChange={(e) => { setUrl(e.target.value); setErr(''); }}
          placeholder="https://tokopedia.com/toko/nama-produk" data-testid="publish-url" />
      </Isian>
    </FormPopup>
  );
}

/* ── Popup: alasan (tolak / arsip / turunkan) ────────────────────────────────── */
function ReasonDialog({ open, onOpenChange, title, describe, required, labelSimpan, onSubmit }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { if (open) { setReason(''); setErr(''); } }, [open]);
  const kirim = async () => {
    if (required && !reason.trim()) { setErr('Alasan wajib diisi.'); return; }
    setBusy(true);
    try { await onSubmit(reason.trim()); onOpenChange(false); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <FormPopup open={open} onClose={() => onOpenChange(false)} ukuran="pendek" onSimpan={kirim} menyimpan={busy}
      galat={err} judul={title} keterangan={describe} labelSimpan={labelSimpan || 'Simpan'} testId="reason-dialog">
      <Isian label="Alasan" wajib={required} htmlFor="reason-input">
        <Input id="reason-input" value={reason} onChange={(e) => { setReason(e.target.value); setErr(''); }}
          data-testid="reason-input" />
      </Isian>
    </FormPopup>
  );
}

/* ── Popup: kelola foto ──────────────────────────────────────────────────────── */
function PhotoDialog({ open, onOpenChange, item, catalogId, headers, onDone }) {
  const [row, setRow] = useState(item);
  const [busy, setBusy] = useState('');
  useEffect(() => { setRow(item); }, [item]);
  if (!row) return null;

  const imgs = row.images || [];
  const master = row.master_images || [];

  const upload = async (file) => {
    if (!file) return;
    setBusy('upload');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch(
        `${API}/api/marketing/catalogs/${catalogId}/items/${row.id}/photos`,
        { method: 'POST', headers: { Authorization: headers.Authorization }, body: fd });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal mengunggah foto');
      setRow((s) => ({ ...s, images: [...(s.images || []), b.url] }));
      toast.success('Foto marketplace diunggah');
      onDone?.();
    } catch (e) { toast.error(e.message, { duration: 8000 }); } finally { setBusy(''); }
  };

  const act = async (path, body, okMsg, patch) => {
    setBusy(path);
    try {
      const r = await fetch(
        `${API}/api/marketing/catalogs/${catalogId}/items/${row.id}/${path}`,
        { method: 'POST', headers, body: JSON.stringify(body) });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.detail || 'Gagal');
      setRow((s) => ({ ...s, ...(patch ? patch(b) : {}) }));
      toast.success(okMsg || b.message);
      onDone?.();
    } catch (e) { toast.error(e.message, { duration: 8000 }); } finally { setBusy(''); }
  };

  const reorder = (urls) => act('photos/reorder', { urls },
    'Urutan foto disimpan', (b) => ({ images: b.images }));

  return (
    <DetailPopup open={open} onClose={() => onOpenChange(false)} judul={`Foto — ${row.name}`} testId="photo-dialog"
      keterangan="Foto master dari R&D (baca saja). Foto marketplace milik marketing; yang paling atas jadi foto utama."
      aksi={(
        <Button asChild size="sm" variant="outline">
          <label className="cursor-pointer">
            {busy === 'upload' ? <Loader2 className="animate-spin" /> : <Upload />}
            Unggah foto
            <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
              data-testid="photo-upload-input" onChange={(e) => upload(e.target.files?.[0])} />
          </label>
        </Button>
      )}>
      <section className="space-y-2">
        <p className="text-sm font-medium">Foto master dari R&amp;D ({master.length})</p>
        {master.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Produk ini belum punya foto di master. Foto desain diunggah tim R&amp;D pada Style, lalu ikut terbawa
            saat produk dipromosikan ke master.
          </p>
        ) : (
          <div className="flex flex-wrap gap-3" data-testid="photo-master-list">
            {master.map((m) => (
              <div key={m.url} className="space-y-1 text-center">
                <Thumb url={m.url} alt={m.caption} besar />
                <p className="text-xs text-muted-foreground">{m.from === 'rnd_style' ? 'R&D' : 'Master'}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-2 border-t border-[var(--glass-border)] pt-4">
        <p className="text-sm font-medium">Foto marketplace ({imgs.length})</p>
        {imgs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Belum ada foto versi marketplace. Selama belum ada, layar memakai foto master sebagai foto utama.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--glass-border)]" data-testid="photo-marketplace-list">
            {imgs.map((u, i) => (
              <li key={u} className="flex items-center gap-2 py-2">
                <Thumb url={u} alt="" />
                <span className="min-w-0 flex-1 truncate text-sm">{u.split('/').pop()}</span>
                {i === 0 && <StatusBadge status="utama" label="Utama" tone="success" />}
                <Button size="icon-sm" variant="ghost" disabled={i === 0}
                  title="Naikkan (jadikan lebih utama)" aria-label="Naikkan" data-testid={`photo-up-${i}`}
                  onClick={() => { const n = [...imgs]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; reorder(n); }}>
                  <ChevronUp />
                </Button>
                <Button size="icon-sm" variant="ghost" disabled={i === imgs.length - 1}
                  title="Turunkan" aria-label="Turunkan" data-testid={`photo-down-${i}`}
                  onClick={() => { const n = [...imgs]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; reorder(n); }}>
                  <ChevronDown />
                </Button>
                <Button size="icon-sm" variant="ghost" title="Hapus foto" aria-label="Hapus foto"
                  data-testid={`photo-remove-${i}`} className="text-[hsl(var(--danger-text))]"
                  onClick={() => act('photos/remove', { url: u }, 'Foto dihapus',
                    () => ({ images: imgs.filter((x) => x !== u) }))}>
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </DetailPopup>
  );
}

/* ══════════════════════════════════════════════════════════════════════════════ */
export default function CatalogItemsView({
  catalog, token, items, stockSummary, statusOptions,
  filters, onFilterChange, onEdit, onDelete, onReload,
  baseFilters = {}, onBaseFilter = {}, productCategories = [],
}) {
  const [view, setView] = useState(() => {
    try { return localStorage.getItem(VIEW_KEY) || 'table'; } catch { return 'table'; }
  });
  const [picked, setPicked] = useState({});
  const [publishItem, setPublishItem] = useState(null);
  const [photoItem, setPhotoItem] = useState(null);
  const [reason, setReason] = useState(null);   // {title, describe, required, run}
  const [detailId, setDetailId] = useState(null);
  const [busy, setBusy] = useState('');
  const [unggahBuka, setUnggahBuka] = useState(false);
  const pg = useClientPagination(items, view === 'table' ? PER_HALAMAN : 12);
  const detail = detailId ? items.find((r) => r.id === detailId) || null : null;

  const headers = useMemo(() => ({
    Authorization: `Bearer ${token || localStorage.getItem('erp_token')}`,
    'Content-Type': 'application/json',
  }), [token]);

  useEffect(() => {
    try { localStorage.setItem(VIEW_KEY, view); } catch { /* storage penuh/diblokir */ }
  }, [view]);
  useEffect(() => { setPicked({}); setDetailId(null); }, [catalog?.id]);

  const pickedIds = useMemo(
    () => Object.keys(picked).filter((k) => picked[k]), [picked]);
  const byStatus = stockSummary?.by_status || {};
  const byProductStatus = stockSummary?.by_product_status || {};

  const call = useCallback(async (path, body, method = 'POST') => {
    const r = await fetch(`${API}/api/marketing/catalogs/${catalog.id}/${path}`,
      { method, headers, body: body ? JSON.stringify(body) : undefined });
    const b = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(b.detail || 'Gagal menyimpan perubahan');
    return b;
  }, [catalog?.id, headers]);

  const itemAction = async (item, path, body, label, method = 'POST') => {
    setBusy(item.id + path);
    try {
      const b = await call(`items/${item.id}/${path}`, body, method);
      toast.success(b.message || label, { duration: 7000 });
      onReload?.();
    } catch (e) { toast.error(e.message, { duration: 9000 }); } finally { setBusy(''); }
  };

  // ── AKSI MASSAL: pratinjau → konfirmasi → jalankan → toast "Batalkan" ─────────────────────────────
  const batalkan = async (runId) => {
    try {
      const b = await batalkanAksi(token, runId);
      toast.success(b.message, { duration: 9000 });
      onReload?.();
    } catch (e) { toast.error(e.message, { duration: 9000 }); }
  };
  const selesai = (b) => {
    toast.success(b.message, {
      duration: 12000,
      action: b.run_id ? { label: 'Batalkan', onClick: () => batalkan(b.run_id) } : undefined,
    });
    setPicked({});
    onReload?.();
  };
  const kalimatPratinjau = (pv) => {
    const lewat = pv.skipped ? ` ${angka(pv.skipped)} dilewati: ${ringkasLewati(pv.skip_summary)}.` : '';
    return `${angka(pv.would_change)} dari ${angka(pickedIds.length)} item akan diubah.${lewat}`;
  };

  /** Aksi penayangan massal (backend bulk-transition, `dry_run` dulu). */
  const massal = async (action) => {
    const cfg = AKSI_MASSAL[action];
    setBusy(`bulk-${action}`);
    let pv;
    try {
      pv = await call('items/bulk-transition', { item_ids: pickedIds, action, dry_run: true });
    } catch (e) { toast.error(e.message, { duration: 9000 }); setBusy(''); return; }
    setBusy('');
    if (!pv.would_change) {
      toast.info(`Tidak ada item yang berubah — ${ringkasLewati(pv.skip_summary) || 'semua dilewati'}.`, { duration: 9000 });
      return;
    }
    const jalan = async (why = '') => {
      setBusy(`bulk-${action}`);
      try { selesai(await call('items/bulk-transition', { item_ids: pickedIds, action, reason: why })); }
      catch (e) { toast.error(e.message, { duration: 9000 }); throw e; } finally { setBusy(''); }
    };
    if (cfg.alasan) {
      setReason({
        title: `${cfg.judul} — ${angka(pv.would_change)} item`, labelSimpan: cfg.tombol, required: !!cfg.wajib,
        describe: `${kalimatPratinjau(pv)} Bisa dibatalkan sesudahnya.`,
        run: (why) => jalan(why),
      });
      return;
    }
    const ok = await confirmDialog({
      title: `${cfg.judul} — ${angka(pv.would_change)} item?`,
      body: `${kalimatPratinjau(pv)}${action === 'publish' ? ' Hanya item yang punya URL produk sah sendiri yang ditayangkan.' : ''} Bisa dibatalkan sesudahnya.`,
      confirmLabel: cfg.tombol,
    });
    if (ok) await jalan('').catch(() => {});
  };

  /** D1 — isi harga jual dari harga resmi master (per SKU, cadangan harga model). */
  const isiHarga = async (mode) => {
    const url = alatUrl(`/${catalog.id}/fill-price`);
    setBusy('fill-price');
    let pv;
    try { pv = await panggil(token, url, { body: { item_ids: pickedIds, mode, dry_run: true } }); }
    catch (e) { toast.error(e.message, { duration: 9000 }); setBusy(''); return; }
    setBusy('');
    if (!pv.would_change) {
      toast.info(`Tidak ada harga yang diisi — ${ringkasLewati(pv.skip_summary) || 'semua dilewati'}.`, { duration: 9000 });
      return;
    }
    const src = pv.by_source || {};
    const contoh = (pv.sample || []).slice(0, 3).map((s) => `${s.sku}: ${rp(s.old)} → ${rp(s.new)}`).join('; ');
    const ok = await confirmDialog({
      title: `Isi harga dari master — ${angka(pv.would_change)} item?`,
      body: [
        kalimatPratinjau(pv),
        `Sumber: ${angka(src.sku || 0)} harga per SKU, ${angka(src.model || 0)} harga model (cadangan).`,
        pv.coret_below ? `${angka(pv.coret_below)} item harga coretnya lebih kecil dari harga baru — periksa sesudahnya.` : '',
        contoh ? `Contoh: ${contoh}.` : '',
        'Riwayat harga tercatat dan aksi ini bisa dibatalkan.',
      ].filter(Boolean).join(' '),
      confirmLabel: 'Isi harga',
    });
    if (!ok) return;
    setBusy('fill-price');
    try { selesai(await panggil(token, url, { body: { item_ids: pickedIds, mode } })); }
    catch (e) { toast.error(e.message, { duration: 9000 }); } finally { setBusy(''); }
  };

  // ── semua aksi satu item (dipakai menu "Lainnya" di baris dan tombol di popup detail) ──
  const aksiItem = (r) => {
    const out = [];
    if (r.publish_state !== 'published' && r.publish_state !== 'archived') {
      out.push({ key: 'publish', label: 'Tandai tayang', icon: Rocket, testId: `item-publish-${r.sku}`,
        run: () => setPublishItem(r) });
    }
    if (r.publish_state === 'published') {
      out.push({ key: 'unpublish', label: 'Turunkan dari tayang', icon: RotateCcw, testId: `item-unpublish-${r.sku}`,
        disabled: busy === r.id + 'unpublish',
        run: () => setReason({
          title: 'Turunkan dari tayang', labelSimpan: 'Turunkan',
          describe: `${r.name} kembali menjadi draf. Boleh diisi alasannya supaya tim tahu kenapa.`,
          required: false,
          run: (why) => itemAction(r, 'unpublish', { reason: why }, 'Diturunkan'),
        }) });
    }
    if (r.publish_state === 'archived') {
      out.push({ key: 'restore', label: 'Kembalikan dari arsip', icon: RotateCcw, testId: `item-restore-${r.sku}`,
        run: () => itemAction(r, 'restore', { reason: '' }, 'Dikembalikan') });
    }
    out.push({ key: 'edit', label: 'Ubah item', icon: Pencil, testId: `item-edit-${r.sku}`, run: () => onEdit?.(r) });
    out.push({ key: 'preorder', label: r.is_preorder ? 'Lepas tanda pra-pesan' : 'Tandai pra-pesan', icon: Clock,
      testId: `item-preorder-${r.sku}`,
      run: () => itemAction(r, 'preorder', { is_preorder: !r.is_preorder }, 'Pra-pesan diperbarui') });
    out.push({ key: 'photos', label: 'Kelola foto', icon: ImageIcon, testId: `item-photos-${r.sku}`, run: () => setPhotoItem(r) });
    out.push({ key: 'refresh', label: 'Segarkan dari master', icon: Link2, testId: `item-refresh-${r.sku}`,
      disabled: busy === r.id + 'refresh-from-master',
      run: () => itemAction(r, 'refresh-from-master', null, 'Disegarkan dari master') });
    out.push({ key: 'hpp', label: 'Tarik ulang HPP dari master', icon: Coins, testId: `item-refresh-hpp-${r.sku}`,
      disabled: busy === r.id + 'refresh-hpp',
      run: () => itemAction(r, 'refresh-hpp', null, 'HPP disegarkan') });
    out.push({ key: 'sync', label: 'Sinkron stok dari FG', icon: ArrowRightLeft, testId: `item-sync-stock-${r.sku}`,
      disabled: busy === r.id + 'sync-fg-stock',
      run: () => itemAction(r, 'sync-fg-stock', null, 'Stok disinkronkan', 'PUT') });
    if (r.publish_state !== 'archived') {
      out.push({ key: 'archive', label: 'Arsipkan', icon: Archive, testId: `item-archive-${r.sku}`,
        run: () => setReason({
          title: 'Arsipkan item', labelSimpan: 'Arsipkan',
          describe: `${r.name} tidak ditawarkan lagi (nonaktif), tetapi tidak dihapus supaya riwayat pesanannya tetap utuh.`,
          required: false,
          run: (why) => itemAction(r, 'archive', { reason: why }, 'Diarsipkan'),
        }) });
    }
    out.push({ key: 'reject', label: 'Tandai ditolak platform', icon: XCircle, testId: `item-reject-${r.sku}`, bahaya: true,
      run: () => setReason({
        title: 'Ditolak platform', labelSimpan: 'Tandai ditolak',
        describe: `${r.name} — alasan wajib, supaya tim tahu apa yang harus diperbaiki.`,
        required: true,
        run: (why) => itemAction(r, 'reject', { reason: why }, 'Ditandai ditolak'),
      }) });
    out.push({ key: 'delete', label: 'Hapus item', icon: Trash2, testId: `item-delete-${r.sku}`, bahaya: true,
      run: () => onDelete?.(r) });
    return out;
  };

  const menuLainnya = (r, kecuali = []) => {
    const daftar = aksiItem(r).filter((a) => !kecuali.includes(a.key));
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" aria-label="Aksi lain" title="Aksi lain" data-testid={`item-more-${r.sku}`}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {daftar.map((a, i) => (
            <Fragment key={a.key}>
              {a.bahaya && !daftar[i - 1]?.bahaya && <DropdownMenuSeparator />}
              <DropdownMenuItem onSelect={() => a.run()} disabled={a.disabled} data-testid={a.testId}
                className={a.bahaya ? 'text-[hsl(var(--danger-text))]' : undefined}>
                <a.icon className="mr-2 h-4 w-4" />{a.label}
              </DropdownMenuItem>
            </Fragment>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  };

  // Aksi utama per baris = langkah penayangan berikutnya (tayangkan / turunkan / kembalikan)
  const aksiBaris = (r, lain = []) => {
    const utama = aksiItem(r).find((a) => ['publish', 'unpublish', 'restore'].includes(a.key));
    return (
      <div className="flex items-center justify-end gap-1">
        {utama && (
          <Button size="sm" variant="outline" onClick={() => utama.run()} disabled={utama.disabled}
            data-testid={`${utama.testId}-btn`}>
            <utama.icon />{utama.key === 'publish' ? 'Tayangkan' : utama.key === 'unpublish' ? 'Turunkan' : 'Kembalikan'}
          </Button>
        )}
        {menuLainnya(r, [...lain, ...(utama ? [utama.key] : [])])}
      </div>
    );
  };

  const pilihSatu = (id, v) => setPicked((p) => {
    const n = { ...p }; if (v) n[id] = true; else delete n[id]; return n;
  });
  const semuaHalamanDipilih = pg.paged.length > 0 && pg.paged.every((r) => picked[r.id]);

  const kolom = [
    { kunci: 'pilih', hp: 'aksi', lebar: 'w-8',
      label: (
        <Checkbox checked={semuaHalamanDipilih} aria-label="Pilih semua di halaman ini"
          onCheckedChange={(v) => {
            const n = { ...picked };
            pg.paged.forEach((r) => { if (v) n[r.id] = true; else delete n[r.id]; });
            setPicked(n);
          }}
          data-testid="catalog-select-page" />
      ),
      isi: (r) => (
        <Checkbox checked={!!picked[r.id]} onCheckedChange={(v) => pilihSatu(r.id, v)} aria-label={`Pilih ${r.name}`}
          data-testid={`catalog-select-${r.sku}`} />
      ) },
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (r) => (
      <div className="flex min-w-0 items-center gap-2.5 md:max-w-[22rem]" data-testid={`catalog-item-row-${r.sku}`}>
        <span className="hidden md:block"><Thumb url={r.primary_image} alt={r.name} /></span>
        <div className="min-w-0">
          <p className="truncate font-medium text-foreground" title={r.name}>{r.name}</p>
          <p className="text-xs text-muted-foreground">{[r.sku, r.variant_info].filter(Boolean).join(' · ')}</p>
        </div>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (r) => (
      <div className="space-y-0.5">
        <ItemStatus row={r} />
        <p className="text-xs text-muted-foreground">{publishLabel(r)}{r.is_preorder ? ' · pra-pesan' : ''}</p>
        {r.product_status && (
          <span data-testid={`item-product-status-${r.sku}`}>
            <StatusBadge status={r.product_status} label={productStatusLabel(r.product_status)} tone={productStatusTone(r.product_status)} />
          </span>
        )}
      </div>) },
    { kunci: 'harga', label: 'Harga jual', rata: 'kanan', isi: (r) => (
      <div className="md:whitespace-nowrap">
        <p className="tabular-nums">{rp(r.harga_jual)}</p>
        {/* 9 Nov 2026 (B1) — harga resmi master per SKU tampil di bawahnya bila berbeda / harga toko masih 0 */}
        {!!r.retail_price_master && Number(r.retail_price_master) !== Number(r.harga_jual) && (
          <p className="text-xs text-muted-foreground" data-testid={`item-official-${r.sku}`}>resmi {rp(r.retail_price_master)}</p>
        )}
      </div>) },
    { kunci: 'hpp', label: 'HPP', rata: 'kanan', isi: (r) => (
      <div className="md:whitespace-nowrap">
        <p className="tabular-nums">{rp(r.hpp_effective ?? r.hpp)}</p>
        {/* 2026-11-02 (owner No.26a) — label sumber dari backend (core/catalog_margin SOURCE_LABEL) */}
        <p className="text-xs text-muted-foreground">{r.hpp_source_label || 'belum ada'}</p>
      </div>) },
    { kunci: 'marjin', label: 'Marjin', rata: 'kanan', isi: (r) => <Marjin r={r} /> },
    // Stok jual + tautan master dalam satu kolom: item belum tertaut memang tidak punya stok jual.
    { kunci: 'stok', label: 'Stok jual', rata: 'kanan', isi: (r) => (r.fg_code
      ? <span title={`Tautan master: ${r.fg_code}`}><StokJual r={r} /></span>
      : <StatusBadge status="belum" label="Belum tertaut" tone="warning" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => aksiBaris(r) },
  ];

  const unduhKolom = [
    { label: 'SKU', nilai: (r) => r.sku },
    { label: 'Nama', nilai: (r) => r.name },
    { label: 'Varian', nilai: (r) => r.variant_info || '' },
    { label: 'Kategori', nilai: (r) => r.category_name || '' },
    { label: 'Status', nilai: statusLabel },
    { label: 'Penayangan', nilai: publishLabel },
    { label: 'Pra-pesan', nilai: (r) => (r.is_preorder ? 'Ya' : 'Tidak') },
    { label: 'Harga jual', nilai: (r) => Number(r.harga_jual || 0) },
    { label: 'Harga coret', nilai: (r) => Number(r.harga_coret || 0) },
    { label: 'Harga resmi master', nilai: (r) => Number(r.retail_price_master || 0) },
    { label: 'Sumber harga resmi', nilai: (r) => SUMBER_HARGA[r.retail_price_source] || '' },
    { label: 'Status produk', nilai: (r) => (r.product_status ? productStatusLabel(r.product_status) : '') },
    { label: 'HPP', nilai: (r) => Number(r.hpp_effective ?? r.hpp ?? 0) },
    { label: 'Sumber HPP', nilai: (r) => r.hpp_source_label || 'belum ada' },
    { label: 'Marjin (Rp)', nilai: (r) => (belumTerukur(r) ? 'Belum bisa diukur' : Number(r.margin || 0)) },
    { label: 'Marjin (%)', nilai: (r) => (belumTerukur(r) ? 'Belum bisa diukur' : Number(r.margin_pct || 0)) },
    { label: 'Stok jual', nilai: (r) => (r.available === null || r.available === undefined ? '' : Number(r.available)) },
    { label: 'Dipesan (belum kirim)', nilai: (r) => Number(r.fg_reserved || 0) },
    { label: 'Angka simpanan sesuai', nilai: (r) => (r.in_sync ? 'Ya' : 'Tidak') },
    { label: 'Tautan master', nilai: (r) => r.fg_code || 'Belum tertaut' },
    { label: 'URL produk', nilai: (r) => r.platform_url || '' },
    { label: 'Foto utama', nilai: (r) => r.primary_image || '' },
    { label: 'Terakhir sinkron', nilai: (r) => (r.last_stock_sync ? jam(r.last_stock_sync) : '') },
  ];

  const statusAktif = filters.catalogStatus || [];
  const fotoSort = `${filters.sort || 'name'}:${filters.order || 'asc'}`;
  const saringanLainAktif = (filters.hasPhoto ? 1 : 0) + (fotoSort !== 'name:asc' ? 1 : 0);
  const attention = baseFilters.attention || '';
  const opsiPerhatian = [
    { key: 'all', label: 'Perlu perhatian', count: stockSummary?.attention || 0, testid: 'chip-attention' },
    { key: 'unlinked', label: 'Belum tertaut master', count: stockSummary?.unlinked || 0, testid: 'chip-unlinked' },
    { key: 'stale', label: 'Stok basi', count: stockSummary?.stale || 0, testid: 'chip-stale' },
  ].filter((c) => c.key === 'all' || c.count > 0 || attention === c.key);
  const tampilPerhatian = (stockSummary?.attention || 0) > 0 || !!attention;

  return (
    <div className="space-y-4" data-testid="catalog-items-view">
      <Toolbar
        filters={<>
          <div className="relative w-full sm:w-56">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-8" placeholder="Cari nama, SKU, tag" value={baseFilters.search || ''}
              onChange={(e) => onBaseFilter.search?.(e.target.value)} data-testid="catalog-items-search" />
          </div>
          <SmartNativeSelect className="w-40" value={baseFilters.stock || ''}
            onChange={(e) => onBaseFilter.stock?.(e.target.value)} data-testid="catalog-filter-stock">
            <option value="">Semua stok</option>
            <option value="in_stock">Tersedia</option>
            <option value="low_stock">Stok menipis</option>
            <option value="out_of_stock">Stok habis</option>
          </SmartNativeSelect>
          <SmartNativeSelect className="w-44" value={baseFilters.category || ''}
            onChange={(e) => onBaseFilter.category?.(e.target.value)}
            title="Kategori dari Master Produk" data-testid="catalog-filter-category">
            <option value="">Semua kategori</option>
            {productCategories.map((c) => <option key={c.id} value={c.id}>{c.sku_prefix} · {c.name}</option>)}
          </SmartNativeSelect>
          <SmartNativeSelect className="w-48" data-testid="catalog-filter-publish"
            value={filters.publishState || ''} onChange={(e) => onFilterChange({ publishState: e.target.value })}>
            <option value="">Semua penayangan</option>
            <option value="draft">Belum tayang</option>
            <option value="published">Tayang</option>
            <option value="rejected">Ditolak</option>
            <option value="archived">Diarsipkan</option>
          </SmartNativeSelect>
          {/* D5 — status produk varian (Stop = tidak direncanakan cutting); angka dari seluruh katalog */}
          <SmartNativeSelect className="w-44" data-testid="catalog-filter-product-status" title="Status produk dari Master Produk"
            value={filters.productStatus || ''} onChange={(e) => onFilterChange({ productStatus: e.target.value })}>
            <option value="">Semua status produk</option>
            {OPSI_STATUS_PRODUK.map((o) => {
              const n = o.kode.reduce((t, k) => t + Number(byProductStatus[k] || 0), 0);
              return <option key={o.value} value={o.value}>{o.label} ({angka(n)})</option>;
            })}
          </SmartNativeSelect>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" data-testid="catalog-filter-more">
                <SlidersHorizontal />Foto &amp; urutan{saringanLainAktif ? ` (${saringanLainAktif})` : ''}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-56">
              <DropdownMenuLabel>Foto</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={filters.hasPhoto || ''} onValueChange={(v) => onFilterChange({ hasPhoto: v })}>
                <DropdownMenuRadioItem value="" data-testid="catalog-filter-photo-all">Semua</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="true" data-testid="catalog-filter-photo-yes">Punya foto</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="false" data-testid="catalog-filter-photo-no">Tanpa foto</DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>Urutkan</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={fotoSort} onValueChange={(v) => {
                const [s, o] = v.split(':');
                onFilterChange({ sort: s, order: o });
              }}>
                {SORT_OPTIONS.map(([v, l]) => <DropdownMenuRadioItem key={v} value={v}>{l}</DropdownMenuRadioItem>)}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </>}
        tools={<>
          <TombolUnduh namaBerkas={`katalog-${catalog?.name || 'item'}`} namaLembar="Item katalog" baris={items}
            kolom={unduhKolom} testId="catalog-export" />
          {/* D4 — unduh daftar → isi harga & URL per SKU → unggah dengan pratinjau */}
          <Button variant="outline" onClick={() => setUnggahBuka(true)} data-testid="catalog-price-url-open">
            <FileSpreadsheet />Unggah harga &amp; URL
          </Button>
          <ViewToggle value={view} onChange={setView} testId="catalog-view" />
        </>} />

      {/* Status katalog (bisa pilih lebih dari satu) + item bermasalah — satu baris pil */}
      {((statusOptions || []).length > 0 || tampilPerhatian) && (
        <div className="flex max-w-full flex-nowrap items-center gap-1.5 overflow-x-auto pb-0.5 sm:flex-wrap sm:overflow-visible"
          role="group" aria-label="Saring status" data-testid="catalog-status-chips">
          {(statusOptions || []).map((o) => {
            const on = statusAktif.includes(o.value);
            return (
              <Button key={o.value} type="button" variant="outline" aria-pressed={on} title={o.label}
                data-testid={`catalog-chip-${o.value}`}
                className={cn(CHIP_CLASS, on && CHIP_ACTIVE_CLASS)}
                onClick={() => onFilterChange({
                  catalogStatus: on ? statusAktif.filter((x) => x !== o.value) : [...statusAktif, o.value],
                })}>
                {STATUS_CFG[o.value]?.label || o.label} <span className="tabular-nums">({angka(byStatus[o.value] ?? 0)})</span>
              </Button>
            );
          })}
          {statusAktif.length > 0 && (
            <Button type="button" variant="link" size="sm" onClick={() => onFilterChange({ catalogStatus: [] })}
              data-testid="catalog-chip-clear">Bersihkan</Button>
          )}
          {tampilPerhatian && (
            <>
              <span className="mx-1 h-5 w-px shrink-0 bg-[var(--glass-border)]" aria-hidden="true" />
              {opsiPerhatian.map((c) => {
                const on = attention === c.key;
                return (
                  <Button key={c.key} type="button" variant="outline" aria-pressed={on}
                    data-testid={`catalog-attention-${c.testid}`}
                    className={cn(CHIP_CLASS, on && CHIP_ACTIVE_CLASS)}
                    onClick={() => onBaseFilter.attention?.(on ? '' : c.key)}>
                    {c.key === 'all' && <AlertTriangle />}{c.label} <span className="tabular-nums">({angka(c.count)})</span>
                  </Button>
                );
              })}
            </>
          )}
        </div>
      )}

      {/* K-7a — peringatan cache stok basi / item belum tertaut master (bisa diklik → saring) */}
      {(stockSummary?.stale > 0 || stockSummary?.unlinked > 0) && !attention && (
        <div className="space-y-0.5 text-sm text-[hsl(var(--warning-text))]" data-testid="catalog-stock-warning">
          {stockSummary.stale > 0 && (
            <p>
              <AlertTriangle className="mr-1 inline h-4 w-4" />
              <Button variant="link" className="h-auto p-0 font-semibold" onClick={() => onBaseFilter.attention?.('stale')}
                data-testid="catalog-warning-stale-link">{angka(stockSummary.stale)} item stoknya basi</Button>
              {' '}— angka simpanan berbeda dari stok jual. Kolom stok sudah menampilkan angka langsung; "Sinkron stok FG"
              merapikan angka simpanannya.
            </p>
          )}
          {stockSummary.unlinked > 0 && (
            <p>
              <AlertTriangle className="mr-1 inline h-4 w-4" />
              <Button variant="link" className="h-auto p-0 font-semibold" onClick={() => onBaseFilter.attention?.('unlinked')}
                data-testid="catalog-warning-unlinked-link">{angka(stockSummary.unlinked)} item belum tertaut ke master</Button>
              {' '}— stoknya tidak bisa dihitung otomatis dan tidak bisa dijual lewat alur pesanan. Tautkan varian/FG-nya.
            </p>
          )}
          {stockSummary.counts_truncated && (
            <p className="text-xs">Hitungan di atas hanya mencakup {angka(stockSummary.scanned)} item pertama katalog ini.</p>
          )}
        </div>
      )}
      {attention && (
        <p className="text-sm text-muted-foreground" data-testid="catalog-attention-active-note">
          Menampilkan {angka(items.length)} item bermasalah dari {stockSummary?.scanned ?? '—'} item katalog.
        </p>
      )}

      {/* ── aksi massal ─────────────────────────────────────────────────────── */}
      {pickedIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" data-testid="catalog-bulk-bar">
          <span className="text-sm font-medium" data-testid="bulk-count">{angka(pickedIds.length)} item dipilih</span>
          {semuaHalamanDipilih && pickedIds.length < items.length && (
            <Button size="sm" variant="link" className="px-0" data-testid="bulk-select-all-filtered"
              onClick={() => setPicked(Object.fromEntries(items.map((r) => [r.id, true])))}>
              Pilih semua {angka(items.length)} hasil saring
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" disabled={!!busy} data-testid="bulk-fill-price">
                {busy === 'fill-price' ? <Loader2 className="animate-spin" /> : <Tags />}Isi harga dari master<ChevronDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-72">
              <DropdownMenuLabel>Harga resmi per SKU (cadangan harga model)</DropdownMenuLabel>
              <DropdownMenuItem onSelect={() => isiHarga('kosong')} data-testid="bulk-fill-price-empty">
                Hanya yang harga jualnya masih kosong
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => isiHarga('timpa')} data-testid="bulk-fill-price-overwrite">
                Timpa semua yang berbeda dari harga resmi
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="sm" variant="outline" disabled={!!busy} data-testid="bulk-publish"
            title="Hanya item yang sudah punya URL produk sah sendiri" onClick={() => massal('publish')}>
            <Rocket />Tayangkan yang ber-URL
          </Button>
          <Button size="sm" variant="outline" disabled={!!busy} data-testid="bulk-unpublish"
            onClick={() => massal('unpublish')}>Jadikan draf</Button>
          <Button size="sm" variant="outline" disabled={!!busy} data-testid="bulk-archive"
            onClick={() => massal('archive')}><Archive />Arsipkan</Button>
          <Button size="sm" variant="outline" disabled={!!busy} data-testid="bulk-restore"
            onClick={() => massal('restore')}><RotateCcw />Kembalikan</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" disabled={!!busy} data-testid="bulk-more">
                <MoreHorizontal />Lainnya
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuItem onSelect={() => massal('preorder')} data-testid="bulk-preorder">
                <Clock className="mr-2 h-4 w-4" />Tandai pra-pesan
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => massal('unpreorder')} data-testid="bulk-unpreorder">
                <Clock className="mr-2 h-4 w-4" />Lepas pra-pesan
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => massal('reject')} data-testid="bulk-reject"
                className="text-[hsl(var(--danger-text))]">
                <XCircle className="mr-2 h-4 w-4" />Tandai ditolak platform
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="sm" variant="link" onClick={() => setPicked({})} data-testid="bulk-clear">Batalkan pilihan</Button>
        </div>
      )}

      {/* ── TABEL (bawaan) ──────────────────────────────────────────────────── */}
      {view === 'table' && (
        <TabelData kolom={kolom} baris={pg.paged} onKlikBaris={(r) => setDetailId(r.id)} testId="catalog-items-table"
          kosong={<EmptyState icon={AlertTriangle} title="Tidak ada item yang cocok"
            description='Kosongkan saringan di atas, atau isi katalog lewat tab "Isi dari master".' testId="catalog-items-empty" />} />
      )}

      {/* ── KARTU (galeri foto) ─────────────────────────────────────────────── */}
      {view === 'grid' && (
        items.length === 0 ? (
          <EmptyState icon={AlertTriangle} title="Tidak ada item yang cocok"
            description='Kosongkan saringan di atas, atau isi katalog lewat tab "Isi dari master".' testId="catalog-items-empty" />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="catalog-items-grid">
            {pg.paged.map((r) => (
              <ItemTile key={r.id} r={r} picked={!!picked[r.id]} onPick={(v) => pilihSatu(r.id, v)}
                onOpen={() => setDetailId(r.id)} aksi={aksiBaris(r)} />
            ))}
          </div>
        )
      )}

      <PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total}
        onPageChange={pg.setPage} pageSize={view === 'table' ? PER_HALAMAN : 12} />

      {/* ── POPUP DETAIL ITEM ───────────────────────────────────────────────── */}
      {detail && (
        <DetailPopup open onClose={() => setDetailId(null)} judul={detail.name} testId="catalog-item-detail"
          keterangan={[detail.sku, detail.variant_info].filter(Boolean).join(' · ')}
          status={<ItemStatus row={detail} />}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { setDetailId(null); onEdit?.(detail); }}
              data-testid="catalog-item-detail-edit"><Pencil />Ubah</Button>
            {aksiBaris(detail, ['edit'])}
          </>}>
          <div className="flex items-start gap-3">
            <Thumb url={detail.primary_image} alt={detail.name} besar />
            <p className="text-sm text-muted-foreground">{detail.catalog_status_reason || '—'}</p>
          </div>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Kategori">{detail.category_name || '—'}</BarisDetail>
            <BarisDetail label="Penayangan">
              {publishLabel(detail)}
              {detail.publish_state_inferred && (
                <span className="text-muted-foreground"> (disimpulkan dari ada/tidaknya URL produk, belum dikonfirmasi)</span>
              )}
              {detail.is_preorder ? ' · pra-pesan' : ''}
            </BarisDetail>
            <BarisDetail label="Harga jual">{rp(detail.harga_jual)}</BarisDetail>
            <BarisDetail label="Harga coret">{detail.harga_coret ? rp(detail.harga_coret) : '—'}</BarisDetail>
            <BarisDetail label="Status produk">
              {detail.product_status
                ? <StatusBadge status={detail.product_status} label={productStatusLabel(detail.product_status)} tone={productStatusTone(detail.product_status)} />
                : <span className="text-muted-foreground">Belum diisi di Master Produk</span>}
            </BarisDetail>
            <BarisDetail label="Harga resmi master">
              {detail.retail_price_master ? rp(detail.retail_price_master) : '—'}
              {detail.retail_price_source && detail.retail_price_source !== 'none' && (
                <span className="text-muted-foreground"> ({SUMBER_HARGA[detail.retail_price_source]})</span>
              )}
              {!!detail.price_delta_vs_master && (
                <span className={detail.price_delta_vs_master > 0 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}>
                  {' '}({detail.price_delta_vs_master > 0 ? '+' : ''}{rp(detail.price_delta_vs_master)} dari harga jual)
                </span>
              )}
            </BarisDetail>
            <BarisDetail label="HPP">{rp(detail.hpp_effective ?? detail.hpp)} <span className="text-muted-foreground">({detail.hpp_source_label || 'belum ada'})</span></BarisDetail>
            <BarisDetail label="Marjin">
              <Marjin r={detail} />
              {belumTerukur(detail) && detail.margin_reason && <p className="text-xs text-muted-foreground">{detail.margin_reason}</p>}
            </BarisDetail>
            <BarisDetail label="Stok jual"><StokJual r={detail} /> <span className="text-muted-foreground">· dipesan belum kirim {angka(detail.fg_reserved)}</span></BarisDetail>
            <BarisDetail label="Angka simpanan">
              {detail.in_sync ? 'Sama dengan stok jual' : (detail.attention_reason || 'Berbeda dari stok jual')}
            </BarisDetail>
            <BarisDetail label="Tautan master">{detail.fg_code || 'Belum tertaut'}</BarisDetail>
            <BarisDetail label="URL produk">
              {detail.platform_url ? (
                <a href={detail.platform_url} target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[hsl(var(--primary))] hover:underline">
                  Buka produk <ExternalLink className="h-3.5 w-3.5" />
                </a>
              ) : '—'}
            </BarisDetail>
            <BarisDetail label="Terakhir sinkron">{detail.last_stock_sync ? jam(detail.last_stock_sync) : '—'}</BarisDetail>
            {(detail.tags || []).length > 0 && <BarisDetail label="Tag">{detail.tags.join(', ')}</BarisDetail>}
          </dl>
        </DetailPopup>
      )}

      <PublishDialog open={!!publishItem} onOpenChange={(o) => !o && setPublishItem(null)}
        item={publishItem} catalogId={catalog?.id} headers={headers} onDone={onReload} />
      <PhotoDialog open={!!photoItem} onOpenChange={(o) => !o && setPhotoItem(null)}
        item={photoItem} catalogId={catalog?.id} headers={headers} onDone={onReload} />
      <ReasonDialog open={!!reason} onOpenChange={(o) => !o && setReason(null)}
        title={reason?.title} describe={reason?.describe} required={reason?.required} labelSimpan={reason?.labelSimpan}
        onSubmit={async (why) => { await reason.run(why); }} />
      {unggahBuka && (
        <CatalogPriceUrlDialog open catalog={catalog} token={token} onClose={() => setUnggahBuka(false)}
          onDone={(b) => { setUnggahBuka(false); selesai(b); }} />
      )}
    </div>
  );
}

/* Satu kartu di tampilan galeri (fitur lama: melihat foto produk sekilas). */
function ItemTile({ r, picked, onPick, onOpen, aksi }) {
  return (
    <div className="space-y-2 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3"
      data-testid={`catalog-item-card-${r.sku}`}>
      <div className="flex items-start gap-2">
        <Checkbox checked={picked} onCheckedChange={onPick} aria-label={`Pilih ${r.name}`} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={r.name}>{r.name}</p>
          <p className="text-xs text-muted-foreground">{r.sku}</p>
        </div>
        <ItemStatus row={r} />
      </div>
      {r.primary_image ? (
        <img src={`${API}${r.primary_image}`} alt={r.name}
          className="h-32 w-full rounded-[var(--radius-sm)] border border-border object-cover" />
      ) : (
        <div className="flex h-32 w-full flex-col items-center justify-center rounded-[var(--radius-sm)] border border-dashed border-border text-muted-foreground">
          <ImageIcon className="mb-1 h-6 w-6" />
          <span className="text-xs">Belum ada foto</span>
        </div>
      )}
      <dl className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Harga jual</dt><dd className="text-right tabular-nums font-medium">{rp(r.harga_jual)}</dd>
        <dt className="text-muted-foreground">HPP</dt><dd className="text-right tabular-nums">{rp(r.hpp_effective ?? r.hpp)}</dd>
        <dt className="text-muted-foreground">Marjin</dt>
        <dd className="text-right">{belumTerukur(r) ? 'Belum bisa diukur' : `${Number(r.margin_pct || 0).toLocaleString('id-ID')}%`}</dd>
        <dt className="text-muted-foreground">Stok jual</dt><dd className="text-right"><StokJual r={r} /></dd>
      </dl>
      <div className="flex items-center justify-between gap-2">
        <Button size="sm" variant="link" className="px-0" onClick={onOpen}><Eye />Rincian</Button>
        {aksi}
      </div>
    </div>
  );
}
