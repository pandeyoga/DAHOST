/**
 * Bandingkan Revisi Style — berdampingan (2026-08-07).
 *
 * Permintaan owner: "bisa bandingkan revisi style side-by-side supaya perubahan
 * terlihat jelas sebelum diputuskan". Dipakai di dua tempat:
 *   · Portal RnD → Desain & Tech Pack → tab Revisi
 *   · Portal Manajemen → Ringkasan & Approval RnD → dialog Detail (sebelum approve)
 *
 * Sumber data: GET /api/dewi/rnd/styles/{id}/revisions/compare?left=&right=
 * ('current' = kondisi style sekarang).
 * Standar UI/UX v2 (8 Nov 2026): dibuka sebagai DetailPopup standar (dulu lapisan buatan sendiri), tabel perbedaan
 * standar + unduh Excel/CSV, label & warna token (dulu HURUF BESAR / warna mentah).
 */
import { useCallback, useEffect, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { RefreshCw, ImageOff, GitCompare, ArrowRight } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import DetailPopup from '@/components/ui/detail-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

export const authImageUrl = (url, token) => {
  if (!url) return '';
  if (!url.startsWith('/api/')) return url;
  return `${API}${url}${url.includes('?') ? '&' : '?'}auth=${encodeURIComponent(token || '')}`;
};

const fmtDate = (v) => (v ? new Date(v).toLocaleString('id-ID') : '—');

function SideSelect({ label, value, options, onChange, testId }) {
  return (
    <div className="min-w-0 flex-1">
      <label className="mb-1 block text-sm font-medium text-foreground">{label}</label>
      <SmartNativeSelect
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testId}
        className="w-full"
      >
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </SmartNativeSelect>
    </div>
  );
}

function PhotoStrip({ images, token, testId }) {
  if (!images?.length) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed border-[var(--glass-border)] px-3 py-4 text-sm text-muted-foreground"
           data-testid={`${testId}-empty`}>
        <ImageOff className="h-4 w-4" /> Tidak ada foto pada versi ini
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-2" data-testid={testId}>
      {images.map((img, i) => (
        <a key={img.id || i} href={authImageUrl(img.url, token)} target="_blank" rel="noreferrer"
           className="group overflow-hidden rounded-lg border" title={img.caption || 'Buka gambar'}>
          <img src={authImageUrl(img.url, token)} alt={img.caption || `Foto ${i + 1}`} loading="lazy"
               className="h-28 w-full object-cover transition-transform duration-200 group-hover:scale-105" />
          {img.caption && (
            <p className="truncate px-2 py-1 text-xs text-muted-foreground">{img.caption}</p>
          )}
        </a>
      ))}
    </div>
  );
}

