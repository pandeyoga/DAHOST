/**
 * Biaya sample (Portal RnD › Costing & HPP › tab "Biaya sample").
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar = tabel (kartu ringkas di HP) + unduh Excel/CSV,
 * rincian = popup, form = FormPopup panjang, hapus lewat confirmDialog, warna token saja.
 * Hanya tampilan yang berubah — panggilan API, isian, dan hitungan server sama seperti sebelumnya.
 */
import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MoneyInput } from '@/components/ui/money-input';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Calculator, Plus, Trash2, Pencil, X, AlertTriangle, RefreshCw, Search } from 'lucide-react';
import { toast } from '../ui/sonner';
import { formatRupiah } from '@/lib/format';
import { apiDelete } from '@/lib/api';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import RnDUnitSelect, { UOM_STATUS } from './RnDUnitSelect';

const API = process.env.REACT_APP_BACKEND_URL || '';
const fmt = (n) => n != null ? formatRupiah(n) : '—';

const emptyAcc = { name: '', material_id: '', qty: 0, unit: 'm', unit_cost: 0 };

const emptyForm = {
  sample_code: '', style_id: '', style_name: '',
  fabric_items: [{ name: 'Main Fabric', material_id: '', qty: 1, unit: 'm', unit_cost: 0 }],
  trim_items: [],
  labor_cost: 0,
  overhead_cost: 0,
  notes: '',
};

const GRUP_BARIS = [['fabric_items', 'Bahan kain'], ['trim_items', 'Aksesoris / trim'], ['bom_lines', 'Baris BOM']];

/** Jumlah baris bahan yang punya peringatan satuan. */
const jumlahPeringatan = (c) => (c.uom_warnings || []).length;

/**
 * Dokumen lama (sebelum keputusan owner 6 Nov 2026) bisa menyimpan total yang masih memuat overhead.
 * Angka tersimpan tidak diubah; layar hanya memberi tanda supaya total tidak dibaca keliru.
 */
const totalMemuatOverhead = (c) => c.overhead_in_hpp !== false && Number(c.overhead_cost || 0) > 0
  && Math.abs(Number(c.total_cost || 0) - (Number(c.total_material_cost || 0) + Number(c.labor_cost || 0))) > 0.5;

