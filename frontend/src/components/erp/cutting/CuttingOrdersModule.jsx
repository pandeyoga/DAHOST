/**
 * CuttingOrdersModule — pintu utama Portal Cutting.
 *
 * Satu layar, tiga pekerjaan:
 *   1. Daftar order cutting + filter status/pencarian
 *   2. Buat / ubah cutting (`CuttingOrderForm`): beberapa kain + gulungan → beberapa hasil potongan
 *      (keputusan owner 10 Nov 2026: "cutting bisa lebih dari satu", "roll kain juga bisa lebih dari satu,
 *      model lebih dari satu")
 *   3. Rincian: kain & gulungan, hasil potongan, gulungan → hasil, HPP, riwayat progres; lapor progres
 *      (`CuttingProgressForm`), selesaikan, batalkan
 *
 * Semua mutasi stok terjadi di backend lewat SSOT gudang — UI hanya melaporkan
 * hasilnya (stok kain turun, stok potongan naik) supaya user melihat efeknya.
 * HPP potongan per pcs = total biaya kain ÷ total pcs hasil (sama untuk semua baris order).
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Plus, RefreshCw, Search, PlayCircle, CheckCircle2, XCircle,
  Trash2, Package, AlertCircle, Loader2, History, Scissors, PencilLine,
} from 'lucide-react';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { cuttingApi, StatusPill, STATUS_META, fmtNum, fmtRp, fmtDateTime } from './cuttingApi';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { fmtQty } from '../warehouse/rollLines';
import CuttingOrderForm from './CuttingOrderForm';
import CuttingProgressForm from './CuttingProgressForm';
import { qtyPerUnit } from './cuttingLines';

/** Kain terpakai / rencana per satuan ("8 / 30 kg · 2 / 5 m") — kg, yard, meter tidak dijumlah. */
function fabricUse(r) {
  const ins = r.inputs || [];
  if (ins.length <= 1 || !r.input_units_mixed) {
    return `${fmtNum(r.consumed_input_qty, 2)} / ${fmtNum(r.planned_input_qty, 2)} ${r.input_unit || ''}`;
  }
  return qtyPerUnit(ins, 'consumed_input_qty', (q) => fmtNum(q, 2));
}

/** Teks satu sel "kain" / "hasil" untuk order banyak baris. */
const linesText = (rows, labelOf) => (rows || []).map(labelOf).filter(Boolean).join(', ');