export default function RnDRevisionCompare({ token, styleId, initialLeft = '', onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (left, right) => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (left) qs.set('left', left);
      if (right) qs.set('right', right);
      const res = await fetch(
        `${API}/api/dewi/rnd/styles/${styleId}/revisions/compare${qs.toString() ? `?${qs}` : ''}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      setData(body);
    } catch (e) {
      toast.error('Gagal memuat perbandingan revisi', { description: e.message });
    } finally {
      setLoading(false);
    }
  }, [styleId, token]);

  useEffect(() => { load(initialLeft, ''); }, [load, initialLeft]);

  const options = data?.available || [];
  const leftId = data?.left?.id || '';
  const rightId = data?.right?.id || '';
  const noHistory = !loading && (data?.total_revisions || 0) === 0;

  return (
    <DetailPopup open onClose={onClose} testId="rnd-revision-compare" judul="Bandingkan revisi style"
      keterangan={`${data?.style?.style_code || '—'}${data?.style?.style_name ? ` · ${data.style.style_name}` : ''}${data ? ` · ${data.total_revisions} revisi tercatat` : ''}`}
      aksi={(
        <>
          {data?.fields?.length > 0 && (
            <TombolUnduh namaBerkas={`revisi-${data?.style?.style_code || 'style'}`} namaLembar="Perbandingan revisi" baris={data.fields}
              testId="rnd-compare-unduh"
              kolom={[
                { label: 'Isian', nilai: (f) => f.label },
                { label: `Versi A (${data?.left?.label || ''})`, nilai: (f) => f.left || '' },
                { label: `Versi B (${data?.right?.label || ''})`, nilai: (f) => f.right || '' },
                { label: 'Berubah', nilai: (f) => (f.changed ? 'Ya' : 'Tidak') },
              ]} />
          )}
          <Button variant="outline" size="icon" disabled={loading} data-testid="rnd-compare-refresh" title="Muat ulang" aria-label="Muat ulang"
            onClick={() => load(leftId, rightId)}>
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </>
      )}>
      {loading && !data ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
        </div>
      ) : noHistory ? (
        <EmptyState icon={GitCompare} testId="rnd-compare-empty" title="Belum ada revisi tercatat"
          description="Riwayat terbentuk otomatis setiap style disimpan atau foto desain ditambahkan/dihapus di Portal RnD." />
      ) : (
        <>
          {/* Pemilih versi */}
          <div className="flex flex-wrap items-end gap-3">
            <SideSelect label="Versi A (lama)" value={leftId} options={options} testId="rnd-compare-left-select"
              onChange={(v) => load(v, rightId)} />
            <ArrowRight className="mb-2.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <SideSelect label="Versi B (baru)" value={rightId} options={options} testId="rnd-compare-right-select"
              onChange={(v) => load(leftId, v)} />
            <span className="mb-1.5" data-testid="rnd-compare-changed-count">
              <StatusBadge status="berubah" label={`${data?.changed_count || 0} isian berubah`} tone={data?.changed_count ? 'warning' : 'muted'} />
            </span>
          </div>

          {/* Keterangan tiap versi */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[['A', data?.left, 'rnd-compare-meta-left'], ['B', data?.right, 'rnd-compare-meta-right']].map(([tag, side, tid]) => (
              <div key={tag} className="rounded-[var(--radius-md)] border border-[var(--glass-border)] px-3 py-2" data-testid={tid}>
                <p className="text-xs font-medium text-muted-foreground">Versi {tag}</p>
                <p className="truncate text-sm font-semibold text-foreground">{side?.label}</p>
                <p className="text-xs text-muted-foreground">
                  {fmtDate(side?.created_at)}
                  {side?.created_by_name ? ` · oleh ${side.created_by_name}` : ''}
                  {side?.source === 'auto' ? ' · otomatis' : side?.source === 'live' ? ' · kondisi terkini' : ''}
                </p>
                {side?.changes_summary && <p className="mt-1 text-xs italic text-muted-foreground">{side.changes_summary}</p>}
                {side && !side.has_snapshot && (
                  <p className="mt-1 text-xs text-[hsl(var(--warning-text))]">Revisi lama tanpa salinan lengkap — hanya ringkasan perubahan yang tersedia.</p>
                )}
              </div>
            ))}
          </div>

          {/* Tabel perbedaan */}
          <div className="overflow-x-auto">
            <Table data-testid="rnd-compare-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Isian</TableHead>
                  <TableHead>Versi A</TableHead>
                  <TableHead>Versi B</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data?.fields || []).map((f) => (
                  <TableRow key={f.key} className={f.changed ? 'bg-[hsl(var(--warning)/0.08)]' : ''} data-testid={`rnd-compare-row-${f.key}`}>
                    <TableCell className="font-medium">
                      {f.label}
                      {f.changed && <StatusBadge status="berubah" label="Berubah" tone="warning" className="ml-2" />}
                    </TableCell>
                    <TableCell className={`max-w-[320px] whitespace-normal ${f.changed ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{f.left || '—'}</TableCell>
                    <TableCell className={`max-w-[320px] whitespace-normal ${f.changed ? 'font-semibold text-[hsl(var(--success-text))]' : 'text-muted-foreground'}`}>{f.right || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Foto berdampingan */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold text-foreground">Foto desain</p>
              {(data?.images?.added || []).length > 0 && (
                <span data-testid="rnd-compare-img-added">
                  <StatusBadge status="baru" label={`+${data.images.added.length} foto baru`} tone="success" />
                </span>
              )}
              {(data?.images?.removed || []).length > 0 && (
                <span data-testid="rnd-compare-img-removed">
                  <StatusBadge status="hapus" label={`−${data.images.removed.length} foto dihapus`} tone="danger" />
                </span>
              )}
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Versi A</p>
                <PhotoStrip images={data?.images?.left} token={token} testId="rnd-compare-photos-left" />
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Versi B</p>
                <PhotoStrip images={data?.images?.right} token={token} testId="rnd-compare-photos-right" />
              </div>
            </div>
          </div>
        </>
      )}
    </DetailPopup>
  );
}
