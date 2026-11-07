import { useState, useEffect } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Plus, Search, AlertTriangle, Briefcase, Eye, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { MiniBar } from './VendorShared';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { apiGet, apiPost } from '../../../lib/api';

export default function VendorProductionJobs({ user }) {
  const [jobs, setJobs] = useState([]);
  const [receivedShipments, setReceivedShipments] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [detailJob, setDetailJob] = useState(null);
  const [selectedShipment, setSelectedShipment] = useState(null);
  const [form, setForm] = useState({ vendor_shipment_id: '', notes: '' });
  const [loading, setLoading] = useState(false);
  const [expandedJobs, setExpandedJobs] = useState({});
  const [jobItems, setJobItems] = useState({});   // {jobId: 'loading' | item[]}
  const [searchShipment, setSearchShipment] = useState('');
  const [jobSearch, setJobSearch] = useState('');

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    try {
      const [jData, sData] = await Promise.all([
        apiGet('/production-jobs'),
        apiGet('/vendor-shipments'),
      ]);
      setJobs(Array.isArray(jData) ? jData : []);
      const allShipments = Array.isArray(sData) ? sData : [];
      const existingJobShipmentIds = new Set((Array.isArray(jData) ? jData : []).map(j => j.vendor_shipment_id));
      setReceivedShipments(allShipments.filter(s => s.status === 'Received' && !existingJobShipmentIds.has(s.id) && s.inspection_status === 'Inspected' && !s.parent_shipment_id));
    } catch (e) {
      setJobs([]); setReceivedShipments([]);
    }
  };

  const loadShipmentPreview = async (shipmentId) => {
    const ship = receivedShipments.find(s => s.id === shipmentId);
    setSelectedShipment(ship || null);
    setForm(f => ({ ...f, vendor_shipment_id: shipmentId }));
    if (shipmentId && !ship?.items?.length) {
      try {
        // 2026-11-06 (pola P1): rute `/vendor-shipment-items` tidak pernah ada (404 tertelan) —
        // item pengiriman ada di detail GET /vendor-shipments/{id} → `items`.
        const data = await apiGet(`/vendor-shipments/${shipmentId}`);
        if (Array.isArray(data?.items)) setSelectedShipment(prev => prev ? { ...prev, items: data.items } : ship);
      } catch (e) { /* ignore */ }
    }
  };

  const handleCreate = async (e) => {
    e?.preventDefault?.();
    if (!form.vendor_shipment_id) { toast.error('Pilih shipment terlebih dahulu'); return; }
    setLoading(true);
    try {
      await apiPost('/production-jobs', { ...form, vendor_id: user.vendor_id });
      setShowModal(false);
      fetchAll();
    } catch (err) {
      toast.error(err.message || 'Gagal membuat Production Job');
    } finally {
      setLoading(false);
    }
  };

  const openDetail = async (job) => {
    try {
      const data = await apiGet(`/production-jobs/${job.id}`);
      setDetailJob(data);
      setShowDetail(true);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat detail job');
    }
  };

  const toggleJob = async (jobId) => {
    const willOpen = !expandedJobs[jobId];
    setExpandedJobs(prev => ({ ...prev, [jobId]: willOpen }));
    // FASE 22 — dulu baris expand hanya memasang HEADER tabel lalu menulis
    // «Klik "Detail Lengkap" untuk melihat semua item»: tabel kosong yang memaksa
    // buka halaman/dialog lain (persis keluhan owner "terlalu banyak step"), dan
    // kolom hasil QC (Lolos QC DA / Reject / Rework) tak pernah kelihatan di sini.
    // Sekarang item-nya dimuat langsung saat baris dibuka.
    if (willOpen && !jobItems[jobId]) {
      setJobItems(prev => ({ ...prev, [jobId]: 'loading' }));
      try {
        const data = await apiGet(`/production-jobs/${jobId}`);
        setJobItems(prev => ({ ...prev, [jobId]: Array.isArray(data?.items) ? data.items : [] }));
      } catch (e) {
        setJobItems(prev => ({ ...prev, [jobId]: [] }));
        toast.error(e.message || 'Gagal memuat item job');
      }
    }
  };

  const fmtDate = (d) => formatDateID(d, { fallback: '—' });

  // Standar UI/UX v2 (8 Nov 2026): daftar job = tabel (dulu kartu tinggi per job); rincian barang per job (yang
  // dulu dibuka di dalam kartu + popup "Detail lengkap") = satu popup rincian dengan SEMUA kolom.
  const n = (v) => Number(v || 0).toLocaleString('id-ID');
  const STATUS_JOB = { Completed: ['Selesai', 'success'], 'In Progress': ['Berjalan', 'info'] };
  const statusJob = (s) => STATUS_JOB[s] || [s || '—', 'default'];
  const TIPE = { ADDITIONAL: 'Tambahan', REPLACEMENT: 'Pengganti', REWORK: 'Retur perbaikan', NORMAL: 'Awal' };
  const lewat = (job) => job.deadline && new Date(job.deadline) < new Date() && job.status !== 'Completed';
  const cocok = (s) => {
    const q = searchShipment.toLowerCase();
    return !q || s.shipment_number?.toLowerCase().includes(q) || s.po_number?.toLowerCase().includes(q) || fmtDate(s.shipment_date).toLowerCase().includes(q);
  };
  const grupKirim = [
    { label: 'Kiriman awal', list: receivedShipments.filter((s) => (!s.shipment_type || s.shipment_type === 'NORMAL') && cocok(s)) },
    { label: 'Kiriman tambahan', list: receivedShipments.filter((s) => s.shipment_type === 'ADDITIONAL' && cocok(s)) },
    { label: 'Kiriman pengganti', list: receivedShipments.filter((s) => s.shipment_type === 'REPLACEMENT' && cocok(s)) },
  ];
  const jumlahCocok = grupKirim.reduce((t, g) => t + g.list.length, 0);

  const kolom = [
    { kunci: 'job', label: 'Job', hp: 'judul', isi: (job) => (
      <div className="min-w-0">
        <span className="font-medium tabular-nums">{job.job_number}</span>
        {(job.child_jobs || []).length > 0 && <span className="block text-xs text-muted-foreground">+{job.child_jobs.length} job turunan</span>}
      </div>) },
    { kunci: 'po', label: 'PO · kiriman', isi: (job) => (
      <div className="min-w-0 text-sm">
        <span className="tabular-nums">{job.po_number || '—'}</span>
        <span className="block text-xs text-muted-foreground tabular-nums">{job.shipment_number}{job.customer_name ? ` · ${job.customer_name}` : ''}</span>
      </div>) },
    { kunci: 'tenggat', label: 'Tenggat', isi: (job) => (
      <span className={lewat(job) ? 'text-[hsl(var(--danger-text))] font-medium' : ''}>{fmtDate(job.deadline)}{lewat(job) ? ' · lewat' : ''}</span>) },
    { kunci: 'progres', label: 'Kemajuan', isi: (job) => ((job.total_available || 0) > 0 ? (
      <div className="min-w-[9rem]">
        <MiniBar pct={job.progress_pct || 0} />
        <span className="text-xs text-muted-foreground tabular-nums">{n(job.total_produced)} / {n(job.total_available)} pcs</span>
      </div>) : <span className="text-muted-foreground">—</span>) },
    { kunci: 'belum', label: 'Belum sampai di DA', rata: 'kanan', isi: (job) => (Number(job.total_short_open || 0) > 0
      ? <span className="font-semibold tabular-nums text-[hsl(var(--danger-text))]">{n(job.total_short_open)} pcs</span>
      : <span className="tabular-nums text-muted-foreground">0</span>) },
    { kunci: 'status', label: 'Status', isi: (job) => { const [l, t] = statusJob(job.status); return <StatusBadge status={job.status} label={l} tone={t} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (job) => (
      <Button size="icon-sm" variant="ghost" onClick={() => openDetail(job)} data-testid={`vendor-job-detail-${job.job_number}`}
        title="Lihat rincian" aria-label="Lihat rincian"><Eye className="w-4 h-4" /></Button>) },
  ];

  return (
    <PageLayout testId="vendor-production-jobs" title="Pekerjaan produksi"
      subtitle="Job dibuat dari bahan yang sudah diterima & diinspeksi; qty job = bahan diterima."
      actions={<Button onClick={() => { setForm({ vendor_shipment_id: '', notes: '' }); setSelectedShipment(null); setShowModal(true); }}
        disabled={receivedShipments.length === 0} data-testid="vendor-create-job-btn">
        <Plus className="w-4 h-4" /> Buat job produksi
      </Button>}
      tools={<>
        <TombolUnduh namaBerkas="job-produksi" namaLembar="Job" baris={jobs} kolom={[
          { label: 'Job', nilai: (j) => j.job_number }, { label: 'PO', nilai: (j) => j.po_number || '' },
          { label: 'Kiriman', nilai: (j) => j.shipment_number || '' }, { label: 'Pelanggan', nilai: (j) => j.customer_name || '' },
          { label: 'Tenggat', nilai: (j) => fmtDate(j.deadline) }, { label: 'SKU', nilai: (j) => Number(j.item_count) || 0 },
          { label: 'Diproduksi', nilai: (j) => Number(j.total_produced) || 0 }, { label: 'Tersedia', nilai: (j) => Number(j.total_available) || 0 },
          { label: 'Kemajuan (%)', nilai: (j) => Number(j.progress_pct) || 0 }, { label: 'Belum sampai di DA', nilai: (j) => Number(j.total_short_open) || 0 },
          { label: 'Status', nilai: (j) => statusJob(j.status)[0] }, { label: 'No. seri', nilai: (j) => (j.serial_numbers || []).join(', ') },
        ]} />
        <Button variant="outline" size="icon" onClick={fetchAll} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="h-4 w-4" /></Button>
      </>}
      summary={<>
        {receivedShipments.length === 0 && jobs.length === 0 && (
          <Notice tone="warning" icon={AlertTriangle} title="Bahan untuk diproses belum tersedia">
            Pastikan ada kiriman yang sudah dikonfirmasi diterima <strong>dan</strong> diinspeksi di <strong>Penerimaan material</strong>.
          </Notice>
        )}
        {receivedShipments.length > 0 && (
          <p className="text-sm text-muted-foreground">{n(receivedShipments.length)} kiriman siap dibuatkan job produksi (qty job = qty bahan yang diterima, bukan qty PO).</p>
        )}
      </>}>
      <TabelData kolom={kolom} baris={jobs} onKlikBaris={openDetail} testId="vendor-jobs-table"
        kosong={<EmptyState icon={Briefcase} title="Belum ada job produksi"
          description="Konfirmasi penerimaan & inspeksi bahan, lalu buat job produksi." />} />

      {/* Buat job — FormPopup */}
      {showModal && (
        <FormPopup open onClose={() => setShowModal(false)} ukuran="panjang" testId="vendor-create-job-form"
          judul="Buat job produksi" keterangan="Qty produksi = bahan yang DITERIMA (bukan qty PO). Kiriman tambahan yang diterima & diinspeksi membuat job turunan otomatis."
          onSimpan={handleCreate} menyimpan={loading} bisaSimpan={!!form.vendor_shipment_id} labelSimpan="Buat job produksi">
          <Isian label="Kiriman yang diterima & diinspeksi" wajib
            petunjuk={receivedShipments.length === 0 ? 'Tidak ada kiriman yang siap. Konfirmasi penerimaan & inspeksi di Penerimaan material.' : `${jumlahCocok} kiriman tersedia.`}>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="relative w-full sm:w-56">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-8" placeholder="Cari kiriman, PO, tanggal" value={searchShipment} onChange={(e) => setSearchShipment(e.target.value)} />
              </div>
              <SmartNativeSelect required className="w-full" value={form.vendor_shipment_id} onChange={(e) => loadShipmentPreview(e.target.value)}
                aria-label="Pilih kiriman">
                <option value="">Pilih kiriman ({jumlahCocok} tersedia)</option>
                {grupKirim.filter((g) => g.list.length > 0).map((g) => (
                  <optgroup key={g.label} label={g.label}>
                    {g.list.map((s) => (
                      <option key={s.id} value={s.id}>{s.shipment_number} · PO {s.po_number || '—'} · {fmtDate(s.shipment_date)} · {(s.items || []).length} baris</option>
                    ))}
                  </optgroup>
                ))}
              </SmartNativeSelect>
            </div>
          </Isian>
          {selectedShipment && (
            <section className="space-y-2">
              <p className="text-sm font-medium text-foreground">Pratinjau {selectedShipment.shipment_number} (qty terkunci)</p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow><TableHead>Produk</TableHead><TableHead>SKU</TableHead><TableHead>Ukuran / warna</TableHead>
                    <TableHead>No. seri</TableHead><TableHead className="text-right">Qty</TableHead></TableRow></TableHeader>
                  <TableBody>{(selectedShipment.items || []).map((item, idx) => (
                    <TableRow key={item.id || idx}><TableCell className="font-medium">{item.product_name}</TableCell>
                      <TableCell className="tabular-nums">{item.sku || '—'}</TableCell><TableCell>{item.size || '—'}/{item.color || '—'}</TableCell>
                      <TableCell className="tabular-nums">{item.serial_number || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(item.qty_sent)} pcs</TableCell></TableRow>
                  ))}</TableBody>
                </Table>
              </div>
              <p className="text-xs text-muted-foreground">Qty job = qty bahan diterima dari inspeksi. Vendor hanya bisa mengisi progress.</p>
            </section>
          )}
          <Isian label="Catatan (opsional)">
            <Textarea rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} placeholder="Catatan tambahan…" />
          </Isian>
        </FormPopup>
      )}

      {/* Rincian job — DetailPopup */}
      {showDetail && detailJob && (() => {
        const [sl, st] = statusJob(detailJob.status);
        return (
          <DetailPopup open onClose={() => setShowDetail(false)} judul={`Job ${detailJob.job_number}`} testId="vendor-job-detail"
            status={<StatusBadge status={detailJob.status} label={sl} tone={st} />}>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="PO">{detailJob.po_number || '—'}</BarisDetail>
              <BarisDetail label="Kiriman">{detailJob.shipment_number || '—'}</BarisDetail>
              <BarisDetail label="Pelanggan">{detailJob.customer_name || '—'}</BarisDetail>
              <BarisDetail label="Tenggat">{fmtDate(detailJob.deadline)}</BarisDetail>
              {(detailJob.serial_numbers || []).length > 0 && <BarisDetail label="No. seri">{detailJob.serial_numbers.join(', ')}</BarisDetail>}
            </dl>
            {/* SELISIH KIRIM (aturan owner): qty deklarasi mengikuti yang diterima DA; kekurangan tetap kewajiban vendor. */}
            {Number(detailJob.total_short_open || 0) > 0 && (
              <Notice tone="danger" icon={AlertTriangle} testId={`vendor-job-short-banner-${detailJob.job_number}`}
                title={`${n(detailJob.total_short_open)} pcs belum sampai di DA — harus dicari & dikirim ulang`}>
                Klaim kirim {n(detailJob.total_claimed_by_vendor)} pcs, diterima DA {n(detailJob.total_received_by_da)} pcs. Dokumen deklarasi
                dikoreksi mengikuti qty yang diterima DA dan sisa kirim bertambah — kirim ulang lewat <em>Kirim ke DA</em>.
              </Notice>
            )}
            {(detailJob.child_jobs || []).length > 0 && (
              <section className="space-y-1">
                <p className="text-sm font-semibold text-foreground">Job turunan ({detailJob.child_jobs.length})</p>
                <ul className="text-sm space-y-0.5">
                  {detailJob.child_jobs.map((c) => <li key={c.id}>{c.job_number} · {TIPE[c.shipment_type] || c.shipment_type} · {statusJob(c.status)[0]}</li>)}
                </ul>
              </section>
            )}
            {(detailJob.items || []).length > 0 && (
              <section className="space-y-2" data-testid={`vendor-job-items-${detailJob.job_number}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-foreground">Barang produksi (qty terkunci)</p>
                  <TombolUnduh namaBerkas={`job-${detailJob.job_number}`} baris={detailJob.items} kolom={[
                    { label: 'No. seri', nilai: (i) => i.serial_number || '' }, { label: 'Produk', nilai: (i) => i.product_name },
                    { label: 'SKU', nilai: (i) => i.sku || '' }, { label: 'Artikel buyer', nilai: (i) => i.buyer_ref_code || '' },
                    { label: 'Ukuran', nilai: (i) => i.size || '' }, { label: 'Warna', nilai: (i) => i.color || '' },
                    { label: 'Qty PO', nilai: (i) => Number(i.ordered_qty) || 0 }, { label: 'Tersedia', nilai: (i) => Number(i.available_qty ?? i.shipment_qty) || 0 },
                    { label: 'Diproduksi', nilai: (i) => Number(i.produced_qty) || 0 }, { label: 'Klaim kirim', nilai: (i) => Number(i.qty_claimed_by_vendor) || 0 },
                    { label: 'Lolos QC DA', nilai: (i) => Number(i.qty_accepted) || 0 }, { label: 'Ditolak', nilai: (i) => Number(i.qty_reject) || 0 },
                    { label: 'Permak', nilai: (i) => Number(i.qty_rework_open) || 0 }, { label: 'Belum sampai', nilai: (i) => Number(i.qty_short_open) || 0 },
                  ]} />
                </div>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader><TableRow>
                      {['No. seri', 'Produk', 'SKU', 'Artikel buyer', 'Ukuran', 'Warna'].map((h) => <TableHead key={h} className="whitespace-nowrap">{h}</TableHead>)}
                      {['Qty PO', 'Tersedia', 'Diproduksi', 'Klaim kirim', 'Lolos QC DA', 'Ditolak', 'Permak', 'Belum sampai', 'Sisa'].map((h) => <TableHead key={h} className="text-right whitespace-nowrap">{h}</TableHead>)}
                      <TableHead>Kemajuan</TableHead>
                    </TableRow></TableHeader>
                    <TableBody>{detailJob.items.map((item) => {
                      const avail = item.available_qty ?? item.shipment_qty ?? 0;
                      const pct = avail > 0 ? Math.round(((item.produced_qty || 0) / avail) * 100) : 0;
                      const reject = Number(item.qty_reject || 0);
                      const rework = Number(item.qty_rework_open || 0);
                      const shortOpen = Number(item.qty_short_open || 0);
                      return (
                        <TableRow key={item.id}>
                          <TableCell className="tabular-nums whitespace-nowrap">{item.serial_number || '—'}</TableCell>
                          <TableCell className="font-medium">{item.product_name}</TableCell>
                          <TableCell className="tabular-nums whitespace-nowrap">{item.sku || '—'}</TableCell>
                          <TableCell className="tabular-nums">{item.buyer_ref_code || '—'}</TableCell>
                          <TableCell>{item.size || '—'}</TableCell><TableCell>{item.color || '—'}</TableCell>
                          <TableCell className="text-right tabular-nums">{n(item.ordered_qty)}</TableCell>
                          <TableCell className="text-right tabular-nums">{n(avail)}</TableCell>
                          <TableCell className="text-right tabular-nums font-medium">{n(item.produced_qty)}</TableCell>
                          <TableCell className="text-right tabular-nums">{n(item.qty_claimed_by_vendor)}</TableCell>
                          <TableCell className="text-right tabular-nums">{n(item.qty_accepted)}</TableCell>
                          <TableCell className={`text-right tabular-nums ${reject > 0 ? 'text-[hsl(var(--danger-text))] font-medium' : 'text-muted-foreground'}`}>{n(reject)}</TableCell>
                          <TableCell className={`text-right tabular-nums ${rework > 0 ? 'text-[hsl(var(--warning-text))] font-medium' : 'text-muted-foreground'}`}>{n(rework)}</TableCell>
                          <TableCell className={`text-right tabular-nums ${shortOpen > 0 ? 'text-[hsl(var(--danger-text))] font-semibold' : 'text-muted-foreground'}`}
                            data-testid={`vendor-item-short-${item.id}`} title={shortOpen > 0 ? 'Barang belum sampai di DA — harus dicari & dikirim ulang' : ''}>{n(shortOpen)}</TableCell>
                          <TableCell className="text-right tabular-nums">{n(Math.max(0, avail - (item.produced_qty || 0)))}</TableCell>
                          <TableCell className="min-w-[7rem]"><MiniBar pct={pct} /></TableCell>
                        </TableRow>
                      );
                    })}</TableBody>
                  </Table>
                </div>
                <p className="text-xs text-muted-foreground">
                  <strong>Diproduksi</strong> = hasil vendor (tidak dikurangi yang ditolak). <strong>Lolos QC DA</strong> = diterima DA.
                  <strong> Ditolak</strong> = ditolak saat QC DA. <strong>Permak</strong> = barang ditolak yang masih dikerjakan ulang — bila diretur,
                  surat jalan retur perbaikan muncul di Penerimaan material. <strong>Belum sampai</strong> = diklaim terkirim tetapi tidak diterima DA.
                </p>
              </section>
            )}
          </DetailPopup>
        );
      })()}
    </PageLayout>
  );
}

// ─── VENDOR PROGRESS (per SKU from Production Job) ───────────────────────────


