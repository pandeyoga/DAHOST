/**
 * VendorMaterialRequests — Phase 16 (Vendor Portal)
 *
 * Modul khusus vendor untuk mengelola Permintaan Material:
 *   • Lihat daftar permintaan ADDITIONAL & REPLACEMENT milik vendor
 *   • Lihat detail + alasan penolakan admin
 *   • Ajukan Ulang permintaan yang Rejected
 *   • Buat Permintaan Manual untuk shipment yang sudah ter-inspeksi
 */
import { useState, useEffect } from 'react';
import {
  Plus, Eye, RotateCcw, ClipboardList, CheckCircle, XCircle, Clock,
  AlertTriangle, Truck, FileText, AlertCircle, Search
} from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import AdditionalRequestModal from './AdditionalRequestModal';
import MaterialRequestTracker from './MaterialRequestTracker';
import { apiGet, apiFetch } from '../../../lib/api';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';

const TABS = [
  { id: 'ADDITIONAL', label: 'Permintaan tambahan', icon: Plus, color: 'amber' },
  { id: 'REPLACEMENT', label: 'Permintaan pengganti', icon: AlertTriangle, color: 'red' },
];

const STATUS_COLORS = {
  Pending: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))] border-[hsl(var(--warning)/0.35)]',
  Approved: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success-text))] border-[hsl(var(--success)/0.35)]',
  Rejected: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--danger-text))] border-[hsl(var(--destructive)/0.35)]',
};

// Standar UI/UX v2: status & jenis tampil dalam bahasa Indonesia (dulu "Pending/Approved/Rejected" mentah).
const STATUS_LABEL = { Pending: ['Menunggu', 'warning'], Approved: ['Disetujui', 'success'], Rejected: ['Ditolak', 'danger'] };
const TYPE_LABEL = { ADDITIONAL: 'Tambahan', REPLACEMENT: 'Pengganti', NORMAL: 'Awal', REWORK: 'Retur perbaikan' };
const statusLabel = (s) => (STATUS_LABEL[s] || [s || '—', 'default']);

const STATUS_ICONS = {
  Pending: Clock,
  Approved: CheckCircle,
  Rejected: XCircle,
};

