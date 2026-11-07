/**
 * RahazaMaterialReturnModule — Retur material produksi → gudang. 2026-11-02, keputusan owner K10.
 *
 * Jalur koreksi bahan yang SUDAH keluar gudang (Material Issue / Surat Jalan "Kirim ke CMT").
 * Surat jalan yang bahannya sudah keluar TIDAK bisa dihapus; bahan dikembalikan lewat layar ini:
 *   pilih MI / Surat Jalan asal → qty retur ≤ sisa (keluar − sudah diretur − retur berjalan)
 *   → supervisor setuju → gudang terima di lokasi WAJIB → stok kembali + jurnal balik
 *   (Dr persediaan / Cr WIP atau biaya proyek, pada HPP saat keluar) + status retur MI.
 * Backend: /api/production/material-returns (routes/production_material_returns.py).
 *
 * Tahap 9 (7 Nov 2026): tab "Retur" di menu Bahan (Portal Produksi & Maklon, disaring per portal lewat
 * `?business_type=`), dan tetap menu sendiri di Portal Gudang (tanpa saringan — gudang menerima semua).
 * Standar UI/UX v2 (8 Nov 2026): formulir retur = FormPopup panjang (dulu panel di halaman), terima = FormPopup pendek,
 * tabel + unduh Excel/CSV, Setujui hijau / Tolak merah. Isi bahan per retur tetap di bawah barisnya (RowDetail).
 *
 * Berbeda dari "Retur Produksi (barang dari buyer)" (`prod-buyer-returns`) dan Retur Fisik marketplace.
 */
import { Fragment, useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Loader2, PackageCheck, Plus, RefreshCw, Send, Undo2, XCircle, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import PageLayout, { RowDetail, RowToggle } from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { apiGet, apiPost } from '../../lib/api';
import { formatDateID } from '@/lib/format';
import { portalBusinessType, portalQuery } from '@/lib/portalScope';

const BASE = '/api/production/material-returns';
const CONDITIONS = [
  { value: 'good', label: 'Baik — kembali ke stok' },
  { value: 'damaged', label: 'Rusak — tidak kembali ke stok' },
  { value: 'scrap', label: 'Sisa buang — dicatat saja' },
];
const COND_LABEL = { good: 'baik', damaged: 'rusak', scrap: 'sisa buang' };
const STATUS_META = {
  draft: ['Draf', 'muted'], submitted: ['Menunggu supervisor', 'warning'], approved: ['Menunggu gudang', 'primary'],
  receiving: ['Sedang diterima', 'primary'], received: ['Diterima gudang', 'success'], rejected: ['Ditolak', 'danger'],
};
const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });

