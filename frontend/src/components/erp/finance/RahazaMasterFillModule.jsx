import { useState, useRef, useEffect, useCallback } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Download, Upload, CheckCircle2, AlertTriangle, ClipboardList } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { StatTile } from '../moduleAtoms';
import PageLayout from '../layout/PageLayout';
import { fmt, authHeaders, downloadXlsx } from './reportShared';

const tdN = 'text-right tabular-nums';
const CAT_LABEL = {
  model_tanpa_sku: 'model tanpa SKU', model_dihentikan: 'model dihentikan (semua SKU nonaktif)', kelompok_tanpa_varian: 'kelompok tanpa varian', satuan_tak_valid: 'satuan tak valid',
  kode_tak_dikenal: 'kode tak dikenal', qty_kosong: 'qty kosong', warna_tak_dikenal: 'warna tak dikenal', model_tak_dikenal: 'model tak dikenal', baris_tanpa_model: 'baris tanpa model',
};
// kategori baru dari server yang belum berlabel tetap tampil sebagai kata biasa, bukan kode
const catLabel = (k) => CAT_LABEL[k] || String(k || '').replace(/_/g, ' ');

async function postXlsx(url, token, file, fallbackName) {
  const fd = new FormData();
  if (file) fd.append('file', file);
  const r = await fetch(url, { method: 'POST', headers: authHeaders(token), body: fd });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const blob = await r.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href; a.download = fallbackName; a.click();
  URL.revokeObjectURL(href);
}

function ResultCard({ result }) {
  return (
    <GlassCard className="p-4 text-xs space-y-1" data-testid="fill-result">
      <p className="font-semibold text-sm text-[hsl(var(--success-text))]">Selesai ({result.scope === 'bom' ? 'hanya BOM' : 'semua sheet'})</p>
      <div>BOM: {result.bom_lines_appended || 0} baris aksesoris terpasang (mengganti {result.bom_lines_replaced || 0} baris lama) di {result.boms_touched || 0} BOM · {result.boms_unchanged || 0} BOM sudah sama · {result.bom_groups || 0} kelompok / {result.bom_models || 0} model · {result.bom_base_created || 0} BOM dasar baru</div>
      <div>HPP: {result.models_hpp_applied} model dihitung · <span className="text-[hsl(var(--warning-text))]" data-testid="fill-result-hpp-unvalidated">{result.hpp_unvalidated || 0} model HPP belum tervalidasi</span> (material harga 0 / kemasan tanpa isi) · {result.hpp_validated || 0} tervalidasi{result.variants_created ? <> · <span data-testid="fill-result-variants">{result.variants_created} varian/SKU baru dibuat (sheet VARIAN_BARU)</span></> : null}</div>
      {result.scope !== 'bom' && <div data-testid="fill-result-extra">{result.materials_updated} material · {result.accounts_updated} rekening · {result.stores_updated} toko · {result.sku_prices_updated || 0} harga SKU · <span data-testid="fill-result-deactivated">{result.sku_deactivated || 0} SKU dinonaktifkan (sudah tidak dijual)</span> · <span data-testid="fill-result-status">{result.sku_status_updated || 0} status produk</span> · {result.opening_stock_rows || 0} stok awal · {result.salaries_updated || 0} gaji · {result.models_weight_updated || 0} berat model</div>}
      {(result.bom_conflicts || []).length > 0 && <div className="text-[hsl(var(--warning-text))]">Konflik qty (kelompok belakangan menimpa): {result.bom_conflicts.join(' | ')}</div>}
      {/* 2026-11-06 (Tahap 2): harga barang berstok hanya lewat revaluasi berjurnal (stok = buku besar) */}
      {result.price_report && (
        <div data-testid="fill-result-price">
          Harga: {(result.price_report.price_opening || []).length} harga awal (stok kosong) ·{' '}
          {(result.price_report.price_revalued || []).length} direvaluasi berjurnal ·{' '}
          <span className={(result.price_report.price_skipped || []).length ? 'text-[hsl(var(--warning-text))]' : ''}>
            {(result.price_report.price_skipped || []).length} dilewati
          </span>
          {(result.price_report.price_skipped || []).length > 0 && (
            <span className="text-muted-foreground"> — barang sudah berstok: {result.price_report.price_skipped.slice(0, 8).map((s) => s.code).join(', ')}
              {result.price_report.price_skipped.length > 8 ? ', …' : ''}. Isi alasan revaluasi lalu terapkan ulang.</span>
          )}
        </div>
      )}
    </GlassCard>
  );
}

