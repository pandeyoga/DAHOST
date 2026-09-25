import { useState, useRef, useEffect, useCallback } from 'react';
import { Download, Upload, CheckCircle2, AlertTriangle, FileSpreadsheet, ClipboardList } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { PageHeader, StatTile } from '../moduleAtoms';
import { fmt, authHeaders, downloadXlsx } from './reportShared';

const tdN = 'py-1.5 px-2 text-right font-mono text-xs';
const CAT_LABEL = {
  model_tanpa_sku: 'model tanpa SKU', model_dihentikan: 'model dihentikan (semua SKU nonaktif)', kelompok_tanpa_varian: 'kelompok tanpa varian', satuan_tak_valid: 'satuan tak valid',
  kode_tak_dikenal: 'kode tak dikenal', qty_kosong: 'qty kosong', warna_tak_dikenal: 'warna tak dikenal', model_tak_dikenal: 'model tak dikenal', baris_tanpa_model: 'baris tanpa model',
};

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
    <GlassCard className="p-4 text-xs text-emerald-300 space-y-1" data-testid="fill-result">
      <div>Selesai ({result.scope === 'bom' ? 'hanya BOM' : 'semua sheet'}): BOM: {result.bom_lines_appended || 0} baris aksesoris terpasang (mengganti {result.bom_lines_replaced || 0} baris lama) di {result.boms_touched || 0} BOM · {result.boms_unchanged || 0} BOM sudah sama · {result.bom_groups || 0} kelompok / {result.bom_models || 0} model · {result.bom_base_created || 0} BOM dasar baru</div>
      <div>HPP: {result.models_hpp_applied} model dihitung · <span className="text-amber-300" data-testid="fill-result-hpp-unvalidated">{result.hpp_unvalidated || 0} model HPP belum tervalidasi</span> (material harga 0 / kemasan tanpa isi) · {result.hpp_validated || 0} tervalidasi{result.variants_created ? <> · <span data-testid="fill-result-variants">{result.variants_created} varian/SKU baru dibuat (VARIAN_BARU)</span></> : null}</div>
      {result.scope !== 'bom' && <div data-testid="fill-result-extra">{result.materials_updated} material · {result.accounts_updated} rekening · {result.stores_updated} toko · {result.sku_prices_updated || 0} harga SKU · <span data-testid="fill-result-deactivated">{result.sku_deactivated || 0} SKU dinonaktifkan (sudah tidak dijual)</span> · {result.opening_stock_rows || 0} stok awal · {result.salaries_updated || 0} gaji · {result.models_weight_updated || 0} berat model</div>}
      {(result.bom_conflicts || []).length > 0 && <div className="text-amber-300">Konflik qty (kelompok belakangan menimpa): {result.bom_conflicts.join(' | ')}</div>}
    </GlassCard>
  );
}