/** Baris hasil hitung server: qty asli → qty pada satuan harga → biaya. */
function LineHint({ row }) {
  if (!row) return null;
  const st = UOM_STATUS[row.uom_status] || {};
  const warn = st.warn || row.price_source === 'unresolved';
  return (
    <div className={`col-span-full text-xs leading-snug ${warn ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}
      data-testid="costing-line-hint">
      {warn && <AlertTriangle className="mr-1 -mt-0.5 inline h-3 w-3" />}
      {row.qty} {row.unit} → <b>{row.qty_priced}</b> {row.price_unit} × {fmt(row.price_per_unit)} = <b>{fmt(row.total_cost)}</b>
      {row.uom_note ? ` · ${row.uom_note}` : (st.label ? ` · ${st.label}` : '')}
      {row.price_source === 'unresolved' && ' · harga belum ada, isi harga atau lengkapi Riset Material'}
    </div>
  );
}

export default function RnDCostingTab({ token }) {
  const h = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
  const [costings, setCostings] = useState([]);
  const [styles,   setStyles]   = useState([]);
  const [samples,  setSamples]  = useState([]);
  const [matOpts,  setMatOpts]  = useState([]);
  const [loading,  setLoading]  = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing,  setEditing]  = useState(null);
  const [form,     setForm]     = useState({ ...emptyForm });
  const [calc,     setCalc]     = useState(null);   // hasil hitung server (sadar satuan)
  const [detail,   setDetail]   = useState(null);
  const [cari,     setCari]     = useState('');

  const f = (k, v) => setForm(p => ({ ...p, [k]: v }));

  const fetchCostings = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/sample-costing`, { headers: h });
      if (res.ok) setCostings(await res.json());
    } catch { toast.error('Gagal memuat biaya sample'); }
    finally { setLoading(false); }
  };

  const fetchRef = async (path, setter) => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/${path}`, { headers: h });
      if (res.ok) {
        const data = await res.json();
        setter(Array.isArray(data) ? data : (data.items || []));
      }
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchCostings();
    fetchRef('styles', setStyles);
    fetchRef('sample-requests', setSamples);
    // 2026-11-08 (Standar UI/UX v2, perbaikan pemilih): bawaan server 500 baris, diurut aksesoris dulu →
    // ±600 kain aktif tidak pernah muncul di pilihan "Tautkan master". Minta sampai batas server (2000).
    fetchRef('material-options?limit=2000', setMatOpts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Pratinjau biaya dari SERVER (satuan dikonversi di sana) ────────────────
  const fetchCalc = useCallback(async (payload) => {
    try {
      const res = await fetch(`${API}/api/dewi/rnd/sample-costing/preview`, {
        method: 'POST', headers: h, body: JSON.stringify(payload),
      });
      if (res.ok) setCalc(await res.json());
    } catch { /* ignore */ }
  }, [token]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!showForm) return;
    const t = setTimeout(() => fetchCalc({
      fabric_items: form.fabric_items, trim_items: form.trim_items,
      labor_cost: form.labor_cost, overhead_cost: form.overhead_cost,
    }), 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.fabric_items, form.trim_items, form.labor_cost, form.overhead_cost, showForm, fetchCalc]);

  const setRow = (key, i, k, v) => {
    const items = [...(form[key] || [])];
    let row = { ...items[i], [k]: ['qty', 'unit_cost'].includes(k) ? Number(v) : v };
    if (k === 'material_id') {
      const m = matOpts.find(o => o.material_id === v);
      if (m) row = { ...row, name: m.name, unit: row.unit || m.base_unit };
    }
    items[i] = row;
    f(key, items);
  };
  const addRow = (key, seed) => f(key, [...(form[key] || []), { ...emptyAcc, ...seed }]);
  const removeRow = (key, i) => f(key, (form[key] || []).filter((_, j) => j !== i));

  const setStyleField = sid => {
    const sel = styles.find(s => s.id === sid);
    // 2026-11-07 (Tahap 5): sample milik style LAIN dilepas saat style diganti (dulu tertinggal ⇒ costing
    // menunjuk sample style A tetapi style B).
    setForm(p => {
      const cur = samples.find(x => x.sample_code === p.sample_code);
      const drop = cur && cur.style_id && sid && cur.style_id !== sid;
      return { ...p, style_id: sid, style_name: sel?.style_name || '',
               ...(drop ? { sample_code: '', sample_request_id: '' } : {}) };
    });
  };

  const setSampleField = sc => {
    const sel = samples.find(s => s.sample_code === sc);
    if (sel) setForm(p => ({ ...p, sample_code: sc, sample_request_id: sel.id, style_id: sel.style_id || p.style_id, style_name: sel.style_name || p.style_name }));
    else setForm(p => ({ ...p, sample_code: sc, sample_request_id: '' }));
  };
  // Pilihan sample = sample milik style terpilih (tanpa style: semua).
  const sampleChoices = form.style_id ? samples.filter(s => !s.style_id || s.style_id === form.style_id) : samples;

  const openEdit = rec => {
    setForm({
      sample_code: rec.sample_code || '',
      sample_request_id: rec.sample_request_id || '',
      style_id: rec.style_id || '',
      style_name: rec.style_name || '',
      fabric_items: rec.fabric_items?.length ? rec.fabric_items : [{ ...emptyAcc }],
      trim_items: rec.trim_items || [],
      labor_cost: rec.labor_cost || 0,
      overhead_cost: rec.overhead_cost || 0,
      notes: rec.notes || '',
    });
    setCalc(null);
    setEditing(rec.id);
    setDetail(null);
    setShowForm(true);
  };

  const openNew = () => {
    setEditing(null);
    setForm({ ...emptyForm });
    setCalc(null);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.sample_code && !form.sample_request_id) {
      toast.error('Pilih kode sample dulu');
      return;
    }
    try {
      const method = editing ? 'PUT' : 'POST';
      const url = editing
        ? `${API}/api/dewi/rnd/sample-costing/${editing}`
        : `${API}/api/dewi/rnd/sample-costing`;
      const res = await fetch(url, { method, headers: h, body: JSON.stringify(form) });
      const data = await res.json().catch(() => null);
      if (!res.ok) { toast.error(data?.detail || 'Gagal menyimpan biaya sample'); return; }
      toast.success(editing ? 'Biaya sample disimpan' : 'Biaya sample ditambahkan');
      if (data?.uom_warnings?.length) {
        toast.warning(`Satuan perlu dibereskan: ${data.uom_warnings.slice(0, 2).join(' | ')}`);
      }
      setShowForm(false);
      setEditing(null);
      setForm({ ...emptyForm });
      fetchCostings();
    } catch { toast.error('Gagal menyimpan biaya sample'); }
  };

  const handleDelete = async (c) => {
    const ok = await confirmDialog({
      title: 'Hapus biaya sample ini?',
      body: `Rincian biaya sample ${c.sample_code || ''} dihapus permanen.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      // 2026-11-06 (pola P6): helper lib/api melempar bila server menolak → pesan sukses hanya bila benar tersimpan
      await apiDelete(`/api/dewi/rnd/sample-costing/${c.id}`);
      toast.success('Biaya sample dihapus');
      setDetail(null);
      fetchCostings();
    } catch { toast.error('Gagal menghapus'); }
  };

  const rowsOf = (key) => (calc?.[key] || []);

  const q = cari.trim().toLowerCase();
  const baris = costings.filter(c => !q
    || `${c.sample_code || ''} ${c.style_name || ''}`.toLowerCase().includes(q));

  const renderRows = (key, testPrefix) => (
    <div className="space-y-2">
      {(form[key] || []).length > 0 && (
        <div className="hidden gap-2 text-xs text-muted-foreground sm:grid sm:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_72px_96px_104px_36px]">
          <span>Nama bahan</span><span>Master material</span><span>Qty</span><span>Satuan</span><span>Harga</span><span />
        </div>
      )}
      {(form[key] || []).map((it, i) => (
        <div key={i}
          className="grid grid-cols-2 gap-2 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_72px_96px_104px_36px] sm:border-0 sm:p-0">
          <Input value={it.name} onChange={e => setRow(key, i, 'name', e.target.value)}
            placeholder="Nama bahan" className="col-span-2 sm:col-span-1" data-testid={`${testPrefix}-name-${i}`} />
          <div className="col-span-2 min-w-0 sm:col-span-1">
            <SmartNativeSelect value={it.material_id || ''}
              onChange={e => setRow(key, i, 'material_id', e.target.value)}
              data-testid={`${testPrefix}-master-${i}`}
              className="w-full text-sm">
              <option value="">Tautkan master…</option>
              {matOpts.map(m => (
                <option key={m.material_id} value={m.material_id}>{m.code} — {m.name} ({m.base_unit})</option>
              ))}
            </SmartNativeSelect>
          </div>
          <Input type="number" value={it.qty} onChange={e => setRow(key, i, 'qty', e.target.value)}
            placeholder="Qty" className="text-right" data-testid={`${testPrefix}-qty-${i}`} />
          <RnDUnitSelect value={it.unit} onChange={e => setRow(key, i, 'unit', e.target.value)}
            testId={`${testPrefix}-unit-${i}`} />
          <MoneyInput decimals={2} value={it.unit_cost} onChange={e => setRow(key, i, 'unit_cost', e.target.value)}
            placeholder="Harga" data-testid={`${testPrefix}-price-${i}`} />
          <Button type="button" variant="ghost" size="icon" onClick={() => removeRow(key, i)}
            title="Hapus baris" aria-label="Hapus baris" className="justify-self-end">
            <X className="text-[hsl(var(--danger-text))]" /></Button>
          <LineHint row={rowsOf(key)[i]} />
        </div>
      ))}
    </div>
  );

  const kolom = [
    { kunci: 'kode', label: 'Kode sample', hp: 'judul', isi: (c) => (
      <span className="font-medium text-foreground" data-testid={`costing-card-${c.id}`}>{c.sample_code || '—'}</span>) },
    { kunci: 'style', label: 'Style', hp: 'keterangan', isi: (c) => c.style_name || '—' },
    { kunci: 'bahan', label: 'Biaya bahan', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmt(c.total_material_cost)}</span> },
    { kunci: 'jahit', label: 'Ongkos jahit', rata: 'kanan', isi: (c) => <span className="tabular-nums">{fmt(c.labor_cost)}</span> },
    { kunci: 'overhead', label: 'Overhead (di luar HPP)', rata: 'kanan', isi: (c) => <span className="tabular-nums text-muted-foreground">{fmt(c.overhead_cost)}</span> },
    { kunci: 'total', label: 'Total', rata: 'kanan', isi: (c) => (
      <span className="tabular-nums font-semibold text-foreground" title={totalMemuatOverhead(c) ? 'Data lama: total ini masih memuat overhead' : 'Biaya bahan + ongkos jahit'}>
        {fmt(c.total_cost)}{totalMemuatOverhead(c) && <span className="ml-1 text-xs font-normal text-[hsl(var(--warning-text))]">(termasuk overhead)</span>}
      </span>) },
    { kunci: 'satuan', label: 'Cek satuan', isi: (c) => (jumlahPeringatan(c) > 0
      ? <StatusBadge status="peringatan" tone="danger" label={`${jumlahPeringatan(c)} bermasalah`} />
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <div className="flex justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => openEdit(c)} title="Ubah" aria-label="Ubah"
          data-testid={`costing-edit-${c.id}`}><Pencil /></Button>
        <Button variant="ghost" size="icon-sm" onClick={() => handleDelete(c)} title="Hapus" aria-label="Hapus"
          data-testid={`costing-delete-${c.id}`}><Trash2 className="text-[hsl(var(--danger-text))]" /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="rnd-costing-tab" title="Biaya sample"
      subtitle="Rincian biaya per sample — qty dikonversi otomatis ke satuan harga material."
      actions={<Button onClick={openNew} data-testid="create-costing-btn"><Plus />Tambah biaya sample</Button>}
      filters={costings.length > 0 && (
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={e => setCari(e.target.value)} placeholder="Cari kode sample atau style"
            className="pl-8" data-testid="costing-search" />
        </div>
      )}
      tools={<>
        <TombolUnduh namaBerkas="biaya-sample" namaLembar="Biaya sample" baris={baris} testId="costing-unduh"
          kolom={[
            { label: 'Kode sample', nilai: (c) => c.sample_code || '' },
            { label: 'Style', nilai: (c) => c.style_name || '' },
            { label: 'Biaya bahan (Rp)', nilai: (c) => Number(c.total_material_cost || 0) },
            { label: 'Ongkos jahit (Rp)', nilai: (c) => Number(c.labor_cost || 0) },
            { label: 'Overhead di luar HPP (Rp)', nilai: (c) => Number(c.overhead_cost || 0) },
            { label: 'Total (Rp)', nilai: (c) => Number(c.total_cost || 0) },
            { label: 'Satuan bermasalah', nilai: (c) => jumlahPeringatan(c) },
            { label: 'Catatan', nilai: (c) => c.notes || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchCostings} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && costings.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat biaya sample…</p>
      ) : (
        <TabelData kolom={kolom} baris={baris} onKlikBaris={setDetail} testId="costing-table"
          kosong={<EmptyState icon={Calculator}
            title={costings.length ? 'Tidak ada biaya sample yang cocok' : 'Belum ada biaya sample'}
            description={costings.length ? 'Ubah kata pencarian.' : 'Catat biaya bahan dan ongkos jahit untuk sample pertama.'}
            action={!costings.length && <Button onClick={openNew}><Plus />Tambah biaya sample</Button>} />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} testId="costing-detail"
          judul={`Biaya sample ${detail.sample_code || ''}`.trim()}
          keterangan={detail.style_name || undefined}
          status={jumlahPeringatan(detail) > 0
            ? <StatusBadge status="peringatan" tone="danger" label={`${jumlahPeringatan(detail)} satuan bermasalah`} /> : null}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => openEdit(detail)}><Pencil />Ubah</Button>
            <Button size="sm" variant="destructive" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Biaya bahan">{fmt(detail.total_material_cost)}</BarisDetail>
            <BarisDetail label="Ongkos jahit">{fmt(detail.labor_cost)}</BarisDetail>
            <BarisDetail label="Overhead">{fmt(detail.overhead_cost)} <span className="text-muted-foreground">(informasi, tidak masuk HPP)</span></BarisDetail>
            <BarisDetail label="Total">
              <span className="font-semibold">{fmt(detail.total_cost)}</span>{' '}
              <span className="text-muted-foreground">
                {totalMemuatOverhead(detail) ? '(data lama: masih memuat overhead)' : '(biaya bahan + ongkos jahit)'}
              </span>
            </BarisDetail>
            {detail.notes && <BarisDetail label="Catatan">{detail.notes}</BarisDetail>}
          </dl>
          {GRUP_BARIS.map(([key, label]) => (detail[key]?.length > 0 && (
            <div key={key} className="space-y-2">
              <p className="text-sm font-semibold text-foreground">{label}</p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Bahan</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Qty satuan harga</TableHead>
                      <TableHead className="text-right">Harga</TableHead>
                      <TableHead className="text-right">Biaya</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail[key].map((it, i) => {
                      const st = UOM_STATUS[it.uom_status] || {};
                      return (
                        <TableRow key={i}>
                          <TableCell>
                            {it.name}
                            {st.warn && <span className="ml-1 text-xs text-[hsl(var(--danger-text))]">({st.label})</span>}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{it.qty} {it.unit}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {it.qty_priced != null && it.price_unit ? `${it.qty_priced} ${it.price_unit}` : '—'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{fmt(it.price_per_unit ?? it.unit_cost)}</TableCell>
                          <TableCell className="text-right tabular-nums font-medium">{fmt(it.total_cost ?? (it.qty * it.unit_cost))}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>
          )))}
          {jumlahPeringatan(detail) > 0 && (
            <Notice tone="danger" icon={AlertTriangle} title="Satuan yang perlu dibereskan">
              <ul className="list-disc space-y-0.5 pl-4">
                {detail.uom_warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </Notice>
          )}
        </DetailPopup>
      )}

      {/* Form (popup standar, panjang) */}
      <FormPopup open={showForm} onClose={() => setShowForm(false)} ukuran="panjang" onSimpan={handleSave}
        judul={editing ? 'Ubah biaya sample' : 'Tambah biaya sample'}
        keterangan="Biaya dihitung server: qty dikonversi ke satuan harga material."
        testId="costing-form">
        {/* Enter di kolom isian tidak langsung menyimpan: form ini banyak baris bahan (sama seperti sebelumnya). */}
        <div className="space-y-4" onKeyDown={e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault(); }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Kode sample" wajib>
              <SmartNativeSelect value={form.sample_code}
                onChange={e => setSampleField(e.target.value)}
                data-testid="costing-sample-select" className="w-full">
                <option value="">Pilih kode sample</option>
                {sampleChoices.map(s => <option key={s.id} value={s.sample_code}>{`${s.sample_code} — ${s.style_name || ''}`}</option>)}
              </SmartNativeSelect>
            </Isian>
            <Isian label="Style" petunjuk="Pilihan sample menyesuaikan style yang dipilih.">
              <SmartNativeSelect value={form.style_id} onChange={e => setStyleField(e.target.value)}
                data-testid="costing-style-select" className="w-full">
                <option value="">Pilih style</option>
                {styles.map(s => <option key={s.id} value={s.id}>{s.style_code} — {s.style_name}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>

          <Notice tone="info">
            Tautkan baris ke <b>master material</b> agar satuannya bisa dikonversi (mis. gram→kg, lusin→pcs,
            meter↔kg untuk kain lewat gramasi &amp; lebar). Kolom harga boleh dikosongkan — sistem memakai harga
            Riset Material / master material.
          </Notice>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Bahan kain</p>
              <Button type="button" variant="outline" size="sm" onClick={() => addRow('fabric_items', { unit: 'm' })}
                data-testid="add-fabric-row">
                <Plus />Tambah bahan
              </Button>
            </div>
            {renderRows('fabric_items', 'fabric')}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Aksesoris / trim</p>
              <Button type="button" variant="outline" size="sm" onClick={() => addRow('trim_items', { name: 'Label', unit: 'pcs' })}
                data-testid="add-trim-row">
                <Plus />Tambah aksesoris
              </Button>
            </div>
            {renderRows('trim_items', 'trim')}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Ongkos jahit (Rp)">
              <MoneyInput value={form.labor_cost}
                onChange={e => f('labor_cost', Number(e.target.value))} data-testid="costing-labor-input" />
            </Isian>
            <Isian label="Overhead (Rp)" petunjuk="Informasi saja — tidak masuk HPP maupun total.">
              <MoneyInput value={form.overhead_cost}
                onChange={e => f('overhead_cost', Number(e.target.value))} data-testid="costing-overhead-input" />
            </Isian>
          </div>

          {/* Total dari server */}
          <div className="space-y-1 rounded-[var(--radius-md)] border border-[var(--glass-border)] bg-[var(--card-surface)] p-3"
            data-testid="costing-total-panel">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">Biaya bahan (setelah konversi satuan)</span>
              <span className="text-sm font-semibold tabular-nums text-foreground">{fmt(calc?.total_material_cost)}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">Total estimasi (bahan + ongkos jahit)</span>
              <span className="text-lg font-semibold tabular-nums text-primary" data-testid="costing-total-value">
                {fmt(calc?.total_cost)}
              </span>
            </div>
            {!calc && <p className="text-xs text-muted-foreground">Menghitung dari server…</p>}
            {calc?.uom_warnings?.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-4 pt-1 text-xs text-[hsl(var(--danger-text))]"
                data-testid="costing-uom-warnings">
                {calc.uom_warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}
          </div>

          <Isian label="Catatan" htmlFor="costing-notes">
            <Textarea id="costing-notes" rows={2} value={form.notes} onChange={e => f('notes', e.target.value)} />
          </Isian>
        </div>
      </FormPopup>
    </PageLayout>
  );
}
