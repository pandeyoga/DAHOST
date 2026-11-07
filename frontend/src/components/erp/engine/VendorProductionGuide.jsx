import { useState, useEffect } from 'react';
import { BookOpen, Briefcase, ListChecks, Video, Image as ImageIcon, PlayCircle, AlertCircle, Loader2, Package } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup from '@/components/ui/detail-popup';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';

const BACKEND = process.env.REACT_APP_BACKEND_URL || '';
const token = () => localStorage.getItem('erp_token') || '';
const fileUrl = (p) => `${BACKEND}/api/files/${p}?auth=${encodeURIComponent(token())}`;

function ytId(url) {
  const m = String(url || '').match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|shorts\/))([\w-]{11})/);
  return m ? m[1] : null;
}

/**
 * VendorProductionGuide (Portal Vendor CMT) — READ ONLY.
 *
 * RELATION FIX: sekarang membaca pekerjaan NYATA vendor dari `/production-jobs`
 * (koleksi production_jobs, scoped vendor_id di backend) — bukan lagi `vendor_jobs`
 * yang kosong. Panduan Produksi di-resolve dari SUMBER YANG BENAR via
 * `/production-jobs/{id}/production-guide`:
 *   - Maklon  → dewi_maklon_buyer_catalog (SOP yang diinput di ERP Katalog Buyer)
 *   - Internal→ rahaza_models
 * Endpoint mengembalikan `guides[]` (bisa >1 artikel per job).
 */