export default function CuttingOrdersModule({ token, onNavigate }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');

  // Form buat / ubah (satu komponen; `editOrder` = order draf yang diubah)
  const [formOpen, setFormOpen] = useState(false);
  const [editOrder, setEditOrder] = useState(null);

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [acting, setActing] = useState(false);
  // Standar UI/UX v2: form progres = popup sendiri; rincian disembunyikan sementara.
  const [progOpen, setProgOpen] = useState(false);

  // ── FASE H-6b (2026-08-17) — progres yang kainnya sudah keluar tetapi BELUM
  // punya dokumen "Pengeluaran Material". Ditampilkan supaya tidak ada arus
  // keluar yang hilang dari daftar gudang, dan bisa diterbitkan sekali klik.
  const [miMissing, setMiMissing] = useState({ items: [], count: 0 });
  const [miFixing, setMiFixing] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setErr('');
    try {
      const qs = new URLSearchParams();
      if (status) qs.set('status', status);
      if (q) qs.set('q', q);
      setRows(await cuttingApi('GET', `/orders${qs.toString() ? `?${qs}` : ''}`, token));
    } catch (e) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, [token, status, q]);

  useEffect(() => { load(); }, [load]);

  const loadMiMissing = useCallback(async () => {
    if (!token) return;
    try {
      setMiMissing(await cuttingApi('GET', '/issue-docs/missing?limit=200', token));
    } catch {
      setMiMissing({ items: [], count: 0 });
    }
  }, [token]);

  useEffect(() => { loadMiMissing(); }, [loadMiMissing]);

  const backfillMiDocs = async () => {
    setMiFixing(true);
    try {
      const res = await cuttingApi('POST', '/issue-docs/backfill', token, { limit: 500 });
      const n = res?.created || 0;
      if (n > 0) {
        toast.success(`${n} dokumen Pengeluaran Material diterbitkan — arus keluar kain kini tampil di layar Gudang.`);
      } else {
        toast.info('Tidak ada progres yang perlu dokumen baru.');
      }
      if ((res?.failed || []).length) {
        toast.error(`${res.failed.length} progres gagal: ${res.failed[0]?.error || ''}`);
      }
      await loadMiMissing();
      await load();
    } catch (e) {
      toast.error(`Gagal menerbitkan dokumen: ${e.message}`);
    } finally {
      setMiFixing(false);
    }
  };

  const openDetail = async (id) => {
    setDetailLoading(true);
    setProgOpen(false);
    try {
      setDetail(await cuttingApi('GET', `/orders/${id}`, token));
    } catch (e) {
      toast.error(e.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const refreshDetail = async (id) => {
    try {
      setDetail(await cuttingApi('GET', `/orders/${id}`, token));
    } catch { /* rincian tetap yang lama; daftar tetap dimuat ulang */ }
    load();
  };

  const openCreate = () => { setEditOrder(null); setFormOpen(true); };
  const openEdit = () => { setEditOrder(detail); setFormOpen(true); };
  const onFormSaved = async (saved) => {
    setFormOpen(false);
    setEditOrder(null);
    await load();
    if (saved?.id) openDetail(saved.id);
  };

  const doAction = async (path, body, okMsg) => {
    if (!detail) return;
    setActing(true);
    try {
      const res = await cuttingApi('POST', `/orders/${detail.id}${path}`, token, body);
      toast.success(okMsg);
      if (res?.notice) toast.info(res.notice, { duration: 6000 });
      // SESI #32 — kain SUDAH terpotong tetapi nilainya belum bisa dihitung (harga kain 0): peringatan.
      if (res?.value_warning) toast.warning(res.value_warning, { duration: 12000 });
      await refreshDetail(detail.id);
    } catch (e) {
      toast.error(e.message, { duration: 8000 });
    } finally {
      setActing(false);
    }
  };

  const onProgressSaved = async () => {
    setProgOpen(false);
    await refreshDetail(detail.id);
    await loadMiMissing();
  };

  const removeDraft = async (row) => {
    if (!(await confirmDialog({ title: `Hapus draf ${row.number}?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const res = await cuttingApi('DELETE', `/orders/${row.id}`, token);
      toast.success('Draf dihapus.');
      if (res?.notice) toast.info(res.notice, { duration: 6000 });
      if (detail?.id === row.id) setDetail(null);
      load();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const stLabel = (s) => (STATUS_META[s] || STATUS_META.draft).label;
  const kolom = [
    { kunci: 'nomor', label: 'Nomor', hp: 'judul', isi: (r) => <span className="font-medium tabular-nums whitespace-nowrap">{r.number}</span> },
    { kunci: 'style', label: 'Hasil potongan', hp: 'keterangan', isi: (r) => (
      <div className="min-w-0 md:max-w-[16rem]">
        <p className="truncate text-foreground" title={r.style_name}>{r.style_name || '—'}</p>
        <p className="text-xs tabular-nums text-muted-foreground">
          {(r.outputs || []).length > 1 ? `${r.outputs.length} baris hasil` : (r.output_material_code || 'Kode dibuat saat mulai')}
        </p>
      </div>) },
    { kunci: 'kain', label: 'Kain (input)', isi: (r) => (
      <div className="min-w-0 md:max-w-[14rem]">
        <p className="truncate text-sm" title={r.input_material_name}>{r.input_material_name}</p>
        <p className="text-xs tabular-nums text-muted-foreground">
          {(r.inputs || []).length > 1 ? `${r.inputs.length} kain` : r.input_material_code}
        </p>
      </div>) },
    { kunci: 'pakai', label: 'Kain terpakai', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums whitespace-nowrap">{fabricUse(r)}</span>) },
    { kunci: 'jadi', label: 'Potongan jadi', rata: 'kanan', isi: (r) => (
      <div className="tabular-nums whitespace-nowrap">
        <span className="font-medium text-foreground">{fmtNum(r.produced_qty)}</span>
        <span className="text-muted-foreground"> / {fmtNum(r.planned_output_qty)} pcs</span>
        <div className="mt-1 h-1 overflow-hidden rounded-full bg-foreground/10">
          <div className="h-full bg-primary" style={{ width: `${Math.min(r.progress_pct || 0, 100)}%` }} />
        </div>
      </div>) },
    { kunci: 'status', label: 'Status', isi: (r) => <StatusPill status={r.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="outline" onClick={() => openDetail(r.id)} data-testid={`cutting-detail-${r.number}`}>Rincian</Button>
        {r.status === 'draft' && (
          <Button size="icon-sm" variant="ghost" onClick={() => removeDraft(r)} title="Hapus draf" aria-label="Hapus draf"
            data-testid={`cutting-delete-${r.number}`}>
            <Trash2 />
          </Button>
        )}
      </div>) },
  ];

  const hpp = detail?.hpp_summary || {};

  return (
    <PageLayout testId="cutting-orders-module" title="Order Cutting"
      subtitle="Ubah roll kain menjadi kain pola (potongan) yang jadi material untuk BOM produksi."
      actions={<Button onClick={openCreate} data-testid="cutting-create-btn"><Plus />Buat cutting</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nomor, model, kain, kode potongan"
            className="pl-8" data-testid="cutting-search-input" />
        </div>
        <SmartNativeSelect value={status} onChange={(e) => setStatus(e.target.value)} searchable={false}
          className="h-9 w-44" wrapperClassName="w-44" aria-label="Status" data-testid="cutting-status-filter">
          <option value="">Semua status</option>
          <option value="draft">Draf</option>
          <option value="in_progress">Berjalan</option>
          <option value="completed">Selesai</option>
          <option value="cancelled">Dibatalkan</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="order-cutting" namaLembar="Order cutting" baris={rows} testId="cutting-unduh"
          kolom={[
            { label: 'Nomor', nilai: (r) => r.number }, { label: 'Hasil potongan', nilai: (r) => r.style_name || '' },
            { label: 'Kode potongan', nilai: (r) => r.output_material_code || '' },
            { label: 'Kain', nilai: (r) => r.input_material_name || '' }, { label: 'Kode kain', nilai: (r) => r.input_material_code || '' },
            { label: 'Kain terpakai', nilai: (r) => fabricUse(r) },
            { label: 'Potongan jadi (pcs)', nilai: (r) => Number(r.produced_qty || 0) },
            { label: 'Target (pcs)', nilai: (r) => Number(r.planned_output_qty || 0) },
            { label: 'Status', nilai: (r) => stLabel(r.status) }, { label: 'Dibuat', nilai: (r) => fmtDateTime(r.created_at) },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="cutting-refresh-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {err && <Notice tone="danger" icon={AlertCircle}>{err}</Notice>}
        {/* FASE H-6b — progres yang kainnya sudah keluar tetapi belum punya dokumen Pengeluaran Material.
            Menerbitkan dokumen TIDAK memotong stok lagi. */}
        {miMissing.count > 0 && (
          <Notice tone="warning" icon={AlertCircle} testId="cutting-mi-missing-panel"
            title={`${miMissing.count} laporan progres belum punya dokumen Pengeluaran Material`}
            action={<div className="flex flex-wrap gap-2">
              <TombolUnduh namaBerkas="progres-tanpa-dokumen" namaLembar="Progres" baris={miMissing.items || []} testId="cutting-mi-unduh"
                kolom={[
                  { label: 'Order', nilai: (m) => m.cutting_number || '' }, { label: 'Kode kain', nilai: (m) => m.material_code || '' },
                  { label: 'Kain', nilai: (m) => m.material_name || '' },
                  { label: 'Kain keluar', nilai: (m) => missingQty(m) },
                  { label: 'Gudang', nilai: (m) => m.location_name || '' },
                  { label: 'Gulungan', nilai: (m) => (m.roll_numbers || []).join(', ') }, { label: 'Waktu', nilai: (m) => fmtDateTime(m.created_at) },
                ]} />
              <Button size="sm" onClick={backfillMiDocs} disabled={miFixing} data-testid="cutting-mi-backfill-btn">
                {miFixing ? <Loader2 className="animate-spin" /> : <History />}
                {miFixing ? 'Menerbitkan…' : 'Terbitkan dokumen'}
              </Button>
            </div>}>
            <p>Kain dan gulungannya sudah berkurang, tetapi arus keluarnya belum tampil di Gudang › Pengeluaran Material.
              Menerbitkan dokumen hanya membuat bukti — <b>stok tidak dipotong lagi</b>.</p>
            <div className="mt-2 overflow-x-auto">
              <Table data-testid="cutting-mi-missing-table">
                <TableHeader><TableRow>
                  <TableHead>Order</TableHead><TableHead>Kain</TableHead><TableHead className="text-right">Kain keluar</TableHead>
                  <TableHead>Gudang</TableHead><TableHead>Gulungan</TableHead><TableHead>Waktu</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {(miMissing.items || []).slice(0, 8).map((m) => (
                    <TableRow key={m.progress_id} data-testid={`cutting-mi-missing-row-${m.progress_id}`}>
                      <TableCell className="tabular-nums">{m.cutting_number || '—'}</TableCell>
                      <TableCell><span className="tabular-nums">{m.material_code || '—'}</span>
                        <span className="text-muted-foreground"> · {m.material_name || ''}</span></TableCell>
                      <TableCell className="text-right tabular-nums">{missingQty(m)}</TableCell>
                      <TableCell>{m.location_name || '—'}</TableCell>
                      <TableCell className="tabular-nums">{(m.roll_numbers || []).join(', ') || '—'}</TableCell>
                      <TableCell className="whitespace-nowrap">{fmtDateTime(m.created_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {miMissing.count > 8 && (
              <p className="mt-1.5 text-xs text-muted-foreground">…dan {miMissing.count - 8} lagi. Tombol Terbitkan dokumen menerbitkan semuanya.</p>
            )}
          </Notice>
        )}
      </>}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      {loading && rows.length === 0 ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10 rounded-lg" />)}</div>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={(r) => openDetail(r.id)} testId="cutting-orders-table"
          kosong={<EmptyState icon={Scissors} testId="cutting-empty-state"
            title={q || status ? 'Tidak ada order yang cocok' : 'Belum ada order cutting'}
            description={q || status ? 'Ubah kata pencarian atau status.' : 'Mulai dengan memilih kain dari master material Gudang.'}
            action={!q && !status && <Button onClick={openCreate}><Plus />Buat cutting</Button>} />} />
      )}

      {/* ── FORM BUAT / UBAH CUTTING (popup panjang): kain & gulungan → hasil potongan ── */}
      <CuttingOrderForm open={formOpen} onClose={() => { setFormOpen(false); setEditOrder(null); }} token={token}
        order={editOrder} onSaved={onFormSaved} onNavigate={onNavigate} />

      {/* ── RINCIAN ORDER (popup) ─────────────────────────────────────── */}
      {detail && (
        <DetailPopup open={!progOpen && !formOpen} onClose={() => setDetail(null)} judul={`Cutting ${detail.number}`} testId="cutting-detail-panel"
          keterangan={`Dibuat ${fmtDateTime(detail.created_at)} oleh ${detail.created_by_name || '—'} · gudang sumber ${detail.location_name || '—'}`}
          status={<StatusPill status={detail.status} />}
          aksi={<>
            {detail.status === 'draft' && (
              <Button size="sm" variant="outline" onClick={openEdit} disabled={acting} data-testid="cutting-edit-btn">
                <PencilLine />Ubah
              </Button>
            )}
            {detail.status === 'draft' && (
              <Button size="sm" onClick={() => doAction('/start', {}, 'Cutting dimulai — master potongan dibuat.')}
                disabled={acting} data-testid="cutting-start-btn"><PlayCircle />Mulai cutting</Button>
            )}
            {detail.status === 'in_progress' && (
              <Button size="sm" onClick={() => setProgOpen(true)} disabled={acting} data-testid="cutting-progress-open">
                <PencilLine />Catat progres
              </Button>
            )}
            {detail.status === 'in_progress' && (
              <Button size="sm" variant="success" onClick={() => doAction('/complete', {}, 'Cutting selesai — HPP potongan dihitung.')}
                disabled={acting} data-testid="cutting-complete-btn"><CheckCircle2 />Selesaikan</Button>
            )}
            {(detail.status === 'draft' || detail.status === 'in_progress') && (
              <Button size="sm" variant="destructive" onClick={() => doAction('/cancel', { reason: 'dibatalkan user' }, 'Cutting dibatalkan.')}
                disabled={acting} data-testid="cutting-cancel-btn"><XCircle />Batalkan</Button>
            )}
            {detail.status === 'completed' && (detail.outputs || []).some((x) => x.output_material_code) && (
              <Button size="sm" variant="outline" onClick={() => onNavigate?.('cutting-panels')} data-testid="cutting-goto-panels">
                <Package />Lihat master potongan
              </Button>
            )}
          </>}>
          {detailLoading && <div className="h-1 animate-pulse rounded bg-primary" />}

          {/* Kain & gulungan */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Kain & gulungan</p>
            <div className="overflow-x-auto">
              <Table data-testid="cutting-detail-inputs">
                <TableHeader><TableRow>
                  <TableHead>Kain</TableHead><TableHead className="text-right">Terpakai / rencana</TableHead>
                  <TableHead className="text-right">Sisa ke stok</TableHead><TableHead className="text-right">Limbah</TableHead>
                  <TableHead className="text-right">Stok gudang</TableHead><TableHead>Gulungan</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {(detail.inputs || []).length === 0 ? (
                    <TableRow><TableCell colSpan={6}>
                      <EmptyState icon={Package} title="Kain order ini tidak terbaca" description="Muat ulang rinciannya." />
                    </TableCell></TableRow>
                  ) : detail.inputs.map((i) => (
                    <TableRow key={i.line_id}>
                      <TableCell>
                        <p className="text-foreground">{i.input_material_name}</p>
                        <p className="text-xs tabular-nums text-muted-foreground">{i.input_material_code}</p>
                      </TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">
                        <b>{fmtNum(i.consumed_input_qty, 2)}</b> / {fmtNum(i.planned_input_qty, 2)} {i.input_unit}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{fmtNum(i.leftover_qty, 2)}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{fmtNum(i.waste_qty, 2)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(i.input_stock, 2)} {i.input_unit}</TableCell>
                      <TableCell className="text-xs tabular-nums">
                        {(i.roll_ids || []).length
                          ? i.roll_ids.map((r) => `${r.roll_no}${Number(r.consumed_qty) > 0 ? ` (−${fmtQty(r.consumed_qty)})` : ''}`).join(', ')
                          : <span className="text-muted-foreground">{i.roll_required ? 'Dipilih saat lapor progres' : '—'}</span>}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>

          {/* Hasil potongan */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Hasil potongan</p>
            <div className="overflow-x-auto">
              <Table data-testid="cutting-detail-outputs">
                <TableHeader><TableRow>
                  <TableHead>Model · varian</TableHead><TableHead>Kode potongan</TableHead>
                  <TableHead className="text-right">Jadi / target (pcs)</TableHead><TableHead className="text-right">Stok potongan</TableHead>
                  <TableHead className="text-right">HPP/pcs</TableHead><TableHead>Baris PO</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {(detail.outputs || []).length === 0 ? (
                    <TableRow><TableCell colSpan={6}>
                      <EmptyState icon={Scissors} title="Hasil order ini tidak terbaca" description="Muat ulang rinciannya." />
                    </TableCell></TableRow>
                  ) : detail.outputs.map((x) => (
                    <TableRow key={x.line_id}>
                      <TableCell className="text-foreground">{x.label}</TableCell>
                      <TableCell className="text-xs tabular-nums">{x.output_material_code || 'Dibuat saat mulai'}</TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap">
                        <b>{fmtNum(x.produced_qty)}</b> / {fmtNum(x.planned_output_qty)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{x.output_material_id ? fmtNum(x.output_stock) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {Number(x.output_unit_cost) > 0 ? fmtRp(x.output_unit_cost)
                          : Number(x.panel_unit_cost) > 0 ? <span className="text-muted-foreground">{fmtRp(x.panel_unit_cost)}</span> : '—'}
                      </TableCell>
                      <TableCell className="text-xs tabular-nums">{x.po_number || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="text-xs text-muted-foreground" data-testid="cutting-detail-hpp">
              {Number(hpp.produced) > 0 && Number(hpp.value_total) > 0
                ? <>Biaya kain nyata {fmtRp(Math.round(hpp.value_total))} ÷ {fmtNum(hpp.produced)} pcs ={' '}
                  <b className="text-foreground">{fmtRp(Math.round(hpp.per_pcs))}/pcs</b> — sama untuk semua baris hasil.</>
                : <>Perkiraan dari rencana: {fmtRp(Math.round(hpp.estimate_total || 0))} ÷ {fmtNum(hpp.planned_pcs)} pcs ≈{' '}
                  {fmtRp(Math.round(hpp.estimate_per_pcs || 0))}/pcs (sama untuk semua baris; angka pasti dari kain yang terpakai).</>}
              {(hpp.missing_price || []).length > 0 && ` Kain ${hpp.missing_price.join(', ')} belum punya harga dari pembelian.`}
            </p>
          </div>

          {/* Gulungan → hasil potongan (no. roll, kain, lot warna → model/varian, pcs) */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-foreground">Gulungan dipakai untuk hasil potongan</p>
            <div className="overflow-x-auto">
              <Table data-testid="cutting-roll-output-matrix">
                <TableHeader><TableRow>
                  <TableHead>No. roll</TableHead><TableHead>Kain</TableHead><TableHead>Lot warna</TableHead>
                  <TableHead className="text-right">Terpakai</TableHead><TableHead>Dipakai untuk</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {(detail.roll_usage || []).length === 0 ? (
                    <TableRow><TableCell colSpan={5}>
                      <EmptyState icon={Package} title="Belum ada gulungan tercatat"
                        description="Gulungan dipilih saat order dibuat atau saat lapor progres." />
                    </TableCell></TableRow>
                  ) : detail.roll_usage.map((u) => (
                    <TableRow key={`${u.input_line_id}-${u.roll_id}`}>
                      <TableCell className="tabular-nums">{u.roll_no}</TableCell>
                      <TableCell className="tabular-nums">{u.material_code}</TableCell>
                      <TableCell>{u.color_lot || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{Number(u.consumed_qty) > 0 ? `${fmtQty(u.consumed_qty)} ${u.uom}` : '—'}</TableCell>
                      <TableCell className="text-xs">
                        {(u.outputs || []).length
                          ? u.outputs.map((x) => `${x.label}${Number(x.produced_qty) > 0 ? ` (${fmtNum(x.produced_qty)} pcs)` : ''}`).join(', ')
                          : <span className="text-[hsl(var(--warning-text))]">belum ditautkan ke hasil potongan</span>}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>

          {/* Riwayat progres */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
                <History className="h-4 w-4 text-muted-foreground" />Riwayat progres ({(detail.progress || []).length})
              </p>
              <div className="ml-auto flex flex-wrap gap-2">
                {/* FASE H-6b — pintu ke daftar arus keluar gudang (dokumen MI). */}
                {onNavigate && (detail.progress || []).length > 0 && (
                  <Button size="sm" variant="outline" onClick={() => { setDetail(null); onNavigate('wh-material-issue'); }}
                    data-testid="cutting-open-material-issue"><Package />Lihat di Pengeluaran Material</Button>
                )}
                <TombolUnduh namaBerkas={`progres-${detail.number}`} namaLembar="Progres" baris={detail.progress || []}
                  testId="cutting-progress-unduh"
                  kolom={[
                    { label: 'Waktu', nilai: (p) => fmtDateTime(p.created_at) },
                    { label: 'Kain', nilai: (p) => progInputs(p, detail) },
                    { label: 'Potongan', nilai: (p) => progOutputs(p) },
                    { label: 'Potongan (pcs)', nilai: (p) => Number(p.output_qty || 0) },
                    { label: 'Sisa ke stok', nilai: (p) => Number(p.leftover_qty || 0) },
                    { label: 'Limbah', nilai: (p) => Number(p.waste_qty || 0) },
                    { label: 'Nilai kain keluar', nilai: (p) => Number(p.value_out || 0) },
                    { label: 'HPP masuk / pcs', nilai: (p) => Number(p.cost_per_pcs_in || 0) },
                    { label: 'Gulungan dipakai', nilai: (p) => (p.roll_consumption || []).map((rc) => `${rc.roll_no} −${fmtQty(rc.qty)}`).join(', ') },
                    { label: 'Dokumen keluar', nilai: (p) => p.material_issue_number || 'Belum ada' },
                    { label: 'Catatan', nilai: (p) => p.note || '' }, { label: 'Oleh', nilai: (p) => p.created_by_name || '' },
                  ]} />
              </div>
            </div>
            <div className="overflow-x-auto">
              <Table data-testid="cutting-progress-table">
                <TableHeader><TableRow>
                  <TableHead>Waktu</TableHead><TableHead>Kain</TableHead><TableHead>Potongan</TableHead>
                  <TableHead className="text-right">Sisa ke stok</TableHead><TableHead className="text-right">Limbah</TableHead>
                  {/* SESI #32 — nilai yang BERPINDAH dari kain ke potongan */}
                  <TableHead className="text-right">Nilai kain keluar</TableHead><TableHead className="text-right">HPP masuk</TableHead>
                  <TableHead>Gulungan dipakai</TableHead><TableHead>Dokumen keluar</TableHead>
                  <TableHead>Catatan</TableHead><TableHead>Oleh</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {(detail.progress || []).length === 0 ? (
                    <TableRow><TableCell colSpan={11}>
                      <EmptyState icon={History} title="Progres belum dicatat"
                        description={detail.status === 'in_progress' ? 'Tekan Catat progres setelah kain dipotong.' : 'Mulai cutting dulu, lalu catat progresnya.'} />
                    </TableCell></TableRow>
                  ) : detail.progress.map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="whitespace-nowrap text-muted-foreground">{fmtDateTime(p.created_at)}</TableCell>
                      <TableCell className="text-xs tabular-nums">{progInputs(p, detail)}</TableCell>
                      <TableCell className="text-xs tabular-nums">{progOutputs(p)}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{fmtNum(p.leftover_qty || 0, 2)}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{fmtNum(p.waste_qty, 2)}</TableCell>
                      {/* Kalau kainnya belum bernilai, alasannya DITULIS (bukan "-"). */}
                      <TableCell className="text-right" data-testid={`cutting-progress-value-${p.id}`}>
                        {Number(p.value_out || 0) > 0
                          ? <span className="font-medium tabular-nums text-foreground">{fmtRp(p.value_out)}</span>
                          : <span className="text-xs text-[hsl(var(--warning-text))]" title={p.value_note || ''}>Belum bernilai</span>}
                      </TableCell>
                      <TableCell className="text-right">
                        {Number(p.cost_per_pcs_in || 0) > 0
                          ? <span className="font-medium tabular-nums text-foreground">{fmtRp(Math.round(p.cost_per_pcs_in))}/pcs</span>
                          : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell data-testid={`cutting-progress-rolls-${p.id}`}>
                        {(p.roll_consumption || []).length ? (
                          <div className="flex flex-wrap gap-1">
                            {p.roll_consumption.map((rc) => (
                              <span key={`${rc.input_line_id || ''}-${rc.roll_id}`} title={`sisa setelah dipakai: ${fmtQty(rc.remaining_after)}`}>
                                <StatusBadge status="" label={`${rc.roll_no} −${fmtQty(rc.qty)}`} tone="primary" className="tabular-nums" />
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-muted-foreground">{p.roll_id ? 'Tercatat' : '—'}</span>
                        )}
                      </TableCell>
                      {/* FASE H-6b — nomor dokumen "Pengeluaran Material" per progres; kosong HARUS terlihat. */}
                      <TableCell data-testid={`cutting-progress-mi-${p.id}`}>
                        {p.material_issue_number
                          ? <span title="Dokumen Pengeluaran Material yang mencatat arus keluar kain ini">
                              <StatusBadge status="" label={p.material_issue_number} tone="success" className="tabular-nums" /></span>
                          : <StatusBadge status="" label="Belum ada" tone="warning" />}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{p.note || '—'}</TableCell>
                      <TableCell className="text-muted-foreground">{p.created_by_name || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>

          {detail.notes && <p className="text-sm text-muted-foreground">Catatan: {detail.notes}</p>}
        </DetailPopup>
      )}

      {/* ── FORM CATAT PROGRES (popup panjang; rincian disembunyikan sementara) ── */}
      {detail && detail.status === 'in_progress' && (
        <CuttingProgressForm open={progOpen} onClose={() => setProgOpen(false)} order={detail} token={token}
          onSaved={onProgressSaved} onNavigate={onNavigate} />
      )}
    </PageLayout>
  );
}

/** Kain keluar satu progres tanpa dokumen MI (order banyak kain: per kain, satuannya bisa beda). */
function missingQty(m) {
  if ((m.inputs || []).length > 1) {
    return m.inputs.map((x) => `${x.material_code} ${fmtNum(x.input_consumed, 2)} ${x.unit}`).join(' · ');
  }
  return `${fmtNum(m.input_consumed, 2)} ${m.unit || ''}`.trim();
}

/** Kain satu progres: per kain bila tercatat per baris, selain itu angka lama (satu kain). */
function progInputs(p, order) {
  if ((p.inputs || []).length) {
    return linesText(p.inputs, (x) => `${x.input_material_code} ${fmtNum(x.input_consumed, 2)} ${x.input_unit}`);
  }
  return `${fmtNum(p.input_consumed, 2)} ${order?.input_unit || ''}`.trim();
}

/** Potongan satu progres: per hasil bila tercatat per baris, selain itu total pcs. */
function progOutputs(p) {
  if ((p.outputs || []).length > 1) {
    return linesText(p.outputs, (x) => `${x.output_material_code || x.label} ${fmtNum(x.output_qty)}`);
  }
  return `${fmtNum(p.output_qty)} pcs`;
}