export default function RahazaMasterFillModule({ token }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
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
      const r = await fetch(`/api/rahaza/master/fill-apply?scope=${scope}`, { method: 'POST', headers: authHeaders(token), body: fd });
      const j = await r.json();
      if (!r.ok) { toast.error(typeof j.detail === 'string' ? j.detail : j.detail?.message || 'Gagal'); return; }
      setResult(j);
      toast.success(`Diterapkan (${scope === 'bom' ? 'hanya BOM' : 'semua sheet'}): ${j.bom_lines_appended || 0} baris aksesoris di ${j.boms_touched || 0} BOM · HPP ${j.models_hpp_applied} model (${j.hpp_unvalidated || 0} belum tervalidasi). Unduh Laporan Sisa untuk kekurangan.`);
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
  const nApply = (t.materials || 0) + (t.accounts || 0) + (t.stores || 0) + (t.bom_lines || 0) + (t.models || 0) + (t.sku_prices || 0) + (t.sku_deactivate || 0) + (t.stock_rows || 0) + (t.salaries || 0);
  const bomWarn = preview?.warnings || [];
  const cats = Object.entries(preview?.bom_issue_counts || {});

  return (
    <div className="space-y-5" data-testid="fill-page">
      <PageHeader icon={FileSpreadsheet} eyebrow="Master · Pengisian Massal" title="Impor Harga · Satuan · Rekening · BOM"
        subtitle="Sesi go-live: unduh berkas FOKUS (hanya BOM · Varian Baru · Material yang masih kosong; semua baris sudah terisi, klien mengisi sel kuning saja) → unggah → pratinjau → Terapkan. BOM aksesoris per (model, varian) yang ada di berkas diganti utuh; model lain tidak disentuh. Varian yang disarankan sistem (sel biru) berasal dari nama bahan pembeda kelompok, bukan tebakan importir." />
      <div className="grid md:grid-cols-4 gap-4">
        <GlassCard className="p-5 space-y-3"><div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 1</div><h3 className="font-semibold text-sm">Unduh berkas isian</h3>
          <Button onClick={dlFokus} className="h-9 w-full" data-testid="fill-download-fokus"><Download className="w-3.5 h-3.5 mr-1.5" />{file ? 'Berkas FOKUS — sisa dari berkas ini' : 'Berkas FOKUS (yang perlu diisi saja)'}</Button>
          <p className="text-[11px] text-muted-foreground">Hanya yang masih perlu diisi: sheet VARIAN_BARU, BOM_AKSESORIS, MATERIAL. Semua baris sudah terisi — klien cukup mengisi sel <span className="rounded px-1 bg-[#FFF2CC] text-black">kuning</span>; sel <span className="rounded px-1 bg-[#DDEBF7] text-black">biru</span> = diisi otomatis (mis. varian dari nama bahan pembeda), cukup diperiksa. Kelompok yang seluruhnya sudah otomatis dipisah ke sheet BOM_OTOMATIS (ikut diterapkan saat diunggah balik). Kolom "yang_perlu_diisi" menyebut persis kekurangan tiap baris.</p>
          <Button onClick={dlHarga} variant="outline" className="h-8 w-full text-xs" data-testid="fill-download-harga-review"><Download className="w-3.5 h-3.5 mr-1.5" />Review harga aksesoris & kain (HPP)</Button>
          <Button onClick={dlGap} variant="outline" className="h-8 w-full text-xs" data-testid="fill-download-gap"><Download className="w-3.5 h-3.5 mr-1.5" />{file ? 'Berkas lengkap — SISA dari berkas ini' : 'Berkas lengkap (semua sheet, 1 berkas)'}</Button>
          <Button onClick={dl} variant="outline" className="h-8 w-full text-xs" data-testid="fill-download"><Download className="w-3.5 h-3.5 mr-1.5" />Template lengkap (semua material)</Button></GlassCard>
        <GlassCard className="p-5 space-y-3"><div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 2</div><h3 className="font-semibold text-sm">Unggah berkas terisi</h3>
          <input ref={inputRef} type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary/20 file:px-3 file:py-1.5 file:text-xs file:text-primary" data-testid="fill-file" />
          <p className="text-xs text-muted-foreground">Pratinjau muncul otomatis: baris siap / dilewati per kategori, varian tujuan, satuan dasar hasil konversi.</p></GlassCard>
        <GlassCard className="p-5 space-y-3"><div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 3</div><h3 className="font-semibold text-sm">Terapkan</h3>
          <Button onClick={() => doApply('bom')} disabled={!preview || busy || !(t.bom_lines > 0)} className="h-9 w-full" data-testid="fill-apply">
            <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />Terapkan (hanya BOM)</Button>
          <Button onClick={() => doApply('all')} variant="outline" disabled={!preview?.ok || busy || !nApply} className="h-8 w-full text-xs" data-testid="fill-apply-all">
            <Upload className="w-3.5 h-3.5 mr-1.5" />Terapkan semua sheet</Button></GlassCard>
        <GlassCard className="p-5 space-y-3"><div className="text-[10px] uppercase text-muted-foreground font-semibold">Langkah 4</div><h3 className="font-semibold text-sm">Laporan Sisa</h3>
          <Button onClick={dlLaporan} variant="outline" className="h-9 w-full" data-testid="fill-download-laporan"><ClipboardList className="w-3.5 h-3.5 mr-1.5" />Unduh LAPORAN_SISA_DA.xlsx</Button>
          <p className="text-[11px] text-muted-foreground">Kekurangan yang tidak diimpor: model tanpa SKU (+ sheet VARIAN_BARU), kelompok tanpa varian, satuan/kode tak valid, warna tak dikenal, material harga 0, HARGA_JUAL_SKU, berat/toko/rekening/gaji, HPP belum tervalidasi. {file ? 'Memakai berkas yang sedang diunggah.' : 'Tanpa berkas: hanya dari kondisi DB.'}</p></GlassCard>
      </div>
      {preview && (
        <div className="space-y-3" data-testid="fill-preview">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            <StatTile label="Baris BOM siap" value={`${t.bom_lines || 0} (${t.bom_groups || 0} kelompok · ${t.bom_models || 0} model)`} testId="fill-kpi-bom" />
            <StatTile label="BOM dilewati" value={`${t.bom_skipped || 0} catatan · ${t.bom_models_in_file || 0} model di berkas`} accent={t.bom_skipped ? 'warning' : 'success'} testId="fill-kpi-bom-skipped" />
            <StatTile label="Material berubah" value={t.materials} testId="fill-kpi-mat" />
            <StatTile label="Rekening · Toko · Berat" value={`${t.accounts || 0} · ${t.stores || 0} · ${t.models || 0}`} testId="fill-kpi-acc" />
            <StatTile label="Harga SKU · Nonaktif · Stok awal · Gaji" value={`${t.sku_prices || 0} · ${t.sku_deactivate || 0} · ${t.stock_rows || 0} · ${t.salaries || 0}`} testId="fill-kpi-extra" />
            <StatTile label={preview.ok ? (bomWarn.length ? `Siap · ${bomWarn.length} dilewati` : 'Siap') : `${preview.errors.length} masalah sheet lain`} value={preview.ok ? '✓' : '!'} accent={preview.ok ? (bomWarn.length ? 'warning' : 'success') : 'danger'} testId="fill-kpi-status" />
          </div>
          {cats.length > 0 && <GlassCard className="p-3 text-xs flex flex-wrap gap-2" data-testid="fill-issue-cats">{cats.map(([k, n]) => <span key={k} className="rounded-full border border-amber-500/30 px-2.5 py-1" data-testid={`fill-issue-cat-${k}`}>{CAT_LABEL[k] || k}: <b>{n}</b></span>)}</GlassCard>}
          {preview.errors.length > 0 && <GlassCard className="p-4 border border-rose-500/30 text-xs" data-testid="fill-errors"><div className="inline-flex items-center gap-2 text-rose-300 font-semibold mb-2"><AlertTriangle className="w-4 h-4" />Masalah di sheet selain BOM (tidak menghalangi "Terapkan hanya BOM")</div><ul className="list-disc pl-5 space-y-1 max-h-[30vh] overflow-auto">{preview.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></GlassCard>}
          {bomWarn.length > 0 && <GlassCard className="p-4 border border-amber-500/30 text-xs" data-testid="fill-warnings"><div className="inline-flex items-center gap-2 text-amber-500 font-semibold mb-2"><AlertTriangle className="w-4 h-4" />{bomWarn.length} catatan dilewati — masuk Laporan Sisa, tidak menghalangi penerapan sisanya</div><ul className="list-disc pl-5 space-y-1 max-h-[30vh] overflow-auto">{bomWarn.map((e, i) => <li key={i}>{e}</li>)}</ul></GlassCard>}
          {preview.materials.length > 0 && (
            <GlassCard className="p-0 overflow-hidden"><div className="overflow-auto max-h-[40vh]"><table className="w-full text-sm" data-testid="fill-mat-table">
              <thead className="sticky top-0 bg-[var(--card-surface)] text-[10px] uppercase text-muted-foreground"><tr className="border-b border-[var(--glass-border)]"><th className="py-2 px-2 text-left">Kode</th><th className="py-2 px-2 text-left">Nama</th><th className="py-2 px-2 text-left">Beli</th><th className="py-2 px-2 text-right">Isi</th><th className="py-2 px-2 text-right">Harga beli</th><th className="py-2 px-2 text-right">→ per {'{dasar}'}</th><th className="py-2 px-2 text-right">Sebelumnya</th></tr></thead>
              <tbody>{preview.materials.map((m) => <tr key={m.code} className="border-b border-[var(--glass-border)]" data-testid={`fill-mat-${m.code}`}><td className="py-1.5 px-2 font-mono text-xs">{m.code}</td><td className="py-1.5 px-2 text-xs">{m.name}</td><td className="py-1.5 px-2 text-xs">{m.buy_unit}</td><td className={tdN}>{m.pack_size} {m.base_unit}</td><td className={tdN}>{m.buy_price ? fmt(m.buy_price) : ''}</td><td className={`${tdN} text-emerald-300`}>{m.unit_cost != null ? `${fmt(m.unit_cost)}/${m.base_unit}` : ''}</td><td className={`${tdN} text-muted-foreground`}>{fmt(m.unit_cost_before)}</td></tr>)}</tbody>
            </table></div></GlassCard>
          )}
          {(preview.bom_lines || []).length > 0 && (
            <GlassCard className="p-0 overflow-hidden" data-testid="fill-bom-table"><div className="overflow-auto max-h-[40vh]"><table className="w-full text-sm">
              <thead className="sticky top-0 bg-[var(--card-surface)] text-[10px] uppercase text-muted-foreground"><tr className="border-b border-[var(--glass-border)]"><th className="py-2 px-2 text-left">Baris</th><th className="py-2 px-2 text-left">Model</th><th className="py-2 px-2 text-left">Varian tujuan</th><th className="py-2 px-2 text-left">Material</th><th className="py-2 px-2 text-right">Qty/pcs</th><th className="py-2 px-2 text-right">= satuan dasar</th><th className="py-2 px-2 text-left">Catatan</th></tr></thead>
              <tbody>{preview.bom_lines.map((b, i) => <tr key={i} className="border-b border-[var(--glass-border)]" data-testid={`fill-bom-row-${b.row}`}><td className="py-1.5 px-2 font-mono text-xs text-muted-foreground">{b.row}</td><td className="py-1.5 px-2 text-xs"><span className="font-mono">{b.model_code}</span> {b.model_name}</td><td className="py-1.5 px-2 text-xs">{b.target} <span className="text-muted-foreground">({b.target_skus} SKU)</span></td><td className="py-1.5 px-2 text-xs"><span className="font-mono">{b.code}</span> {b.name}</td><td className={tdN}>{b.qty} {b.unit}</td><td className={tdN}>{b.qty_base} {b.unit_base}</td><td className="py-1.5 px-2 text-[11px] text-muted-foreground">{b.note}</td></tr>)}</tbody>
            </table></div></GlassCard>
          )}
          {(preview.models || []).length > 0 && (
            <GlassCard className="p-4 text-xs space-y-1" data-testid="fill-models">{preview.models.map((m) => <div key={m.model_code}>Model <span className="font-mono">{m.model_code}</span> → berat {m.weight_gram} gram</div>)}</GlassCard>
          )}
          {(preview.accounts.length > 0 || preview.stores.length > 0 || (preview.sku_deactivate || []).length > 0) && (
            <GlassCard className="p-4 text-xs space-y-1" data-testid="fill-acc-store">
              {preview.accounts.map((a) => <div key={a.gl_account_code}><span className="font-mono">{a.gl_account_code}</span> → no. rek {a.account_number || '-'} a.n. {a.holder_name || '-'}</div>)}
              {preview.stores.map((s) => <div key={s.account_code}>Toko <span className="font-mono">{s.account_code}</span> → pencairan ke <span className="font-mono">{s.coa_cash_code}</span></div>)}
              {(preview.sku_deactivate || []).length > 0 && <div className="text-amber-300" data-testid="fill-deactivate-list">SKU akan dinonaktifkan ("{preview.sku_deactivate[0].teks}"): {preview.sku_deactivate.map((d) => d.sku).join(', ')}</div>}
            </GlassCard>
          )}
        </div>
      )}
      {result && <ResultCard result={result} />}
    </div>
  );
}