export default function VendorMaterialRequests({ user }) {
  const [activeTab, setActiveTab] = useState('ADDITIONAL');
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  // Detail modal
  const [showDetail, setShowDetail] = useState(false);
  const [selectedReq, setSelectedReq] = useState(null);

  // Resubmit modal
  const [resubmitData, setResubmitData] = useState(null);

  // Manual request: shipment picker + modal
  const [showShipmentPicker, setShowShipmentPicker] = useState(false);
  const [inspectedShipments, setInspectedShipments] = useState([]);
  const [manualReqShipment, setManualReqShipment] = useState(null);
  const [manualReqItems, setManualReqItems] = useState([]);
  const [loadingShipPicker, setLoadingShipPicker] = useState(false);
  // Jenis permintaan yang sedang dibuat lewat picker: ADDITIONAL | REPLACEMENT.
  // 2026-06 — tombol buat DULU hanya dirender di tab ADDITIONAL, sementara jalur
  // lama untuk PENGGANTI (Laporan Cacat Material) sudah dimatikan backend
  // (HTTP 410). Akibatnya vendor CMT benar-benar TIDAK BISA mengajukan material
  // pengganti sama sekali — permintaannya harus dititipkan lewat telepon/chat
  // dan tidak pernah tercatat di ERP.
  const [createType, setCreateType] = useState('ADDITIONAL');

  useEffect(() => {
    fetchRequests();
  }, [activeTab]);

  const fetchRequests = async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/material-requests?request_type=${activeTab}`);
      setRequests(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error('Gagal memuat permintaan');
      setRequests([]);
    } finally {
      setLoading(false);
    }
  };

  const openDetail = (req) => {
    setSelectedReq(req);
    setShowDetail(true);
  };

  const openResubmit = async (req) => {
    // Phase 16 Fix: Fetch shipment items untuk mengisi serial_number yang hilang
    // (penting untuk request lama yang dibuat sebelum mapping serial diperbaiki)
    let shipItemsMap = {}; // key: sku|size|color → si
    let shipItemsByIdMap = {}; // key: shipment_item_id → si
    if (req.original_shipment_id) {
      try {
        const fullShip = await apiGet(`/vendor-shipments/${req.original_shipment_id}`);
        for (const si of (fullShip.items || [])) {
          const k = `${si.sku || ''}|${si.size || ''}|${si.color || ''}`;
          if (!shipItemsMap[k] || (si.serial_number && !shipItemsMap[k].serial_number)) {
            shipItemsMap[k] = si;
          }
          if (si.id) shipItemsByIdMap[si.id] = si;
        }
      } catch (e) {
        // Silent fail — backend juga punya defensive lookup
      }
    }
    const items = (req.items || []).map((it) => {
      // Resolve serial_number dari shipment item jika item request tidak punya
      let serial = it.serial_number || '';
      let poItemId = it.po_item_id || '';
      let shipmentItemId = it.shipment_item_id || '';
      if (!serial || !poItemId) {
        let matched = null;
        if (shipmentItemId && shipItemsByIdMap[shipmentItemId]) {
          matched = shipItemsByIdMap[shipmentItemId];
        } else {
          const k = `${it.sku || ''}|${it.size || ''}|${it.color || ''}`;
          matched = shipItemsMap[k];
        }
        if (matched) {
          if (!serial) serial = matched.serial_number || '';
          if (!poItemId) poItemId = matched.po_item_id || '';
          if (!shipmentItemId) shipmentItemId = matched.id || '';
        }
      }
      return {
        shipment_item_id: shipmentItemId,
        po_item_id: poItemId,
        sku: it.sku || '',
        product_name: it.product_name || '',
        size: it.size || '',
        color: it.color || '',
        serial_number: serial,
        requested_qty: Number(it.requested_qty || 0),
        reason: it.reason || req.reason || '',
      };
    });
    setResubmitData({
      shipment: {
        id: req.original_shipment_id,
        shipment_number: req.original_shipment_number || '-',
        vendor_name: req.vendor_name,
        po_id: req.po_id,
        po_number: req.po_number,
      },
      defaultItems: items,
      defaultReason: req.reason || '',
      previousRequestId: req.id,
      previousRequestNumber: req.request_number,
      // ajukan ulang WAJIB memakai jenis yang sama (tambahan vs pengganti)
      requestType: req.request_type || 'ADDITIONAL',
    });
    setShowDetail(false);
  };

  // ─── Manual Request: pilih shipment yang sudah ter-inspeksi ────────────────
  const openShipmentPicker = async (type = 'ADDITIONAL') => {
    setCreateType(type);
    setLoadingShipPicker(true);
    setShowShipmentPicker(true);
    try {
      const data = await apiGet('/vendor-shipments');
      // Filter: shipment milik vendor ini, sudah Received & sudah Inspected
      const list = Array.isArray(data) ? data : [];
      const filtered = list.filter(
        (s) => s.inspection_status === 'Inspected'
      );
      setInspectedShipments(filtered);
    } catch (e) {
      toast.error('Gagal memuat daftar shipment');
      setInspectedShipments([]);
    } finally {
      setLoadingShipPicker(false);
    }
  };

  const pickShipmentForManual = async (shipment) => {
    try {
      const fullShip = await apiGet(`/vendor-shipments/${shipment.id}`);
      const items = (fullShip.items || []).map((si) => ({
        shipment_item_id: si.id,
        po_item_id: si.po_item_id || '',
        sku: si.sku || '',
        product_name: si.product_name || '',
        size: si.size || '',
        color: si.color || '',
        serial_number: si.serial_number || '',
        requested_qty: 0,
        reason: '',
      }));
      setManualReqShipment({
        id: shipment.id,
        shipment_number: shipment.shipment_number,
        vendor_name: shipment.vendor_name,
        po_id: fullShip.po_id || (fullShip.items?.[0]?.po_id || ''),
        po_number: fullShip.po_number || (fullShip.items?.[0]?.po_number || ''),
      });
      setManualReqItems(items);
      setShowShipmentPicker(false);
    } catch (e) {
      toast.error(e.message || 'Gagal memuat detail shipment');
    }
  };

  const downloadPDF = async (req) => {
    try {
      const res = await apiFetch(`/export-pdf?type=material-request&id=${req.id}`);
      if (!res.ok) {
        toast.error('Gagal export PDF');
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Permohonan-${req.request_number}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error('Gagal export PDF: ' + e.message);
    }
  };

  const fmtDate = (d) => formatDateID(d, { fallback: '—' });

  // Filter local
  const filtered = requests.filter((r) => {
    if (statusFilter !== 'all' && r.status !== statusFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      const hay = `${r.request_number || ''} ${r.original_shipment_number || ''} ${r.po_number || ''}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const currentTab = TABS.find((t) => t.id === activeTab);
  const isAdditional = activeTab === 'ADDITIONAL';

  // Stats per tab
  const stats = {
    total: requests.length,
    pending: requests.filter((r) => r.status === 'Pending').length,
    approved: requests.filter((r) => r.status === 'Approved').length,
    rejected: requests.filter((r) => r.status === 'Rejected').length,
  };

  const kolom = [
    { kunci: 'no', label: 'No. permintaan', hp: 'judul', isi: (row) => (
      <div className="min-w-0">
        <span className="font-medium tabular-nums">{row.request_number}</span>
        {row.previous_request_number && <span className="block text-xs text-muted-foreground tabular-nums">ajukan ulang dari {row.previous_request_number}</span>}
        {row.resubmitted_as_number && <span className="block text-xs text-muted-foreground tabular-nums">→ {row.resubmitted_as_number}</span>}
      </div>) },
    { kunci: 'asal', label: 'Kiriman asal', isi: (row) => <span className="tabular-nums">{row.original_shipment_number || '—'}</span> },
    { kunci: 'po', label: 'PO', isi: (row) => <span className="tabular-nums">{row.po_number || '—'}</span> },
    { kunci: 'qty', label: 'Total qty', rata: 'kanan', isi: (row) => <span className="tabular-nums">{Number(row.total_requested_qty || 0).toLocaleString('id-ID')} pcs</span> },
    { kunci: 'tgl', label: 'Tanggal', isi: (row) => fmtDate(row.created_at) },
    { kunci: 'status', label: 'Status', isi: (row) => { const [l, t] = statusLabel(row.status); return <StatusBadge status={row.status} label={l} tone={t} />; } },
    // Rantai pengganti terlacak sampai diinspeksi (INV-F28)
    { kunci: 'turunan', label: 'Kiriman turunan', isi: (row) => <MaterialRequestTracker req={row} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (row) => {
      const canResubmit = isAdditional && row.status === 'Rejected' && !row.resubmitted_as_id;
      return (
        <div className="flex justify-end gap-1">
          <Button size="icon-sm" variant="ghost" onClick={() => openDetail(row)} title="Lihat rincian" aria-label="Lihat rincian"
            data-testid={`vendor-mr-detail-btn-${row.id}`}><Eye className="w-4 h-4" /></Button>
          {canResubmit && (
            <Button size="icon-sm" variant="ghost" onClick={() => openResubmit(row)} title="Ajukan ulang" aria-label="Ajukan ulang"
              data-testid={`vendor-mr-resubmit-btn-${row.id}`}><RotateCcw className="w-4 h-4" /></Button>
          )}
        </div>
      );
    } },
  ];

  return (
    <PageLayout testId="vendor-material-requests" title="Permintaan material"
      subtitle="Permintaan bahan tambahan (kurang kirim) dan pengganti (cacat) ke DA."
      actions={isAdditional ? (
        <Button onClick={() => openShipmentPicker('ADDITIONAL')} data-testid="vendor-create-manual-request-btn">
          <Plus className="w-4 h-4" /> Buat permintaan manual
        </Button>
      ) : (
        <Button onClick={() => openShipmentPicker('REPLACEMENT')} data-testid="vendor-create-replacement-request-btn">
          <Plus className="w-4 h-4" /> Buat permintaan pengganti
        </Button>
      )}
      filters={<>
        {/* PANDUAN_UI G4: pil standar; kunci huruf kecil supaya data-testid tetap vendor-mr-tab-<jenis> */}
        <FilterChips value={activeTab.toLowerCase()} onChange={(k) => setActiveTab(String(k).toUpperCase())}
          testId="vendor-mr-tab" ariaLabel="Jenis permintaan" hideWhenEmpty={false}
          options={TABS.map((t) => ({ key: t.id.toLowerCase(), label: t.label, icon: t.icon }))} />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari no. permintaan, kiriman, PO" className="pl-8" value={search}
            onChange={(e) => setSearch(e.target.value)} data-testid="vendor-mr-search" />
        </div>
        <SmartNativeSelect className="w-44" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          data-testid="vendor-mr-status-filter" aria-label="Saring status">
          <option value="all">Semua status</option>
          <option value="Pending">Menunggu</option>
          <option value="Approved">Disetujui</option>
          <option value="Rejected">Ditolak</option>
        </SmartNativeSelect>
      </>}
      tools={<TombolUnduh namaBerkas={`permintaan-material-${activeTab.toLowerCase()}`} baris={filtered} kolom={[
        { label: 'No. permintaan', nilai: (r) => r.request_number }, { label: 'Kiriman asal', nilai: (r) => r.original_shipment_number || '' },
        { label: 'PO', nilai: (r) => r.po_number || '' }, { label: 'Total qty', nilai: (r) => Number(r.total_requested_qty) || 0 },
        { label: 'Tanggal', nilai: (r) => fmtDate(r.created_at) }, { label: 'Status', nilai: (r) => statusLabel(r.status)[0] },
        { label: 'Alasan', nilai: (r) => r.reason || '' },
      ]} />}
      summary={<>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {/* `key` menjaga data-testid lama (vendor-mr-stat-pending, …) walau labelnya diterjemahkan */}
          {[
            { key: 'total', label: `Total ${currentTab.label.toLowerCase()}`, value: stats.total, accent: 'default' },
            { key: 'pending', label: 'Menunggu', value: stats.pending, accent: 'warning' },
            { key: 'disetujui', label: 'Disetujui', value: stats.approved, accent: 'success' },
            { key: 'ditolak', label: 'Ditolak', value: stats.rejected, accent: 'danger' },
          ].map((s) => (
            <StatTile key={s.key} label={s.label} value={s.value} accent={s.accent} testId={`vendor-mr-stat-${s.key}`} />
          ))}
        </div>
        <p className="text-sm text-muted-foreground">
          {isAdditional
            ? 'Permintaan tambahan dibuat saat ada bahan kurang dari inspeksi. Boleh diajukan ulang bila ditolak, atau dibuat manual untuk kiriman yang sudah diinspeksi.'
            : 'Permintaan pengganti untuk bahan CACAT/RUSAK (bukan kurang kirim): pilih surat jalan yang sudah diinspeksi, lalu isi qty dan cacatnya. Setelah disetujui terbit surat jalan pengganti (kode "-R1") di Penerimaan material.'}
        </p>
      </>}>
      {loading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat data…</p>
      ) : (
        <TabelData kolom={kolom} baris={filtered} onKlikBaris={openDetail} testId="vendor-mr-table"
          kosong={<EmptyState icon={ClipboardList}
            title={`Belum ada ${currentTab.label.toLowerCase()}`}
            description={isAdditional
              ? 'Permintaan otomatis terbuat saat ada bahan kurang di inspeksi, atau klik "Buat permintaan manual".'
              : 'Klik "Buat permintaan pengganti" untuk bahan yang cacat atau rusak.'} />} />
      )}

      {/* Rincian permintaan — DetailPopup */}
      {showDetail && selectedReq && (
        <DetailPopup open onClose={() => setShowDetail(false)} judul={`Permintaan ${selectedReq.request_number}`} testId="vendor-mr-detail"
          status={(() => { const [l, t] = statusLabel(selectedReq.status); return <StatusBadge status={selectedReq.status} label={l} tone={t} />; })()}
          aksi={<>
            {selectedReq.status === 'Rejected' && isAdditional && !selectedReq.resubmitted_as_id && (
              <Button size="sm" onClick={() => openResubmit(selectedReq)} data-testid="vendor-mr-resubmit-detail-btn">
                <RotateCcw className="w-4 h-4" /> Ajukan ulang dengan revisi
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => downloadPDF(selectedReq)} data-testid="vendor-mr-pdf-btn">
              <FileText className="w-4 h-4" /> Unduh PDF
            </Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Jenis">{TYPE_LABEL[selectedReq.request_type] || selectedReq.request_type}</BarisDetail>
            <BarisDetail label="Kiriman asal"><span className="tabular-nums">{selectedReq.original_shipment_number || '—'}</span></BarisDetail>
            <BarisDetail label="PO">{selectedReq.po_number || '—'}</BarisDetail>
            <BarisDetail label="Total qty">{Number(selectedReq.total_requested_qty || 0).toLocaleString('id-ID')} pcs</BarisDetail>
            <BarisDetail label="Tanggal">{fmtDate(selectedReq.created_at)}</BarisDetail>
            <BarisDetail label="Alasan">{selectedReq.reason || '—'}</BarisDetail>
            <BarisDetail label="Dibuat oleh">{selectedReq.created_by || '—'}</BarisDetail>
          </dl>
          {selectedReq.items?.length > 0 && (
            <section className="space-y-2">
              <p className="text-sm font-semibold text-foreground">Barang yang diminta</p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow><TableHead>Produk</TableHead><TableHead>SKU</TableHead><TableHead>No. seri</TableHead>
                    <TableHead>Ukuran / warna</TableHead><TableHead className="text-right">Qty</TableHead><TableHead>Alasan</TableHead></TableRow></TableHeader>
                  <TableBody>{selectedReq.items.map((item, idx) => (
                    <TableRow key={idx}>
                      <TableCell className="font-medium">{item.product_name}</TableCell>
                      <TableCell className="tabular-nums">{item.sku || '—'}</TableCell>
                      <TableCell className="tabular-nums">{item.serial_number || '—'}</TableCell>
                      <TableCell>{item.size}/{item.color}</TableCell>
                      <TableCell className="text-right tabular-nums">{Number(item.requested_qty || 0).toLocaleString('id-ID')} pcs</TableCell>
                      <TableCell className="text-muted-foreground">{item.reason || '—'}</TableCell>
                    </TableRow>
                  ))}</TableBody>
                </Table>
              </div>
            </section>
          )}
          {selectedReq.child_shipment_number && (
            <Notice tone="success" icon={CheckCircle}>
              Disetujui. Kiriman turunan <strong className="tabular-nums">{selectedReq.child_shipment_number}</strong> dibuat oleh {selectedReq.approved_by} pada {fmtDate(selectedReq.approved_at)}.
            </Notice>
          )}
          {selectedReq.status === 'Rejected' && (
            <Notice tone="danger" icon={XCircle} title="Permintaan ditolak">
              {selectedReq.admin_notes && <span className="block">Alasan admin: {selectedReq.admin_notes}</span>}
              {selectedReq.rejected_by && <span className="block text-xs">Ditolak oleh {selectedReq.rejected_by} pada {fmtDate(selectedReq.rejected_at)}</span>}
            </Notice>
          )}
          {selectedReq.resubmitted_as_number && (
            <p className="text-sm text-muted-foreground">Sudah diajukan ulang sebagai <strong className="tabular-nums">{selectedReq.resubmitted_as_number}</strong>.</p>
          )}
          {selectedReq.previous_request_number && (
            <p className="text-sm text-muted-foreground">Ajukan ulang dari <strong className="tabular-nums">{selectedReq.previous_request_number}</strong>.</p>
          )}
        </DetailPopup>
      )}

      {/* Pilih kiriman (permintaan manual/pengganti) */}
      {showShipmentPicker && (
        <DetailPopup open onClose={() => setShowShipmentPicker(false)} testId="vendor-mr-ship-picker"
          judul={createType === 'REPLACEMENT' ? 'Pilih surat jalan untuk permintaan pengganti' : 'Pilih kiriman untuk permintaan manual'}
          keterangan={createType === 'REPLACEMENT'
            ? 'Pilih surat jalan yang sudah diinspeksi, lalu tandai barang yang CACAT/RUSAK beserta qty penggantinya.'
            : 'Pilih kiriman yang sudah diinspeksi untuk membuat permintaan bahan tambahan secara manual.'}>
          <span className="sr-only" data-testid="ship-picker-hint"><AlertCircle /></span>
          {loadingShipPicker ? (
            <p className="py-8 text-center text-sm text-muted-foreground">Memuat kiriman…</p>
          ) : (
            <TabelData baris={inspectedShipments} testId="vendor-mr-ship-table"
              kolom={[
                { kunci: 'no', label: 'Kiriman', hp: 'judul', isi: (s) => <span className="font-medium tabular-nums">{s.shipment_number}</span> },
                { kunci: 'jenis', label: 'Jenis', isi: (s) => TYPE_LABEL[s.shipment_type || 'NORMAL'] || s.shipment_type },
                { kunci: 'baris', label: 'Baris', rata: 'kanan', isi: (s) => (s.items || []).length },
                { kunci: 'tgl', label: 'Tanggal', isi: (s) => fmtDate(s.shipment_date) },
                { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
                  <Button size="sm" variant="outline" onClick={() => pickShipmentForManual(s)} data-testid={`vendor-pick-shipment-${s.id}`}>
                    <Truck className="w-4 h-4" />Pilih
                  </Button>) },
              ]}
              kosong={<EmptyState icon={Truck} title="Belum ada kiriman yang diinspeksi"
                description='Lakukan inspeksi bahan terlebih dahulu di "Inspeksi material".' />} />
          )}
        </DetailPopup>
      )}

      {/* Resubmit modal */}
      {resubmitData && (
        <AdditionalRequestModal
          shipment={resubmitData.shipment}
          defaultItems={resubmitData.defaultItems}
          defaultReason={resubmitData.defaultReason}
          previousRequestId={resubmitData.previousRequestId}
          previousRequestNumber={resubmitData.previousRequestNumber}
          mode="resubmit"
          requestType={resubmitData.requestType || 'ADDITIONAL'}
          onClose={() => setResubmitData(null)}
          onSuccess={() => {
            setResubmitData(null);
            fetchRequests();
          }}
        />
      )}

      {/* Manual request modal */}
      {manualReqShipment && (
        <AdditionalRequestModal
          shipment={manualReqShipment}
          defaultItems={manualReqItems}
          defaultReason={createType === 'REPLACEMENT'
            ? `Material cacat/rusak pada shipment ${manualReqShipment.shipment_number} — mohon diganti`
            : `Permintaan tambahan manual untuk shipment ${manualReqShipment.shipment_number}`}
          mode="manual"
          requestType={createType}
          onClose={() => {
            setManualReqShipment(null);
            setManualReqItems([]);
          }}
          onSuccess={() => {
            setManualReqShipment(null);
            setManualReqItems([]);
            fetchRequests();
          }}
        />
      )}
    </PageLayout>
  );
}