export default function VendorProductionGuide() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null); // job
  const [guide, setGuide] = useState(null);
  const [guideLoading, setGuideLoading] = useState(false);
  const [lightbox, setLightbox] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await apiGet('/production-jobs');
        const list = Array.isArray(data) ? data : (data?.items || data?.data || []);
        if (alive) setJobs(list);
      } catch (_e) {
        if (alive) setJobs([]);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const openGuide = async (job) => {
    setSelected(job);
    setGuide(null);
    setGuideLoading(true);
    try {
      const data = await apiGet(`/production-jobs/${job.id}/production-guide`);
      setGuide(data);
    } catch (_e) {
      setGuide({ has_guide: false, guides: [], message: 'Gagal memuat panduan.' });
    } finally {
      setGuideLoading(false);
    }
  };

  const renderGuideCard = (g, gi) => {
    const photos = g.image_paths || [];
    const steps = g.sop_steps || [];
    const videos = g.reference_videos || [];
    const refImages = g.reference_images || [];
    const empty = photos.length === 0 && steps.length === 0 && videos.length === 0 && refImages.length === 0 && !g.hero_image_url;
    const badge = g.source_type === 'buyer_catalog' ? 'Katalog Buyer' : 'Model Internal';
    return (
      <section key={gi} className="space-y-5 border-t border-[var(--glass-border)] pt-4 first:border-t-0 first:pt-0" data-testid={`vendor-guide-article-${gi}`}>
        <div className="flex items-center gap-2 flex-wrap border-b border-border pb-3">
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-0.5 rounded-full bg-primary/10 text-primary">
            <Package className="w-3.5 h-3.5" /> {badge}
          </span>
          {g.code && <span className="tabular-nums text-xs text-muted-foreground">{g.code}</span>}
          <span className="text-sm font-semibold text-foreground">{g.name}</span>
        </div>

        {g.description && <p className="text-sm text-muted-foreground">{g.description}</p>}

        {g.hero_image_url && (
          <img src={g.hero_image_url} alt="produk" onClick={() => setLightbox(g.hero_image_url)}
            className="w-40 h-40 rounded-lg object-cover border border-border cursor-zoom-in hover:ring-2 hover:ring-primary/40" />
        )}

        {photos.length > 0 && (
          <section>
            <p className="text-sm font-semibold text-foreground mb-2 flex items-center gap-1.5"><ImageIcon className="w-4 h-4 text-primary" /> Foto Produk</p>
            <div className="flex flex-wrap gap-2" data-testid="vendor-guide-photos">
              {photos.map((p) => (
                <img key={p} src={fileUrl(p)} alt="produk" onClick={() => setLightbox(fileUrl(p))}
                  className="w-24 h-24 rounded-lg object-cover border border-border cursor-zoom-in hover:ring-2 hover:ring-primary/40" />
              ))}
            </div>
          </section>
        )}

        {steps.length > 0 && (
          <section>
            <p className="text-sm font-semibold text-foreground mb-2 flex items-center gap-1.5"><ListChecks className="w-4 h-4 text-primary" /> Tata Cara Produksi ({steps.length} langkah)</p>
            <ol className="space-y-2" data-testid="vendor-guide-steps">
              {steps.map((s, i) => (
                <li key={s.id || i} className="flex gap-3 rounded-xl border border-border bg-muted/30 p-3">
                  <span className="w-7 h-7 rounded-full bg-primary/15 text-primary text-sm font-bold flex items-center justify-center shrink-0">{s.seq || i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-foreground">{s.title || `Langkah ${i + 1}`}</div>
                    {s.description && <div className="text-sm text-muted-foreground whitespace-pre-line mt-0.5">{s.description}</div>}
                  </div>
                  {s.image_path && (
                    <img src={fileUrl(s.image_path)} alt="langkah" onClick={() => setLightbox(fileUrl(s.image_path))}
                      className="w-20 h-20 rounded-lg object-cover border border-border cursor-zoom-in shrink-0" />
                  )}
                </li>
              ))}
            </ol>
          </section>
        )}

        {videos.length > 0 && (
          <section>
            <p className="text-sm font-semibold text-foreground mb-2 flex items-center gap-1.5"><Video className="w-4 h-4 text-primary" /> Referensi Video</p>
            <div className="flex flex-wrap gap-3" data-testid="vendor-guide-videos">
              {videos.map((v, i) => {
                const yid = ytId(v.url);
                return (
                  <a key={i} href={v.url} target="_blank" rel="noreferrer"
                    className="flex items-center gap-2 rounded-xl border border-border bg-muted/30 p-2 hover:bg-muted/60 max-w-[260px]">
                    {yid
                      ? <div className="relative w-20 h-14 shrink-0"><img src={`https://img.youtube.com/vi/${yid}/mqdefault.jpg`} alt="yt" className="w-20 h-14 rounded object-cover" /><PlayCircle className="w-6 h-6 text-white absolute inset-0 m-auto drop-shadow" /></div>
                      : <div className="w-20 h-14 rounded bg-muted flex items-center justify-center shrink-0"><PlayCircle className="w-6 h-6 text-muted-foreground" /></div>}
                    <span className="text-sm text-foreground truncate">{v.title || v.url}</span>
                  </a>
                );
              })}
            </div>
          </section>
        )}

        {refImages.length > 0 && (
          <section>
            <p className="text-sm font-semibold text-foreground mb-2 flex items-center gap-1.5"><ImageIcon className="w-4 h-4 text-primary" /> Gambar Referensi</p>
            <div className="flex flex-wrap gap-2" data-testid="vendor-guide-refimages">
              {refImages.map((v, i) => (
                <a key={i} href={v.url} target="_blank" rel="noreferrer" title={v.caption}>
                  <img src={v.url} alt={v.caption || 'ref'} className="w-24 h-24 rounded-lg object-cover border border-border hover:ring-2 hover:ring-primary/40" />
                </a>
              ))}
            </div>
          </section>
        )}

        {empty && (
          <div className="text-sm text-[hsl(var(--warning-text))] flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            Panduan Produksi untuk artikel ini belum diisi. Admin/PPIC dapat mengisi SOP di
            {g.source_type === 'buyer_catalog' ? ' Katalog Buyer → Panduan Produksi.' : ' Master Produk → Panduan.'}
          </div>
        )}
      </section>
    );
  };

  // Standar UI/UX v2 (8 Nov 2026): daftar pekerjaan = tabel (dulu tombol-kartu berulang); panduan satu pekerjaan
  // dibuka sebagai popup (dulu halaman pengganti dengan tombol "Kembali" dan judul kedua).
  const kolom = [
    { kunci: 'job', label: 'Pekerjaan', hp: 'judul', isi: (j) => (
      <div className="min-w-0"><span className="font-medium tabular-nums">{j.job_number}</span>
        <span className="block text-xs text-muted-foreground">{j.customer_name || j.vendor_name || 'Pekerjaan produksi'}</span></div>) },
    { kunci: 'po', label: 'PO', isi: (j) => <span className="tabular-nums">{j.po_number || '—'}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (j) => ((j.business_type || 'maklon') !== 'internal'
      ? <StatusBadge status="maklon" tone="success" label="Maklon" /> : <StatusBadge status="internal" tone="primary" label="Internal" />) },
    { kunci: 'target', label: 'Target', rata: 'kanan', isi: (j) => (j.item_count != null
      ? <span className="tabular-nums text-sm">{j.item_count} baris · {j.total_available || j.total_ordered || 0} pcs</span> : '—') },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (j) => (
      <Button type="button" size="sm" variant="outline" onClick={() => openGuide(j)} data-testid={`guide-job-${j.job_number}`}><BookOpen className="w-4 h-4" />Lihat panduan</Button>) },
  ];
  const guides = guide?.guides || [];

  return (
    <PageLayout testId="vendor-production-guide" title="Panduan produksi"
      subtitle="Cara & tahapan pembuatan artikel untuk pekerjaan yang ditugaskan: SOP, video, dan gambar referensi."
      tools={<TombolUnduh namaBerkas="pekerjaan-panduan-produksi" baris={jobs} kolom={[
        { label: 'Pekerjaan', nilai: (j) => j.job_number }, { label: 'PO', nilai: (j) => j.po_number || '' },
        { label: 'Pelanggan', nilai: (j) => j.customer_name || '' },
        { label: 'Jenis', nilai: (j) => ((j.business_type || 'maklon') !== 'internal' ? 'Maklon' : 'Internal') },
        { label: 'Baris', nilai: (j) => (j.item_count != null ? Number(j.item_count) : '') },
        { label: 'Target (pcs)', nilai: (j) => Number(j.total_available || j.total_ordered) || 0 },
      ]} />}>
      {loading ? (
        <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /> Memuat…</p>
      ) : (
        <TabelData kolom={kolom} baris={jobs} onKlikBaris={openGuide} testId="guide-jobs-list"
          kosong={<div data-testid="guide-empty"><EmptyState icon={Briefcase} title="Belum ada pekerjaan yang ditugaskan"
            description="Panduan produksi muncul setelah pekerjaan produksi dibuat untuk vendor ini." /></div>} />
      )}

      {selected && (
        <DetailPopup open onClose={() => { setSelected(null); setGuide(null); }} testId="vendor-guide-detail"
          judul={`Panduan produksi ${selected.job_number}`} keterangan={selected.po_number ? `PO ${selected.po_number}` : undefined}>
          {guideLoading ? (
            <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /> Memuat panduan…</p>
          ) : !guide?.has_guide ? (
            <Notice tone="warning" icon={AlertCircle} testId="guide-no-model">{guide?.message || 'Belum ada panduan produksi untuk pekerjaan ini.'}</Notice>
          ) : (
            <div className="space-y-4" data-testid="vendor-guide-content">
              {guides.map((g, gi) => renderGuideCard(g, gi))}
            </div>
          )}
        </DetailPopup>
      )}

      {lightbox && (
        <div className="fixed inset-0 z-[200] bg-black/80 flex items-center justify-center p-6" onClick={() => setLightbox(null)} data-testid="vendor-guide-lightbox">
          <img src={lightbox} alt="pratinjau" className="max-w-full max-h-full rounded-lg object-contain" />
        </div>
      )}
    </PageLayout>
  );
}