const StepLabel = ({ n }) => <p className="text-xs text-muted-foreground font-semibold">Langkah {n}</p>;

/**
 * Impor go-live (menu Pengaturan Keuangan › Impor go-live) — harga, satuan, rekening, dan BOM dari satu berkas Excel.
 * 2026-11-05 (PANDUAN_UI G1/G3/G11): cetakan PageLayout; satu tombol utama (Terapkan); penjelasan panjang dipendekkan
 * dan istilah program ("yang_perlu_diisi", "{dasar}") diganti kalimat biasa; warna hanya token.
 */
export default function RahazaMasterFillModule({ token }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [revalReason, setRevalReason] = useState('');
  const inputRef = useRef(null);

  const doPreview = useCallback(async () => {
    if (!file) { setPreview(null); return; }
    setBusy(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const r = await fetch('/api/rahaza/master/fill-preview', { method: 'POST', headers: authHeaders(token), body: fd });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : 'Gagal membaca berkas'); return; }
      setPreview(j); setResult(null);
    } finally { setBusy(false); }
  }, [file, token]);
  useEffect(() => { doPreview(); }, [doPreview]);

  const doApply = async (scope) => {
    setBusy(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const qs = new URLSearchParams({ scope });
      if (scope !== 'bom' && revalReason.trim()) qs.set('revaluation_reason', revalReason.trim());
      const r = await fetch(`/api/rahaza/master/fill-apply?${qs}`, { method: 'POST', headers: authHeaders(token), body: fd });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : j.detail?.message || 'Gagal'); return; }
      setResult(j);
      toast.success(`Diterapkan (${scope === 'bom' ? 'hanya BOM' : 'semua sheet'}): ${j.bom_lines_appended || 0} baris aksesoris di ${j.boms_touched || 0} BOM · HPP ${j.models_hpp_applied} model (${j.hpp_unvalidated || 0} belum tervalidasi). Unduh laporan sisa untuk kekurangannya.`);
    } finally { setBusy(false); }
  };
  const dl = () => downloadXlsx('/api/rahaza/master/fill-template', token, 'TEMPLATE_HARGA_SATUAN_REKENING_BOM.xlsx').catch((e) => toast.error(e.message));
  const dlGap = () => (file
    ? postXlsx('/api/rahaza/master/gap-workbook', token, file, 'DATA_YANG_PERLU_DIISI_DA_SISA.xlsx')
    : downloadXlsx('/api/rahaza/master/gap-workbook', token, 'DATA_YANG_PERLU_DIISI_DA.xlsx')).catch((e) => toast.error(e.message));
  const dlLaporan = () => postXlsx('/api/rahaza/master/laporan-sisa', token, file, 'LAPORAN_SISA_DA.xlsx').catch((e) => toast.error(e.message));
  const dlFokus = () => postXlsx('/api/rahaza/master/gap-fokus', token, file, 'DATA_YANG_PERLU_DIISI_DA_FOKUS.xlsx').catch((e) => toast.error(e.message));
  const dlHarga = () => downloadXlsx('/api/rahaza/master/harga-review', token, 'REVIEW_HARGA_MATERIAL_DA.xlsx').catch((e) => toast.error(e.message));
  const t = preview?.totals || {};
  const nApply = (t.materials || 0) + (t.accounts || 0) + (t.stores || 0) + (t.bom_lines || 0) + (t.models || 0) + (t.sku_prices || 0) + (t.sku_deactivate || 0) + (t.sku_status || 0) + (t.stock_rows || 0) + (t.salaries || 0);
  const bomWarn = preview?.warnings || [];
  const cats = Object.entries(preview?.bom_issue_counts || {});

  return (
    <PageLayout
      testId="fill-page"
      title="Impor harga, satuan, rekening, dan BOM"
      subtitle="Sesi go-live: unduh berkas isian, isi sel kuning, unggah untuk pratinjau, lalu terapkan."
    >
      <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
        <GlassCard className="p-4 space-y-3"><StepLabel n={1} /><p className="text-sm font-semibold text-foreground">Unduh berkas isian</p>
          <Button type="button" variant="outline" onClick={dlFokus} className="w-full" data-testid="fill-download-fokus"><Download className="w-4 h-4" />{file ? 'Berkas fokus — sisa dari berkas ini' : 'Berkas fokus (yang perlu diisi saja)'}</Button>
          <p className="text-xs text-muted-foreground">Hanya yang masih perlu diisi: sheet VARIAN_BARU, BOM_AKSESORIS, dan MATERIAL. Isi sel {/* warna sel templat Excel (bukan warna layar) */}<span className="rounded px-1 bg-[#FFF2CC] text-black">kuning</span>; sel <span className="rounded px-1 bg-[#DDEBF7] text-black">biru</span> diisi otomatis (mis. varian dari nama bahan pembeda), cukup diperiksa. Kolom "Yang perlu diisi" menyebut persis kekurangan tiap baris.</p>
          <Button type="button" size="sm" onClick={dlHarga} variant="outline" className="w-full" data-testid="fill-download-harga-review"><Download className="w-4 h-4" />Periksa harga aksesoris & kain (HPP)</Button>
          <Button type="button" size="sm" onClick={dlGap} variant="outline" className="w-full" data-testid="fill-download-gap"><Download className="w-4 h-4" />{file ? 'Berkas lengkap — sisa dari berkas ini' : 'Berkas lengkap (semua sheet)'}</Button>
          <Button type="button" size="sm" onClick={dl} variant="outline" className="w-full" data-testid="fill-download"><Download className="w-4 h-4" />Template lengkap (semua material)</Button></GlassCard>
        <GlassCard className="p-4 space-y-3"><StepLabel n={2} /><p className="text-sm font-semibold text-foreground">Unggah berkas terisi</p>
          <input ref={inputRef} type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary/20 file:px-3 file:py-1.5 file:text-xs file:text-primary" data-testid="fill-file" />
          <p className="text-xs text-muted-foreground">Pratinjau muncul otomatis: baris siap dan yang dilewati per kategori, varian tujuan, dan satuan dasar hasil konversi. BOM aksesoris per model & varian di berkas diganti utuh; model lain tidak disentuh.</p></GlassCard>
        <GlassCard className="p-4 space-y-3"><StepLabel n={3} /><p className="text-sm font-semibold text-foreground">Terapkan</p>
          <Button type="button" onClick={() => doApply('bom')} disabled={!preview || busy || !(t.bom_lines > 0)} className="w-full" data-testid="fill-apply">
            <CheckCircle2 className="w-4 h-4" />Terapkan (hanya BOM)</Button>
          <Button type="button" size="sm" onClick={() => doApply('all')} variant="outline" disabled={!preview?.ok || busy || !nApply} className="w-full" data-testid="fill-apply-all">
            <Upload className="w-4 h-4" />Terapkan semua sheet</Button>
          <div>
            <label className="block text-xs text-muted-foreground mb-1" htmlFor="fill-reval-reason">Alasan revaluasi (barang yang sudah berstok)</label>
            <GlassInput id="fill-reval-reason" value={revalReason} onChange={(e) => setRevalReason(e.target.value)}
              placeholder="kosongkan = harga barang berstok tidak diubah" className="h-8 text-xs" data-testid="fill-reval-reason" />
            <p className="text-xs text-muted-foreground mt-1">Harga barang tanpa stok langsung jadi harga awal. Harga barang berstok hanya diubah lewat revaluasi berjurnal bila alasan diisi.</p>
          </div></GlassCard>
        <GlassCard className="p-4 space-y-3"><StepLabel n={4} /><p className="text-sm font-semibold text-foreground">Laporan sisa</p>
          <Button type="button" onClick={dlLaporan} variant="outline" className="w-full" data-testid="fill-download-laporan"><ClipboardList className="w-4 h-4" />Unduh laporan sisa</Button>
          <p className="text-xs text-muted-foreground">Kekurangan yang tidak diimpor: model tanpa SKU, kelompok tanpa varian, satuan/kode tak valid, warna tak dikenal, material harga 0, harga jual SKU, berat/toko/rekening/gaji, HPP belum tervalidasi. {file ? 'Memakai berkas yang sedang diunggah.' : 'Tanpa berkas: hanya dari data yang sudah ada di sistem.'}</p></GlassCard>
      </div>
      {preview && (
        <div className="space-y-3" data-testid="fill-preview">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <StatTile label="Baris BOM siap" value={`${t.bom_lines || 0} (${t.bom_groups || 0} kelompok · ${t.bom_models || 0} model)`} testId="fill-kpi-bom" />
            <StatTile label="BOM dilewati" value={`${t.bom_skipped || 0} catatan · ${t.bom_models_in_file || 0} model di berkas`} accent={t.bom_skipped ? 'warning' : 'success'} testId="fill-kpi-bom-skipped" />
            <StatTile label="Material berubah" value={t.materials} testId="fill-kpi-mat" />
            <StatTile label="Rekening · Toko · Berat" value={`${t.accounts || 0} · ${t.stores || 0} · ${t.models || 0}`} testId="fill-kpi-acc" />
            <StatTile label="Harga SKU · Nonaktif · Stok awal · Gaji" value={`${t.sku_prices || 0} · ${t.sku_deactivate || 0} · ${t.stock_rows || 0} · ${t.salaries || 0}`} testId="fill-kpi-extra" />
            <StatTile label={preview.ok ? (bomWarn.length ? `Siap · ${bomWarn.length} dilewati` : 'Siap') : `${preview.errors.length} masalah sheet lain`} value={preview.ok ? 'Siap' : 'Periksa'} accent={preview.ok ? (bomWarn.length ? 'warning' : 'success') : 'danger'} testId="fill-kpi-status" />
          </div>
          {cats.length > 0 && (
            <div className="flex flex-wrap gap-2 text-xs" data-testid="fill-issue-cats">
              {cats.map(([k, n]) => <span key={k} className="rounded-full border border-[hsl(var(--warning)/0.3)] px-2.5 py-1" data-testid={`fill-issue-cat-${k}`}>{catLabel(k)}: <b>{n}</b></span>)}
            </div>
          )}
          {preview.errors.length > 0 && (
            <div className="bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.3)] rounded-[var(--radius-md)] px-4 py-3 text-xs" data-testid="fill-errors">
              <p className="inline-flex items-center gap-2 text-[hsl(var(--danger-text))] font-semibold mb-2"><AlertTriangle className="w-4 h-4" />Masalah di sheet selain BOM (tidak menghalangi "Terapkan hanya BOM")</p>
              <ul className="list-disc pl-5 space-y-1 max-h-[30vh] overflow-auto">{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
            </div>
          )}
          {bomWarn.length > 0 && (
            <div className="bg-[hsl(var(--warning)/0.08)] border border-[hsl(var(--warning)/0.3)] rounded-[var(--radius-md)] px-4 py-3 text-xs" data-testid="fill-warnings">
              <p className="inline-flex items-center gap-2 text-[hsl(var(--warning-text))] font-semibold mb-2"><AlertTriangle className="w-4 h-4" />{bomWarn.length} catatan dilewati — masuk laporan sisa, tidak menghalangi penerapan sisanya</p>
              <ul className="list-disc pl-5 space-y-1 max-h-[30vh] overflow-auto">{bomWarn.map((e, i) => <li key={i}>{e}</li>)}</ul>
            </div>
          )}
          {preview.materials.length > 0 && (<>
            <div className="flex justify-end"><TombolUnduh namaBerkas="pratinjau-material" baris={preview.materials} testId="fill-mat-unduh" kolom={[
              { label: 'Kode', nilai: (m) => m.code }, { label: 'Nama', nilai: (m) => m.name }, { label: 'Satuan beli', nilai: (m) => m.buy_unit || '' },
              { label: 'Isi', nilai: (m) => Number(m.pack_size) || 0 }, { label: 'Satuan dasar', nilai: (m) => m.base_unit || '' },
              { label: 'Harga beli', nilai: (m) => Number(m.buy_price) || 0 }, { label: 'Per satuan dasar', nilai: (m) => (m.unit_cost == null ? '' : Number(m.unit_cost)) },
              { label: 'Sebelumnya', nilai: (m) => Number(m.unit_cost_before) || 0 },
            ]} /></div>
            <GlassCard className="p-0 overflow-hidden"><div className="overflow-auto max-h-[40vh]"><Table data-testid="fill-mat-table">
              <TableHeader><TableRow><TableHead>Kode</TableHead><TableHead>Nama</TableHead><TableHead>Beli</TableHead><TableHead className="text-right">Isi</TableHead><TableHead className="text-right">Harga beli</TableHead><TableHead className="text-right">Per satuan dasar</TableHead><TableHead className="text-right">Sebelumnya</TableHead></TableRow></TableHeader>
              <TableBody>{preview.materials.map((m) => <TableRow key={m.code} data-testid={`fill-mat-${m.code}`}><TableCell className="whitespace-nowrap">{m.code}</TableCell><TableCell>{m.name}</TableCell><TableCell>{m.buy_unit}</TableCell><TableCell className={tdN}>{m.pack_size} {m.base_unit}</TableCell><TableCell className={tdN}>{m.buy_price ? fmt(m.buy_price) : ''}</TableCell><TableCell className={`${tdN} text-[hsl(var(--success-text))]`}>{m.unit_cost != null ? `${fmt(m.unit_cost)}/${m.base_unit}` : ''}</TableCell><TableCell className={`${tdN} text-muted-foreground`}>{fmt(m.unit_cost_before)}</TableCell></TableRow>)}</TableBody>
            </Table></div></GlassCard>
          </>)}
          {(preview.bom_lines || []).length > 0 && (<>
            <div className="flex justify-end"><TombolUnduh namaBerkas="pratinjau-bom" baris={preview.bom_lines} testId="fill-bom-unduh" kolom={[
              { label: 'Baris', nilai: (b) => b.row }, { label: 'Model', nilai: (b) => `${b.model_code || ''} ${b.model_name || ''}`.trim() },
              { label: 'Varian tujuan', nilai: (b) => b.target || '' }, { label: 'Material', nilai: (b) => `${b.code || ''} ${b.name || ''}`.trim() },
              { label: 'Qty/pcs', nilai: (b) => Number(b.qty) || 0 }, { label: 'Satuan', nilai: (b) => b.unit || '' },
              { label: 'Satuan dasar', nilai: (b) => Number(b.qty_base) || 0 }, { label: 'Catatan', nilai: (b) => b.note || '' },
            ]} /></div>
            <GlassCard className="p-0 overflow-hidden" data-testid="fill-bom-table"><div className="overflow-auto max-h-[40vh]"><Table>
              <TableHeader><TableRow><TableHead>Baris</TableHead><TableHead>Model</TableHead><TableHead>Varian tujuan</TableHead><TableHead>Material</TableHead><TableHead className="text-right">Qty/pcs</TableHead><TableHead className="text-right">Dalam satuan dasar</TableHead><TableHead>Catatan</TableHead></TableRow></TableHeader>
              <TableBody>{preview.bom_lines.map((b, i) => <TableRow key={i} data-testid={`fill-bom-row-${b.row}`}><TableCell className="tabular-nums text-muted-foreground">{b.row}</TableCell><TableCell><span className="whitespace-nowrap">{b.model_code}</span> {b.model_name}</TableCell><TableCell>{b.target} <span className="text-muted-foreground">({b.target_skus} SKU)</span></TableCell><TableCell><span className="whitespace-nowrap">{b.code}</span> {b.name}</TableCell><TableCell className={tdN}>{b.qty} {b.unit}</TableCell><TableCell className={tdN}>{b.qty_base} {b.unit_base}</TableCell><TableCell className="text-xs text-muted-foreground">{b.note}</TableCell></TableRow>)}</TableBody>
            </Table></div></GlassCard>
          </>)}
          {(preview.models || []).length > 0 && (
            <GlassCard className="p-4 text-xs space-y-1" data-testid="fill-models">{preview.models.map((m) => <div key={m.model_code}>Model {m.model_code} → berat {m.weight_gram} gram</div>)}</GlassCard>
          )}
          {(preview.accounts.length > 0 || preview.stores.length > 0 || (preview.sku_deactivate || []).length > 0 || (preview.sku_status || []).length > 0) && (
            <GlassCard className="p-4 text-xs space-y-1" data-testid="fill-acc-store">
              {preview.accounts.map((a) => <div key={a.gl_account_code}>Akun {a.gl_account_code} → no. rek {a.account_number || '-'} a.n. {a.holder_name || '-'}</div>)}
              {preview.stores.map((s) => <div key={s.account_code}>Toko {s.account_code} → pencairan ke akun {s.coa_cash_code}</div>)}
              {(preview.sku_status || []).length > 0 && <div data-testid="fill-status-list">Status produk diubah ({preview.sku_status.length} SKU): {preview.sku_status.map((d) => `${d.sku} → ${d.label}`).join(', ')}</div>}
              {(preview.sku_deactivate || []).length > 0 && <div className="text-[hsl(var(--warning-text))]" data-testid="fill-deactivate-list">SKU akan dinonaktifkan ("{preview.sku_deactivate[0].teks}"): {preview.sku_deactivate.map((d) => d.sku).join(', ')}</div>}
            </GlassCard>
          )}
        </div>
      )}
      {result && <ResultCard result={result} />}
    </PageLayout>
  );
}
