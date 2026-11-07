/**
 * Detail satu style RnD — POPUP (Standar UI/UX v2, keputusan owner 8 Nov 2026 #1: detail = popup).
 * Dulu panel samping buatan sendiri dengan deret tab bergaris bawah + lencana angka terpisah, dan isi tiap
 * bagian berupa kartu berulang. Kini: DetailPopup, satu baris pil (dengan jumlah) sebagai pemilih bagian,
 * isi bagian berupa tabel yang bisa diunduh. Sumber data tidak berubah: GET /dewi/rnd/styles/{id}/overview.
 *
 * Props tetap: { token, styleId, onClose } — tanpa styleId tidak menggambar apa pun (menu rnd-style-detail).
 */
import { useState, useEffect } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { toast } from '../ui/sonner';
import { formatDateID, formatRupiah } from '@/lib/format';
import { EmptyState, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = (n) => (n != null ? formatRupiah(n) : '—');
const tgl = (v) => (v ? formatDateID(v) : '—');

/** Status style RnD → label Indonesia + warna (dipakai juga oleh Daftar style). */
export const STATUS_STYLE = {
  draft:                { label: 'Draf', tone: 'muted' },
  active:               { label: 'Aktif', tone: 'success' },
  review:               { label: 'Ditinjau', tone: 'warning' },
  pending_owner_review: { label: 'Menunggu tinjauan owner', tone: 'warning' },
  approved_for_launch:  { label: 'Disetujui owner', tone: 'info' },
  // 2026-11-08: status 'promoted' (style sudah jadi Model DA) dulu tidak punya label sehingga tampil "Draft".
  promoted:             { label: 'Dipromosikan', tone: 'success' },
  archived:             { label: 'Diarsipkan', tone: 'muted' },
};

export function StyleStatusBadge({ status }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.draft;
  return <StatusBadge status={status} label={s.label} tone={s.tone} />;
}

const STATUS_SAMPLE = {
  draft:     { label: 'Draf', tone: 'muted' },
  submitted: { label: 'Diajukan', tone: 'warning' },
  approved:  { label: 'Disetujui', tone: 'success' },
  rejected:  { label: 'Ditolak', tone: 'danger' },
};
const PRIORITAS = { low: 'Rendah', normal: 'Normal', medium: 'Sedang', high: 'Tinggi', urgent: 'Mendesak' };
const STATUS_DOK = {
  approved: { label: 'Disetujui', tone: 'success' },
  superseded: { label: 'Digantikan', tone: 'muted' },
  draft: { label: 'Draf', tone: 'warning' },
};
const dok = (s) => STATUS_DOK[s] || STATUS_DOK.draft;

/** Warna contoh varian: hex baru (`color_hex`) atau hex lama yang tersimpan di `color_code`. */
const swatchOf = (v) => {
  const hx = String(v?.color_hex || '').trim();
  if (hx.startsWith('#')) return hx;
  const legacy = String(v?.color_code || '').trim();
  return legacy.startsWith('#') ? legacy : null;
};
const kodeWarna = (v) => {
  const c = String(v?.color_code || '').trim();
  return c.startsWith('#') ? '' : c;
};
const ukuranAktif = (v) => (v.sizes || []).filter((s) => s && typeof s === 'object' && (s.qty_plan > 0 || s.sku));
const teksUkuran = (v) => ukuranAktif(v).map((s) => (s.qty_plan > 0 ? `${s.size} × ${s.qty_plan}` : s.size)).join(', ');

function Swatch({ hex }) {
  return (
    <span className="inline-block h-4 w-4 shrink-0 rounded border border-[var(--glass-border)]"
      style={hex ? { backgroundColor: hex } : undefined} aria-hidden="true" />
  );
}

export default function RnDStyleDetailPage({ token, styleId, onClose }) {
  const h = { Authorization: `Bearer ${token}` };
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab,     setTab]     = useState('overview');

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/styles/${styleId}/overview`, { headers: h });
      if (!res.ok) throw new Error();
      setData(await res.json());
    } catch { toast.error('Gagal memuat detail style'); }
    finally { setLoading(false); }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (styleId) load(); }, [styleId]);

  if (!styleId) return null;

  const style = data?.style || {};
  const variants = data?.variants || [];
  const samples = data?.samples || [];
  const patterns = data?.patterns || [];
  const hpp = data?.hpp_records || [];
  const revisions = data?.revisions || [];
  const techPacks = data?.tech_packs || [];

  // Jumlah di pil = panjang daftar yang tampil di bagian itu (sama dengan `summary` server = len(list)).
  const opsi = [
    { key: 'overview', label: 'Ringkasan' },
    { key: 'variants', label: 'Varian', count: variants.length },
    { key: 'samples', label: 'Sample', count: samples.length },
    { key: 'patterns', label: 'Pola', count: patterns.length },
    { key: 'hpp', label: 'HPP', count: hpp.length },
    { key: 'revisions', label: 'Revisi', count: revisions.length },
    { key: 'techpack', label: 'Tech pack', count: techPacks.length },
  ];

  const nama = `style-${style.style_code || styleId}`;
  const BAGIAN = {
    variants: {
      baris: variants, kosong: 'Belum ada varian untuk style ini.',
      kolom: [
        { kunci: 'warna', label: 'Warna', hp: 'judul', isi: (v) => (
          <span className="inline-flex items-center gap-2"><Swatch hex={swatchOf(v)} />{v.color || '—'}</span>) },
        { kunci: 'kode', label: 'Kode warna', isi: (v) => <span className="text-xs">{kodeWarna(v) || '—'}</span> },
        { kunci: 'ukuran', label: 'Ukuran (rencana)', isi: (v) => teksUkuran(v) || '—' },
        { kunci: 'jumlah', label: 'Ukuran aktif', rata: 'kanan', isi: (v) => <span className="tabular-nums">{ukuranAktif(v).length}</span> },
      ],
      unduh: [
        { label: 'Warna', nilai: (v) => v.color || '' },
        { label: 'Kode warna', nilai: (v) => kodeWarna(v) },
        { label: 'Ukuran (rencana)', nilai: (v) => teksUkuran(v) },
        { label: 'SKU', nilai: (v) => ukuranAktif(v).map((s) => s.sku).filter(Boolean).join(', ') },
        { label: 'Ukuran aktif', nilai: (v) => ukuranAktif(v).length },
      ],
    },
    samples: {
      baris: samples, kosong: 'Belum ada permintaan sample untuk style ini.',
      kolom: [
        { kunci: 'kode', label: 'Kode sample', hp: 'judul', isi: (s) => <span className="text-xs font-medium">{s.sample_code}</span> },
        { kunci: 'qty', label: 'Jumlah', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.quantity} pcs</span> },
        { kunci: 'prioritas', label: 'Prioritas', isi: (s) => PRIORITAS[s.priority] || s.priority || '—' },
        { kunci: 'tenggat', label: 'Tenggat', isi: (s) => tgl(s.due_date) },
        { kunci: 'status', label: 'Status', isi: (s) => { const t = STATUS_SAMPLE[s.status] || STATUS_SAMPLE.draft; return <StatusBadge status={s.status} label={t.label} tone={t.tone} />; } },
        { kunci: 'catatan', label: 'Catatan', hp: 'keterangan', isi: (s) => <span className="text-sm text-muted-foreground">{s.notes || '—'}</span> },
      ],
      unduh: [
        { label: 'Kode sample', nilai: (s) => s.sample_code },
        { label: 'Jumlah (pcs)', nilai: (s) => Number(s.quantity) || 0 },
        { label: 'Prioritas', nilai: (s) => PRIORITAS[s.priority] || s.priority || '' },
        { label: 'Tenggat', nilai: (s) => (s.due_date ? formatDateID(s.due_date) : '') },
        { label: 'Status', nilai: (s) => (STATUS_SAMPLE[s.status] || STATUS_SAMPLE.draft).label },
        { label: 'Catatan', nilai: (s) => s.notes || '' },
      ],
    },
    patterns: {
      baris: patterns, kosong: 'Belum ada dokumentasi pola untuk style ini.',
      kolom: [
        { kunci: 'kode', label: 'Kode pola', hp: 'judul', isi: (p) => <span className="text-xs font-medium">{p.pattern_code}</span> },
        { kunci: 'status', label: 'Status', isi: (p) => <StatusBadge status={p.status} label={p.status === 'approved' ? 'Disetujui' : 'Draf'} tone={p.status === 'approved' ? 'success' : 'warning'} /> },
        { kunci: 'rentang', label: 'Rentang ukuran', isi: (p) => p.size_range || '—' },
        { kunci: 'kain', label: 'Kain per pcs', rata: 'kanan', isi: (p) => (p.fabric_usage_per_pcs ? `${p.fabric_usage_per_pcs} m` : '—') },
        { kunci: 'efisiensi', label: 'Efisiensi', rata: 'kanan', isi: (p) => (p.efficiency_pct ? `${String(p.efficiency_pct).replace('.', ',')}%` : '—') },
        { kunci: 'hpp', label: 'HPP bahan per pcs', rata: 'kanan', isi: (p) => (p.hpp_fabric_per_pcs > 0 ? fmt(p.hpp_fabric_per_pcs) : '—') },
        { kunci: 'catatan', label: 'Catatan', hp: 'keterangan', isi: (p) => <span className="text-sm text-muted-foreground">{p.notes || '—'}</span> },
      ],
      unduh: [
        { label: 'Kode pola', nilai: (p) => p.pattern_code },
        { label: 'Status', nilai: (p) => (p.status === 'approved' ? 'Disetujui' : 'Draf') },
        { label: 'Rentang ukuran', nilai: (p) => p.size_range || '' },
        { label: 'Kain per pcs (m)', nilai: (p) => Number(p.fabric_usage_per_pcs) || '' },
        { label: 'Efisiensi (%)', nilai: (p) => Number(p.efficiency_pct) || '' },
        { label: 'HPP bahan per pcs', nilai: (p) => Number(p.hpp_fabric_per_pcs) || 0 },
        { label: 'Catatan', nilai: (p) => p.notes || '' },
      ],
    },
    hpp: {
      baris: hpp, kosong: 'Belum ada perhitungan HPP untuk style ini.',
      kolom: [
        { kunci: 'kode', label: 'Kode HPP', hp: 'judul', isi: (r) => <span className="text-xs font-medium">{r.hpp_code}</span> },
        { kunci: 'langsung', label: 'Biaya langsung', rata: 'kanan', isi: (r) => fmt(r.direct_cost) },
        { kunci: 'overhead', label: 'Overhead', rata: 'kanan', isi: (r) => fmt(r.overhead_value) },
        { kunci: 'hpp', label: 'HPP', rata: 'kanan', isi: (r) => <span className="font-medium">{fmt(r.hpp_total)}</span> },
        { kunci: 'jual', label: 'Usulan harga jual', rata: 'kanan', isi: (r) => fmt(r.selling_price_proposal) },
        { kunci: 'margin', label: 'Margin', rata: 'kanan', isi: (r) => (r.margin_pct != null ? `${String(r.margin_pct).replace('.', ',')}%` : '—') },
      ],
      unduh: [
        { label: 'Kode HPP', nilai: (r) => r.hpp_code },
        { label: 'Biaya langsung', nilai: (r) => Number(r.direct_cost) || 0 },
        { label: 'Overhead', nilai: (r) => Number(r.overhead_value) || 0 },
        { label: 'HPP', nilai: (r) => Number(r.hpp_total) || 0 },
        { label: 'Usulan harga jual', nilai: (r) => Number(r.selling_price_proposal) || 0 },
        { label: 'Margin (%)', nilai: (r) => Number(r.margin_pct) || 0 },
      ],
    },
    revisions: {
      baris: revisions, kosong: 'Belum ada revisi untuk style ini.',
      kolom: [
        { kunci: 'no', label: 'No.', rata: 'kanan', hp: false, isi: (r) => <span className="tabular-nums">{r.revision_number}</span> },
        { kunci: 'nama', label: 'Revisi', hp: 'judul', isi: (r) => (
          <div className="min-w-0 md:max-w-[22rem]">
            <p className="font-medium">{r.revision_name}</p>
            {r.changes_summary && <p className="text-xs text-muted-foreground">{r.changes_summary}</p>}
          </div>) },
        { kunci: 'ubah', label: 'Perubahan', isi: (r) => ((r.old_value || r.new_value) ? (
          <span className="text-sm">
            {r.old_value && <span className="text-[hsl(var(--danger-text))] line-through">{r.old_value}</span>}
            {r.old_value && r.new_value && ' → '}
            {r.new_value && <span className="text-[hsl(var(--success-text))]">{r.new_value}</span>}
          </span>) : '—') },
        { kunci: 'oleh', label: 'Oleh', isi: (r) => r.created_by_name || '—' },
        { kunci: 'tanggal', label: 'Tanggal', isi: (r) => tgl(r.created_at) },
      ],
      unduh: [
        { label: 'No.', nilai: (r) => r.revision_number },
        { label: 'Revisi', nilai: (r) => r.revision_name || '' },
        { label: 'Ringkasan perubahan', nilai: (r) => r.changes_summary || '' },
        { label: 'Nilai lama', nilai: (r) => r.old_value || '' },
        { label: 'Nilai baru', nilai: (r) => r.new_value || '' },
        { label: 'Oleh', nilai: (r) => r.created_by_name || '' },
        { label: 'Tanggal', nilai: (r) => (r.created_at ? formatDateID(r.created_at) : '') },
      ],
    },
    techpack: {
      baris: techPacks, kosong: 'Belum ada tech pack untuk style ini.',
      kolom: [
        { kunci: 'judul', label: 'Tech pack', hp: 'judul', isi: (tp) => (
          <div className="min-w-0 md:max-w-[22rem]">
            <p className="font-medium">{tp.title || `Tech pack ${tp.version}`}</p>
            {tp.description && <p className="text-xs text-muted-foreground">{tp.description}</p>}
          </div>) },
        { kunci: 'versi', label: 'Versi', isi: (tp) => <span className="text-xs">{tp.version || '—'}</span> },
        { kunci: 'status', label: 'Status', isi: (tp) => <StatusBadge status={tp.status} label={dok(tp.status).label} tone={dok(tp.status).tone} /> },
        { kunci: 'ukuran', label: 'Ukuran dasar · rentang', isi: (tp) => `${tp.base_size || '—'} · ${tp.size_range || '—'}` },
        { kunci: 'bom', label: 'BOM', rata: 'kanan', isi: (tp) => <span className="tabular-nums">{(tp.bom_items || []).length} bahan</span> },
        { kunci: 'dok', label: 'Dokumen', hp: 'aksi', isi: (tp) => (tp.doc_url ? (
          <Button asChild variant="link" size="sm" className="h-auto p-0">
            <a href={tp.doc_url} target="_blank" rel="noreferrer"><ExternalLink />Buka</a>
          </Button>) : <span className="text-muted-foreground">—</span>) },
      ],
      unduh: [
        { label: 'Tech pack', nilai: (tp) => tp.title || `Tech pack ${tp.version}` },
        { label: 'Versi', nilai: (tp) => tp.version || '' },
        { label: 'Status', nilai: (tp) => dok(tp.status).label },
        { label: 'Ukuran dasar', nilai: (tp) => tp.base_size || '' },
        { label: 'Rentang ukuran', nilai: (tp) => tp.size_range || '' },
        { label: 'Catatan konstruksi', nilai: (tp) => tp.construction_notes || '' },
        { label: 'BOM', nilai: (tp) => (tp.bom_items || []).map((b) => `${b.material} ${b.qty || ''} ${b.unit || ''}`.trim()).join('; ') },
        { label: 'Dokumen', nilai: (tp) => tp.doc_url || '' },
      ],
    },
  };
  const aktif = BAGIAN[tab];

  return (
    <DetailPopup open onClose={onClose} testId="rnd-style-detail"
      judul={loading && !data ? 'Memuat style…' : `${style.style_code || ''} — ${style.style_name || ''}`}
      status={!loading || data ? <StyleStatusBadge status={style.status} /> : null}
      aksi={(
        <Button variant="outline" size="icon-sm" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}>
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat detail style…</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <FilterChips options={opsi} value={tab} onChange={setTab} hideWhenEmpty={false}
                ariaLabel="Bagian detail style" testId="rnd-style-detail-tab" />
            </div>
            {aktif && aktif.baris.length > 0 && (
              <TombolUnduh namaBerkas={`${nama}-${tab}`} namaLembar={opsi.find((o) => o.key === tab)?.label}
                baris={aktif.baris} kolom={aktif.unduh} testId="rnd-style-detail-unduh" />
            )}
          </div>

          {tab === 'overview' && (
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Kode style"><span className="tabular-nums">{style.style_code || '—'}</span></BarisDetail>
              <BarisDetail label="Nama style">{style.style_name || '—'}</BarisDetail>
              <BarisDetail label="Kategori">{style.category || '—'}</BarisDetail>
              <BarisDetail label="Klien">{style.client_name || style.buyer || 'Internal DA'}</BarisDetail>
              <BarisDetail label="Musim">{style.season || '—'}</BarisDetail>
              <BarisDetail label="Jenis kain">{style.fabric_type || '—'}</BarisDetail>
              <BarisDetail label="Deskripsi">{style.description || '—'}</BarisDetail>
              {style.owner_review_result && (
                <BarisDetail label="Keputusan owner">
                  {style.owner_review_result === 'approved' ? 'Disetujui' : 'Ditolak'}
                  {style.owner_reviewed_by ? ` oleh ${style.owner_reviewed_by}` : ''}
                  {style.owner_review_notes ? ` — ${style.owner_review_notes}` : ''}
                </BarisDetail>
              )}
              <BarisDetail label="Dibuat">{tgl(style.created_at)}</BarisDetail>
              <BarisDetail label="Terakhir diubah">{tgl(style.updated_at)}</BarisDetail>
            </dl>
          )}

          {aktif && (
            <TabelData kolom={aktif.kolom} baris={aktif.baris} kunci={(r) => r.id || JSON.stringify(r)}
              testId={`rnd-style-detail-${tab}`}
              kosong={<EmptyState title={aktif.kosong} className="py-6" />} />
          )}

          {tab === 'techpack' && techPacks.filter((tp) => (tp.bom_items || []).length > 0).map((tp) => (
            <div key={`bom-${tp.id}`} className="space-y-2">
              <p className="text-sm font-medium text-foreground">BOM — {tp.title || `Tech pack ${tp.version}`}</p>
              {tp.construction_notes && <p className="text-sm text-muted-foreground">{tp.construction_notes}</p>}
              <TabelData baris={tp.bom_items} kunci={(b) => `${b.material}-${b.spec}-${b.qty}-${b.unit}`}
                testId={`rnd-style-detail-bom-${tp.id}`}
                kolom={[
                  { kunci: 'material', label: 'Bahan', hp: 'judul' },
                  { kunci: 'spec', label: 'Spesifikasi', isi: (b) => b.spec || '—' },
                  { kunci: 'qty', label: 'Jumlah', rata: 'kanan', isi: (b) => <span className="tabular-nums">{b.qty} {b.unit}</span> },
                  { kunci: 'supplier', label: 'Pemasok', isi: (b) => b.supplier || '—' },
                ]} />
            </div>
          ))}
        </>
      )}
    </DetailPopup>
  );
}
