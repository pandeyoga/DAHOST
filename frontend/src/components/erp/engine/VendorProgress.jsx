import { useState, useEffect } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import PageLayout from '../layout/PageLayout';
import { PageLayoutSatuBaris } from './DataTable';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { MiniBar } from './VendorShared';
import { apiGet, apiPost } from '../../../lib/api';
import { todayWIB } from '../../../lib/waktu';

export default function VendorProgress({ token, user }) {
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [jobItems, setJobItems] = useState([]);
  const [childJobs, setChildJobs] = useState([]);
  const [selectedChildJobId, setSelectedChildJobId] = useState('');
  const [childJobItems, setChildJobItems] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);
  const [form, setForm] = useState({ progress_date: todayWIB(), completed_quantity: '', notes: '' });
  const [loading, setLoading] = useState(false);

  useEffect(() => { fetchJobs(); }, []);

  const fetchJobs = async () => {
    try {
      const data = await apiGet('/production-jobs');
      setJobs(Array.isArray(data) ? data.filter(j => j.status === 'In Progress') : []);
    } catch (e) { console.error(e); }
  };

  const loadJobItems = async (jobId) => {
    const job = jobs.find(j => j.id === jobId);
    setSelectedJob(job || null);
    setSelectedChildJobId('');
    setChildJobItems([]);
    if (!jobId) { setJobItems([]); setChildJobs([]); return; }
    try {
      const data = await apiGet(`/production-job-items?job_id=${jobId}`);
      setJobItems(Array.isArray(data) ? data : []);
      setChildJobs(job?.child_jobs || []);
    } catch (e) { console.error(e); }
  };

  const loadChildJobItems = async (childJobId) => {
    setSelectedChildJobId(childJobId);
    if (!childJobId) { setChildJobItems([]); return; }
    try {
      const data = await apiGet(`/production-job-items?job_id=${childJobId}`);
      setChildJobItems(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); }
  };

  const openProgress = (item) => {
    setSelectedItem(item);
    setForm({ progress_date: todayWIB(), completed_quantity: '', notes: '' });
    setShowModal(true);
  };

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (!selectedItem) return;
    setLoading(true);
    try {
      await apiPost('/production-progress', {
        job_item_id: selectedItem.id,
        progress_date: form.progress_date,
        completed_quantity: Number(form.completed_quantity),
        notes: form.notes
      });
      setShowModal(false);
      loadJobItems(selectedJob?.id);
      if (selectedChildJobId) loadChildJobItems(selectedChildJobId);
      fetchJobs();
    } catch (err) {
      toast.error(err.message || 'Gagal menyimpan progress');
    } finally {
      setLoading(false);
    }
  };

  // Standar UI/UX v2 (8 Nov 2026): PageLayout; pilih job di baris penyaring; barang = TabelData (+ unduh);
  // job turunan dipilih dengan pil; form progress = FormPopup pendek dengan DatePicker. API & aturan sama.
  const n = (v) => Number(v || 0).toLocaleString('id-ID');
  const tersedia = (it) => it.available_qty ?? it.shipment_qty ?? 0;
  const sisaDari = (it) => Math.max(0, tersedia(it) - (it.produced_qty || 0));
  const kolomBarang = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (it) => (
      <div className="min-w-0"><span className="font-medium">{it.product_name}</span>
        <span className="block text-xs text-muted-foreground tabular-nums">{it.sku || '—'} · {it.size || '—'}/{it.color || '—'}{it.serial_number ? ` · seri ${it.serial_number}` : ''}</span></div>) },
    { kunci: 'tersedia', label: 'Tersedia', rata: 'kanan', isi: (it) => <span className="tabular-nums">{n(tersedia(it))}</span> },
    { kunci: 'produksi', label: 'Diproduksi', rata: 'kanan', isi: (it) => <span className="tabular-nums font-medium">{n(it.produced_qty)}</span> },
    { kunci: 'sisa', label: 'Sisa', rata: 'kanan', isi: (it) => <span className={`tabular-nums ${sisaDari(it) === 0 ? 'text-muted-foreground' : 'text-[hsl(var(--warning-text))]'}`}>{n(sisaDari(it))}</span> },
    { kunci: 'progres', label: 'Kemajuan', isi: (it) => {
      const av = tersedia(it);
      return <div className="min-w-[7rem]"><MiniBar pct={av > 0 ? Math.round(((it.produced_qty || 0) / av) * 100) : 0} /></div>;
    } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => ((it.produced_qty || 0) >= tersedia(it) && tersedia(it) > 0
      ? <StatusBadge status="done" tone="success" label="Selesai" />
      : <Button size="sm" onClick={() => openProgress(it)} data-testid={`vendor-progress-input-${it.id}`}><Plus className="w-3.5 h-3.5" />Isi progress</Button>) },
  ];
  const kolomUnduh = [
    { label: 'No. seri', nilai: (it) => it.serial_number || '' }, { label: 'Produk', nilai: (it) => it.product_name },
    { label: 'SKU', nilai: (it) => it.sku || '' }, { label: 'Ukuran', nilai: (it) => it.size || '' }, { label: 'Warna', nilai: (it) => it.color || '' },
    { label: 'Tersedia', nilai: (it) => Number(tersedia(it)) || 0 }, { label: 'Diproduksi', nilai: (it) => Number(it.produced_qty) || 0 },
    { label: 'Sisa', nilai: sisaDari },
  ];
  const anakAktif = childJobs.find((c) => c.id === selectedChildJobId);
  const maks = selectedItem ? sisaDari(selectedItem) : 0;

  return (
    <PageLayoutSatuBaris testId="vendor-progress" title="Progress produksi"
      subtitle="Isi progress harian per SKU: pilih job produksi, lalu isi qty yang selesai."
      filters={jobs.length > 0 && (
        <SmartNativeSelect className="w-full sm:w-96" value={selectedJob?.id || ''} onChange={(e) => loadJobItems(e.target.value)}
          aria-label="Pilih job produksi" data-testid="vendor-progress-job-select">
          <option value="">Pilih job produksi</option>
          {jobs.map((j) => (
            <option key={j.id} value={j.id}>
              {j.job_number} — PO {j.po_number || '—'} ({j.progress_pct || 0}% selesai){j.child_job_count > 0 ? ` · +${j.child_job_count} turunan` : ''}
            </option>
          ))}
        </SmartNativeSelect>
      )}
      tools={jobItems.length > 0 && <TombolUnduh namaBerkas={`progress-${selectedJob?.job_number || 'job'}`} baris={jobItems} kolom={kolomUnduh} />}
      summary={selectedJob && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span className="font-medium">{selectedJob.job_number} · PO {selectedJob.po_number || '—'} · kiriman {selectedJob.shipment_number}</span>
          <span className="text-muted-foreground tabular-nums">Diproduksi {n(selectedJob.total_produced)} dari {n(selectedJob.total_available)} pcs tersedia</span>
          <span className="w-40"><MiniBar pct={selectedJob.progress_pct || 0} /></span>
          {(selectedJob.serial_numbers || []).length > 0 && <span className="text-xs text-muted-foreground tabular-nums">Seri: {selectedJob.serial_numbers.join(', ')}</span>}
        </div>
      )}>
      {jobs.length === 0 ? (
        <EmptyState title="Tidak ada job produksi yang aktif" description="Buat job produksi di Pekerjaan produksi." />
      ) : !selectedJob ? (
        <EmptyState title="Pilih job produksi" description="Barang job yang dipilih tampil di sini untuk diisi progressnya." />
      ) : (
        <>
          <section className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Barang job utama ({selectedJob.job_number})</p>
            <TabelData kolom={kolomBarang} baris={jobItems} testId="vendor-progress-items"
              kosong={<EmptyState title="Tidak ada barang" description="Job ini belum punya baris barang." />} />
          </section>
          {childJobs.length > 0 && (
            <section className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Job turunan (kiriman tambahan/pengganti)</p>
              <FilterChips value={selectedChildJobId || ''} onChange={(v) => loadChildJobItems(v)} hideWhenEmpty={false} ariaLabel="Job turunan"
                options={childJobs.map((child) => ({ key: child.id, label: `${child.job_number} · ${child.shipment_type === 'ADDITIONAL' ? 'tambahan' : child.shipment_type === 'REPLACEMENT' ? 'pengganti' : child.shipment_type}` }))} />
              {anakAktif && (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm text-muted-foreground">Barang job turunan {anakAktif.job_number}</p>
                    <TombolUnduh namaBerkas={`progress-${anakAktif.job_number}`} baris={childJobItems} kolom={kolomUnduh} />
                  </div>
                  <TabelData kolom={kolomBarang} baris={childJobItems} testId="vendor-progress-child-items"
                    kosong={<EmptyState title="Tidak ada barang" description="Job turunan ini belum punya baris barang." />} />
                </div>
              )}
            </section>
          )}
        </>
      )}

      {/* Isi progress — FormPopup pendek */}
      {showModal && selectedItem && (
        <FormPopup open onClose={() => setShowModal(false)} ukuran="pendek" testId="vendor-progress-form"
          judul={`Isi progress ${selectedItem.sku || selectedItem.product_name}`} onSimpan={handleSubmit} menyimpan={loading} labelSimpan="Simpan progress">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            {[
              ['No. seri / batch', selectedItem.serial_number || '—'], ['Produk', selectedItem.product_name],
              ['SKU', selectedItem.sku || '—'], ['Ukuran / warna', `${selectedItem.size || '—'} / ${selectedItem.color || '—'}`],
              ['Bahan tersedia', `${n(tersedia(selectedItem))} pcs`], ['Sudah diproduksi', `${n(selectedItem.produced_qty)} pcs`],
              ['Sisa (maks isi)', `${n(maks)} pcs`],
            ].map(([l, v]) => (
              <div key={l} className="min-w-0"><dt className="text-xs text-muted-foreground">{l}</dt><dd className="font-medium">{v}</dd></div>
            ))}
          </dl>
          <Isian label="Tanggal progress" wajib>
            <DatePicker value={form.progress_date} onChange={(v) => setForm((f) => ({ ...f, progress_date: v }))} bolehKosong={false} />
          </Isian>
          <Isian label="Jumlah selesai (pcs)" wajib htmlFor="vp-qty" petunjuk={`Maksimal ${n(maks)} pcs.`}>
            <Input id="vp-qty" required type="number" min="1" max={maks} className="text-right"
              value={form.completed_quantity} onChange={(e) => setForm((f) => ({ ...f, completed_quantity: e.target.value }))} placeholder={`1 – ${maks}`} />
          </Isian>
          <Isian label="Catatan" htmlFor="vp-notes">
            <Textarea id="vp-notes" rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} placeholder="Catatan produksi…" />
          </Isian>
        </FormPopup>
      )}
    </PageLayoutSatuBaris>
  );
}

// ─── VENDOR BUYER SHIPMENTS (cumulative dispatches per job) ───────────────────


