import { useState, useEffect } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Plus, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import { apiGet, apiPost } from '../../../lib/api';

export default function VendorVarianceReport({ token, user }) {
  const [variances, setVariances] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState({
    job_id: '',
    variance_type: 'OVERPRODUCTION',
    reason: '',
    notes: '',
    items: []
  });

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [vData, jData] = await Promise.all([
        apiGet('/production-variances'),
        apiGet('/production-jobs'),
      ]);
      setVariances(Array.isArray(vData) ? vData : []);
      setJobs(Array.isArray(jData) ? jData : []);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const openCreate = () => {
    setForm({ job_id: '', variance_type: 'OVERPRODUCTION', reason: '', notes: '', items: [] });
    setShowModal(true);
  };

  const handleJobChange = async (jobId) => {
    setForm(prev => ({ ...prev, job_id: jobId, items: [] }));
    if (!jobId) return;
    try {
      const data = await apiGet(`/production-jobs/${jobId}`);
      const items = (data.items || []).map(ji => ({
        job_item_id: ji.id,
        product_name: ji.product_name,
        sku: ji.sku,
        size: ji.size,
        color: ji.color,
        ordered_qty: ji.ordered_qty || 0,
        produced_qty: ji.produced_qty || 0,
        // 2026-11-06 (Tahap 2): variance dari catatan produksi (sistem), tidak diketik.
        diff: (ji.produced_qty || 0) - (ji.ordered_qty || 0),
        variance_qty: Math.abs((ji.produced_qty || 0) - (ji.ordered_qty || 0)),
      }));
      setForm(prev => ({ ...prev, items }));
    } catch (e) { console.error(e); }
  };

  const submit = async () => {
    if (!form.job_id || !form.variance_type || !form.reason) {
      toast.error('Job, Tipe Variance, dan Alasan wajib diisi');
      return;
    }
    const over = form.variance_type === 'OVERPRODUCTION';
    const itemsWithVariance = form.items.filter(i => (over ? i.diff > 0 : i.diff < 0));
    if (itemsWithVariance.length === 0) {
      toast.error(over ? 'Menurut catatan produksi tidak ada baris yang produksinya lebih dari pesanan.'
        : 'Menurut catatan produksi tidak ada baris yang produksinya kurang dari pesanan.');
      return;
    }
    try {
      await apiPost('/production-variances', { ...form, items: itemsWithVariance.map(i => ({ job_item_id: i.job_item_id })) });
      toast.success('Laporan variance berhasil disimpan');
      setShowModal(false);
      fetchAll();
    } catch (err) {
      toast.error(`Gagal: ${err.message || 'Unknown error'}`);
    }
  };

  // Standar UI/UX v2 (8 Nov 2026): PageLayout, kartu angka StatTile, tabel TabelData (+ unduh), form FormPopup.
  const JENIS = { OVERPRODUCTION: ['Produksi lebih', 'warning'], UNDERPRODUCTION: ['Produksi kurang', 'info'] };
  const STATUS_V = { Reported: ['Dilaporkan', 'warning'], Acknowledged: ['Diterima DA', 'info'], Resolved: ['Selesai', 'success'] };
  const lbl = (map, k) => map[k] || [k || '—', 'default'];
  const kolom = [
    { kunci: 'job', label: 'No. job', hp: 'judul', isi: (v) => <span className="font-medium tabular-nums">{v.job_number}</span> },
    { kunci: 'po', label: 'No. PO', isi: (v) => <span className="tabular-nums">{v.po_number || '—'}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (v) => { const [l, t] = lbl(JENIS, v.variance_type); return <StatusBadge status={v.variance_type} label={l} tone={t} />; } },
    { kunci: 'qty', label: 'Total selisih (pcs)', rata: 'kanan', isi: (v) => <span className="tabular-nums">{v.total_variance_qty}</span> },
    { kunci: 'alasan', label: 'Alasan', hp: 'keterangan', isi: (v) => <span className="block max-w-xs truncate text-sm text-muted-foreground" title={v.reason}>{v.reason}</span> },
    { kunci: 'status', label: 'Status', isi: (v) => { const [l, t] = lbl(STATUS_V, v.status); return <StatusBadge status={v.status} label={l} tone={t} />; } },
    { kunci: 'tgl', label: 'Tanggal', isi: (v) => formatDateID(v.created_at, { fallback: '—' }) },
  ];
  const nOver = variances.filter((v) => v.variance_type === 'OVERPRODUCTION').length;
  const nUnder = variances.filter((v) => v.variance_type === 'UNDERPRODUCTION').length;

  return (
    <PageLayout testId="vendor-variance-report" title="Laporan selisih produksi" subtitle="Laporkan produksi yang lebih atau kurang dari pesanan."
      actions={<Button type="button" onClick={openCreate} data-testid="vendor-variance-create"><Plus className="w-4 h-4" /> Buat laporan</Button>}
      tools={<TombolUnduh namaBerkas="laporan-selisih-produksi" baris={variances} kolom={[
        { label: 'No. job', nilai: (v) => v.job_number || '' }, { label: 'No. PO', nilai: (v) => v.po_number || '' },
        { label: 'Jenis', nilai: (v) => lbl(JENIS, v.variance_type)[0] }, { label: 'Total selisih (pcs)', nilai: (v) => Number(v.total_variance_qty) || 0 },
        { label: 'Alasan', nilai: (v) => v.reason || '' }, { label: 'Status', nilai: (v) => lbl(STATUS_V, v.status)[0] },
        { label: 'Tanggal', nilai: (v) => formatDateID(v.created_at, { fallback: '' }) },
      ]} />}
      summary={variances.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatTile label="Total laporan" value={variances.length} sub="Semua laporan selisih vendor ini" />
          <StatTile label="Produksi lebih" value={nOver} accent={nOver ? 'warning' : 'default'} sub="Laporan jenis lebih" />
          <StatTile label="Produksi kurang" value={nUnder} sub="Laporan jenis kurang" />
        </div>
      )}>
      {loading ? <p className="py-10 text-center text-sm text-muted-foreground">Memuat laporan…</p> : (
        <TabelData kolom={kolom} baris={variances} testId="vendor-variance-table"
          kosong={<EmptyState icon={AlertTriangle} title="Belum ada laporan selisih" description="Buat laporan bila produksi lebih atau kurang dari pesanan." />} />
      )}

      {showModal && (
        <FormPopup open onClose={() => setShowModal(false)} ukuran="panjang" judul="Buat laporan selisih produksi" testId="vendor-variance-form"
          keterangan="Selisih per baris dihitung dari catatan produksi, tidak diketik." onSimpan={submit} labelSimpan="Simpan laporan">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Isian label="Job produksi" wajib>
              <SmartNativeSelect value={form.job_id} onChange={(e) => handleJobChange(e.target.value)} className="w-full" aria-label="Pilih job">
                <option value="">Pilih job</option>
                {jobs.map((j) => <option key={j.id} value={j.id}>{j.job_number} · PO {j.po_number}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Jenis selisih" wajib>
              <SmartNativeSelect value={form.variance_type} onChange={(e) => setForm({ ...form, variance_type: e.target.value })}
                className="w-full" data-testid="vendor-variance-type">
                <option value="OVERPRODUCTION">Produksi lebih</option>
                <option value="UNDERPRODUCTION">Produksi kurang</option>
              </SmartNativeSelect>
            </Isian>
          </div>
          <Isian label="Alasan" wajib>
            <Textarea value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} rows={2}
              placeholder="Jelaskan alasan selisih (contoh: bahan lebih/kurang, permintaan mendadak)" />
          </Isian>
          <Isian label="Catatan tambahan">
            <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} placeholder="Catatan internal (opsional)" />
          </Isian>
          {form.items.length > 0 && (
            <section className="space-y-2">
              <p className="text-sm font-medium text-foreground">Barang produksi — selisih dari catatan produksi</p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow>
                    {['Produk', 'SKU', 'Ukuran', 'Warna'].map((h) => <TableHead key={h}>{h}</TableHead>)}
                    {['Dipesan', 'Diproduksi', 'Selisih'].map((h) => <TableHead key={h} className="text-right">{h}</TableHead>)}
                  </TableRow></TableHeader>
                  <TableBody>{form.items.map((item, idx) => (
                    <TableRow key={idx}>
                      <TableCell>{item.product_name}</TableCell><TableCell className="tabular-nums">{item.sku}</TableCell>
                      <TableCell>{item.size}</TableCell><TableCell>{item.color}</TableCell>
                      <TableCell className="text-right tabular-nums">{item.ordered_qty}</TableCell>
                      <TableCell className="text-right tabular-nums">{item.produced_qty}</TableCell>
                      <TableCell className="text-right tabular-nums">{item.diff > 0 ? `+${item.diff}` : item.diff}</TableCell>
                    </TableRow>
                  ))}</TableBody>
                </Table>
              </div>
            </section>
          )}
        </FormPopup>
      )}
    </PageLayout>
  );
}


