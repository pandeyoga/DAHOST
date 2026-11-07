/**
 * Pengeluaran Material (MI) — Portal Gudang.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (kepala tipis, penyaring satu baris), tabel ui/table + unduh Excel/CSV,
 * form Buat MI = FormPopup panjang, detail = DetailPopup (dulu Modal), status & sumber = StatusBadge berlabel Indonesia,
 * tolak lewat confirmDialog (dulu window.prompt), Setujui hijau / Tolak merah.
 */
import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { materialOptionLabel } from '@/lib/materialFields';
import { Plus, Trash2, CheckCircle2, XCircle, AlertTriangle, Package, Send, ScanLine, Scissors, ExternalLink, Info, RefreshCw } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
// Sprint A.1: UniversalScanner SSOT replaces inline BarcodeScanner
import UniversalScanner from './scanner/UniversalScanner';
import ScanResult from './scanner/ScanResult';
import { sameScanCode, scanFeedback } from './scanner/scanCode';
import useUomOptions from '@/hooks/useUomOptions';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from './docnum/DocNumberField';
import { UomSelect, UomConversionHint, baseUnitOf } from './uom/UomPicker';

// ── FASE H-6b (2026-08-17) — SATU DAFTAR UNTUK SEMUA ARUS KELUAR GUDANG ───────
// Sampai sesi lalu, layar ini hanya memuat MI manual/job produksi/Kirim CMT.
// Kain yang keluar lewat Portal Cutting memotong stok TANPA dokumen, jadi tidak
// pernah tampil di sini. Sekarang setiap baris membawa SUMBER-nya, dan sumber
// bisa disaring lewat chip (angkanya dari `GET /material-issues/sources`).
const SOURCE_META = {
  cutting: { label: 'Cutting', tone: 'primary' },
  vendor_shipment: { label: 'Kirim material CMT', tone: 'primary' },
  job: { label: 'Job produksi', tone: 'primary' },
  work_order: { label: 'Work order', tone: 'warning' },
  manual: { label: 'Manual', tone: 'muted' },
};

function SourceBadge({ mi }) {
  const key = mi.source_key || 'manual';
  const m = SOURCE_META[key] || SOURCE_META.manual;
  return <StatusBadge status={key} label={mi.source_label || m.label} tone={m.tone} testId={`mi-source-${mi.mi_number}`} />;
}

/** Acuan dokumen per sumber — supaya kolom "Acuan" tidak pernah kosong. */
function refOf(mi) {
  if (mi.source_key === 'cutting') return mi.cutting_order_number || 'Cutting';
  if (mi.source_key === 'vendor_shipment') return mi.vendor_shipment_number || mi.vendor_name || 'Kirim CMT';
  if (mi.source_key === 'job') return mi.job_number_snapshot || 'Job produksi';
  if (mi.source_key === 'work_order') return mi.wo_number_snapshot || 'Work Order';
  return mi.wo_number_snapshot || '';
}

const STATUS_META = {
  draft:            { label: 'Draf', tone: 'muted' },
  pending_approval: { label: 'Menunggu persetujuan', tone: 'warning' },
  rejected:         { label: 'Ditolak', tone: 'danger' },
  issued:           { label: 'Sudah keluar', tone: 'success' },
  cancelled:        { label: 'Dibatalkan', tone: 'muted' },
};
const JENIS_MATERIAL = { fabric: 'Kain', yarn: 'Benang', accessory: 'Aksesoris', packaging: 'Kemasan', interlining: 'Kain keras', fg: 'Produk jadi' };
const fmtQty = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 3 });

function StatusMI({ status }) {
  const s = STATUS_META[status] || STATUS_META.draft;
  return <StatusBadge status={status} label={s.label} tone={s.tone} />;
}

