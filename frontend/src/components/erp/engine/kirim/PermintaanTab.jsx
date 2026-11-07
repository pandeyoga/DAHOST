/**
 * Tab "Permintaan tambahan" (Tahap 9, keputusan owner 12, 7 Nov 2026).
 *
 * SATU daftar: permintaan dari Portal Vendor (tambahan/pengganti) + input staf (dulu menu "Komponen Kurang") +
 * hasil pemeriksaan vendor. Setelah DISETUJUI, permintaan menjadi KIRIMAN TAMBAHAN yang mengurangi stok lewat
 * hitungan yang sama dengan kiriman biasa (potongan dari BOM wajib cukup, aksesoris dalam satuan serah).
 * Disaring per portal (PO internal / PO maklon).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Inbox, Loader2, Plus, RefreshCw, Search, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { apiGet, apiPost } from '../../../../lib/api';
import PageLayout, { DetailPanel } from '../../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../../moduleAtoms';
import { AksesorisTable, PotonganTable, SectionLabel, fmtDate, fmtNum, handoverOptions } from './kirimShared';

const PER_PAGE = 25;
const STATUS_TONE = { menunggu: 'warning', dikirim: 'success', ditolak: 'danger' };
const STATUS_LABEL = { menunggu: 'Menunggu', dikirim: 'Sudah dikirim', ditolak: 'Ditolak' };
const APPROVER = ['superadmin', 'admin', 'admin_produksi', 'admin_maklon', 'supervisor_produksi', 'owner', 'manager', 'ppic',
  'manager_produksi'];
const asList = (d) => (Array.isArray(d) ? d : (d?.items || []));

export default function PermintaanTab({ portalId, userRole }) {
  const businessType = portalId === 'maklon' ? 'maklon' : portalId === 'production' ? 'internal' : null;
  const [rows, setRows] = useState([]);
  const [counts, setCounts] = useState({});
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('menunggu');
  const [source, setSource] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(null);       // {src, id}
  const [creating, setCreating] = useState(false);
  const canDecide = APPROVER.includes(userRole);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const qs = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE) });
      if (businessType) qs.set('business_type', businessType);
      if (status) qs.set('status', status);
      if (source) qs.set('source', source);
      if (search.trim()) qs.set('search', search.trim());
      const env = await apiGet(`/kirim-cmt/requests?${qs}`);
      setRows(env.items || []); setTotal(env.total || 0); setCounts(env.counts || {});
    } catch (e) { setError(e.message || 'Daftar permintaan gagal dimuat'); setRows([]); }
    finally { setLoading(false); }
  }, [businessType, page, status, source, search]);
  useEffect(() => { load(); }, [businessType, page, status, source]); // eslint-disable-line react-hooks/exhaustive-deps

  const allCount = (counts.menunggu || 0) + (counts.dikirim || 0) + (counts.ditolak || 0);
  return (
    <PageLayout
      testId="kirim-permintaan"
      title="Permintaan tambahan"
      subtitle="Permintaan vendor dan input staf; setelah disetujui menjadi kiriman tambahan yang mengurangi stok."
      actions={canDecide && (
        <Button onClick={() => { setOpen(null); setCreating(true); }} data-testid="permintaan-new"><Plus className="w-4 h-4" />Permintaan baru</Button>
      )}
      filters={<>
        <FilterChips value={status} onChange={(v) => { setPage(1); setStatus(v); }} testId="permintaan-status" ariaLabel="Status permintaan"
          hideWhenEmpty={false} options={[
            { key: 'menunggu', label: 'Menunggu', count: counts.menunggu || 0 },
            { key: 'dikirim', label: 'Sudah dikirim', count: counts.dikirim || 0 },
            { key: 'ditolak', label: 'Ditolak', count: counts.ditolak || 0 },
            { key: '', label: 'Semua', count: allCount }]} />
        <div className="relative w-64 max-w-full">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nomor / vendor / PO…"
            onKeyDown={(e) => { if (e.key === 'Enter') { setPage(1); load(); } }} className="pl-8 h-9" data-testid="permintaan-search" />
        </div>
        <SmartNativeSelect value={source} onChange={(e) => { setPage(1); setSource(e.target.value); }} className="h-9 w-52"
          aria-label="Asal permintaan" data-testid="permintaan-source">
          <option value="">Semua asal</option>
          <option value="vendor">Portal vendor</option>
          <option value="staf">Input staf</option>
          <option value="pemeriksaan">Hasil pemeriksaan vendor</option>
        </SmartNativeSelect>
      </>}
      tools={<Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={load} data-testid="permintaan-refresh">
        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /></Button>}
      summary={error && <Notice tone="danger" title="Gagal memuat data">{error}</Notice>}
      detail={creating ? (
        <PermintaanForm businessType={businessType} onClose={() => setCreating(false)}
          onSaved={(doc) => { setCreating(false); setStatus('menunggu'); load(); setOpen({ src: 'krg', id: doc.id }); }} />
      ) : open && (
        <PermintaanDetail key={`${open.src}:${open.id}`} src={open.src} id={open.id} canDecide={canDecide}
          onClose={() => setOpen(null)} onChanged={load} />
      )}
      footer={total > PER_PAGE && (
        <PaginationLite page={page} totalPages={Math.max(1, Math.ceil(total / PER_PAGE))} total={total} pageSize={PER_PAGE} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground"><RefreshCw className="w-4 h-4 animate-spin inline mr-2" />Memuat permintaan…</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={Inbox} testId="permintaan-empty"
            title={status === 'menunggu' ? 'Tidak ada permintaan yang menunggu' : 'Tidak ada permintaan yang cocok'}
            description="Permintaan dari vendor (kurang/cacat) dan input staf muncul di sini." />
        ) : (
          <Table data-testid="permintaan-table">
            <TableHeader><TableRow>
              <TableHead>No. permintaan</TableHead><TableHead>Asal</TableHead><TableHead>Vendor CMT</TableHead><TableHead>PO</TableHead>
              <TableHead>Isi</TableHead><TableHead>Status</TableHead><TableHead>Kiriman tambahan</TableHead><TableHead>Tanggal</TableHead>
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.key} data-testid={`permintaan-row-${r.number}`}
                  className={open && `${open.src}:${open.id}` === r.key ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell className="whitespace-nowrap">
                    <Button variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => { setCreating(false); setOpen({ src: r.src, id: r.id }); }}
                      data-testid={`permintaan-open-${r.number}`}>{r.number}</Button>
                    <span className="block text-xs text-muted-foreground">{r.kind_label}</span>
                  </TableCell>
                  <TableCell className="text-xs">{r.source_label}</TableCell>
                  <TableCell>{r.vendor_name || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{r.po_number || '—'}
                    {r.shipment_number && <span className="block">dari {r.shipment_number}</span>}</TableCell>
                  <TableCell className="text-xs max-w-xs">{r.summary || '—'}</TableCell>
                  <TableCell>
                    <StatusBadge status={r.status} label={STATUS_LABEL[r.status]} tone={STATUS_TONE[r.status]} />
                    {r.sub_status && r.status === 'menunggu' && <span className="block text-xs text-muted-foreground">{r.sub_status}</span>}
                  </TableCell>
                  <TableCell className="text-xs whitespace-nowrap">{r.child_shipment_number || '—'}
                    {r.material_issue_number && <span className="block text-muted-foreground">{r.material_issue_number}</span>}</TableCell>
                  <TableCell className="text-xs whitespace-nowrap">{fmtDate(r.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => { setCreating(false); setOpen({ src: r.src, id: r.id }); }}>Rincian</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
    </PageLayout>
  );
}

function PermintaanDetail({ src, id, canDecide, onClose, onChanged }) {
  const [d, setD] = useState(null);
  const [accVals, setAccVals] = useState({});
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setD(await apiGet(`/kirim-cmt/requests/${src}/${id}`)); }
    catch (e) { toast.error(e.message || 'Rincian gagal dimuat'); onClose?.(); }
  }, [src, id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  if (!d) return <DetailPanel testId="permintaan-detail" title="Memuat…" onClose={onClose}><p className="text-sm text-muted-foreground">Memuat…</p></DetailPanel>;
  const r = d.row || {};
  const pv = d.preview;
  const pending = r.status === 'menunggu';
  const editableAcc = src === 'mr' && pending;

  const approve = async () => {
    setBusy(true);
    try {
      const body = { admin_notes: notes };
      if (editableAcc && pv) {
        body.accessory_items = (pv.aksesoris || []).map((a) => ({ accessory_id: a.material_id, accessory_code: a.code,
          accessory_name: a.name, qty_sent: Number(accVals[a.key]?.qty ?? a.qty_handover) || 0,
          unit: accVals[a.key]?.uom || a.handover_uom }));
      }
      const res = await apiPost(`/kirim-cmt/requests/${src}/${id}/approve`, body);
      toast.success(`Disetujui · kiriman tambahan ${res.shipment_number} dibuat dan stok berkurang`);
      onChanged?.(); await load();
    } catch (e) { toast.error(e.message || 'Persetujuan gagal'); }
    finally { setBusy(false); }
  };
  const reject = async () => {
    const reason = await confirmDialog({ title: `Tolak permintaan ${r.number}?`, confirmLabel: 'Tolak permintaan', danger: true,
      body: 'Alasan dibaca vendor / staf yang meminta.', input: { label: 'Alasan penolakan', minLength: 3 } });
    if (!reason) return;
    try {
      await apiPost(`/kirim-cmt/requests/${src}/${id}/reject`, { reason });
      toast.info('Permintaan ditolak');
      onChanged?.(); await load();
    } catch (e) { toast.error(e.message || 'Gagal menolak'); }
  };

  return (
    <DetailPanel testId="permintaan-detail" closeTestId="permintaan-detail-close" onClose={onClose}
      title={`${r.number} · ${r.vendor_name || '—'}`}
      description={`${r.kind_label} · ${r.source_label} · PO ${r.po_number || '—'}${r.shipment_number ? ` · dari ${r.shipment_number}` : ''} · ${fmtDate(r.created_at)}`}
      actions={pending && canDecide && <>
        <Button variant="outline" onClick={reject} data-testid="permintaan-reject"><X className="w-4 h-4" />Tolak</Button>
        <Button onClick={approve} disabled={busy || !pv || pv.blocking} data-testid="permintaan-approve">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}Setujui & kirim
        </Button>
      </>}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status={r.status} label={STATUS_LABEL[r.status]} tone={STATUS_TONE[r.status]} testId="permintaan-detail-status" />
        {r.child_shipment_number && <span>Kiriman tambahan <b className="tabular-nums">{r.child_shipment_number}</b>
          {r.material_issue_number && <span className="text-muted-foreground"> · pengeluaran {r.material_issue_number}</span>}</span>}
      </div>
      {d.reason && <p className="text-sm text-muted-foreground">Alasan: {d.reason}</p>}
      {r.status_note && <p className="text-sm text-muted-foreground" data-testid="permintaan-status-note">Catatan status: {r.status_note}</p>}
      {r.admin_notes && r.status !== 'menunggu' && <p className="text-sm">Catatan keputusan: {r.admin_notes}</p>}
      {(d.lines || []).length > 0 && (
        <>
          <SectionLabel>Pcs per SKU yang diminta</SectionLabel>
          <Table data-testid="permintaan-lines">
            <TableHeader><TableRow><TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran / warna</TableHead>
              <TableHead className="text-right">Qty (pcs)</TableHead></TableRow></TableHeader>
            <TableBody>
              {d.lines.map((l) => (
                <TableRow key={l.po_item_id}><TableCell>{l.sku || '—'}</TableCell><TableCell>{l.product_name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{[l.size, l.color].filter(Boolean).join(' / ')}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(l.qty)}</TableCell></TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
      {pending && pv && (
        <>
          {pv.blocking && (
            <Notice tone="danger" icon={AlertTriangle} title="Belum bisa disetujui" testId="permintaan-blocking">
              <ul className="list-disc pl-4 text-xs">{(pv.blocking_reasons || []).map((x, i) => <li key={i}>{x}</li>)}</ul>
            </Notice>
          )}
          <SectionLabel aside={<span className="text-xs text-muted-foreground">dari BOM · keluar saat disetujui</span>}>Potongan</SectionLabel>
          {(pv.potongan || []).length ? <PotonganTable rows={pv.potongan} withStock testId="permintaan-potongan" />
            : <p className="text-xs text-muted-foreground">Tidak ada potongan pada permintaan ini.</p>}
          <SectionLabel aside={editableAcc && <span className="text-xs text-muted-foreground">isi 0 bila tidak ikut dikirim sekarang</span>}>Aksesoris</SectionLabel>
          {(pv.aksesoris || []).length ? (
            <AksesorisTable rows={pv.aksesoris} mode={editableAcc ? 'form' : 'detail'} values={accVals} testId="permintaan-aksesoris"
              onChange={editableAcc ? (key, v) => setAccVals((s) => ({ ...s, [key]: v })) : undefined} />
          ) : <p className="text-xs text-muted-foreground">Tidak ada aksesoris pada permintaan ini.</p>}
          {canDecide && (
            <label className="block text-xs font-medium text-foreground/80 space-y-1">
              <span>Catatan untuk vendor (opsional)</span>
              <Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} data-testid="permintaan-notes" />
            </label>
          )}
        </>
      )}
      {!pending && (d.materials || []).length > 0 && (
        <p className="text-xs text-muted-foreground">Barang langsung: {d.materials.map((m) => `${m.material_code || m.material_id} ${fmtNum(m.qty)} ${m.uom || ''}`).join(', ')}</p>
      )}
    </DetailPanel>
  );
}

function PermintaanForm({ businessType, onClose, onSaved }) {
  const [pos, setPos] = useState([]);
  const [poId, setPoId] = useState('');
  const [items, setItems] = useState([]);
  const [ships, setShips] = useState([]);
  const [shipId, setShipId] = useState('');
  const [qty, setQty] = useState({});
  const [mats, setMats] = useState([]);
  const [acc, setAcc] = useState([]);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    apiGet(`/production-pos${businessType ? `?business_type=${businessType}` : ''}`)
      .then((d) => setPos(asList(d).filter((p) => !['Closed'].includes(p.status)))).catch(() => setPos([]));
    apiGet('/acc/items?type=accessory').then((d) => setMats(asList(d).filter((m) => m.active !== false))).catch(() => setMats([]));
  }, [businessType]);
  const [planIds, setPlanIds] = useState([]);
  const pickPo = async (id) => {
    setPoId(id); setShipId(''); setQty({});
    if (!id) { setItems([]); setShips([]); setPlanIds([]); return; }
    try {
      const [its, sh, plan] = await Promise.all([apiGet(`/po-items?po_id=${id}`), apiGet(`/vendor-shipments?po_id=${id}&parent_only=1`),
        apiGet(`/kirim-cmt/po/${id}/accessory-plan`).catch(() => ({ rows: [] }))]);
      setItems(asList(its)); setShips(asList(sh));
      setPlanIds((plan?.rows || []).map((r) => r.accessory_id).filter(Boolean));
    } catch (e) { toast.error(e.message || 'Data PO gagal dimuat'); }
  };
  const matById = useMemo(() => Object.fromEntries(mats.map((m) => [m.id, m])), [mats]);
  // aksesoris rencana PO (dari BOM / tambahan) tampil paling atas — padanan "(dari BOM)" layar Komponen Kurang lama
  const matChoices = useMemo(() => [...mats.filter((m) => planIds.includes(m.id)).map((m) => ({ ...m, _plan: true })),
    ...mats.filter((m) => !planIds.includes(m.id))], [mats, planIds]);
  const lines = items.filter((i) => Number(qty[i.id]) > 0).map((i) => ({ po_item_id: i.id, qty: Number(qty[i.id]) }));
  const accLines = acc.filter((a) => a.material_id && Number(a.qty) > 0);
  const canSave = poId && (lines.length || accLines.length) && reason.trim().length >= 3 && !saving;
  const save = async () => {
    setSaving(true);
    try {
      const doc = await apiPost('/kirim-cmt/requests', { po_id: poId, source_shipment_id: shipId || null, business_type: businessType,
        lines, materials: accLines.map((a) => ({ material_id: a.material_id, qty: Number(a.qty), uom: a.uom })), reason });
      toast.success(`Permintaan ${doc.request_code} dicatat — setujui untuk mengirim`);
      onSaved?.(doc);
    } catch (e) { toast.error(e.message || 'Permintaan gagal disimpan'); }
    finally { setSaving(false); }
  };
  return (
    <DetailPanel testId="permintaan-form" closeTestId="permintaan-form-close" onClose={onClose} title="Permintaan tambahan baru"
      description="Input staf: pcs per SKU (potongan diambil dari BOM) dan/atau aksesoris dalam satuan serah."
      actions={<Button onClick={save} disabled={!canSave} data-testid="permintaan-form-submit">
        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}Simpan permintaan</Button>}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="text-xs font-medium text-foreground/80 space-y-1">
          <span>PO</span>
          <SmartNativeSelect value={poId} onChange={(e) => pickPo(e.target.value)} className="h-9 w-full" aria-label="PO" data-testid="permintaan-form-po">
            <option value="">Pilih PO</option>
            {pos.map((p) => <option key={p.id} value={p.id}>{p.po_number} · {p.vendor_name || 'belum ada vendor'}</option>)}
          </SmartNativeSelect>
        </label>
        <label className="text-xs font-medium text-foreground/80 space-y-1">
          <span>Kiriman asal (opsional)</span>
          <SmartNativeSelect value={shipId} onChange={(e) => setShipId(e.target.value)} disabled={!poId} className="h-9 w-full"
            aria-label="Kiriman asal" data-testid="permintaan-form-ship">
            <option value="">Tanpa kiriman asal</option>
            {ships.map((s) => <option key={s.id} value={s.id}>{s.shipment_number} · {fmtDate(s.shipment_date)}</option>)}
          </SmartNativeSelect>
        </label>
      </div>
      {items.length > 0 && (
        <>
          <SectionLabel>Pcs per SKU (potongan dari BOM)</SectionLabel>
          <Table data-testid="permintaan-form-lines">
            <TableHeader><TableRow><TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran / warna</TableHead>
              <TableHead className="text-right">Qty diminta (pcs)</TableHead></TableRow></TableHeader>
            <TableBody>
              {items.map((i) => (
                <TableRow key={i.id}>
                  <TableCell>{i.sku || '—'}</TableCell><TableCell>{i.product_name}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{[i.size, i.color].filter(Boolean).join(' / ')}</TableCell>
                  <TableCell className="text-right">
                    <GlassInput type="number" min="0" className="h-8 w-24 text-right ml-auto" value={qty[i.id] ?? ''}
                      aria-label={`Qty diminta ${i.sku || ''}`} onChange={(e) => setQty((q) => ({ ...q, [i.id]: e.target.value }))}
                      data-testid={`permintaan-form-qty-${i.sku || i.id}`} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
      {poId && (
        <>
          <SectionLabel aside={<Button variant="outline" size="sm" onClick={() => setAcc((a) => [...a, { material_id: '', qty: '', uom: '' }])}
            data-testid="permintaan-form-add-acc"><Plus className="w-3.5 h-3.5" />Tambah aksesoris</Button>}>Aksesoris</SectionLabel>
          {acc.length === 0 && <p className="text-xs text-muted-foreground">Klik "Tambah aksesoris" bila CMT kekurangan aksesoris.</p>}
          {acc.map((a, idx) => {
            const ho = handoverOptions(matById[a.material_id]);
            return (
              <div key={idx} className="grid grid-cols-1 sm:grid-cols-[1fr_8rem_14rem_auto] gap-2 items-center" data-testid={`permintaan-form-acc-${idx}`}>
                <SmartNativeSelect value={a.material_id} aria-label="Aksesoris" className="h-9 w-full"
                  onChange={(e) => { const m = matById[e.target.value]; setAcc((rows) => rows.map((x, i) => (i === idx
                    ? { ...x, material_id: e.target.value, uom: handoverOptions(m).default } : x))); }}>
                  <option value="">Pilih aksesoris</option>
                  {matChoices.map((m) => <option key={m.id} value={m.id}>{m.name || m.accessory_name} · {m.code || m.accessory_code}{m._plan ? ' (rencana PO)' : ''}</option>)}
                </SmartNativeSelect>
                <GlassInput type="number" min="0" step="any" className="h-9 text-right" placeholder="Qty" value={a.qty} aria-label="Qty serah"
                  onChange={(e) => setAcc((rows) => rows.map((x, i) => (i === idx ? { ...x, qty: e.target.value } : x)))} />
                <SmartNativeSelect value={a.uom || ho.default} aria-label="Satuan serah" className="h-9 w-full"
                  onChange={(e) => setAcc((rows) => rows.map((x, i) => (i === idx ? { ...x, uom: e.target.value } : x)))}>
                  {ho.options.map((o) => <option key={o.uom} value={o.uom}>{o.label}</option>)}
                </SmartNativeSelect>
                <Button variant="outline" size="icon" title="Hapus baris" aria-label="Hapus baris"
                  onClick={() => setAcc((rows) => rows.filter((_, i) => i !== idx))}><X className="w-4 h-4" /></Button>
              </div>
            );
          })}
        </>
      )}
      <label className="block text-xs font-medium text-foreground/80 space-y-1">
        <span>Alasan (wajib)</span>
        <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="mis. potongan rusak saat dijahit"
          data-testid="permintaan-form-reason" />
      </label>
    </DetailPanel>
  );
}
