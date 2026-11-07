import { useState, useEffect } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Plus, Send, Download, Search, CheckCircle, Pencil, Eye, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';
import { postWithOverQtyReason } from '../../../lib/overQty';
import { todayWIB } from '../../../lib/waktu';

export default function VendorBuyerShipments({ user }) {
  const [shipments, setShipments] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [shorts, setShorts] = useState({ items: [], total_qty_open: 0 });
  const [jobItems, setJobItems] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [expandedShipment, setExpandedShipment] = useState(null);
  const [dispatches, setDispatches] = useState({});
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ job_id: '', shipment_date: todayWIB(), notes: '', items: [] });
  const [searchJob, setSearchJob] = useState('');
  const [showAllJobs, setShowAllJobs] = useState(false);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    try {
      const [sData, jData] = await Promise.all([
        apiGet('/buyer-shipments'),
        apiGet('/production-jobs'),
      ]);
      setShipments(Array.isArray(sData) ? sData : []);
      setJobs(Array.isArray(jData) ? jData : []);
      try {
        const sh = await apiGet('/prod/short-shipments?status=open');
        setShorts(sh && typeof sh === 'object' ? sh : { items: [], total_qty_open: 0 });
      } catch { setShorts({ items: [], total_qty_open: 0 }); }
    } catch (e) {
      setShipments([]); setJobs([]);
    }
  };

  const loadJobItems = async (jobId) => {
    const job = jobs.find(j => j.id === jobId);
    setSelectedJob(job || null);
    setForm(f => ({ ...f, job_id: jobId, items: [] }));
    if (!jobId) { setJobItems([]); return; }
    const data = await apiGet(`/production-job-items?job_id=${jobId}`);
    const items = Array.isArray(data) ? data : [];
    setJobItems(items);
    setForm(f => ({
      ...f,
      po_id: job?.po_id || '',
      items: items.map(i => ({
        job_item_id: i.id,
        po_item_id: i.po_item_id || null,
        product_name: i.product_name,
        sku: i.sku,
        size: i.size,
        color: i.color,
        serial_number: i.serial_number || '',
        ordered_qty: i.ordered_qty,
        produced_qty: i.total_produced_qty ?? i.produced_qty,  // parent + child
        // Angka yang relevan untuk vendor = deklarasi ke DA & yang DITERIMA DA
        // (bukan dispatch DA→buyer). Selisih kirim membuka kembali sisa kirim.
        shipped_to_da: i.declared_to_da ?? i.shipped_to_buyer ?? 0,
        received_by_da: i.received_by_da ?? i.received_to_buyer ?? 0,
        qty_short_open: i.qty_short_open || 0,
        shipped_to_buyer: i.shipped_to_buyer || 0,
        received_to_buyer: i.received_to_buyer || 0,
        remaining_to_ship: i.remaining_to_ship || 0,  // produced − diterima DA; selisih membuka lagi
        qty_shipped: 0,
      }))
    }));
  };

  const updateQty = (idx, val) => {
    const items = [...form.items];
    items[idx] = { ...items[idx], qty_shipped: val };
    setForm(f => ({ ...f, items }));
  };

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    if (!form.job_id) { toast.error('Pilih Production Job terlebih dahulu'); return; }
    const validItems = form.items.filter(i => Number(i.qty_shipped) > 0);
    if (validItems.length === 0) { toast.error('Isi minimal 1 item dengan qty > 0'); return; }

    // Check: qty to ship now <= remaining_to_ship
    for (const item of validItems) {
      if (Number(item.qty_shipped) > Number(item.remaining_to_ship)) {
        toast.warning(`Qty kirim ${item.sku} (${item.qty_shipped}) melebihi sisa pengiriman (${item.remaining_to_ship} pcs). Server akan memvalidasi terhadap qty produksi aktual.`);
        return;
      }
    }

    // Check if master shipment already exists for this job
    const existingShipment = shipments.find(s => s.job_id === form.job_id);
    const shipmentNumber = existingShipment ? existingShipment.shipment_number : `SJ-${form.job_id.slice(-6).toUpperCase()}-${Date.now().toString().slice(-4)}`;

    setLoading(true);
    try {
      await postWithOverQtyReason('/buyer-shipments', {
        shipment_number: shipmentNumber,
        job_id: form.job_id,
        po_id: form.po_id || selectedJob?.po_id,
        shipment_date: form.shipment_date,
        notes: form.notes,
        vendor_id: user.vendor_id,
        items: validItems.map(i => ({ ...i, qty_shipped: Number(i.qty_shipped) }))
      });
      setShowModal(false);
      fetchAll();
    } catch (err) {
      toast.error(err.message || 'Gagal membuat pengiriman');
    } finally {
      setLoading(false);
    }
  };

  const loadDispatches = async (shipmentId) => {
    if (expandedShipment === shipmentId) { setExpandedShipment(null); return; }
    setExpandedShipment(shipmentId);
    if (!dispatches[shipmentId]) {
      try {
        const data = await apiGet(`/buyer-shipment-dispatches?shipment_id=${shipmentId}`);
        setDispatches(prev => ({ ...prev, [shipmentId]: Array.isArray(data) ? data : [] }));
      } catch (e) {
        setDispatches(prev => ({ ...prev, [shipmentId]: [] }));
      }
    }
  };

  const openDispatch = (shipment) => {
    // Open modal pre-selected with this job
    const job = jobs.find(j => j.id === shipment.job_id);
    setSelectedJob(job || null);
    setForm({ job_id: shipment.job_id || '', shipment_date: todayWIB(), notes: '', items: [], po_id: shipment.po_id || '' });
    setJobItems([]);
    if (shipment.job_id) loadJobItems(shipment.job_id);
    setShowModal(true);
  };

  const downloadPDF = async (shipment, dispatchData) => {
    try {
      const { default: jsPDF } = await import('jspdf');
      const autoTable = (await import('jspdf-autotable')).default;
      const doc = new jsPDF();
      doc.setFontSize(18); doc.setFont('helvetica', 'bold');
      doc.text('SURAT JALAN / DELIVERY NOTE', 105, 20, { align: 'center' });
      doc.setFontSize(10); doc.setFont('helvetica', 'normal');
      doc.text(`No. SJ: ${shipment.shipment_number}`, 14, 36);
      doc.text(`Status: ${shipment.ship_status || 'Pending'}`, 14, 43);
      doc.text(`Vendor: ${shipment.vendor_name}`, 14, 50);
      doc.text(`PO: ${shipment.po_number || '-'} | Customer: ${shipment.customer_name || '-'}`, 14, 57);

      const allItems = (dispatches[shipment.id] || []).flatMap(d => d.items || []);
      autoTable(doc, {
        startY: 65,
        head: [['No', 'Produk', 'SKU', 'Size', 'Warna', 'Dispatch', 'Dikirim']],
        body: allItems.map((it, i) => [i + 1, it.product_name, it.sku || '-', it.size || '-', it.color || '-', `#${it.dispatch_seq || 1}`, it.qty_shipped]),
        foot: [['', '', '', '', '', 'Total', allItems.reduce((s, i) => s + (i.qty_shipped || 0), 0)]],
        styles: { fontSize: 9 }, headStyles: { fillColor: [16, 185, 129] }, footStyles: { fontStyle: 'bold' }
      });
      doc.save(`SJ-${shipment.shipment_number}.pdf`);
    } catch (err) { toast.error('Gagal generate PDF: ' + err.message); }
  };

  const fmtDate = (d) => formatDateID(d, { fallback: '—' });
  const getStatusColor = (s) => {
    if (s === 'Fully Shipped') return 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))] border border-[hsl(var(--success)/0.35)]';
    if (s === 'Partially Shipped') return 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))] border border-[hsl(var(--warning)/0.35)]';
    return 'bg-muted text-muted-foreground';
  };

  // Compute remaining_to_ship for modal items
  const canAddDispatch = (job) => {
    if (!job) return false;
    return job.status === 'In Progress' || job.total_produced > 0;
  };

  // Standar UI/UX v2 (8 Nov 2026): daftar deklarasi = tabel (dulu kartu tinggi per deklarasi), riwayat dispatch &
  // PDF di popup rincian, form = FormPopup panjang dengan DatePicker. Perhitungan & API sama.
  const n = (v) => Number(v || 0).toLocaleString('id-ID');
  const hitung = (s) => {
    const totalOrdered = s.total_ordered || 0;
    const totalShipped = s.total_shipped || 0;
    const progressPct = s.progress_pct || (totalOrdered > 0 ? Math.round((totalShipped / totalOrdered) * 100) : 0);
    return { totalOrdered, totalShipped, remaining: s.remaining || Math.max(0, totalOrdered - totalShipped), progressPct };
  };
  const statusKirim = (pct) => (pct >= 100 ? ['Terkirim penuh', 'success'] : pct > 0 ? ['Terkirim sebagian', 'warning'] : ['Belum dikirim', 'muted']);
  const [rincian, setRincian] = useState(null);
  const bukaRincian = (s) => { setRincian(s); if (expandedShipment !== s.id) loadDispatches(s.id); };
  const tutupRincian = () => { setRincian(null); setExpandedShipment(null); };
  const lanjutan = !!(form.job_id && shipments.find((s) => s.job_id === form.job_id));
  const sumF = (k) => form.items.reduce((t, i) => t + (Number(i[k]) || 0), 0);

  const kolom = [
    { kunci: 'no', label: 'Deklarasi', hp: 'judul', isi: (s) => (
      <div className="min-w-0"><span className="font-medium tabular-nums">{s.shipment_number}</span>
        <span className="block text-xs text-muted-foreground">{(s.dispatch_count || s.last_dispatch_seq || 0)} dispatch</span></div>) },
    { kunci: 'po', label: 'PO · pelanggan', isi: (s) => (
      <div className="min-w-0 text-sm"><span className="tabular-nums">{s.po_number || '—'}</span>
        <span className="block text-xs text-muted-foreground">{s.customer_name || '—'} · job {jobs.find((j) => j.id === s.job_id)?.job_number || s.job_id || '—'}</span></div>) },
    { kunci: 'kirim', label: 'Dikirim / dipesan', isi: (s) => { const h = hitung(s); return (
      <div className="min-w-[9rem]">
        <span className="text-sm tabular-nums">{n(h.totalShipped)} / {n(h.totalOrdered)} pcs ({h.progressPct}%)</span>
        <div className="mt-1 h-1.5 w-full rounded-full bg-muted"><div className="h-1.5 rounded-full bg-[hsl(var(--primary))]" style={{ width: `${Math.min(h.progressPct, 100)}%` }} /></div>
      </div>); } },
    { kunci: 'sisa', label: 'Sisa', rata: 'kanan', isi: (s) => <span className="tabular-nums">{n(hitung(s).remaining)} pcs</span> },
    { kunci: 'status', label: 'Status', isi: (s) => { const [l, t] = statusKirim(hitung(s).progressPct); return <StatusBadge status={l} label={l} tone={t} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex justify-end gap-1">
        {hitung(s).progressPct < 100 && (
          <Button size="sm" variant="outline" onClick={() => openDispatch(s)} data-testid={`vendor-dispatch-${s.id}`}><Plus className="w-3.5 h-3.5" />Dispatch</Button>
        )}
        <Button size="icon-sm" variant="ghost" onClick={() => bukaRincian(s)} title="Riwayat dispatch & PDF" aria-label="Riwayat dispatch"><Eye className="w-4 h-4" /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="vendor-buyer-shipments" title="Kirim ke DA"
      subtitle="Deklarasi kiriman barang jadi dari CMT ke gudang DA; DA memverifikasi qty dan reject."
      actions={<Button onClick={() => { setForm({ job_id: '', shipment_date: todayWIB(), notes: '', items: [] }); setSelectedJob(null); setJobItems([]); setShowModal(true); }}
        data-testid="btn-create-cmt-shipment"><Plus /> Deklarasi kirim ke DA</Button>}
      tools={<TombolUnduh namaBerkas="deklarasi-kirim-ke-da" namaLembar="Deklarasi" baris={shipments} kolom={[
        { label: 'Deklarasi', nilai: (s) => s.shipment_number }, { label: 'PO', nilai: (s) => s.po_number || '' },
        { label: 'Pelanggan', nilai: (s) => s.customer_name || '' }, { label: 'Job', nilai: (s) => jobs.find((j) => j.id === s.job_id)?.job_number || '' },
        { label: 'Dipesan', nilai: (s) => hitung(s).totalOrdered }, { label: 'Dikirim', nilai: (s) => hitung(s).totalShipped },
        { label: 'Sisa', nilai: (s) => hitung(s).remaining }, { label: 'Kemajuan (%)', nilai: (s) => hitung(s).progressPct },
        { label: 'Status', nilai: (s) => statusKirim(hitung(s).progressPct)[0] }, { label: 'Dispatch', nilai: (s) => s.dispatch_count || s.last_dispatch_seq || 0 },
      ]} />}
      summary={<p className="text-sm text-muted-foreground" data-testid="phase-b-banner">
        Alur CMT → DA → buyer: tiap deklarasi otomatis menjadi draf penerimaan CMT di DA. Setelah DA menyetujui (bisa menolak
        sebagian bila cacat), stok barang jadi DA naik dan utang CMT tercatat sebesar qty aktual × tarif CMT. DA yang mengirim ke buyer.
      </p>}>
      {/* KEWAJIBAN: barang yang BELUM SAMPAI di DA (aturan owner: qty deklarasi mengikuti yang diterima DA). */}
      {shorts.items?.length > 0 && (
        <section className="space-y-2" data-testid="vendor-short-panel">
          <Notice tone="danger" icon={AlertTriangle} title={`${n(shorts.total_qty_open)} pcs belum sampai di DA — harus dicari & dikirim ulang`}>
            DA menerima lebih sedikit dari klaim kirim. Dokumen deklarasi sudah dikoreksi mengikuti qty yang diterima dan sisa kirim bertambah —
            buat dispatch baru untuk mengirim ulang kekurangannya.
          </Notice>
          <div className="flex justify-end">
            <TombolUnduh namaBerkas="barang-belum-sampai-di-da" baris={shorts.items} kolom={[
              { label: 'No. selisih', nilai: (s) => s.short_number }, { label: 'PO', nilai: (s) => s.po_number || '' }, { label: 'SKU', nilai: (s) => s.sku || '' },
              { label: 'Klaim kirim', nilai: (s) => Number(s.qty_claimed) || 0 }, { label: 'Diterima DA', nilai: (s) => Number(s.qty_arrived) || 0 },
              { label: 'Belum sampai', nilai: (s) => Number(s.qty_open ?? s.qty_short) || 0 }, { label: 'Tanggal', nilai: (s) => s.short_date || '' },
            ]} />
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>No. selisih</TableHead><TableHead>PO</TableHead><TableHead>SKU</TableHead>
                <TableHead className="text-right">Klaim kirim</TableHead><TableHead className="text-right">Diterima DA</TableHead>
                <TableHead className="text-right">Belum sampai</TableHead><TableHead>Tanggal</TableHead></TableRow></TableHeader>
              <TableBody>{shorts.items.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="tabular-nums font-medium">{s.short_number}</TableCell><TableCell>{s.po_number || '—'}</TableCell>
                  <TableCell className="tabular-nums">{s.sku || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(s.qty_claimed)}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(s.qty_arrived)}</TableCell>
                  <TableCell className="text-right tabular-nums font-semibold text-[hsl(var(--danger-text))]">{n(s.qty_open ?? s.qty_short)}</TableCell>
                  <TableCell>{s.short_date ? formatDateID(s.short_date, { fallback: s.short_date }) : '—'}</TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </div>
        </section>
      )}

      <TabelData kolom={kolom} baris={shipments} onKlikBaris={bukaRincian} testId="vendor-buyer-shipments-table"
        kosong={<EmptyState icon={Send} title="Belum ada data pengiriman" description="Klik Deklarasi kirim ke DA untuk mencatat pengiriman pertama." />} />

      {/* Rincian deklarasi: riwayat dispatch + PDF */}
      {rincian && (() => {
        const h = hitung(rincian);
        const list = dispatches[rincian.id];
        let kumulatif = 0;
        const [sl, st] = statusKirim(h.progressPct);
        return (
          <DetailPopup open onClose={tutupRincian} judul={`Deklarasi ${rincian.shipment_number}`} testId="vendor-buyer-shipment-detail"
            keterangan={`PO ${rincian.po_number || '—'} · ${rincian.customer_name || '—'}`}
            status={<StatusBadge status={sl} label={sl} tone={st} />}
            aksi={<>
              {h.progressPct < 100 && <Button size="sm" variant="outline" onClick={() => { tutupRincian(); openDispatch(rincian); }}><Plus className="w-4 h-4" />Dispatch</Button>}
              <Button size="sm" variant="outline" disabled={!list} onClick={() => downloadPDF(rincian, list)}><Download className="w-4 h-4" />Unduh PDF</Button>
            </>}>
            <dl className="divide-y divide-[var(--glass-border)]">
              <BarisDetail label="Dikirim / dipesan">{n(h.totalShipped)} / {n(h.totalOrdered)} pcs ({h.progressPct}%)</BarisDetail>
              <BarisDetail label="Sisa">{n(h.remaining)} pcs</BarisDetail>
            </dl>
            <section className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Riwayat dispatch</p>
              {!list ? <p className="text-sm text-muted-foreground">Memuat riwayat…</p> : list.length === 0 ? (
                <p className="text-sm text-muted-foreground">Belum ada dispatch.</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader><TableRow><TableHead>Dispatch</TableHead><TableHead>Tanggal</TableHead><TableHead>No. seri</TableHead><TableHead>SKU</TableHead>
                      <TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Kumulatif</TableHead><TableHead className="text-right">Sisa</TableHead></TableRow></TableHeader>
                    <TableBody>{list.flatMap((d) => {
                      kumulatif += d.total_qty || 0;
                      const sisa = Math.max(0, h.totalOrdered - kumulatif);
                      const kum = kumulatif;
                      return (d.items || []).map((it, i) => (
                        <TableRow key={`${d.dispatch_seq}-${it.id}`}>
                          <TableCell className="tabular-nums">{i === 0 ? `#${d.dispatch_seq}` : ''}</TableCell>
                          <TableCell>{i === 0 ? fmtDate(d.dispatch_date) : ''}</TableCell>
                          <TableCell className="tabular-nums">{it.serial_number || '—'}</TableCell>
                          <TableCell className="tabular-nums">
                            {it.sku || '—'}
                            {it.edit_history?.length > 0 && (
                              <span data-testid={`vendor-edited-badge-${it.id}`} className="ml-2 inline-flex items-center gap-1 text-xs text-[hsl(var(--warning-text))]"
                                title={(it.edit_history || []).map((x) => `${fmtDate(x.edited_at)} • ${x.old_qty}→${x.new_qty} pcs • ${x.edited_by}: ${x.reason}`).join('\n')}>
                                <Pencil className="w-3 h-3" />diubah admin
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{n(it.qty_shipped)}</TableCell>
                          <TableCell className="text-right tabular-nums">{i === 0 ? n(kum) : ''}</TableCell>
                          <TableCell className="text-right tabular-nums">{i === 0 ? n(sisa) : ''}</TableCell>
                        </TableRow>
                      ));
                    })}</TableBody>
                  </Table>
                </div>
              )}
            </section>
          </DetailPopup>
        );
      })()}

      {/* Buat / tambah dispatch — FormPopup panjang */}
      {showModal && (
        <FormPopup open onClose={() => setShowModal(false)} ukuran="panjang" testId="vendor-buyer-shipment-form"
          judul={lanjutan ? 'Tambah dispatch pengiriman' : 'Deklarasi kirim ke DA'}
          keterangan={lanjutan ? 'Dispatch baru ditambahkan ke deklarasi yang sudah ada untuk job ini.' : 'Qty kirim tidak boleh melebihi sisa yang belum dikirim.'}
          onSimpan={handleSubmit} menyimpan={loading} labelSimpan="Kirim">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Isian label="Job produksi" wajib petunjuk={jobs.length === 0 ? 'Job produksi untuk vendor ini belum tersedia.' : null}>
              <div className="space-y-2">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input className="pl-8" placeholder="Cari no. job atau PO" value={searchJob} onChange={(e) => setSearchJob(e.target.value)} />
                </div>
                <SmartNativeSelect className="w-full" value={form.job_id} onChange={(e) => { setSearchJob(''); loadJobItems(e.target.value); }} aria-label="Pilih job produksi">
                  <option value="">Pilih job produksi</option>
                  {(() => {
                    const q = searchJob.toLowerCase();
                    const cocok = (j) => !q || j.job_number?.toLowerCase().includes(q) || j.po_number?.toLowerCase().includes(q);
                    const available = jobs.filter((j) => (j.remaining_to_ship || 0) > 0 && cocok(j));
                    const notStarted = jobs.filter((j) => (j.total_produced || 0) === 0 && cocok(j) && (showAllJobs || q));
                    const completed = jobs.filter((j) => (j.remaining_to_ship || 0) <= 0 && (j.total_produced || 0) > 0 && cocok(j) && (showAllJobs || q));
                    return (
                      <>
                        {available.length > 0 && (
                          <optgroup label={`Ada sisa kirim (${available.length})`}>
                            {available.map((j) => (
                              <option key={j.id} value={j.id}>{j.job_number} · PO {j.po_number || '—'} · {j.progress_pct || 0}% produksi · {shipments.find((s) => s.job_id === j.id) ? 'lanjut kirim' : 'belum dikirim'}</option>
                            ))}
                          </optgroup>
                        )}
                        {notStarted.length > 0 && (
                          <optgroup label={`Belum ada produksi (${notStarted.length})`}>
                            {notStarted.map((j) => <option key={j.id} value={j.id}>{j.job_number} · PO {j.po_number || '—'} · 0% produksi</option>)}
                          </optgroup>
                        )}
                        {completed.length > 0 && (
                          <optgroup label={`Sudah terkirim penuh (${completed.length})`}>
                            {completed.map((j) => <option key={j.id} value={j.id}>{j.job_number} · PO {j.po_number || '—'} · selesai</option>)}
                          </optgroup>
                        )}
                        {available.length === 0 && notStarted.length === 0 && completed.length === 0 && q && (
                          <option disabled>Tidak ditemukan: "{searchJob}"</option>
                        )}
                      </>
                    );
                  })()}
                </SmartNativeSelect>
                <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => setShowAllJobs((v) => !v)}>
                  {showAllJobs ? 'Sembunyikan job selesai/belum mulai' : 'Tampilkan semua job'}
                </Button>
              </div>
            </Isian>
            <Isian label="Tanggal dispatch">
              <DatePicker value={form.shipment_date} onChange={(v) => setForm((f) => ({ ...f, shipment_date: v }))} bolehKosong={false} />
            </Isian>
          </div>
          {selectedJob && <p className="text-sm text-muted-foreground">{selectedJob.job_number} — {selectedJob.po_number}. Qty kirim tidak boleh melebihi sisa kirim.</p>}
          {form.items.length > 0 && (
            <section className="space-y-2">
              <p className="text-sm font-medium text-foreground">Barang yang dikirim</p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow>
                    <TableHead>No. seri</TableHead><TableHead>Produk / SKU</TableHead>
                    {['Dipesan', 'Diproduksi', 'Diklaim ke DA', 'Diterima DA', 'Belum sampai', 'Sisa kirim', 'Kirim sekarang *'].map((h) => <TableHead key={h} className="text-right whitespace-nowrap">{h}</TableHead>)}
                  </TableRow></TableHeader>
                  <TableBody>{form.items.map((item, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="tabular-nums">{item.serial_number || '—'}</TableCell>
                      <TableCell><p className="font-medium">{item.product_name}</p><p className="text-xs text-muted-foreground tabular-nums">{item.sku || '—'} · {item.size}/{item.color}</p></TableCell>
                      <TableCell className="text-right tabular-nums">{n(item.ordered_qty)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(item.produced_qty)}{item.child_produced_qty > 0 && <span className="block text-xs text-muted-foreground">+{item.child_produced_qty} turunan</span>}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(item.shipped_to_da)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(item.received_by_da)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${(item.qty_short_open || 0) > 0 ? 'text-[hsl(var(--danger-text))] font-semibold' : 'text-muted-foreground'}`}>{n(item.qty_short_open)}</TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{n(item.remaining_to_ship)}</TableCell>
                      <TableCell className="text-right">
                        <Input type="number" min="0" max={item.remaining_to_ship} aria-label={`Kirim sekarang ${item.product_name}`}
                          className={`h-8 w-24 ml-auto text-right ${Number(item.qty_shipped) > Number(item.remaining_to_ship) ? 'border-[hsl(var(--destructive))] text-[hsl(var(--danger-text))]' : ''}`}
                          value={item.qty_shipped} onChange={(e) => updateQty(idx, e.target.value)} />
                      </TableCell>
                    </TableRow>
                  ))}</TableBody>
                  <TableFooter><TableRow>
                    <TableCell colSpan={2} className="font-semibold">Total</TableCell>
                    {['ordered_qty', 'produced_qty', 'shipped_to_da', 'received_by_da', 'qty_short_open', 'remaining_to_ship'].map((k) => (
                      <TableCell key={k} className="text-right tabular-nums font-semibold">{n(sumF(k))}</TableCell>
                    ))}
                    <TableCell className="text-right tabular-nums font-semibold">{n(sumF('qty_shipped'))} pcs</TableCell>
                  </TableRow></TableFooter>
                </Table>
              </div>
            </section>
          )}
          <Isian label="Catatan">
            <Textarea rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
          </Isian>
        </FormPopup>
      )}
    </PageLayout>
  );
}
// ─── VENDOR MATERIAL INSPECTION ───────────────────────────────────────────────