export default function RahazaMaterialIssueModule({ token, onNavigate }) {
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState([]);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterBuilding, setFilterBuilding] = useState('');
  const [filterSource, setFilterSource] = useState('');   // FASE H-6b
  const [srcMeta, setSrcMeta] = useState({ sources: [], all_count: 0 });
  const [buildings, setBuildings] = useState([]);
  const [detail, setDetail] = useState(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  // SESI #19 — kebijakan penomoran Pengeluaran Material (Otomatis/Manual).
  const numPolicy = useDocNumberPolicy('rahaza_material_issues.mi_number', token);
  const [miNumber, setMiNumber] = useState('');
  const [showScanner, setShowScanner] = useState(false);
  const [scanTarget, setScanTarget] = useState(null); // { miId, itemIdx }
  const [materials, setMaterials] = useState([]);

  // Satuan sah untuk semua baris MI yang sedang dibuka (batch 1 request)
  const { options: uomOpts } = useUomOptions((detail?.items || []).map(it => it.material_id));

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
      if (filterBuilding) params.set('building_id', filterBuilding);
      if (filterSource) params.set('source', filterSource);   // FASE H-6b
      const qs = params.toString() ? `?${params.toString()}` : '';
      const r = await fetch(`/api/rahaza/material-issues${qs}`, { headers });
      if (r.ok) setList(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, filterStatus, filterBuilding, filterSource]);

  // FASE H-6b — rekap jumlah dokumen per sumber (angka pada chip penyaring).
  const fetchSources = useCallback(async () => {
    const p = new URLSearchParams();
    if (filterStatus) p.set('status', filterStatus);
    const r = await fetch(`/api/rahaza/material-issues/sources${p.toString() ? `?${p}` : ''}`, { headers });
    if (r.ok) setSrcMeta(await r.json());
  }, [token, filterStatus]);

  useEffect(() => { fetchList(); }, [fetchList]);
  useEffect(() => { fetchSources(); }, [fetchSources]);
  useEffect(() => {
    const h = { Authorization: `Bearer ${token}` };
    Promise.all([
      Promise.resolve([]),  // FASE 5: WO engine lama diarsip — MI draft kini auto dari job internal
      // 2026-11-02 — No.18(a): daftar lokasi = SSOT lokasi PENYIMPANAN (dulu semua
      // rahaza_locations, termasuk KTR-PST/KTR-ADM/KTR-HRD/KTR-MKT → MI kain bisa
      // mengambil dari "Ruang Admin" dan meninggalkan baris minus di sana).
      fetch('/api/rahaza/storage-locations', { headers: h }).then(r => r.ok ? r.json() : []),
      fetch('/api/rahaza/materials', { headers: h }).then(r => r.ok ? r.json() : []),
      fetch(`${process.env.REACT_APP_BACKEND_URL}/api/wms/buildings`, { headers: h }).then(r => r.ok ? r.json() : []),
    ]).then(([w, l, m, b]) => {
      // lokasi karantina (QC) bukan tempat mengambil material produksi
      setLocations((Array.isArray(l) ? l : []).filter(x => x.role !== 'karantina' && x.storage_role !== 'karantina'));
      setMaterials(m || []);
      setBuildings(Array.isArray(b) ? b : []);
    });
  }, [token]);

  // 2026-11-06 (audit layar scan Gudang): hasil scan tampil di dekat yang diisi — di bawah material baris
  // itu (scan per baris) atau di bawah tombol scan atas. `idx` null = tombol scan atas.
  const [scanRes, setScanRes] = useState(null);   // { idx, tone, title, detail }
  useEffect(() => { setScanRes(null); }, [detail?.id]);

  // U3 — Barcode scan handler: match scanned code to material
  const handleBarcodeScan = useCallback((code) => {
    setShowScanner(false);
    const rowIdx = scanTarget?.itemIdx;
    const at = rowIdx !== undefined ? rowIdx : null;
    // 2026-11-02 (Paket 3a): aturan kode scan bersama (tanpa beda huruf, prefix scanner dibuang)
    const mat = materials.find(m => sameScanCode(m.code, code) || m.id === code);
    if (!mat) {
      scanFeedback('error');
      setScanRes({ idx: at, tone: 'error', title: `Ditolak: kode "${code}" tidak ada di master material`,
        detail: 'Periksa labelnya, atau pilih material lewat master.' });
      setScanTarget(null);
      return;
    }
    // If scanTarget has miId+itemIdx, update that specific MI item
    if (scanTarget && detail) {
      const updItems = [...(detail.items || [])];
      if (scanTarget.itemIdx !== undefined) {
        updItems[scanTarget.itemIdx] = { ...updItems[scanTarget.itemIdx], material_id: mat.id, material_code: mat.code, material_name: mat.name };
      }
      setDetail(prev => ({ ...prev, items: updItems }));
    }
    if (at !== null) {
      scanFeedback('ok');
      setScanRes({ idx: at, tone: 'ok', title: `Terisi: ${mat.code} · ${mat.name}`,
        detail: 'Belum tersimpan — tekan "Simpan qty, satuan & lokasi".' });
    } else {
      // Scan dari tombol atas tidak mengganti baris mana pun: kabarkan apakah material ini ada di daftar MI.
      const found = (detail?.items || []).findIndex(it => it.material_id === mat.id);
      scanFeedback(found >= 0 ? 'ok' : 'error');
      setScanRes(found >= 0
        ? { idx: null, tone: 'ok', title: `Ada di daftar: ${mat.code} · ${mat.name}`, detail: `Baris ${found + 1}.` }
        : { idx: null, tone: 'error', title: `Ditolak: ${mat.code} tidak ada di daftar MI ini`,
            detail: 'Untuk mengganti material sebuah baris, pakai ikon scan di baris itu.' });
    }
    setScanTarget(null);
  }, [materials, detail, scanTarget]);

  // FASE 5: openDraft/createDraft (draft-from-wo) dihapus.

  const openDetail = async (mi) => {
    const r = await fetch(`/api/rahaza/material-issues/${mi.id}`, { headers });
    if (r.ok) setDetail(await r.json());
  };

  // eslint-disable-next-line no-unused-vars -- PROD-01: legacy dimatikan, disimpan untuk riwayat
  const confirmMI = async (mi) => {
    // DEPRECATED: Legacy direct confirm (kept for old draft MIs)
    // New flow: submit → approve
    const missing = (mi.items || []).filter(it => !it.location_id);
    if (missing.length > 0) {
      toast.warning(`${missing.length} item belum punya lokasi. Edit MI untuk set lokasi per item.`);
      return;
    }
    if (!(await confirmDialog({
      title: `Konfirmasi pengeluaran MI ${mi.mi_number}?`,
      body: 'Stok akan dikurangi langsung tanpa persetujuan.',
      confirmLabel: 'Konfirmasi',
    }))) return;
    const r = await fetch(`/api/rahaza/material-issues/${mi.id}/confirm`, { method: 'POST', headers, body: JSON.stringify({}) });
    if (!r.ok) {
      let msg = `Gagal confirm (HTTP ${r.status})`;
      try {
        const err = await r.json();
        if (err.detail?.message) msg = err.detail.message + (err.detail.shortages ? `\nKurang di: ${JSON.stringify(err.detail.shortages)}` : '');
        else if (typeof err.detail === 'string') msg = err.detail;
      } catch { /* ignore */ }
      toast.error(msg);
      return;
    }
    fetchList();
    openDetail(mi);
  };

  // Sprint 2.2: Submit MI for approval
  const submitMI = async (mi) => {
    // 2026-09-24: lokasi kosong diisi otomatis backend (stok terbanyak / gudang bawaan) — tidak memblokir.
    const missing = (mi.items || []).filter(it => !it.location_id);
    const note = missing.length > 0 ? `${missing.length} baris tanpa lokasi akan diisi otomatis dari gudang bawaan.` : undefined;
    if (!(await confirmDialog({
      title: `Ajukan MI ${mi.mi_number} untuk persetujuan?`,
      body: note,
      confirmLabel: 'Ajukan',
    }))) return;
    const r = await fetch(`/api/rahaza/material-issues/${mi.id}/submit`, { method: 'POST', headers });
    if (!r.ok) {
      let msg = `Gagal submit (HTTP ${r.status})`;
      try {
        const err = await r.json();
        if (typeof err.detail === 'string') msg = err.detail;
      } catch { /* ignore */ }
      toast.error(msg);
      return;
    }
    fetchList();
    openDetail(mi);
  };

  // Sprint 2.2: Approve MI (and execute issue)
  const approveMI = async (mi) => {
    if (!(await confirmDialog({
      title: `Setujui dan keluarkan MI ${mi.mi_number}?`,
      body: 'Stok akan dikurangi.',
      confirmLabel: 'Setujui',
    }))) return;
    const r = await fetch(`/api/rahaza/material-issues/${mi.id}/approve`, { method: 'POST', headers, body: JSON.stringify({}) });
    if (!r.ok) {
      let msg = `Gagal approve (HTTP ${r.status})`;
      try {
        const err = await r.json();
        if (err.detail?.message) msg = err.detail.message + (err.detail.shortages ? `\nKurang di: ${JSON.stringify(err.detail.shortages)}` : '');
        else if (typeof err.detail === 'string') msg = err.detail;
      } catch { /* ignore */ }
      toast.error(msg);
      return;
    }
    fetchList();
    openDetail(mi);
  };

  // Sprint 2.2: Reject MI
  const rejectMI = async (mi) => {
    const reason = await confirmDialog({ title: `Tolak MI ${mi.mi_number}?`, confirmLabel: 'Tolak', danger: true,
      input: { label: 'Alasan penolakan' } });
    if (!reason || typeof reason !== 'string') return;
    const r = await fetch(`/api/rahaza/material-issues/${mi.id}/reject`, { method: 'POST', headers, body: JSON.stringify({ reason }) });
    if (!r.ok) {
      toast.error(`Gagal menolak MI (HTTP ${r.status})`);
      return;
    }
    fetchList();
    openDetail(mi);
  };

  const cancelMI = async (mi) => {
    if (!(await confirmDialog({
      title: `Batalkan MI ${mi.mi_number}?`,
      confirmLabel: 'Batalkan MI',
      cancelLabel: 'Kembali',
      danger: true,
    }))) return;
    await fetch(`/api/rahaza/material-issues/${mi.id}/cancel`, { method: 'POST', headers });
    fetchList();
    if (detail?.id === mi.id) openDetail(mi);
  };

  const deleteMI = async (mi) => {
    if (!(await confirmDialog({
      title: `Hapus MI ${mi.mi_number}?`,
      body: 'Dokumen ini akan dihapus.',
      confirmLabel: 'Hapus',
      danger: true,
    }))) return;
    await fetch(`/api/rahaza/material-issues/${mi.id}`, { method: 'DELETE', headers });
    fetchList();
    setDetail(null);
  };

  const updateDetailItemLocation = (itemId, locId) => {
    setDetail(d => ({
      ...d,
      items: d.items.map(it => it.id === itemId ? { ...it, location_id: locId } : it),
    }));
  };

  // ROADMAP P1 (2026-08-05) — qty & SATUAN per baris bisa diubah saat draft.
  // Backend (`_norm_mi_items`) menerima `qty_uom` dan menyimpan `qty_required`
  // selalu dalam satuan dasar (INV-UOM-2), jadi layar cukup mengirim apa yang
  // diketik operator + satuannya.
  const updateDetailItem = (itemId, patch) => {
    setDetail(d => ({
      ...d,
      items: d.items.map(it => it.id === itemId ? { ...it, ...patch } : it),
    }));
  };

  const saveDetailItems = async () => {
    if (!detail || detail.status !== 'draft') return;
    setSaving(true);
    setFormError('');
    try {
      const r = await fetch(`/api/rahaza/material-issues/${detail.id}`, {
        method: 'PUT', headers,
        body: JSON.stringify({
          items: detail.items.map(it => {
            const base = baseUnitOf(uomOpts[it.material_id], it.unit);
            const chosen = (it._uom || it.input_uom || base || '').toLowerCase();
            const row = {
              id: it.id, material_id: it.material_id,
              qty_required: Number(it._qty_input ?? it.input_qty ?? it.qty_required) || 0,
              location_id: it.location_id, notes: it.notes,
            };
            if (chosen && base && chosen !== base) row.qty_uom = chosen;
            return row;
          }),
        }),
      });
      const data = await r.json().catch(() => null);
      if (!r.ok) { setFormError(data?.detail || `Gagal menyimpan (HTTP ${r.status})`); return; }
      setDetail(data);
    } finally { setSaving(false); }
  };

  // ── FASE H-2 (2026-08-16) — PINTU MASUK "BUAT MI" ─────────────────────────
  // Sebelum ini layar Pengeluaran Material hanya bisa MELIHAT & menyetujui:
  // tidak ada satu pun tombol membuat MI. Satu-satunya jalur create dari UI
  // adalah endpoint maklon lama yang di backend sudah ditandai `deprecated`.
  // Akibatnya arus keluar gudang yang TIDAK lahir dari job produksi internal
  // (sampel, permak, pemakaian internal) tidak punya dokumen sama sekali —
  // stok berkurang di kenyataan tanpa berkurang di sistem.
  //
  // Dua jalur, sengaja dibedakan:
  //   · "Dari job produksi" — kebutuhan DIHITUNG dari BOM job (tidak diketik),
  //     sehingga qty-nya mustahil beda dengan rencana produksi.
  //   · "Manual dari master" — untuk kebutuhan di luar job. Materialnya WAJIB
  //     dipilih dari master (aturan F14): nama material yang diketik bebas
  //     membuat laporan pemakaian bahan salah diam-diam.
  const [showCreate, setShowCreate] = useState(false);
  const [createTab, setCreateTab] = useState('job');
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState('');
  const [createLoc, setCreateLoc] = useState('');
  const [manualRows, setManualRows] = useState([{ material_id: '', qty: '', uom: '', location_id: '' }]);
  const [createNotes, setCreateNotes] = useState('');
  const [createErr, setCreateErr] = useState('');
  const [creating, setCreating] = useState(false);

  const { options: manualUom } = useUomOptions(manualRows.map(r => r.material_id).filter(Boolean));
  const issuableMaterials = materials.filter(m => m.type !== 'fg');

  const openCreate = async () => {
    setShowCreate(true); setCreateErr('');
    try {
      const r = await fetch('/api/production-jobs?business_type=internal', { headers });
      if (r.ok) {
        const d = await r.json();
        setJobs(Array.isArray(d) ? d : (d.items || []));
      }
    } catch { /* daftar job opsional — jalur manual tetap bisa dipakai */ }
  };

  const closeCreate = () => {
    setShowCreate(false); setCreateErr(''); setJobId('');
    setManualRows([{ material_id: '', qty: '', uom: '', location_id: '' }]);
    setCreateNotes('');
    setMiNumber('');
  };

  const readErr = async (r, fallback) => {
    try {
      const e = await r.json();
      if (typeof e.detail === 'string') return e.detail;
      if (e.detail?.message) return e.detail.message;
      return fallback;
    } catch { return fallback; }
  };

  const createFromJob = async () => {
    if (!jobId) { setCreateErr('Pilih job produksi internal dulu.'); return; }
    setCreating(true); setCreateErr('');
    try {
      const r = await fetch('/api/rahaza/material-issues/draft-from-job', {
        method: 'POST', headers,
        body: JSON.stringify({ job_id: jobId, default_location_id: createLoc || null }),
      });
      if (!r.ok) { setCreateErr(await readErr(r, `Gagal membuat draft (HTTP ${r.status})`)); return; }
      const mi = await r.json();
      // Backend memakai kembali MI yang sudah ada untuk job yang sama (satu job
      // satu MI). Kalau itu terjadi, KATAKAN — dulu layar langsung membuka dokumen
      // lama tanpa pesan, dan pemakai yakin baru saja membuat draft baru lalu
      // menunggu barang yang tidak pernah diminta ulang.
      if (list.some(x => x.mi_number === mi.mi_number)) {
        setCreateErr(`MI untuk job ini SUDAH ADA: ${mi.mi_number} (status ${mi.status}). `
          + 'Tidak dibuat dokumen kedua — tutup jendela ini dan buka dokumennya dari daftar.');
        await fetchList();
        return;
      }
      closeCreate();
      await fetchList();
      openDetail(mi);
    } finally { setCreating(false); }
  };

  const createManual = async () => {
    const items = manualRows
      .filter(r => r.material_id && Number(r.qty) > 0)
      .map(r => {
        const mat = materials.find(m => m.id === r.material_id) || {};
        const base = baseUnitOf(manualUom[r.material_id], mat.unit);
        const chosen = (r.uom || base || '').toLowerCase();
        const row = { material_id: r.material_id, qty_required: Number(r.qty),
          location_id: r.location_id || null };
        if (chosen && base && chosen !== base) row.qty_uom = chosen;
        return row;
      });
    if (items.length === 0) {
      setCreateErr('Minimal 1 baris dengan material dan jumlah lebih dari 0.');
      return;
    }
    // 2026-11-02 — No.18(a): baris yang diketik pengguna WAJIB menunjuk lokasi ambil.
    if (items.some(it => !it.location_id)) {
      setCreateErr('Pilih lokasi ambil untuk setiap baris material.');
      return;
    }
    setCreating(true); setCreateErr('');
    try {
      const r = await fetch('/api/rahaza/material-issues', {
        method: 'POST', headers,
        body: JSON.stringify({ items, notes: createNotes,
          ...docNumberPayload(numPolicy, 'mi_number', miNumber) }),
      });
      if (!r.ok) { setCreateErr(await readErr(r, `Gagal menyimpan (HTTP ${r.status})`)); return; }
      const mi = await r.json();
      closeCreate();
      await fetchList();
      openDetail(mi);
    } finally { setCreating(false); }
  };

  const setManualRow = (idx, patch) => setManualRows(
    rows => rows.map((r, i) => i === idx ? { ...r, ...patch } : r));

  if (loading && list.length === 0) return (<div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>);

  const tglMI = (mi) => (mi.created_at ? formatDateID(mi.created_at) : '—');
  const selPil = 'w-full';
  const chips = [
    { key: '', label: 'Semua', count: srcMeta.all_count ?? 0 },
    ...(srcMeta.sources || []).map((s) => ({ key: s.key, label: s.label, count: s.count, icon: s.key === 'cutting' ? Scissors : undefined })),
  ];

  return (
    <PageLayout testId="rahaza-mi-page" title="Pengeluaran Material"
      subtitle="Satu daftar semua bahan keluar gudang: MI manual, job produksi, kirim ke CMT, dan kain yang dipotong di Portal Cutting."
      actions={<Button onClick={openCreate} data-testid="mi-create-btn"><Plus /> Buat MI</Button>}
      filters={<>
        {/* FASE H-6b — penyaring SUMBER arus keluar; angka dari `GET /material-issues/sources`. Pil berangka 0 tetap
            tampil supaya jelas pintunya ada tapi kosong. */}
        <div className="w-full sm:w-auto" data-testid="mi-source-chips">
          <FilterChips value={filterSource} onChange={setFilterSource} options={chips} hideWhenEmpty={false}
            testId="mi-src" ariaLabel="Sumber arus keluar" />
        </div>
        <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className={selPil}
          wrapperClassName="w-full sm:w-48" searchable={false} aria-label="Status" data-testid="mi-filter-status">
          <option value="">Semua status</option>
          {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
        {buildings.length > 0 && (
          <SmartNativeSelect value={filterBuilding} onChange={e => setFilterBuilding(e.target.value)} className={selPil}
            wrapperClassName="w-full sm:w-48" aria-label="Gedung" data-testid="mi-filter-building" title="Saring berdasarkan gedung WMS">
            <option value="">Semua gedung</option>
            {buildings.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </SmartNativeSelect>
        )}
        {/* Alat di akhir baris penyaring (bukan slot tools): di HP 390 px Toolbar bersama memeras penyaring. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {onNavigate && (
            <Button variant="outline" onClick={() => onNavigate('cutting-orders')} data-testid="mi-open-cutting">
              <ExternalLink /> Portal Cutting
            </Button>
          )}
          <TombolUnduh namaBerkas="pengeluaran-material" namaLembar="Pengeluaran material" baris={list} testId="mi-unduh"
            kolom={[
              { label: 'No. MI', nilai: (mi) => mi.mi_number },
              { label: 'Sumber', nilai: (mi) => mi.source_label || (SOURCE_META[mi.source_key] || SOURCE_META.manual).label },
              { label: 'Acuan', nilai: (mi) => refOf(mi) || 'Manual' },
              { label: 'Jumlah item', nilai: (mi) => Number(mi.item_count || 0) },
              { label: 'Material pertama', nilai: (mi) => mi.first_material_code || '' },
              { label: 'Total qty', nilai: (mi) => Number(mi.total_required || 0) },
              { label: 'Satuan', nilai: (mi) => mi.first_unit || '' },
              { label: 'Status', nilai: (mi) => (STATUS_META[mi.status] || STATUS_META.draft).label },
              { label: 'Tanggal', nilai: (mi) => tglMI(mi) },
            ]} />
          <Button variant="outline" size="icon" onClick={() => { fetchList(); fetchSources(); }} disabled={loading}
            title="Muat ulang" aria-label="Muat ulang" data-testid="mi-refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </>}>
      <GlassCard className="p-0 overflow-hidden">
        {list.length === 0 ? (
          <EmptyState icon={Package}
            title={filterSource ? `Belum ada arus keluar dari sumber "${SOURCE_META[filterSource]?.label || filterSource}"` : 'Belum ada pengeluaran material'}
            description="MI draf dibuat otomatis saat job produksi internal dibuat — gudang tinggal konfirmasi. MI manual juga bisa dibuat di sini, dan dokumen Cutting terbit sendiri saat progres potong dilaporkan."
            action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              {filterSource && (
                <Button size="sm" variant="outline" onClick={() => setFilterSource('')} data-testid="mi-empty-cta-clear-source">
                  Tampilkan semua sumber
                </Button>
              )}
              <Button size="sm" onClick={openCreate} data-testid="mi-empty-cta-create">
                <Plus /> Buat MI
              </Button>
              {onNavigate && (
                <Button size="sm" variant="outline" onClick={() => onNavigate('prod-work-orders')} data-testid="mi-empty-cta-wo" >
                  Buka work order
                </Button>
              )}
            </div>
            } />
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>No. MI</TableHead>
                  <TableHead>Sumber</TableHead>
                  <TableHead>Acuan</TableHead>
                  <TableHead>Item</TableHead>
                  <TableHead className="text-right">Total qty</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Tanggal</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map(mi => (
                  <TableRow key={mi.id} data-testid={`mi-row-${mi.mi_number}`} className="cursor-pointer" onClick={() => openDetail(mi)}>
                    <TableCell className="whitespace-nowrap">
                      <Button variant="link" className="h-auto p-0 font-medium" onClick={(e) => { e.stopPropagation(); openDetail(mi); }}
                        title="Lihat rincian" data-testid={`mi-detail-${mi.mi_number}`}>{mi.mi_number}</Button>
                    </TableCell>
                    <TableCell><SourceBadge mi={mi} /></TableCell>
                    <TableCell className="text-sm">{refOf(mi) || <span className="text-muted-foreground">Manual</span>}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {mi.item_count} item
                      {mi.first_material_code && <span className="block text-xs">{mi.first_material_code}</span>}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right font-medium tabular-nums">
                      {fmtQty(mi.total_required)}
                      {mi.first_unit && <span className="ml-1 text-xs font-normal text-muted-foreground">{mi.first_unit}</span>}
                    </TableCell>
                    <TableCell><StatusMI status={mi.status} /></TableCell>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">{tglMI(mi)}</TableCell>
                    <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="inline-flex items-center gap-1">
                        {/* FASE H-6b: dokumen Cutting tidak punya tombol Setujui/Hapus —
                            kainnya sudah keluar; menyetujuinya akan memotong stok dua kali. */}
                        {mi.source_key === 'cutting' && onNavigate && (
                          <Button variant="ghost" size="icon-sm" onClick={() => onNavigate('cutting-orders')}
                            title={`Buka order cutting ${mi.cutting_order_number || ''}`} aria-label="Buka order cutting"
                            data-testid={`mi-open-cutting-${mi.mi_number}`}>
                            <Scissors />
                          </Button>
                        )}
                        {mi.status === 'draft' && (
                          <>
                            <Button size="sm" variant="outline" onClick={() => submitMI(mi)} title="Ajukan persetujuan" data-testid={`mi-submit-${mi.mi_number}`}><Send />Ajukan</Button>
                            <Button variant="ghost" size="icon-sm" onClick={() => deleteMI(mi)} title="Hapus" aria-label="Hapus"><Trash2 /></Button>
                          </>
                        )}
                        {mi.status === 'pending_approval' && (
                          <>
                            <Button size="sm" variant="success" onClick={() => approveMI(mi)} data-testid={`mi-approve-${mi.mi_number}`}><CheckCircle2 />Setujui</Button>
                            <Button size="sm" variant="destructive" onClick={() => rejectMI(mi)} data-testid={`mi-reject-${mi.mi_number}`}><XCircle />Tolak</Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </GlassCard>

      {/* FASE H-2 — form Buat MI (dari job BOM / manual dari master) = FormPopup panjang */}
      <FormPopup open={showCreate} onClose={closeCreate} ukuran="panjang" judul="Buat pengeluaran material"
        keterangan="MI dibuat sebagai draf; stok baru berkurang setelah disetujui."
        onSimpan={createTab === 'job' ? createFromJob : createManual} menyimpan={creating} galat={createErr}
        labelSimpan="Buat draf MI" testId="mi-create-form">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Cara membuat MI">
          <Button type="button" size="sm" variant={createTab === 'job' ? 'default' : 'outline'} aria-pressed={createTab === 'job'}
            onClick={() => setCreateTab('job')} data-testid="mi-create-tab-job">Dari job produksi</Button>
          <Button type="button" size="sm" variant={createTab === 'manual' ? 'default' : 'outline'} aria-pressed={createTab === 'manual'}
            onClick={() => setCreateTab('manual')} data-testid="mi-create-tab-manual">Manual dari master</Button>
        </div>

        {createTab === 'job' ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Kebutuhan material dihitung dari BOM job (kain + aksesoris × qty job) — tidak diketik, sehingga tidak mungkin
              berbeda dengan rencana produksi. Hanya job <b>internal</b>: material job maklon milik klien, bukan stok DA.
            </p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Isian label="Job produksi internal" wajib>
                <SmartNativeSelect value={jobId} onChange={e => setJobId(e.target.value)} className="w-full" data-testid="mi-create-job-select">
                  <option value="">Pilih job</option>
                  {jobs.map(j => (
                    <option key={j.id} value={j.id}>
                      {j.job_number} · {j.po_number || '-'} · {j.status}
                    </option>
                  ))}
                </SmartNativeSelect>
              </Isian>
              <Isian label="Lokasi ambil" petunjuk="Bawaan untuk semua baris; bisa diubah nanti.">
                <SmartNativeSelect value={createLoc} onChange={e => setCreateLoc(e.target.value)} className="w-full" data-testid="mi-create-location-select">
                  <option value="">Tentukan per baris nanti</option>
                  {locations.map(l => <option key={l.id} value={l.id}>{`${l.code}${l.name ? ` · ${l.name}` : ''}`}</option>)}
                </SmartNativeSelect>
              </Isian>
            </div>
            {jobs.length === 0 && (
              <Notice tone="warning" testId="mi-create-no-jobs">
                Belum ada job produksi internal. Buat PO internal & job-nya dulu di Portal Produksi, atau pakai “Manual dari master”.
              </Notice>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Material wajib dipilih dari master — barang jadi tidak ikut, karena yang keluar ke produksi adalah bahan.
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Material</TableHead>
                    <TableHead className="text-right">Jumlah</TableHead>
                    <TableHead>Satuan</TableHead>
                    <TableHead>Lokasi ambil</TableHead>
                    <TableHead><span className="sr-only">Hapus</span></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {manualRows.map((row, idx) => {
                    const mat = materials.find(m => m.id === row.material_id) || {};
                    return (
                      <TableRow key={idx}>
                        <TableCell className="min-w-[14rem]">
                          <SmartNativeSelect value={row.material_id}
                            onChange={e => setManualRow(idx, { material_id: e.target.value, uom: '' })}
                            className="h-8 w-full text-sm" aria-label="Material" data-testid={`mi-manual-material-${idx}`}>
                            <option value="">Pilih material</option>
                            {issuableMaterials.map(m => (
                              <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>
                            ))}
                          </SmartNativeSelect>
                        </TableCell>
                        <TableCell className="text-right">
                          <Input type="number" min="0" step="0.0001" value={row.qty} aria-label="Jumlah"
                            onChange={e => setManualRow(idx, { qty: e.target.value })}
                            className="ml-auto h-8 w-24 text-right" data-testid={`mi-manual-qty-${idx}`} />
                        </TableCell>
                        <TableCell>
                          <UomSelect opt={manualUom[row.material_id]} fallbackUnit={mat.unit}
                            value={row.uom || baseUnitOf(manualUom[row.material_id], mat.unit)}
                            onChange={e => setManualRow(idx, { uom: e.target.value })}
                            testId={`mi-manual-uom-${idx}`} className="h-8 w-24 text-sm" />
                          <UomConversionHint opt={manualUom[row.material_id]} qty={row.qty}
                            unit={row.uom || baseUnitOf(manualUom[row.material_id], mat.unit)}
                            fallbackUnit={mat.unit} testId={`mi-manual-uom-hint-${idx}`} />
                        </TableCell>
                        <TableCell className="min-w-[10rem]">
                          <SmartNativeSelect value={row.location_id}
                            onChange={e => setManualRow(idx, { location_id: e.target.value })}
                            className="h-8 w-full text-sm" aria-label="Lokasi ambil" data-testid={`mi-manual-location-${idx}`}>
                            <option value="">Pilih</option>
                            {locations.map(l => <option key={l.id} value={l.id}>{`${l.code}${l.name ? ` · ${l.name}` : ''}`}</option>)}
                          </SmartNativeSelect>
                        </TableCell>
                        <TableCell className="text-right">
                          {manualRows.length > 1 && (
                            <Button type="button" variant="ghost" size="icon-sm" title="Hapus baris" aria-label="Hapus baris"
                              onClick={() => setManualRows(rows => rows.filter((_, i) => i !== idx))}
                              data-testid={`mi-manual-remove-${idx}`}>
                              <Trash2 />
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={() => setManualRows(rows => [...rows, { material_id: '', qty: '', uom: '', location_id: '' }])} data-testid="mi-manual-add-row">
              <Plus /> Tambah baris
            </Button>
            <Isian label="Keterangan" htmlFor="mi-manual-notes-in">
              <Input id="mi-manual-notes-in" value={createNotes} onChange={e => setCreateNotes(e.target.value)}
                placeholder="Mis. sampel buyer, permak lot 3" data-testid="mi-manual-notes" />
            </Isian>
          </div>
        )}

        {/* SESI #19 — kolom nomor mengikuti kebijakan Otomatis/Manual owner. */}
        <DocNumberField
          policy={numPolicy}
          value={miNumber}
          onChange={setMiNumber}
          label="Nomor pengeluaran material"
          testId="mi-number"
        />
        {createErr && <span className="sr-only" data-testid="mi-create-error">{createErr}</span>}
      </FormPopup>

      {/* Detail = DetailPopup */}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={`Pengeluaran material ${detail.mi_number}`} testId="mi-detail-popup"
          status={<><StatusMI status={detail.status} /><SourceBadge mi={detail} /></>}
          keterangan={`Acuan: ${refOf(detail) || 'Manual'} · ${tglMI(detail)}`}
          aksi={detail.status === 'draft' ? (
            <>
              <Button size="sm" variant="destructive" onClick={() => cancelMI(detail)}><XCircle /> Batalkan</Button>
              {/* PROD-01: tombol legacy "Konfirmasi & Kurangi Stok" (tanpa persetujuan) DIMATIKAN — satu jalur: Ajukan → Setujui */}
              <Button size="sm" onClick={() => submitMI(detail)} data-testid="mi-submit-approval-btn"><Send /> Ajukan persetujuan</Button>
            </>
          ) : null}>
          {/* ── FASE H-6b — ASAL DOKUMEN CUTTING (jejak yang bisa dipertanggungjawabkan) ── */}
          {detail.source_key === 'cutting' && (
            <Notice tone="info" icon={Scissors} testId="mi-cutting-panel"
              title={<>
                Dari Portal Cutting — order {detail.cutting_order_number || '-'}
                {detail.backfilled && (
                  <span className="ml-2" data-testid="mi-cutting-backfilled"><StatusBadge status="backfilled" label="Diterbitkan retroaktif" tone="warning" /></span>
                )}
              </>}>
              <div className="space-y-2 text-sm">
                <div>{detail.stock_note}</div>
                <dl className="divide-y divide-[var(--glass-border)]">
                  <BarisDetail label="Model">{detail.cutting_style_name || '-'}</BarisDetail>
                  <BarisDetail label="Potongan jadi">{Number(detail.cutting_output_qty || 0).toLocaleString('id-ID')} pcs</BarisDetail>
                  <BarisDetail label="Buangan">{Number(detail.cutting_waste_qty || 0).toLocaleString('id-ID')}</BarisDetail>
                  <BarisDetail label="Kode potongan">{detail.cutting_output_material_code || '-'}</BarisDetail>
                </dl>
                {(detail.roll_numbers || []).length > 0 && (
                  <div data-testid="mi-cutting-rolls">
                    <span className="text-muted-foreground">Gulungan dipakai:</span>{' '}
                    {(detail.roll_consumption || []).length > 0
                      ? (detail.roll_consumption || []).map((c, i) => (
                        <span key={i} className="mr-2 inline-block tabular-nums">
                          {c.roll_no} <span className="font-medium">−{Number(c.qty || 0).toLocaleString('id-ID')}</span>
                          {c.remaining_after != null && <span className="text-muted-foreground"> (sisa {Number(c.remaining_after).toLocaleString('id-ID')})</span>}
                        </span>
                      ))
                      : <span className="tabular-nums">{(detail.roll_numbers || []).join(', ')}</span>}
                  </div>
                )}
                {detail.gl_skip_reason && (
                  <div className="flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="mi-cutting-gl-reason">
                    <Info className="mt-0.5 h-3 w-3 flex-shrink-0" />
                    <span><b>Tidak dijurnal.</b> {detail.gl_skip_reason}</span>
                  </div>
                )}
                {onNavigate && (
                  <div>
                    <Button size="sm" variant="outline" onClick={() => { setDetail(null); onNavigate('cutting-orders'); }}
                      data-testid="mi-cutting-open-order">
                      <ExternalLink /> Buka order cutting
                    </Button>
                  </div>
                )}
              </div>
            </Notice>
          )}

          {detail.missing_codes?.length > 0 && (
            <Notice tone="warning" icon={AlertTriangle} title="Kode material kosong pada BOM">
              {detail.missing_codes.join(', ')} — item ini tidak ikut di MI. Lengkapi kode di BOM lalu buat ulang.
            </Notice>
          )}

          {/* U3 — Scan button for draft MI */}
          {detail.status === 'draft' && (
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" size="sm" variant="outline"
                  onClick={() => { setScanTarget({ miId: detail.id }); setShowScanner(true); }}
                  data-testid="mi-scan-barcode-btn">
                  <ScanLine /> Scan barcode material
                </Button>
                <span className="text-xs text-muted-foreground">Cek apakah material ada di daftar; ikon scan di baris mengganti material baris itu.</span>
              </div>
              {scanRes && scanRes.idx === null && <ScanResult {...scanRes} testId="mi-scan-result" />}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-base font-semibold text-foreground">Barang ({(detail.items || []).length})</p>
            <TombolUnduh namaBerkas={`mi-${detail.mi_number}`} namaLembar="Barang MI" baris={detail.items || []} testId="mi-detail-unduh"
              kolom={[
                { label: 'Kode', nilai: (it) => it.material_code },
                { label: 'Material', nilai: (it) => it.material_name || '' },
                { label: 'Jenis', nilai: (it) => JENIS_MATERIAL[it.material_type] || it.material_type || '' },
                { label: 'Qty dibutuhkan', nilai: (it) => Number(it.qty_required || 0) },
                { label: 'Qty keluar', nilai: (it) => Number(it.qty_issued || 0) },
                { label: 'Satuan', nilai: (it) => it.unit || '' },
                { label: 'Lokasi ambil', nilai: (it) => it.location_code || '' },
              ]} />
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Material</TableHead>
                  <TableHead>Jenis</TableHead>
                  <TableHead className="text-right">Qty dibutuhkan</TableHead>
                  <TableHead className="text-right">Qty keluar</TableHead>
                  <TableHead>Lokasi ambil</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(detail.items || []).map((it, idx) => (
                  <TableRow key={it.id}>
                    <TableCell>
                      <div className="flex items-center gap-1 font-medium text-foreground">
                        {it.material_code}
                        {detail.status === 'draft' && (
                          <Button type="button" variant="ghost" size="icon-sm"
                            onClick={() => { setScanTarget({ miId: detail.id, itemIdx: idx }); setShowScanner(true); }}
                            title="Scan barcode untuk material ini" aria-label="Scan barcode untuk material ini"
                            data-testid={`mi-item-scan-${it.material_code}`}
                          >
                            <ScanLine />
                          </Button>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground">{it.material_name}</div>
                      {scanRes && scanRes.idx === idx && <ScanResult {...scanRes} testId={`mi-item-scan-result-${idx}`} />}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{JENIS_MATERIAL[it.material_type] || it.material_type || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {detail.status === 'draft' ? (
                        <div className="space-y-1">
                          <div className="flex items-center justify-end gap-1.5">
                            <Input type="number" min="0" step="0.0001" aria-label="Qty dibutuhkan"
                              value={it._qty_input ?? it.input_qty ?? it.qty_required ?? 0}
                              onChange={e => updateDetailItem(it.id, { _qty_input: e.target.value })}
                              className="h-8 w-24 text-right" data-testid={`mi-item-qty-${it.material_code}`} />
                            <UomSelect opt={uomOpts[it.material_id]} fallbackUnit={it.unit}
                              value={it._uom || it.input_uom || baseUnitOf(uomOpts[it.material_id], it.unit)}
                              onChange={e => updateDetailItem(it.id, { _uom: e.target.value })}
                              testId={`mi-item-uom-${it.material_code}`} className="h-8 w-20 shrink-0 text-sm" />
                          </div>
                          <UomConversionHint opt={uomOpts[it.material_id]}
                            qty={it._qty_input ?? it.input_qty ?? it.qty_required}
                            unit={it._uom || it.input_uom || baseUnitOf(uomOpts[it.material_id], it.unit)}
                            fallbackUnit={it.unit} className="text-right"
                            testId={`mi-item-uom-hint-${it.material_code}`} />
                        </div>
                      ) : (
                        <>
                          {fmtQty(it.qty_required)} {it.unit}
                          {it.input_uom && it.input_qty != null && (
                            <div className="text-xs font-normal text-muted-foreground" data-testid={`mi-item-uom-trace-${it.material_code}`}>
                              input: {Number(it.input_qty)} {it.input_uom}
                            </div>
                          )}
                        </>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">{fmtQty(it.qty_issued)} {it.unit}</TableCell>
                    <TableCell className="min-w-[9rem]">
                      {detail.status === 'draft' ? (
                        <SmartNativeSelect value={it.location_id || ''} onChange={e => updateDetailItemLocation(it.id, e.target.value)}
                          className="h-8 w-full text-sm" aria-label="Lokasi ambil" data-testid={`mi-item-location-${it.material_code}`}>
                          <option value="">Pilih</option>
                          {locations.map(l => <option key={l.id} value={l.id}>{`${l.code}${l.name ? ` · ${l.name}` : ''}`}</option>)}
                        </SmartNativeSelect>
                      ) : (
                        <span className="text-sm text-muted-foreground">{it.location_code || '—'}</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {formError && <Notice tone="danger" testId="mi-form-error">{formError}</Notice>}
          {detail.status === 'draft' && (
            <div className="flex justify-end">
              <Button variant="success" onClick={saveDetailItems} disabled={saving} data-testid="mi-save-items-btn">
                {saving ? 'Menyimpan…' : 'Simpan qty, satuan & lokasi'}
              </Button>
            </div>
          )}
        </DetailPopup>
      )}

      {/* U3 — Barcode Scanner Modal (Sprint A.1: UniversalScanner SSOT) */}
      <UniversalScanner
        variant="modal"
        open={showScanner}
        onClose={() => { setShowScanner(false); setScanTarget(null); }}
        onScan={handleBarcodeScan}
        title="Scan barcode material"
      />
    </PageLayout>
  );
}