export default function RahazaMaterialReturnModule({ deepLinkParams, portalId }) {
  const businessType = portalBusinessType(portalId);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [creating, setCreating] = useState(null);
  const [receiving, setReceiving] = useState(null);
  const [busy, setBusy] = useState('');
  const [openRow, setOpenRow] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const [res, sum] = await Promise.all([
        apiGet(`${BASE}${portalQuery(businessType, { limit: 200, status })}`),
        apiGet(`${BASE}/summary${portalQuery(businessType)}`).catch(() => null),
      ]);
      setRows(res?.data || []);
      setSummary(sum?.data || null);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [businessType, status]);
  useEffect(() => { load(); }, [load]);
  // tautan dari "Kirim ke CMT" (hapus surat jalan ditolak → Retur material)
  useEffect(() => {
    if (deepLinkParams?.vendor_shipment_id || deepLinkParams?.material_issue_id) setCreating({ ...deepLinkParams, key: Date.now() });
  }, [deepLinkParams]);

  const act = async (doc, path, msg) => {
    setBusy(doc.id);
    try {
      await apiPost(`${BASE}/${doc.id}/${path}`, { note: '' });
      toast.success(`${msg} ${doc.ref_no}`);
      load();
    } catch (e) { toast.error(e.message); }
    finally { setBusy(''); }
  };

  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(rows, 25);
  const s = summary || {};
  const chips = [
    { key: '', label: 'Semua' },
    { key: 'submitted', label: 'Menunggu supervisor', count: summary ? Number(s.submitted || 0) : undefined },
    { key: 'approved', label: 'Menunggu gudang', count: summary ? Number(s.approved || 0) : undefined },
    { key: 'received', label: 'Diterima', count: summary ? Number(s.received || 0) : undefined },
    { key: 'rejected', label: 'Ditolak', count: summary ? Number(s.rejected || 0) : undefined },
  ];

  return (
    <PageLayout
      testId="material-return-module"
      title="Retur material"
      subtitle="Bahan yang sudah keluar ke produksi atau CMT dikembalikan ke gudang, dengan jurnal balik pada HPP saat keluar."
      actions={<Button onClick={() => setCreating({ key: Date.now() })} data-testid="pmr-new"><Plus className="w-4 h-4" />Retur material</Button>}
      filters={<>
        <FilterChips className="w-full sm:w-auto" value={status} onChange={setStatus} testId="pmr-filter" ariaLabel="Penyaring status retur" hideWhenEmpty={false} options={chips} />
        {/* Alat di akhir baris penyaring (bukan slot tools): di HP 390 px Toolbar bersama memeras penyaring. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <TombolUnduh namaBerkas="retur-material" namaLembar="Retur material" baris={rows} testId="pmr-unduh"
            kolom={[
              { label: 'No. retur', nilai: (r) => r.ref_no },
              { label: 'Tanggal', nilai: (r) => (r.created_at ? formatDateID(r.created_at) : '') },
              { label: 'Diajukan oleh', nilai: (r) => r.submitted_by || '' },
              { label: 'MI', nilai: (r) => r.mi_number || '' },
              { label: 'Surat jalan / WO', nilai: (r) => r.vendor_shipment_number || r.work_order_code || '' },
              { label: 'Baris bahan', nilai: (r) => (r.items || []).length },
              { label: 'Status', nilai: (r) => (STATUS_META[r.status] || STATUS_META.draft)[0] },
              { label: 'Jurnal', nilai: (r) => r.gl_je_number || r.gl_error || '' },
              { label: 'Alasan', nilai: (r) => r.return_reason || r.notes || '' },
            ]} />
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} data-testid="pmr-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}
      summary={err ? <Notice tone="danger" icon={AlertTriangle} title="Gagal memuat retur" testId="pmr-error">{err}</Notice> : null}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading && !rows.length ? (
          <p className="py-10 text-center text-sm text-muted-foreground"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />Memuat…</p>
        ) : rows.length === 0 ? (
          <EmptyState icon={Undo2} title="Belum ada retur material" description="Retur dibuat dari pengeluaran material atau surat jalan ke CMT yang bahannya sudah keluar." />
        ) : (
          <div className="overflow-x-auto">
          <Table>
            <TableHeader><TableRow>
              <TableHead className="w-10" />
              <TableHead>No. retur</TableHead><TableHead>Asal (MI · surat jalan)</TableHead><TableHead className="text-right">Baris bahan</TableHead>
              <TableHead>Status</TableHead><TableHead>Jurnal</TableHead><TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((r) => {
                const [label, tone] = STATUS_META[r.status] || STATUS_META.draft;
                const open = openRow === r.id;
                return (
                  <Fragment key={r.id}>
                    <TableRow data-testid={`pmr-row-${r.ref_no}`}>
                      <TableCell><RowToggle open={open} onClick={() => setOpenRow(open ? null : r.id)} label="Lihat bahan" /></TableCell>
                      <TableCell className="whitespace-nowrap">
                        <span className="font-medium">{r.ref_no}</span>
                        <span className="block text-xs text-muted-foreground">{r.created_at ? formatDateID(r.created_at) : '—'} · {r.submitted_by || '—'}</span>
                      </TableCell>
                      <TableCell>{r.mi_number || '—'}<span className="block text-xs text-muted-foreground">{r.vendor_shipment_number || r.work_order_code || ''}</span></TableCell>
                      <TableCell className="text-right tabular-nums">{(r.items || []).length}</TableCell>
                      <TableCell><StatusBadge status={r.status} label={label} tone={tone} /></TableCell>
                      <TableCell className="text-sm">{r.gl_je_number || (r.gl_error ? <span className="text-[hsl(var(--danger-text))]">{r.gl_error}</span> : '—')}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1 flex-wrap">
                          {r.status === 'draft' && (
                            <Button size="sm" variant="outline" disabled={busy === r.id} onClick={() => act(r, 'submit', 'Diajukan')}><Send className="w-3.5 h-3.5" />Ajukan</Button>
                          )}
                          {r.status === 'submitted' && (<>
                            <Button size="sm" variant="success" disabled={busy === r.id} onClick={() => act(r, 'approve', 'Disetujui')} data-testid={`pmr-approve-${r.ref_no}`}>
                              <CheckCircle2 className="w-3.5 h-3.5" />Setujui</Button>
                            <Button size="sm" variant="destructive" disabled={busy === r.id} onClick={() => act(r, 'reject', 'Ditolak')}>
                              <XCircle className="w-3.5 h-3.5" />Tolak</Button>
                          </>)}
                          {r.status === 'approved' && (
                            <Button size="sm" variant="outline" disabled={busy === r.id} onClick={() => setReceiving(r)} data-testid={`pmr-receive-${r.ref_no}`}>
                              <PackageCheck className="w-3.5 h-3.5" />Terima</Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={7} testId={`pmr-items-${r.ref_no}`}>
                        <Table>
                          <TableHeader><TableRow>
                            <TableHead>Kode</TableHead><TableHead>Bahan</TableHead><TableHead className="text-right">Qty retur</TableHead><TableHead>Kondisi</TableHead>
                          </TableRow></TableHeader>
                          <TableBody>
                            {(r.items || []).map((it, i) => (
                              <TableRow key={i}>
                                <TableCell className="whitespace-nowrap">{it.material_code || '—'}</TableCell>
                                <TableCell>{it.material_name || '—'}</TableCell>
                                <TableCell className="text-right tabular-nums">{fmtNum(it.qty_returned)} {it.unit}</TableCell>
                                <TableCell>{COND_LABEL[it.condition] || it.condition || '—'}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        {(r.return_reason || r.notes) && <p className="mt-2 text-xs text-muted-foreground">Alasan: {r.return_reason || r.notes}</p>}
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
          </div>
        )}
      </GlassCard>
      {creating && (
        <CreatePanel key={creating.key} preset={creating} businessType={businessType} onClose={() => setCreating(null)}
          onSaved={() => { setCreating(null); load(); }} />
      )}
      {receiving && <ReceiveDialog doc={receiving} onClose={() => setReceiving(null)} onDone={() => { setReceiving(null); load(); }} />}
    </PageLayout>
  );
}

/* ── Formulir retur — FormPopup panjang ──────────────────────────────────── */
function CreatePanel({ preset, businessType, onClose, onSaved }) {
  const [q, setQ] = useState(preset?.vendor_shipment_number || '');
  const [sources, setSources] = useState([]);
  const [src, setSrc] = useState(null);
  const [qty, setQty] = useState({});
  const [cond, setCond] = useState({});
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const loadSource = useCallback(async (params) => {
    setErr(''); setSrc(null); setQty({}); setCond({});
    try {
      const res = await apiGet(`${BASE}/source?${new URLSearchParams(params).toString()}`);
      setSrc(res?.data || null);
    } catch (e) { setErr(e.message); }
  }, []);

  useEffect(() => {
    apiGet(`${BASE}/sources${portalQuery(businessType, { q })}`)
      .then((res) => setSources(res?.data || [])).catch((e) => setErr(e.message));
  }, [businessType, q]);
  useEffect(() => {
    if (preset?.material_issue_id) loadSource({ material_issue_id: preset.material_issue_id });
    else if (preset?.vendor_shipment_id) loadSource({ vendor_shipment_id: preset.vendor_shipment_id });
  }, [preset, loadSource]);

  const submit = async () => {
    if (!src) { setErr('Pilih MI / surat jalan asal'); return; }
    const items = [];
    for (const l of src.lines) {
      const v = parseFloat(qty[l.material_id]);
      if (!(v > 0)) continue;
      if (v - l.returnable > 1e-6) { setErr(`${l.material_code}: retur ${v} > sisa ${fmtNum(l.returnable)}`); return; }
      items.push({ material_id: l.material_id, material_code: l.material_code, material_name: l.material_name,
        qty_returned: v, unit: l.unit, condition: cond[l.material_id] || 'good', reason: 'sisa_produksi' });
    }
    if (!items.length) { setErr('Isi qty retur minimal satu bahan'); return; }
    setBusy(true); setErr('');
    try {
      const created = await apiPost(BASE, {
        material_issue_id: src.material_issue_id, return_reason: reason, notes: reason, items, work_order_id: src.work_order_id || '',
      });
      const doc = created?.data;
      await apiPost(`${BASE}/${doc.id}/submit`, {});
      toast.success(`Retur ${doc.ref_no} diajukan — menunggu persetujuan supervisor`);
      onSaved?.();
    } catch (e) { setErr(e.message); setBusy(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul="Retur material ke gudang" testId="pmr-create-modal"
      keterangan="Bahan kondisi baik kembali ke stok di lokasi yang dipilih gudang saat menerima, dengan jurnal balik pada HPP saat keluar."
      onSimpan={submit} menyimpan={busy} bisaSimpan={!!src} labelSimpan="Ajukan retur" galat={err}>
      <div className="grid gap-4 md:grid-cols-2">
        <Isian label="Cari asal retur" htmlFor="pmr-source-search-in">
          <Input id="pmr-source-search-in" value={q} onChange={(e) => setQ(e.target.value)} placeholder="No. MI / surat jalan / vendor"
            data-testid="pmr-source-search" />
        </Isian>
        <Isian label="MI / surat jalan asal" wajib>
          <SmartNativeSelect value={src?.material_issue_id || ''} className="w-full" data-testid="pmr-source-select" aria-label="MI / surat jalan asal"
            onChange={(e) => e.target.value && loadSource({ material_issue_id: e.target.value })}>
            <option value="">Pilih MI / surat jalan asal</option>
            {sources.map((x) => (
              <option key={x.id} value={x.id}>
                {[x.mi_number, x.vendor_shipment_number ? `SJ ${x.vendor_shipment_number}` : '', x.vendor_name,
                  x.return_status === 'partial' ? 'sebagian diretur' : ''].filter(Boolean).join(' · ')}
              </option>
            ))}
          </SmartNativeSelect>
        </Isian>
      </div>
      {src && (
        <div className="overflow-x-auto">
          <p className="mb-1 text-sm text-muted-foreground">
            MI {src.mi_number}{src.vendor_shipment_number ? ` · surat jalan ${src.vendor_shipment_number}` : ''}{src.vendor_name ? ` · ${src.vendor_name}` : ''}
          </p>
          <Table data-testid="pmr-source-lines">
            <TableHeader><TableRow>
              <TableHead>Bahan</TableHead><TableHead className="text-right">Keluar</TableHead><TableHead className="text-right">Sudah diretur</TableHead>
              <TableHead className="text-right">Sisa</TableHead><TableHead className="text-right">Qty retur</TableHead><TableHead>Kondisi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {src.lines.map((l) => (
                <TableRow key={l.material_id}>
                  <TableCell><span className="font-medium">{l.material_code}</span><span className="block text-xs text-muted-foreground">{l.material_name}</span></TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(l.qty_issued)} {l.unit}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(l.qty_returned)}</TableCell>
                  <TableCell className="text-right tabular-nums font-medium">{fmtNum(l.returnable)}</TableCell>
                  <TableCell className="text-right">
                    <Input type="number" min="0" step="any" max={l.returnable} disabled={!(l.returnable > 0)} aria-label="Qty retur"
                      value={qty[l.material_id] ?? ''} onChange={(e) => setQty({ ...qty, [l.material_id]: e.target.value })}
                      className="ml-auto h-8 w-24 text-right" data-testid={`pmr-qty-${l.material_code}`} />
                  </TableCell>
                  <TableCell>
                    <SmartNativeSelect value={cond[l.material_id] || 'good'} className="h-8 w-56" searchable={false} aria-label="Kondisi"
                      onChange={(e) => setCond({ ...cond, [l.material_id]: e.target.value })}>
                      {CONDITIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </SmartNativeSelect>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <Isian label="Alasan retur" htmlFor="pmr-reason-in">
        <Input id="pmr-reason-in" value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="Mis. surat jalan salah / sisa produksi" data-testid="pmr-reason" />
      </Isian>
      {err && <span className="sr-only" data-testid="pmr-create-error">{err}</span>}
    </FormPopup>
  );
}

/* ── Isian pendek: lokasi penerima retur ─────────────────────────────────── */
function ReceiveDialog({ doc, onClose, onDone }) {
  const [locs, setLocs] = useState([]);
  const [locId, setLocId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    apiGet('/rahaza/storage-locations').then((r) => setLocs(Array.isArray(r) ? r : [])).catch((e) => setErr(e.message));
  }, []);
  const submit = async () => {
    if (!locId) { setErr('Lokasi penerima wajib dipilih'); return; }
    setBusy(true); setErr('');
    try {
      const out = await apiPost(`${BASE}/${doc.id}/receive`, { location_id: locId });
      const p = out?.posting || {};
      toast.success(`Retur ${doc.ref_no} diterima${p.je_number ? ` · jurnal ${p.je_number}` : ''}${p.ok === false ? ` · jurnal GAGAL: ${p.error}` : ''}`);
      onDone();
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" judul={`Terima retur ${doc.ref_no}`} testId="pmr-receive-dialog"
      keterangan="Bahan kondisi baik masuk ke stok lokasi ini, jurnal balik dibuat otomatis."
      onSimpan={submit} menyimpan={busy} labelSimpan="Terima ke stok" galat={err}>
      <Isian label="Lokasi penerima" wajib>
        <SmartNativeSelect value={locId} onChange={(e) => setLocId(e.target.value)} className="w-full" data-testid="pmr-receive-location" aria-label="Lokasi penerima">
          <option value="">Pilih lokasi penerima (wajib)</option>
          {locs.map((l) => <option key={l.id} value={l.id}>{l.code ? `${l.code} · ` : ''}{l.name || l.code}</option>)}
        </SmartNativeSelect>
      </Isian>
    </FormPopup>
  );
}
