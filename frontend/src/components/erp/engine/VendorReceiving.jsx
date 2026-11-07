/**
 * VendorReceiving — Penerimaan material (Portal Vendor CMT; juga di Input atas nama CMT).
 *
 * Standar UI/UX v2 (8 Nov 2026): daftar kiriman = tabel (dulu kartu tinggi berwarna per kiriman, berulang tanpa
 * batas), rincian kiriman (barang, aksesoris PO, kiriman turunan) dibuka sebagai popup, bisa diunduh Excel/CSV.
 * Aksi & API tidak berubah: konfirmasi terima (PUT /vendor-shipments/{id} status Received).
 */
import { useEffect, useState } from 'react';
import { CheckCircle, Eye, Package, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { apiGet, apiPut } from '../../../lib/api';

const n = (v) => Number(v || 0).toLocaleString('id-ID');
const tgl = (d) => formatDateID(d, { fallback: '—' });

// FASE 22 — surat jalan REWORK (barang reject dikembalikan untuk diperbaiki) diberi label sendiri supaya
// vendor tahu ini pekerjaan ULANG dari reject QC.
const JENIS = {
  ADDITIONAL: ['Kiriman tambahan', 'warning'],
  REPLACEMENT: ['Kiriman pengganti', 'danger'],
  REWORK: ['Retur perbaikan', 'warning'],
};
const jenisDari = (t) => JENIS[t] || ['Kiriman awal', 'primary'];

function keadaan(s) {
  if (s.status === 'Sent') return ['Belum diterima', 'warning'];
  if (s.status === 'Received' && s.inspection_status !== 'Inspected') return ['Diterima · menunggu inspeksi', 'info'];
  if (s.status === 'Received' && s.inspection_status === 'Inspected') return ['Diterima & diinspeksi', 'success'];
  return [s.status || '—', 'default'];
}
const totalKirim = (s) => (s.items || []).reduce((t, i) => t + (Number(i.qty_sent) || 0), 0);

function RincianKiriman({ s, induk, anak, onClose, onTerima }) {
  const [aks, setAks] = useState(null);
  useEffect(() => {
    if (!(s.po_accessories_count > 0)) return;
    apiGet(`/vendor-shipments/${s.id}`).then((d) => setAks(d.po_accessories || [])).catch(() => setAks([]));
  }, [s.id, s.po_accessories_count]);
  const [jl, jt] = jenisDari(s.shipment_type);
  const [kl, kt] = keadaan(s);
  return (
    <DetailPopup open onClose={onClose} judul={`Kiriman ${s.shipment_number}`} testId="vendor-receiving-detail"
      keterangan={`${tgl(s.shipment_date)} · ${s.vendor_name || ''}`}
      status={<><StatusBadge status={s.shipment_type || 'NORMAL'} label={jl} tone={jt} /><StatusBadge status={s.status} label={kl} tone={kt} /></>}
      aksi={s.status === 'Sent' && <Button type="button" size="sm" variant="success" onClick={() => onTerima(s)}><CheckCircle className="w-4 h-4" />Konfirmasi terima</Button>}>
      <dl className="divide-y divide-[var(--glass-border)]">
        {s.delivery_note_number && <BarisDetail label="No. surat jalan">{s.delivery_note_number}</BarisDetail>}
        {induk && <BarisDetail label="Turunan dari">{induk.shipment_number}</BarisDetail>}
        <BarisDetail label="Diterima">{s.total_received != null ? `${n(s.total_received)} pcs` : '—'}</BarisDetail>
        {(s.total_missing || 0) > 0 && <BarisDetail label="Kurang"><span className="text-[hsl(var(--danger-text))]">{n(s.total_missing)} pcs</span></BarisDetail>}
        {(s.notes_for_vendor || s.notes) && <BarisDetail label="Catatan admin">{s.notes_for_vendor || s.notes}</BarisDetail>}
      </dl>
      {s.status === 'Received' && s.inspection_status !== 'Inspected' && (
        <Notice tone="warning">Wajib inspeksi dalam 3 hari. Produksi tidak bisa dimulai sebelum inspeksi selesai.</Notice>
      )}
      <section className="space-y-2">
        <p className="text-sm font-semibold text-foreground">Barang ({(s.items || []).length} baris)</p>
        {(s.items || []).length === 0 ? <p className="text-sm text-muted-foreground">Tidak ada baris barang.</p> : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Produk</TableHead><TableHead>SKU</TableHead><TableHead>Ukuran / warna</TableHead>
                <TableHead>No. seri</TableHead><TableHead className="text-right">Qty kirim</TableHead></TableRow></TableHeader>
              <TableBody>{s.items.map((it) => (
                <TableRow key={it.id}><TableCell className="font-medium">{it.product_name}</TableCell>
                  <TableCell className="tabular-nums">{it.sku || '—'}</TableCell><TableCell>{it.size || '—'} / {it.color || '—'}</TableCell>
                  <TableCell className="tabular-nums">{it.serial_number || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{n(it.qty_sent)} pcs</TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </div>
        )}
      </section>
      {s.po_accessories_count > 0 && (
        <section className="space-y-2" data-testid="vendor-accessories-toggle">
          <p className="text-sm font-semibold text-foreground">Aksesoris PO ({s.po_accessories_count} baris)</p>
          {!aks ? <p className="text-sm text-muted-foreground">Memuat aksesoris…</p> : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow><TableHead>Aksesoris</TableHead><TableHead>Kode</TableHead>
                  <TableHead className="text-right">Kebutuhan</TableHead><TableHead>Catatan</TableHead></TableRow></TableHeader>
                <TableBody>{aks.map((a, i) => (
                  <TableRow key={a.id || i}><TableCell className="font-medium">{a.accessory_name}</TableCell>
                    <TableCell className="tabular-nums">{a.accessory_code || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{n(a.qty_needed)} {a.unit || 'pcs'}</TableCell>
                    <TableCell className="text-muted-foreground">{a.notes || '—'}</TableCell></TableRow>
                ))}</TableBody>
              </Table>
            </div>
          )}
        </section>
      )}
      {anak.length > 0 && (
        <section className="space-y-2">
          <p className="text-sm font-semibold text-foreground">Kiriman turunan ({anak.length})</p>
          <ul className="space-y-1 text-sm">
            {anak.map((c) => <li key={c.id}>{c.shipment_number} · {jenisDari(c.shipment_type)[0]} · {keadaan(c)[0]}</li>)}
          </ul>
        </section>
      )}
    </DetailPopup>
  );
}

export default function VendorReceiving() {
  const [shipments, setShipments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);

  const fetchShipments = async () => {
    setLoading(true);
    try {
      const data = await apiGet('/vendor-shipments');
      setShipments(Array.isArray(data) ? data : []);
    } catch (e) { setShipments([]); }
    finally { setLoading(false); }
  };
  useEffect(() => { fetchShipments(); }, []);

  const confirmReceive = async (shipment) => {
    if (!(await confirmDialog({
      title: `Konfirmasi penerimaan kiriman ${shipment.shipment_number}?`,
      body: 'Setelah dikonfirmasi, selesaikan inspeksi material sebelum memulai produksi.',
      confirmLabel: 'Konfirmasi',
    }))) return;
    try {
      await apiPut(`/vendor-shipments/${shipment.id}`, { status: 'Received', received_at: new Date() });
      setDetail(null);
      fetchShipments();
    } catch (e) { toast.error(e.message || 'Gagal mengkonfirmasi'); }
  };

  // Kiriman induk lalu turunannya tepat di bawahnya (tambahan/pengganti/rework).
  const byId = Object.fromEntries(shipments.map((s) => [s.id, s]));
  const anakDari = (id) => shipments.filter((s) => s.parent_shipment_id === id);
  const baris = [];
  shipments.filter((s) => !s.parent_shipment_id || !byId[s.parent_shipment_id]).forEach((s) => {
    baris.push(s);
    anakDari(s.id).forEach((c) => baris.push(c));
  });

  const pendingCount = shipments.filter((s) => s.status === 'Sent').length;
  const needsInspection = shipments.filter((s) => s.status === 'Received' && s.inspection_status !== 'Inspected').length;

  const kolom = [
    { kunci: 'no', label: 'No. kiriman', hp: 'judul', isi: (s) => (
      <div className="min-w-0">
        <span className="font-medium tabular-nums">{s.parent_shipment_id ? '↳ ' : ''}{s.shipment_number}</span>
        {s.delivery_note_number && <span className="block text-xs text-muted-foreground tabular-nums">SJ {s.delivery_note_number}</span>}
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (s) => { const [l, t] = jenisDari(s.shipment_type); return <StatusBadge status={s.shipment_type || 'NORMAL'} label={l} tone={t} />; } },
    { kunci: 'tgl', label: 'Tanggal', isi: (s) => tgl(s.shipment_date) },
    { kunci: 'barang', label: 'Dikirim', rata: 'kanan', isi: (s) => <span className="tabular-nums">{n(totalKirim(s))} pcs · {(s.items || []).length} baris</span> },
    { kunci: 'terima', label: 'Diterima / kurang', rata: 'kanan', isi: (s) => (
      <span className="tabular-nums">{s.total_received != null ? n(s.total_received) : '—'}
        {(s.total_missing || 0) > 0 && <span className="text-[hsl(var(--danger-text))]"> / −{n(s.total_missing)}</span>}</span>) },
    { kunci: 'status', label: 'Status', isi: (s) => { const [l, t] = keadaan(s); return <StatusBadge status={s.status} label={l} tone={t} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex justify-end gap-1">
        {s.status === 'Sent' && (
          <Button type="button" size="sm" variant="success" onClick={() => confirmReceive(s)} data-testid={`vendor-receive-${s.id}`}>
            <CheckCircle className="w-4 h-4" />Terima
          </Button>
        )}
        <Button type="button" size="icon-sm" variant="ghost" onClick={() => setDetail(s)} title="Lihat rincian" aria-label="Lihat rincian"><Eye className="w-4 h-4" /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="vendor-receiving" title="Penerimaan material"
      subtitle="Konfirmasi kiriman bahan yang sudah sampai; kiriman tambahan/pengganti tampil di bawah kiriman awalnya."
      tools={<>
        <TombolUnduh namaBerkas="penerimaan-material" namaLembar="Kiriman" baris={baris} kolom={[
          { label: 'No. kiriman', nilai: (s) => s.shipment_number }, { label: 'Turunan dari', nilai: (s) => byId[s.parent_shipment_id]?.shipment_number || '' },
          { label: 'No. surat jalan', nilai: (s) => s.delivery_note_number || '' }, { label: 'Jenis', nilai: (s) => jenisDari(s.shipment_type)[0] },
          { label: 'Tanggal', nilai: (s) => tgl(s.shipment_date) }, { label: 'Baris', nilai: (s) => (s.items || []).length },
          { label: 'Dikirim (pcs)', nilai: totalKirim }, { label: 'Diterima (pcs)', nilai: (s) => (s.total_received != null ? Number(s.total_received) : '') },
          { label: 'Kurang (pcs)', nilai: (s) => Number(s.total_missing) || 0 }, { label: 'Status', nilai: (s) => keadaan(s)[0] },
        ]} />
        <Button type="button" variant="outline" size="icon" onClick={fetchShipments} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={(pendingCount > 0 || needsInspection > 0) && (
        <p className="text-sm text-[hsl(var(--warning-text))]" data-testid="vendor-receiving-summary">
          {pendingCount > 0 && `${n(pendingCount)} kiriman menunggu konfirmasi terima. `}
          {needsInspection > 0 && `${n(needsInspection)} kiriman menunggu inspeksi material (wajib dalam 3 hari; produksi belum bisa dimulai).`}
        </p>
      )}>
      {loading && !shipments.length ? <p className="py-10 text-center text-sm text-muted-foreground">Memuat kiriman…</p> : (
        <TabelData kolom={kolom} baris={baris} onKlikBaris={setDetail} testId="vendor-receiving-table"
          kosong={<EmptyState icon={Package} title="Tidak ada kiriman masuk"
            description="Kiriman bahan dari DA muncul di sini untuk dikonfirmasi." />} />
      )}
      {detail && (
        <RincianKiriman s={detail} induk={byId[detail.parent_shipment_id]} anak={anakDari(detail.id)}
          onClose={() => setDetail(null)} onTerima={confirmReceive} />
      )}
    </PageLayout>
  );
}
