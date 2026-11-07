import { useState, useEffect } from 'react';
import { ClipboardCheck, Eye, FileDown, RefreshCw } from 'lucide-react';
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
import { EmptyState, StatusBadge } from '../moduleAtoms';
import AdditionalRequestModal from './AdditionalRequestModal';
import { apiGet, apiPost, apiFetch } from '../../../lib/api';
import { todayWIB } from '../../../lib/waktu';

export default function VendorMaterialInspection({ user }) {
  const [shipments, setShipments] = useState([]);
  const [inspections, setInspections] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [selectedShipment, setSelectedShipment] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ inspection_date: todayWIB(), overall_notes: '', items: [], accessory_items: [] });
  // Phase 16: state untuk modal Permintaan Tambahan
  const [showReqModal, setShowReqModal] = useState(false);
  const [reqModalData, setReqModalData] = useState(null);

  useEffect(() => { fetchShipments(); fetchInspections(); }, []);

  const fetchShipments = async () => {
    try {
      const data = await apiGet('/vendor-shipments');
      const received = Array.isArray(data) ? data.filter(s => s.status === 'Received') : [];
      setShipments(received);
    } catch (e) { setShipments([]); }
  };

  const fetchInspections = async () => {
    try {
      const data = await apiGet('/vendor-material-inspections');
      setInspections(Array.isArray(data) ? data : []);
    } catch (e) { setInspections([]); }
  };

  const openInspect = async (shipment) => {
    setSelectedShipment(shipment);
    const data = await apiGet(`/vendor-shipments/${shipment.id}`);
    const items = (data.items || []).map(si => ({
      shipment_item_id: si.id,
      po_item_id: si.po_item_id || '',
      po_id: si.po_id || data.po_id || '',
      sku: si.sku || '',
      product_name: si.product_name || '',
      size: si.size || '',
      color: si.color || '',
      serial_number: si.serial_number || '',
      ordered_qty: si.qty_sent || 0,
      received_qty: si.qty_sent || 0,
      missing_qty: 0,
      condition_notes: ''
    }));
    
    // Load accessories for inspection
    // For additional accessory shipments, use accessory_items from shipment
    // For normal shipments, use po_accessories from linked PO
    let accessory_items = [];
    if (data.accessory_items && data.accessory_items.length > 0) {
      // This is an additional accessory shipment
      accessory_items = data.accessory_items.map(asi => ({
        accessory_id: asi.accessory_id || '',
        accessory_name: asi.accessory_name || '',
        accessory_code: asi.accessory_code || '',
        unit: asi.unit || 'pcs',
        ordered_qty: asi.qty_sent || 0,
        received_qty: asi.qty_sent || 0,
        missing_qty: 0,
        condition_notes: ''
      }));
    } else if (data.po_accessories && data.po_accessories.length > 0) {
      // Normal shipment with PO accessories
      accessory_items = data.po_accessories.map(acc => ({
        accessory_id: acc.accessory_id || acc.id || '',
        accessory_name: acc.accessory_name || '',
        accessory_code: acc.accessory_code || '',
        unit: acc.unit || 'pcs',
        ordered_qty: acc.qty_needed || 0,
        received_qty: acc.qty_needed || 0,
        missing_qty: 0,
        condition_notes: ''
      }));
    }
    
    setForm({ inspection_date: todayWIB(), overall_notes: '', items, accessory_items });
    setShowModal(true);
  };

  const updateItem = (idx, field, value) => {
    const newItems = [...form.items];
    newItems[idx] = { ...newItems[idx], [field]: value };
    if (field === 'received_qty') {
      newItems[idx].missing_qty = Math.max(0, (newItems[idx].ordered_qty || 0) - (Number(value) || 0));
    }
    setForm(f => ({ ...f, items: newItems }));
  };

  const updateAccItem = (idx, field, value) => {
    const newItems = [...form.accessory_items];
    newItems[idx] = { ...newItems[idx], [field]: value };
    if (field === 'received_qty') {
      newItems[idx].missing_qty = Math.max(0, (newItems[idx].ordered_qty || 0) - (Number(value) || 0));
    }
    setForm(f => ({ ...f, accessory_items: newItems }));
  };

  const handleSubmit = async (e) => {
    e?.preventDefault?.();
    setLoading(true);
    try {
      let inspectionData;
      try {
        inspectionData = await apiPost('/vendor-material-inspections', { shipment_id: selectedShipment.id, ...form });
      } catch (err) {
        toast.error(err.message || 'Gagal menyimpan inspeksi');
        return;
      }
      setShowModal(false);
      fetchShipments();
      fetchInspections();

      // Phase 16: jika ada missing item, buka AdditionalRequestModal (bukan window.confirm)
      const totalMissingMaterial = form.items.reduce((s, i) => s + (i.missing_qty || 0), 0);
      const totalMissingAccessory = (form.accessory_items || []).reduce((s, a) => s + (a.missing_qty || 0), 0);
      const totalMissing = totalMissingMaterial + totalMissingAccessory;

      if (totalMissingMaterial > 0) {
        // Build defaultItems untuk modal (per-item dengan max_qty = missing_qty)
        const shipNumber = selectedShipment.shipment_number;
        const defaultItems = form.items
          .filter(i => (i.missing_qty || 0) > 0)
          .map(i => ({
            shipment_item_id: i.shipment_item_id,
            po_item_id: i.po_item_id || '',
            sku: i.sku,
            product_name: i.product_name,
            size: i.size,
            color: i.color,
            serial_number: i.serial_number || '',
            requested_qty: i.missing_qty,
            max_qty: i.missing_qty, // tidak boleh minta lebih dari yang missing
            reason: `Missing dari inspeksi shipment ${shipNumber}`
          }));

        setReqModalData({
          shipment: {
            id: selectedShipment.id,
            shipment_number: shipNumber,
            vendor_name: selectedShipment.vendor_name,
            po_id: selectedShipment.po_id || (form.items[0]?.po_id || ''),
            po_number: selectedShipment.po_number || '',
          },
          defaultItems,
          defaultReason: `Material missing setelah inspeksi shipment ${shipNumber}`,
          inspectionId: inspectionData.id,
          mode: 'inspection',
        });
        setShowReqModal(true);
      }
      if (totalMissing === 0) {
        toast.success('Inspeksi berhasil disimpan! Material & aksesoris lengkap — Anda dapat memulai produksi.');
      } else if (totalMissingMaterial === 0 && totalMissingAccessory > 0) {
        toast.info(`Inspeksi disimpan. Terdeteksi ${totalMissingAccessory} pcs aksesoris missing — sistem membuat permintaan otomatis.`);
      } else {
        toast.success('Inspeksi disimpan. Silakan lengkapi permintaan material tambahan.');
      }
    } finally {
      setLoading(false);
    }
  };

  const openDetail = (insp) => {
    setDetailData(insp);
    setShowDetail(true);
  };

  const fmtDate = (d) => formatDateID(d, { fallback: '—' });

  // Check if inspection is overdue (>3 days from shipment received)
  const isOverdue = (shipment) => {
    if (!shipment.updated_at) return false;
    const receivedDate = new Date(shipment.updated_at);
    const threeDaysLater = new Date(receivedDate.getTime() + 3 * 24 * 60 * 60 * 1000);
    return new Date() > threeDaysLater;
  };

  // Already inspected shipment IDs
  const inspectedShipmentIds = new Set(inspections.map(i => i.shipment_id));

  const pendingShipments = shipments.filter(s => !inspectedShipmentIds.has(s.id));

  const unduhPdf = async (insp) => {
    try {
      const res = await apiFetch(`/export-pdf?type=vendor-inspection&id=${insp.id}`);
      if (!res.ok) throw new Error('Unduh gagal');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Inspeksi-${insp.shipment_number || 'tanpa-nomor'}.pdf`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) { toast.error('Gagal mengunduh PDF: ' + err.message); }
  };
  const sum = (list, k) => list.reduce((s, i) => s + (Number(i[k]) || 0), 0);

  const kolomTunggu = [
    { kunci: 'no', label: 'Kiriman', hp: 'judul', isi: (s) => <span className="font-medium tabular-nums">{s.shipment_number}</span> },
    { kunci: 'tgl', label: 'Diterima', isi: (s) => fmtDate(s.updated_at) },
    { kunci: 'jenis', label: 'Jenis', isi: (s) => s.shipment_type || 'NORMAL' },
    { kunci: 'batas', label: 'Batas 3 hari', isi: (s) => (isOverdue(s)
      ? <StatusBadge status="late" tone="danger" label="Terlambat" /> : <StatusBadge status="ok" tone="warning" label="Masih dalam batas" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <Button size="sm" onClick={() => openInspect(s)} data-testid={`vendor-inspect-${s.id}`}><ClipboardCheck className="w-4 h-4" />Inspeksi</Button>) },
  ];
  const kolomRiwayat = [
    { kunci: 'no', label: 'Kiriman', hp: 'judul', isi: (i) => <span className="font-medium tabular-nums">{i.shipment_number}</span> },
    { kunci: 'tgl', label: 'Tanggal inspeksi', isi: (i) => fmtDate(i.inspection_date) },
    { kunci: 'terima', label: 'Diterima', rata: 'kanan', isi: (i) => <span className="tabular-nums">{i.total_received} pcs</span> },
    { kunci: 'kurang', label: 'Kurang', rata: 'kanan', isi: (i) => (
      <span className={`tabular-nums ${i.total_missing > 0 ? 'text-[hsl(var(--danger-text))] font-medium' : 'text-muted-foreground'}`}>{i.total_missing} pcs</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (i) => (
      <Button size="icon-sm" variant="ghost" onClick={() => openDetail(i)} title="Lihat rincian" aria-label="Lihat rincian"><Eye className="w-4 h-4" /></Button>) },
  ];

  return (
    <PageLayout testId="vendor-material-inspection" title="Inspeksi material"
      subtitle="Laporkan hasil inspeksi bahan yang diterima (wajib dalam 3 hari)."
      tools={<Button variant="outline" size="icon" onClick={() => { fetchShipments(); fetchInspections(); }} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="h-4 w-4" /></Button>}>
      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">Menunggu inspeksi ({pendingShipments.length})</p>
          <TombolUnduh namaBerkas="kiriman-menunggu-inspeksi" baris={pendingShipments} kolom={[
            { label: 'Kiriman', nilai: (s) => s.shipment_number }, { label: 'Diterima', nilai: (s) => fmtDate(s.updated_at) },
            { label: 'Jenis', nilai: (s) => s.shipment_type || 'NORMAL' }, { label: 'Terlambat', nilai: (s) => (isOverdue(s) ? 'Ya' : 'Tidak') },
          ]} />
        </div>
        <TabelData kolom={kolomTunggu} baris={pendingShipments} testId="vendor-inspection-pending"
          kosong={<EmptyState icon={ClipboardCheck} title="Tidak ada kiriman yang menunggu inspeksi" description="Kiriman yang sudah dikonfirmasi diterima muncul di sini." />} />
      </section>
      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">Riwayat inspeksi ({inspections.length})</p>
          <TombolUnduh namaBerkas="riwayat-inspeksi-material" baris={inspections} kolom={[
            { label: 'Kiriman', nilai: (i) => i.shipment_number }, { label: 'Tanggal inspeksi', nilai: (i) => fmtDate(i.inspection_date) },
            { label: 'Diterima (pcs)', nilai: (i) => Number(i.total_received) || 0 }, { label: 'Kurang (pcs)', nilai: (i) => Number(i.total_missing) || 0 },
            { label: 'Catatan', nilai: (i) => i.overall_notes || '' },
          ]} />
        </div>
        <TabelData kolom={kolomRiwayat} baris={inspections} onKlikBaris={openDetail} testId="vendor-inspection-history"
          kosong={<EmptyState title="Belum ada inspeksi" description="Hasil inspeksi yang sudah dikirim tampil di sini." />} />
      </section>

      {/* Form inspeksi — FormPopup panjang */}
      {showModal && selectedShipment && (
        <FormPopup open onClose={() => setShowModal(false)} ukuran="panjang" testId="vendor-inspection-form"
          judul={`Inspeksi ${selectedShipment.shipment_number}`}
          keterangan="Isi jumlah yang benar-benar diterima; kekurangan dihitung otomatis."
          onSimpan={handleSubmit} menyimpan={loading} labelSimpan="Kirim laporan inspeksi">
          <Isian label="Tanggal inspeksi">
            <DatePicker value={form.inspection_date} onChange={(v) => setForm(f => ({ ...f, inspection_date: v }))} bolehKosong={false} />
          </Isian>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow>
                <TableHead>Produk / SKU</TableHead><TableHead className="text-right">Dikirim</TableHead>
                <TableHead className="text-right">Diterima *</TableHead><TableHead className="text-right">Kurang</TableHead><TableHead>Kondisi / catatan</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {form.items.map((item, idx) => (
                  <TableRow key={idx}>
                    <TableCell><p className="font-medium">{item.product_name}</p><p className="text-xs text-muted-foreground tabular-nums">{item.sku} {item.size}/{item.color}</p></TableCell>
                    <TableCell className="text-right tabular-nums">{item.ordered_qty}</TableCell>
                    <TableCell className="text-right">
                      <Input type="number" min="0" max={item.ordered_qty} className="h-8 w-24 ml-auto text-right"
                        value={item.received_qty} onChange={e => updateItem(idx, 'received_qty', e.target.value)} aria-label={`Diterima ${item.product_name}`} />
                    </TableCell>
                    <TableCell className={`text-right tabular-nums font-medium ${item.missing_qty > 0 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{item.missing_qty}</TableCell>
                    <TableCell><Input className="h-8 min-w-[10rem]" value={item.condition_notes} onChange={e => updateItem(idx, 'condition_notes', e.target.value)} placeholder="Kondisi barang…" /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
              <TableFooter><TableRow>
                <TableCell className="font-semibold">Total</TableCell>
                <TableCell className="text-right tabular-nums font-semibold">{sum(form.items, 'ordered_qty')}</TableCell>
                <TableCell className="text-right tabular-nums font-semibold">{sum(form.items, 'received_qty')}</TableCell>
                <TableCell className="text-right tabular-nums font-semibold text-[hsl(var(--danger-text))]">{sum(form.items, 'missing_qty')}</TableCell>
                <TableCell />
              </TableRow></TableFooter>
            </Table>
          </div>
          <Isian label="Catatan umum">
            <Textarea rows={2} value={form.overall_notes} onChange={e => setForm(f => ({ ...f, overall_notes: e.target.value }))} placeholder="Catatan kondisi bahan secara umum…" />
          </Isian>
          {form.accessory_items.length > 0 && (
            <section className="space-y-2" data-testid="inspection-accessories">
              <p className="text-sm font-medium text-foreground">Inspeksi aksesoris ({form.accessory_items.length} baris)</p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow>
                    <TableHead>Aksesoris</TableHead><TableHead>Kode</TableHead><TableHead className="text-right">Dibutuhkan</TableHead>
                    <TableHead className="text-right">Diterima *</TableHead><TableHead className="text-right">Kurang</TableHead><TableHead>Catatan</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {form.accessory_items.map((acc, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-medium">{acc.accessory_name}</TableCell>
                        <TableCell className="tabular-nums">{acc.accessory_code}</TableCell>
                        <TableCell className="text-right tabular-nums">{acc.ordered_qty} {acc.unit}</TableCell>
                        <TableCell className="text-right">
                          <Input type="number" min="0" className="h-8 w-24 ml-auto text-right" value={acc.received_qty}
                            onChange={e => updateAccItem(idx, 'received_qty', e.target.value)} aria-label={`Diterima ${acc.accessory_name}`} />
                        </TableCell>
                        <TableCell className={`text-right tabular-nums font-medium ${acc.missing_qty > 0 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{acc.missing_qty}</TableCell>
                        <TableCell><Input className="h-8 min-w-[10rem]" value={acc.condition_notes} onChange={e => updateAccItem(idx, 'condition_notes', e.target.value)} placeholder="Kondisi aksesoris…" /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                  <TableFooter><TableRow>
                    <TableCell className="font-semibold" colSpan={2}>Total aksesoris</TableCell>
                    <TableCell className="text-right tabular-nums font-semibold">{sum(form.accessory_items, 'ordered_qty')}</TableCell>
                    <TableCell className="text-right tabular-nums font-semibold">{sum(form.accessory_items, 'received_qty')}</TableCell>
                    <TableCell className="text-right tabular-nums font-semibold text-[hsl(var(--danger-text))]">{sum(form.accessory_items, 'missing_qty')}</TableCell>
                    <TableCell />
                  </TableRow></TableFooter>
                </Table>
              </div>
            </section>
          )}
        </FormPopup>
      )}

      {/* Rincian inspeksi — DetailPopup */}
      {showDetail && detailData && (
        <DetailPopup open onClose={() => setShowDetail(false)} judul={`Inspeksi ${detailData.shipment_number}`} testId="vendor-inspection-detail"
          aksi={<Button size="sm" variant="outline" onClick={() => unduhPdf(detailData)} data-testid="export-inspection-pdf"><FileDown className="w-4 h-4" />Unduh PDF</Button>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Tanggal inspeksi">{fmtDate(detailData.inspection_date)}</BarisDetail>
            <BarisDetail label="Total diterima">{detailData.total_received} pcs</BarisDetail>
            <BarisDetail label="Total kurang"><span className={detailData.total_missing > 0 ? 'text-[hsl(var(--danger-text))]' : ''}>{detailData.total_missing} pcs</span></BarisDetail>
            {detailData.overall_notes && <BarisDetail label="Catatan">{detailData.overall_notes}</BarisDetail>}
          </dl>
          {detailData.items?.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow><TableHead>Produk / SKU</TableHead><TableHead className="text-right">Dikirim</TableHead>
                  <TableHead className="text-right">Diterima</TableHead><TableHead className="text-right">Kurang</TableHead><TableHead>Catatan</TableHead></TableRow></TableHeader>
                <TableBody>{detailData.items.map(item => (
                  <TableRow key={item.id}>
                    <TableCell><p className="font-medium">{item.product_name}</p><p className="text-xs text-muted-foreground tabular-nums">{item.sku} {item.size}/{item.color}</p></TableCell>
                    <TableCell className="text-right tabular-nums">{item.ordered_qty}</TableCell>
                    <TableCell className="text-right tabular-nums">{item.received_qty}</TableCell>
                    <TableCell className={`text-right tabular-nums ${item.missing_qty > 0 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{item.missing_qty}</TableCell>
                    <TableCell className="text-muted-foreground">{item.condition_notes || '—'}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </div>
          )}
          {(detailData.accessory_items || []).length > 0 && (
            <section className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Aksesoris ({detailData.accessory_items.length} baris)</p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow><TableHead>Aksesoris</TableHead><TableHead>Kode</TableHead><TableHead className="text-right">Dibutuhkan</TableHead>
                    <TableHead className="text-right">Diterima</TableHead><TableHead className="text-right">Kurang</TableHead><TableHead>Catatan</TableHead></TableRow></TableHeader>
                  <TableBody>{detailData.accessory_items.map(acc => (
                    <TableRow key={acc.id}>
                      <TableCell className="font-medium">{acc.accessory_name}</TableCell>
                      <TableCell className="tabular-nums">{acc.accessory_code || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{acc.ordered_qty} {acc.unit || 'pcs'}</TableCell>
                      <TableCell className="text-right tabular-nums">{acc.received_qty}</TableCell>
                      <TableCell className={`text-right tabular-nums ${acc.missing_qty > 0 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{acc.missing_qty}</TableCell>
                      <TableCell className="text-muted-foreground">{acc.condition_notes || '—'}</TableCell>
                    </TableRow>
                  ))}</TableBody>
                </Table>
              </div>
            </section>
          )}
        </DetailPopup>
      )}

      {/* Phase 16: Modal Permintaan Material Tambahan (auto-prompt setelah inspeksi missing) */}
      {showReqModal && reqModalData && (
        <AdditionalRequestModal
          shipment={reqModalData.shipment}
          defaultItems={reqModalData.defaultItems}
          defaultReason={reqModalData.defaultReason}
          inspectionId={reqModalData.inspectionId}
          mode={reqModalData.mode}
          onClose={() => { setShowReqModal(false); setReqModalData(null); }}
          onSuccess={() => { setShowReqModal(false); setReqModalData(null); }}
        />
      )}
    </PageLayout>
  );
}

// ─── VENDOR DEFECT REPORTS ─────────────────────────────────────────────────────


