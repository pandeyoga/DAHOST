/**
 * Form "Kiriman baru" ke CMT — dibuka DI HALAMAN (DetailPanel), bukan popup (PANDUAN_UI G13). Tahap 9, 7 Nov 2026.
 *
 * Dua bagian yang jelas:
 *   1. POTONGAN — otomatis dari BOM, pcs per SKU, dikunci. Stok kurang / BOM warna belum ada → tidak bisa disimpan.
 *   2. AKSESORIS — perkiraan BOM tampil sebagai acuan; user mengisi jumlah FINAL dalam satuan serah.
 * Pratinjau = `POST /kirim-cmt/preview` — hitungan yang SAMA dengan yang dipakai saat menyimpan.
 */
import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2, Truck } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { apiGet, apiPost } from '../../../../lib/api';
import { todayWIB } from '../../../../lib/waktu';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from '../../docnum/DocNumberField';
import { DetailPanel } from '../../layout/PageLayout';
import { EmptyState, Notice } from '../../moduleAtoms';
import { AksesorisTable, PotonganTable, SectionLabel, fmtNum, fmtRp } from './kirimShared';

const asList = (d) => (Array.isArray(d) ? d : (d?.items || []));

export default function KirimanForm({ businessType, onClose, onSaved, onNavigate }) {
  const maklon = businessType === 'maklon';
  const [vendors, setVendors] = useState([]);
  const [pos, setPos] = useState([]);
  const [form, setForm] = useState({ shipment_number: '', delivery_note_number: '', vendor_id: '', po_id: '',
    shipment_date: todayWIB(), notes: '' });
  const [poItems, setPoItems] = useState([]);
  const [qty, setQty] = useState({});
  const [accVals, setAccVals] = useState({});
  const [calc, setCalc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const numPolicy = useDocNumberPolicy('vendor_shipments.shipment_number', localStorage.getItem('erp_token'), null, true);

  useEffect(() => {
    apiGet('/garments').then((d) => setVendors(asList(d).filter((v) => v.status === 'active'))).catch(() => setVendors([]));
    const bt = businessType ? `?business_type=${businessType}` : '';
    apiGet(`/production-pos${bt}`).then((d) => setPos(asList(d).filter((p) => !['Completed', 'Closed'].includes(p.status)
      && (typeof p.remaining_qty_to_vendor === 'number' ? p.remaining_qty_to_vendor > 0 : true)))).catch(() => setPos([]));
  }, [businessType]);

  const po = pos.find((p) => p.id === form.po_id) || null;
  const poOptions = pos.filter((p) => !form.vendor_id || !p.vendor_id || p.vendor_id === form.vendor_id);

  const choosePo = async (poId) => {
    setForm((f) => ({ ...f, po_id: poId }));
    setCalc(null); setAccVals({});
    if (!poId) { setPoItems([]); setQty({}); return; }
    try {
      const rows = asList(await apiGet(`/po-items?po_id=${poId}`))
        .filter((i) => (typeof i.remaining_qty_to_vendor === 'number' ? i.remaining_qty_to_vendor > 0 : true));
      setPoItems(rows);
      setQty(Object.fromEntries(rows.map((i) => [i.id, typeof i.remaining_qty_to_vendor === 'number' ? i.remaining_qty_to_vendor : i.qty])));
    } catch (e) { setPoItems([]); toast.error(e.message || 'Baris PO gagal dimuat'); }
  };

  const lines = useMemo(() => poItems.filter((i) => Number(qty[i.id]) > 0)
    .map((i) => ({ po_id: form.po_id, po_number: po?.po_number, po_item_id: i.id, qty_sent: Number(qty[i.id]) })),
  [poItems, qty, form.po_id, po]);
  const accInput = useMemo(() => Object.entries(accVals).filter(([, v]) => v && v.qty !== '' && v.qty !== undefined)
    .map(([key, v]) => ({ key, qty_handover: Number(v.qty), handover_uom: v.uom })), [accVals]);
  const sig = JSON.stringify([form.po_id, lines.map((l) => [l.po_item_id, l.qty_sent]), accInput]);

  useEffect(() => {
    if (!form.po_id || !lines.length) { setCalc(null); return undefined; }
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        setCalc(await apiPost('/kirim-cmt/preview', { po_id: form.po_id, items: lines, accessory_items: accInput }));
      } catch (e) { setCalc({ blocking: true, blocking_reasons: [e.message || 'Pratinjau gagal'], potongan: [], aksesoris: [] }); }
      finally { setLoading(false); }
    }, 450);
    return () => clearTimeout(t);
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  const overRemaining = poItems.filter((i) => typeof i.remaining_qty_to_vendor === 'number' && Number(qty[i.id]) > i.remaining_qty_to_vendor);
  const noRate = po && !po.vendor_id ? lines.filter((l) => !(Number((poItems.find((i) => i.id === l.po_item_id) || {}).cmt_price_snapshot) > 0)) : [];
  const accRows = (calc?.aksesoris || []).filter((a) => a.qty_base > 0 || a.default_handover > 0 || a.estimate_base > 0 || accVals[a.key]);
  const canSave = form.vendor_id && form.po_id && lines.length && calc && !calc.blocking && !loading && !saving
    && !overRemaining.length && !noRate.length;

  const submit = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const { shipment_number: typed, ...rest } = form;
      const accessory_items = (calc.aksesoris || []).map((a) => ({
        key: a.key, material_id: a.material_id, qty_handover: Number(accVals[a.key]?.qty ?? a.qty_handover) || 0,
        handover_uom: accVals[a.key]?.uom || a.handover_uom }));
      const data = await apiPost('/vendor-shipments', {
        ...rest, po_number: po?.po_number || '', shipment_type: 'NORMAL', items: lines, accessory_items,
        ...docNumberPayload(numPolicy, 'shipment_number', typed) });
      const mi = data.material_issue;
      toast.success(`Kiriman ${data.shipment_number} dibuat${mi?.mi_number ? ` · stok berkurang (${mi.mi_number})` : ''}`
        + ((data.po_vendor_assigned || []).length ? ` · vendor PO diisi ${data.vendor_name || ''}` : ''));
      if ((mi?.negative_stock_lines || []).length) {
        toast.warning(`${mi.negative_stock_lines.length} aksesoris kini bersaldo minus — betulkan lewat stock opname.`, { duration: 8000 });
      }
      onSaved?.(data);
    } catch (e) { toast.error(e.message || 'Kiriman gagal dibuat'); }
    finally { setSaving(false); }
  };

  return (
    <DetailPanel testId="kirim-form" closeTestId="kirim-form-close" onClose={onClose}
      title="Kiriman baru ke CMT"
      description="Potongan otomatis dari BOM; aksesoris diisi jumlah final dalam satuan serah."
      actions={<Button onClick={submit} disabled={!canSave} data-testid="kirim-form-submit">
        {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Truck className="w-4 h-4" />}Simpan kiriman</Button>}>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <DocNumberField policy={numPolicy} value={form.shipment_number} label="No. kiriman" testId="kirim-number"
          onChange={(v) => setForm((f) => ({ ...f, shipment_number: v }))} />
        <label className="text-xs font-medium text-foreground/80 space-y-1">
          <span>No. surat jalan (opsional)</span>
          <GlassInput value={form.delivery_note_number} onChange={(e) => setForm((f) => ({ ...f, delivery_note_number: e.target.value }))}
            className="h-9" data-testid="kirim-sj" />
        </label>
        <label className="text-xs font-medium text-foreground/80 space-y-1">
          <span>Vendor CMT</span>
          <SmartNativeSelect value={form.vendor_id} aria-label="Vendor CMT" className="h-9 w-full" data-testid="kirim-vendor"
            onChange={(e) => { setForm((f) => ({ ...f, vendor_id: e.target.value, po_id: '' })); setPoItems([]); setCalc(null); }}>
            <option value="">Pilih vendor CMT</option>
            {vendors.map((v) => <option key={v.id} value={v.id}>{v.garment_name}{v.garment_code ? ` (${v.garment_code})` : ''}</option>)}
          </SmartNativeSelect>
        </label>
        <label className="text-xs font-medium text-foreground/80 space-y-1">
          <span>Tanggal kirim</span>
          <GlassInput type="date" value={form.shipment_date} className="h-9" data-testid="kirim-date"
            onChange={(e) => setForm((f) => ({ ...f, shipment_date: e.target.value }))} />
        </label>
      </div>
      <label className="block text-xs font-medium text-foreground/80 space-y-1">
        <span>PO</span>
        <SmartNativeSelect value={form.po_id} disabled={!form.vendor_id} aria-label="PO" className="h-9 w-full" data-testid="kirim-po"
          onChange={(e) => choosePo(e.target.value)}>
          <option value="">{form.vendor_id ? 'Pilih PO' : 'Pilih vendor CMT dulu'}</option>
          {poOptions.map((p) => (
            <option key={p.id} value={p.id}>{p.po_number} · {p.customer_name || '—'}{p.vendor_id ? '' : ' · belum ada vendor'}</option>
          ))}
        </SmartNativeSelect>
      </label>
      {po && !po.vendor_id && (
        <p className="text-xs text-muted-foreground" data-testid="kirim-po-no-vendor">
          PO {po.po_number} belum punya vendor — vendor kiriman ini akan dicatat sebagai vendor PO.
        </p>
      )}
      {noRate.length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} testId="kirim-no-rate" title="Upah jahit per pcs belum diisi"
          action={onNavigate && <Button variant="link" size="sm" onClick={() => onNavigate(maklon ? 'maklon-pos-engine' : 'prod-pos-internal',
            { edit_po_id: po.id, vendor_id: form.vendor_id })}>Isi upah di form PO</Button>}>
          Penjahit dipilih saat kirim, jadi upah per pcs untuk baris yang dikirim diisi dulu di form PO.
        </Notice>
      )}
      {calc?.sample_warning && (
        <Notice tone="warning" icon={AlertTriangle} testId="kirim-sample-warning" title="Sampel belum disetujui">
          {calc.sample_warning.message}
        </Notice>
      )}

      {form.po_id && (
        <div className="space-y-2">
          <SectionLabel testId="kirim-items-title">Barang dikirim (pcs per SKU)</SectionLabel>
          {poItems.length === 0 ? (
            <EmptyState icon={Truck} title="Semua baris PO sudah dikirim" description="Gunakan Permintaan tambahan untuk kiriman susulan." />
          ) : (
            <Table data-testid="kirim-items">
              <TableHeader><TableRow>
                <TableHead>SKU</TableHead><TableHead>Produk</TableHead><TableHead>Ukuran / warna</TableHead>
                <TableHead className="text-right">Sisa ke CMT</TableHead><TableHead className="text-right">Dikirim</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {poItems.map((i) => {
                  const over = typeof i.remaining_qty_to_vendor === 'number' && Number(qty[i.id]) > i.remaining_qty_to_vendor;
                  return (
                    <TableRow key={i.id} data-testid={`kirim-item-${i.sku || i.id}`}>
                      <TableCell className="whitespace-nowrap">{i.sku || '—'}</TableCell>
                      <TableCell>{i.product_name}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{[i.size, i.color].filter(Boolean).join(' / ')}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtNum(i.remaining_qty_to_vendor ?? i.qty)}</TableCell>
                      <TableCell className="text-right">
                        <GlassInput type="number" min="0" className={`h-8 w-24 text-right ml-auto ${over ? 'border-[hsl(var(--destructive))]' : ''}`}
                          value={qty[i.id] ?? ''} aria-label={`Qty dikirim ${i.sku || ''}`}
                          onChange={(e) => setQty((q) => ({ ...q, [i.id]: e.target.value }))} data-testid={`kirim-item-qty-${i.sku || i.id}`} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          {overRemaining.length > 0 && (
            <p className="text-xs text-[hsl(var(--destructive))]">Qty melebihi sisa ke CMT — kurangi, atau pakai Permintaan tambahan.</p>
          )}
        </div>
      )}

      {lines.length > 0 && (
        <>
          {loading && <p className="text-xs text-muted-foreground flex items-center gap-1" data-testid="kirim-preview-loading">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> Menghitung dari BOM…</p>}
          {calc?.blocking && (
            <Notice tone="danger" icon={AlertTriangle} testId="kirim-blocking" title="Kiriman belum bisa dibuat">
              <ul className="list-disc pl-4 text-xs space-y-0.5">{(calc.blocking_reasons || []).map((r, i) => <li key={i}>{r}</li>)}</ul>
            </Notice>
          )}
          <div className="space-y-2" data-testid="kirim-section-potongan">
            <SectionLabel aside={<span className="text-xs text-muted-foreground">otomatis dari BOM · tidak bisa diubah</span>}>
              Potongan
            </SectionLabel>
            {(calc?.potongan || []).length > 0 ? <PotonganTable rows={calc.potongan} withStock testId="kirim-potongan" />
              : <p className="text-xs text-muted-foreground">{maklon ? 'Kain dan potongan disediakan klien — tidak dikeluarkan dari gudang.' : 'Belum ada potongan yang terhitung.'}</p>}
          </div>
          <div className="space-y-2" data-testid="kirim-section-aksesoris">
            <SectionLabel aside={<span className="text-xs text-muted-foreground">perkiraan BOM hanya acuan · isi jumlah yang diserahkan</span>}>
              Aksesoris
            </SectionLabel>
            {accRows.length > 0 ? (
              <AksesorisTable rows={accRows} mode="form" values={accVals} testId="kirim-aksesoris"
                onChange={(key, v) => setAccVals((s) => ({ ...s, [key]: v }))} />
            ) : <p className="text-xs text-muted-foreground">Tidak ada aksesoris dari gudang untuk kiriman ini.</p>}
            {(calc?.client_accessories || []).length > 0 && (
              <p className="text-xs text-muted-foreground">Disediakan klien: {calc.client_accessories.map((c) => c.accessory_name).join(', ')}.</p>
            )}
            {calc?.has_negative && (
              <Notice tone="warning" icon={AlertTriangle} testId="kirim-negative">
                Mode sementara stok boleh minus aktif: aksesoris yang kurang akan bersaldo minus. Potongan tidak pernah boleh minus.
              </Notice>
            )}
          </div>
          {(calc?.warnings || []).length > 0 && (
            <Notice tone="info" icon={AlertTriangle} testId="kirim-warnings">
              <ul className="list-disc pl-4 text-xs space-y-0.5">{calc.warnings.slice(0, 5).map((w, i) => <li key={i}>{w}</li>)}</ul>
            </Notice>
          )}
          {calc && (
            <p className="text-sm" data-testid="kirim-total">
              Nilai keluar gudang: <b className="tabular-nums">{fmtRp(calc.value?.total)}</b>
              <span className="text-muted-foreground"> · potongan {fmtRp(calc.value?.potongan)} · aksesoris {fmtRp(calc.value?.aksesoris)} — langsung menjadi biaya PO</span>
            </p>
          )}
        </>
      )}
      <label className="block text-xs font-medium text-foreground/80 space-y-1">
        <span>Catatan (opsional)</span>
        <Textarea rows={2} value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} data-testid="kirim-notes" />
      </label>
    </DetailPanel>
  );
}
