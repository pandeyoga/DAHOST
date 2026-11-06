import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Plus, Eye, Trash2, CheckCircle2, XCircle, AlertTriangle, Package, Sparkles, FileText, Send, ScanLine, Scissors, ExternalLink, Info } from 'lucide-react';
import { GlassCard, GlassPanel, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState, Notice } from './moduleAtoms';
import Modal from './Modal';
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
  cutting: { label: 'Cutting', cls: 'bg-[hsl(var(--primary)/0.15)]  text-[hsl(var(--primary))]  border-[hsl(var(--primary)/0.35)] ' },
  vendor_shipment: { label: 'Kirim Material CMT', cls: 'bg-[hsl(var(--primary)/0.15)]  text-[hsl(var(--primary))]  border-[hsl(var(--primary)/0.35)] ' },
  job: { label: 'Job Produksi', cls: 'bg-[hsl(var(--primary)/0.15)]  text-[hsl(var(--primary))]  border-[hsl(var(--primary)/0.35)] ' },
  work_order: { label: 'Work Order', cls: 'bg-[hsl(var(--warning)/0.15)]  text-[hsl(var(--warning))]  border-[hsl(var(--warning)/0.35)] ' },
  manual: { label: 'Manual', cls: 'bg-muted text-muted-foreground border-border' },
};

function SourceBadge({ mi }) {
  const key = mi.source_key || 'manual';
  const m = SOURCE_META[key] || SOURCE_META.manual;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-[10px] font-semibold ${m.cls}`}
      data-testid={`mi-source-${mi.mi_number}`}>
      {key === 'cutting' && <Scissors className="w-2.5 h-2.5" />}
      {mi.source_label || m.label}
    </span>
  );
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
  draft:             { label: 'Draft',             bg: 'bg-muted',   border: 'border-border/25',   text: 'text-foreground/70' },
  pending_approval:  { label: 'Menunggu Approval', bg: 'bg-[hsl(var(--warning)/0.1)] ',   border: 'border-[hsl(var(--warning)/0.25)]',   text: 'text-[hsl(var(--warning))] ' },
  rejected:          { label: 'Ditolak',           bg: 'bg-[hsl(var(--destructive)/0.1)] ',     border: 'border-[hsl(var(--destructive)/0.25)]',     text: 'text-[hsl(var(--destructive))] ' },
  issued:            { label: 'Issued',            bg: 'bg-[hsl(var(--success)/0.1)] ', border: 'border-[hsl(var(--success)/0.25)]', text: 'text-[hsl(var(--success))] ' },
  cancelled:         { label: 'Cancelled',         bg: 'bg-muted',    border: 'border-border/25',    text: 'text-foreground/80' },
};

function StatusBadge({ status }) {
  const s = STATUS_META[status] || STATUS_META.draft;
  return <span className={`inline-flex items-center text-[10px] font-semibold px-2 py-0.5 rounded-full ${s.bg} ${s.border} border ${s.text}`}>{s.label}</span>;
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
    const reason = prompt(`Alasan menolak MI ${mi.mi_number}:`);
    if (!reason) return;
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

  if (loading) return (<div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>);

  return (
    <div className="space-y-5" data-testid="rahaza-mi-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Pengeluaran Material (MI)</h1>
          <p className="text-muted-foreground text-sm mt-1">
            SATU daftar untuk seluruh arus keluar gudang: MI manual, BOM job produksi,
            Kirim Material CMT, dan — sejak Fase H-6b — kain yang dipotong di Portal Cutting.
            Untuk MI manual/job, Approval-lah yang memotong stok; dokumen Cutting lahir sudah
            &quot;issued&quot; karena kainnya memang sudah keluar saat progres dilaporkan.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={openCreate} data-testid="mi-create-btn">
            <Plus className="w-4 h-4 mr-1.5" /> Buat MI
          </Button>
          {buildings.length > 0 && (
            <SmartNativeSelect
              value={filterBuilding}
              onChange={e => setFilterBuilding(e.target.value)}
              className="h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"
              data-testid="mi-filter-building"
              title="Filter berdasarkan gedung WMS"
            >
              <option value="">🏢 Semua Gedung</option>
              {buildings.map(b => <option key={b.id} value={b.id}>🏢 {b.name}</option>)}
            </SmartNativeSelect>
          )}
          <SmartNativeSelect value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground" data-testid="mi-filter-status">
            <option value="">Semua Status</option>
            <option value="draft">Draft</option>
            <option value="pending_approval">Menunggu Approval</option>
            <option value="rejected">Ditolak</option>
            <option value="issued">Sudah Keluar</option>
            <option value="cancelled">Dibatalkan</option>
          </SmartNativeSelect>
        </div>
      </div>

      {/* ── FASE H-6b — CHIP PENYARING SUMBER ARUS KELUAR ──────────────────────
          Angka diambil dari `GET /material-issues/sources` (read-only). Chip yang
          angkanya 0 tetap ditampilkan supaya jelas pintu itu ADA tapi masih kosong
          — bukan hilang. */}
      <div className="flex flex-wrap items-center gap-1.5" data-testid="mi-source-chips">
        <span className="text-[11px] text-muted-foreground mr-1">Sumber:</span>
        <button type="button" onClick={() => setFilterSource('')}
          className={`h-8 px-2.5 rounded-lg text-xs border transition-colors ${filterSource === ''
            ? 'bg-primary text-primary-foreground border-primary'
            : 'bg-foreground/5 text-foreground border-foreground/10 hover:bg-foreground/10'}`}
          data-testid="mi-src-all">
          Semua ({srcMeta.all_count ?? 0})
        </button>
        {(srcMeta.sources || []).map(s => (
          <button key={s.key} type="button" onClick={() => setFilterSource(s.key)}
            className={`h-8 px-2.5 rounded-lg text-xs border transition-colors ${filterSource === s.key
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-foreground/5 text-foreground border-foreground/10 hover:bg-foreground/10'}`}
            data-testid={`mi-src-${s.key}`}>
            {s.key === 'cutting' && <Scissors className="w-3 h-3 mr-1 inline-block align-[-1px]" />}
            {s.label} ({s.count})
          </button>
        ))}
        {onNavigate && (
          <button type="button" onClick={() => onNavigate('cutting-orders')}
            className="h-8 px-2.5 rounded-lg text-xs border border-foreground/10 bg-foreground/5 text-muted-foreground hover:text-foreground hover:bg-foreground/10 ml-auto inline-flex items-center gap-1"
            data-testid="mi-open-cutting">
            <ExternalLink className="w-3 h-3" /> Buka Portal Cutting
          </button>
        )}
      </div>

      <GlassCard className="p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[var(--glass-bg)]">
              <tr className="text-left text-xs text-muted-foreground">
                <th className="px-4 py-3">No. MI</th>
                <th className="px-4 py-3">Sumber</th>
                <th className="px-4 py-3">Acuan</th>
                <th className="px-4 py-3">Item</th>
                <th className="px-4 py-3 text-right">Total Qty</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Tanggal</th>
                <th className="px-4 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {list.length === 0 ? (
                <tr><td colSpan={8}>
                  <EmptyState icon={Package}
                    title={filterSource ? `Belum ada arus keluar dari sumber "${SOURCE_META[filterSource]?.label || filterSource}"` : 'Belum ada Material Issue'}
                    description="MI draft dibuat otomatis saat job produksi internal dibuat — gudang tinggal konfirmasi. MI manual juga bisa dibuat di sini, dan dokumen Cutting terbit sendiri saat progres potong dilaporkan."
                    action={
                    <div className="flex items-center justify-center gap-2">
                      {filterSource && (
                        <Button size="sm" variant="outline" onClick={() => setFilterSource('')} data-testid="mi-empty-cta-clear-source">
                          Tampilkan semua sumber
                        </Button>
                      )}
                      <Button size="sm" onClick={openCreate} data-testid="mi-empty-cta-create">
                        <Plus className="w-3.5 h-3.5 mr-1.5" /> Buat MI
                      </Button>
                      {onNavigate && (
                        <Button size="sm" variant="outline" onClick={() => onNavigate('prod-work-orders')} data-testid="mi-empty-cta-wo" >
                          Buka Work Order
                        </Button>
                      )}
                    </div>
                    } />
                </td></tr>
              ) : list.map(mi => (
                <tr key={mi.id} className="border-t border-[var(--glass-border)] hover:bg-[var(--glass-bg-hover)]" data-testid={`mi-row-${mi.mi_number}`}>
                  <td className="px-4 py-3 tabular-nums text-xs text-foreground">{mi.mi_number}</td>
                  <td className="px-4 py-3"><SourceBadge mi={mi} /></td>
                  <td className="px-4 py-3">
                    {refOf(mi)
                      ? <span className="text-foreground text-xs">{refOf(mi)}</span>
                      : <span className="text-muted-foreground italic text-xs">Manual</span>}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {mi.item_count} item
                    {mi.first_material_code && (
                      <span className="block text-[10px] text-foreground/50 tabular-nums">{mi.first_material_code}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold text-foreground">
                    {Number(mi.total_required || 0).toFixed(2)}
                    {mi.first_unit && <span className="text-[10px] text-muted-foreground font-normal ml-1">{mi.first_unit}</span>}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={mi.status} /></td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">{new Date(mi.created_at).toLocaleDateString('id-ID')}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button onClick={() => openDetail(mi)} className="p-1.5 rounded hover:bg-[var(--glass-bg-hover)] text-muted-foreground hover:text-foreground" title="Detail" data-testid={`mi-detail-${mi.mi_number}`}><Eye className="w-3.5 h-3.5" /></button>
                      {/* FASE H-6b: dokumen Cutting tidak punya tombol Approve/Hapus —
                          kainnya sudah keluar; menyetujuinya akan memotong stok dua kali. */}
                      {mi.source_key === 'cutting' && onNavigate && (
                        <button onClick={() => onNavigate('cutting-orders')}
                          className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-muted-foreground hover:text-[hsl(var(--primary))] "
                          title={`Buka order cutting ${mi.cutting_order_number || ''}`}
                          data-testid={`mi-open-cutting-${mi.mi_number}`}>
                          <Scissors className="w-3.5 h-3.5" />
                        </button>
                      )}
                      {mi.status === 'draft' && (
                        <>
                          <button onClick={() => submitMI(mi)} className="p-1.5 rounded hover:bg-[hsl(var(--primary)/0.1)] text-muted-foreground hover:text-[hsl(var(--primary))] " title="Ajukan Approval" data-testid={`mi-submit-${mi.mi_number}`}><Send className="w-3.5 h-3.5" /></button>
                          <button onClick={() => deleteMI(mi)} className="p-1.5 rounded hover:bg-[hsl(var(--destructive)/0.1)] text-muted-foreground hover:text-[hsl(var(--destructive))] " title="Hapus"><Trash2 className="w-3.5 h-3.5" /></button>
                        </>
                      )}
                      {mi.status === 'pending_approval' && (
                        <>
                          <button onClick={() => approveMI(mi)} className="p-1.5 rounded hover:bg-[hsl(var(--success)/0.1)] text-muted-foreground hover:text-[hsl(var(--success))] " title="Setujui" data-testid={`mi-approve-${mi.mi_number}`}><CheckCircle2 className="w-3.5 h-3.5" /></button>
                          <button onClick={() => rejectMI(mi)} className="p-1.5 rounded hover:bg-[hsl(var(--destructive)/0.1)] text-muted-foreground hover:text-[hsl(var(--destructive))] " title="Tolak" data-testid={`mi-reject-${mi.mi_number}`}><XCircle className="w-3.5 h-3.5" /></button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </GlassCard>

      {/* FASE 5: modal Draft-dari-WO dihapus (MI draft auto dari job internal) */}

      {/* FASE H-2 — modal Buat MI (dari job BOM / manual dari master) */}
      {showCreate && (
        <Modal onClose={closeCreate} title="Buat Pengeluaran Material" size="xl">
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <button onClick={() => setCreateTab('job')} data-testid="mi-create-tab-job"
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  createTab === 'job'
                    ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-transparent'
                    : 'bg-[var(--glass-bg)] text-muted-foreground border-[var(--glass-border)]'}`}>
                Dari job produksi
              </button>
              <button onClick={() => setCreateTab('manual')} data-testid="mi-create-tab-manual"
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  createTab === 'manual'
                    ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-transparent'
                    : 'bg-[var(--glass-bg)] text-muted-foreground border-[var(--glass-border)]'}`}>
                Manual dari master
              </button>
            </div>

            {createTab === 'job' ? (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Kebutuhan material DIHITUNG dari BOM job (kain + aksesoris × qty job) —
                  tidak diketik, sehingga tidak mungkin berbeda dengan rencana produksi.
                  Hanya job <b>internal</b>: material job maklon milik klien, bukan stok DA.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Job produksi internal</div>
                    <SmartNativeSelect value={jobId} onChange={e => setJobId(e.target.value)}
                      className="h-9 px-2 text-sm w-full" data-testid="mi-create-job-select">
                      <option value="">— Pilih job —</option>
                      {jobs.map(j => (
                        <option key={j.id} value={j.id}>
                          {j.job_number} · {j.po_number || '-'} · {j.status}
                        </option>
                      ))}
                    </SmartNativeSelect>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Lokasi ambil (bawaan, bisa diubah nanti)</div>
                    <SmartNativeSelect value={createLoc} onChange={e => setCreateLoc(e.target.value)}
                      className="h-9 px-2 text-sm w-full" data-testid="mi-create-location-select">
                      <option value="">— Tentukan per baris nanti —</option>
                      {locations.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}
                    </SmartNativeSelect>
                  </div>
                </div>
                {jobs.length === 0 && (
                  <div className="text-xs text-[hsl(var(--warning))] bg-[hsl(var(--warning)/0.1)]  border border-[hsl(var(--warning)/0.4)] rounded-md px-3 py-2"
                    data-testid="mi-create-no-jobs">
                    Belum ada job produksi internal. Buat PO internal & job-nya dulu di Portal
                    Produksi, atau pakai tab “Manual dari master”.
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Material WAJIB dipilih dari master — barang jadi tidak ikut, karena yang
                  keluar ke produksi adalah bahan.
                </p>
                <GlassPanel className="p-0 overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-[var(--glass-bg)]">
                      <tr className="text-left text-xs text-muted-foreground">
                        <th className="px-3 py-2">Material</th>
                        <th className="px-3 py-2 text-right">Jumlah</th>
                        <th className="px-3 py-2">Satuan</th>
                        <th className="px-3 py-2">Lokasi ambil</th>
                        <th className="px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {manualRows.map((row, idx) => {
                        const mat = materials.find(m => m.id === row.material_id) || {};
                        return (
                          <tr key={idx} className="border-t border-[var(--glass-border)]">
                            <td className="px-3 py-2">
                              <SmartNativeSelect value={row.material_id}
                                onChange={e => setManualRow(idx, { material_id: e.target.value, uom: '' })}
                                className="h-8 px-2 text-xs w-full" data-testid={`mi-manual-material-${idx}`}>
                                <option value="">— Pilih material —</option>
                                {issuableMaterials.map(m => (
                                  <option key={m.id} value={m.id}>{m.code} · {m.name}</option>
                                ))}
                              </SmartNativeSelect>
                            </td>
                            <td className="px-3 py-2 text-right">
                              <input type="number" min="0" step="0.0001" value={row.qty}
                                onChange={e => setManualRow(idx, { qty: e.target.value })}
                                className="h-8 w-24 rounded-md border border-input bg-background px-2 text-right text-xs text-foreground"
                                data-testid={`mi-manual-qty-${idx}`} />
                            </td>
                            <td className="px-3 py-2">
                              <UomSelect opt={manualUom[row.material_id]} fallbackUnit={mat.unit}
                                value={row.uom || baseUnitOf(manualUom[row.material_id], mat.unit)}
                                onChange={e => setManualRow(idx, { uom: e.target.value })}
                                testId={`mi-manual-uom-${idx}`} className="w-24 h-8 text-xs" />
                              <UomConversionHint opt={manualUom[row.material_id]} qty={row.qty}
                                unit={row.uom || baseUnitOf(manualUom[row.material_id], mat.unit)}
                                fallbackUnit={mat.unit} testId={`mi-manual-uom-hint-${idx}`} />
                            </td>
                            <td className="px-3 py-2">
                              <SmartNativeSelect value={row.location_id}
                                onChange={e => setManualRow(idx, { location_id: e.target.value })}
                                className="h-8 px-2 text-xs" data-testid={`mi-manual-location-${idx}`}>
                                <option value="">— Pilih —</option>
                                {locations.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}
                              </SmartNativeSelect>
                            </td>
                            <td className="px-3 py-2 text-right">
                              {manualRows.length > 1 && (
                                <button onClick={() => setManualRows(rows => rows.filter((_, i) => i !== idx))}
                                  className="p-1.5 rounded hover:bg-[hsl(var(--destructive)/0.1)] text-muted-foreground hover:text-[hsl(var(--destructive))]"
                                  data-testid={`mi-manual-remove-${idx}`}>
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </GlassPanel>
                <Button size="sm" variant="outline" onClick={() => setManualRows(rows => [...rows, { material_id: '', qty: '', uom: '', location_id: '' }])} data-testid="mi-manual-add-row">
                  <Plus className="w-3.5 h-3.5 mr-1.5" /> Tambah baris
                </Button>
                <GlassInput value={createNotes} onChange={e => setCreateNotes(e.target.value)}
                  placeholder="Keterangan (mis. 'sampel buyer', 'permak lot 3')"
                  data-testid="mi-manual-notes" />
              </div>
            )}

            {/* SESI #19 — kolom nomor mengikuti kebijakan Otomatis/Manual owner. */}
            <DocNumberField
              policy={numPolicy}
              value={miNumber}
              onChange={setMiNumber}
              label="Nomor Pengeluaran Material"
              testId="mi-number"
              className="mt-3"
            />

            {createErr && (
              <div className="text-xs text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.1)]  border border-[hsl(var(--destructive)/0.35)]  rounded-md px-3 py-2"
                data-testid="mi-create-error">{createErr}</div>
            )}

            <div className="flex items-center justify-end gap-2 pt-1">
              <Button variant="outline" onClick={closeCreate} data-testid="mi-create-cancel">Batal</Button>
              <Button onClick={createTab === 'job' ? createFromJob : createManual} disabled={creating}
                data-testid="mi-create-submit">
                <FileText className="w-4 h-4 mr-1.5" />
                {creating ? 'Menyimpan…' : 'Buat Draft MI'}
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Detail modal */}
      {detail && (
        <Modal onClose={() => setDetail(null)} title={`Detail ${detail.mi_number}`} size="xl">
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-2 text-sm">
              <div><span className="text-muted-foreground">Status:</span> <StatusBadge status={detail.status} /></div>
              <div><span className="text-muted-foreground">Sumber:</span> <SourceBadge mi={detail} /></div>
              <div><span className="text-muted-foreground">Acuan:</span> <b>{refOf(detail) || 'Manual'}</b></div>
              <div><span className="text-muted-foreground">Tanggal:</span> <b>{new Date(detail.created_at).toLocaleDateString('id-ID')}</b></div>
            </div>

            {/* ── FASE H-6b — ASAL DOKUMEN CUTTING (jejak yang bisa dipertanggungjawabkan) ── */}
            {detail.source_key === 'cutting' && (
              <Notice tone="info" icon={Scissors} testId="mi-cutting-panel"
                title={<>
                  Dari Portal Cutting — order {detail.cutting_order_number || '-'}
                  {detail.backfilled && (
                    <span className="ml-2 px-1.5 py-0.5 rounded-full border border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]  text-[10px] font-semibold"
                      data-testid="mi-cutting-backfilled">diterbitkan retroaktif</span>
                  )}
                </>}>
                <div className="space-y-2">
                <div className="text-xs">{detail.stock_note}</div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1 text-xs">
                  <div><span className="text-[hsl(var(--primary)/0.7)] ">Style:</span> <b>{detail.cutting_style_name || '-'}</b></div>
                  <div><span className="text-[hsl(var(--primary)/0.7)] ">Potongan jadi:</span> <b>{Number(detail.cutting_output_qty || 0).toLocaleString('id-ID')} pcs</b></div>
                  <div><span className="text-[hsl(var(--primary)/0.7)] ">Buangan:</span> <b>{Number(detail.cutting_waste_qty || 0).toLocaleString('id-ID')}</b></div>
                  <div><span className="text-[hsl(var(--primary)/0.7)] ">Kode potongan:</span> <b className="tabular-nums">{detail.cutting_output_material_code || '-'}</b></div>
                </div>
                {(detail.roll_numbers || []).length > 0 && (
                  <div className="text-xs" data-testid="mi-cutting-rolls">
                    <span className="text-[hsl(var(--primary)/0.7)] ">Gulungan dipakai:</span>{' '}
                    {(detail.roll_consumption || []).length > 0
                      ? (detail.roll_consumption || []).map((c, i) => (
                        <span key={i} className="inline-block mr-2 tabular-nums">
                          {c.roll_no} <span className="text-[hsl(var(--primary))] ">−{Number(c.qty || 0).toLocaleString('id-ID')}</span>
                          {c.remaining_after != null && <span className="text-[hsl(var(--primary)/0.6)] "> (sisa {Number(c.remaining_after).toLocaleString('id-ID')})</span>}
                        </span>
                      ))
                      : <span className="tabular-nums">{(detail.roll_numbers || []).join(', ')}</span>}
                  </div>
                )}
                {detail.gl_skip_reason && (
                  <div className="flex items-start gap-1.5 text-[11px] text-[hsl(var(--primary)/0.8)] "
                    data-testid="mi-cutting-gl-reason">
                    <Info className="w-3 h-3 mt-0.5 flex-shrink-0" />
                    <span><b>Tidak dijurnal.</b> {detail.gl_skip_reason}</span>
                  </div>
                )}
                {onNavigate && (
                  <div>
                    <Button size="sm" variant="outline" className="text-xs border-[hsl(var(--primary)/0.4)]"
                      onClick={() => { setDetail(null); onNavigate('cutting-orders'); }}
                      data-testid="mi-cutting-open-order">
                      <ExternalLink className="w-3 h-3 mr-1" /> Buka order cutting
                    </Button>
                  </div>
                )}
                </div>
              </Notice>
            )}

            {detail.missing_codes?.length > 0 && (
              <Notice tone="warning" icon={AlertTriangle} title="Kode material kosong pada BOM">
                <span className="text-xs">{detail.missing_codes.join(', ')} — item ini tidak ikut di MI. Lengkapi kode di BOM lalu buat ulang.</span>
              </Notice>
            )}

            {/* U3 — Scan button for draft MI */}
            {detail.status === 'draft' && (
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" size="sm" variant="outline"
                    onClick={() => { setScanTarget({ miId: detail.id }); setShowScanner(true); }}
                    data-testid="mi-scan-barcode-btn">
                    <ScanLine className="w-4 h-4" /> Scan barcode material
                  </Button>
                  <span className="text-xs text-muted-foreground">Cek apakah material ada di daftar; ikon scan di baris mengganti material baris itu.</span>
                </div>
                {scanRes && scanRes.idx === null && <ScanResult {...scanRes} testId="mi-scan-result" />}
              </div>
            )}

            <GlassPanel className="p-0 overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-[var(--glass-bg)]">
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="px-3 py-2">Material</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2 text-right">Qty Required</th>
                    <th className="px-3 py-2 text-right">Qty Issued</th>
                    <th className="px-3 py-2">Lokasi Ambil</th>
                  </tr>
                </thead>
                <tbody>
                  {(detail.items || []).map((it, idx) => (
                    <tr key={it.id} className="border-t border-[var(--glass-border)]">
                      <td className="px-3 py-2">
                        <div className="tabular-nums text-xs text-foreground flex items-center gap-1">
                          {it.material_code}
                          {detail.status === 'draft' && (
                            <Button type="button" variant="ghost" size="icon-sm"
                              onClick={() => { setScanTarget({ miId: detail.id, itemIdx: idx }); setShowScanner(true); }}
                              className="text-[hsl(var(--primary))]"
                              title="Scan barcode untuk material ini" aria-label="Scan barcode untuk material ini"
                              data-testid={`mi-item-scan-${it.material_code}`}
                            >
                              <ScanLine className="w-4 h-4" />
                            </Button>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground">{it.material_name}</div>
                        {scanRes && scanRes.idx === idx && <ScanResult {...scanRes} testId={`mi-item-scan-result-${idx}`} />}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{it.material_type}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-foreground">
                        {detail.status === 'draft' ? (
                          <div className="space-y-1">
                            <div className="flex items-center justify-end gap-1.5">
                              <input type="number" min="0" step="0.0001"
                                value={it._qty_input ?? it.input_qty ?? it.qty_required ?? 0}
                                onChange={e => updateDetailItem(it.id, { _qty_input: e.target.value })}
                                className="h-8 w-24 rounded-md border border-input bg-background px-2 text-right text-xs text-foreground"
                                data-testid={`mi-item-qty-${it.material_code}`} />
                              <UomSelect opt={uomOpts[it.material_id]} fallbackUnit={it.unit}
                                value={it._uom || it.input_uom || baseUnitOf(uomOpts[it.material_id], it.unit)}
                                onChange={e => updateDetailItem(it.id, { _uom: e.target.value })}
                                testId={`mi-item-uom-${it.material_code}`} className="w-20 shrink-0 h-8 text-xs" />
                            </div>
                            <UomConversionHint opt={uomOpts[it.material_id]}
                              qty={it._qty_input ?? it.input_qty ?? it.qty_required}
                              unit={it._uom || it.input_uom || baseUnitOf(uomOpts[it.material_id], it.unit)}
                              fallbackUnit={it.unit} className="text-right"
                              testId={`mi-item-uom-hint-${it.material_code}`} />
                          </div>
                        ) : (
                          <>
                            {Number(it.qty_required).toFixed(3)} {it.unit}
                            {it.input_uom && it.input_qty != null && (
                              <div className="text-[10px] text-muted-foreground font-normal" data-testid={`mi-item-uom-trace-${it.material_code}`}>
                                input: {Number(it.input_qty)} {it.input_uom}
                              </div>
                            )}
                          </>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{Number(it.qty_issued || 0).toFixed(3)} {it.unit}</td>
                      <td className="px-3 py-2">
                        {detail.status === 'draft' ? (
                          <SmartNativeSelect value={it.location_id || ''} onChange={e => updateDetailItemLocation(it.id, e.target.value)} className="h-8 px-2 text-xs" data-testid={`mi-item-location-${it.material_code}`}>
                            <option value="">— Pilih —</option>
                            {locations.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}
                          </SmartNativeSelect>
                        ) : (
                          <span className="text-xs text-muted-foreground">{it.location_code || '—'}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </GlassPanel>

            <div className="flex items-center justify-between gap-2 pt-2 flex-wrap">
              {formError && (
                <div className="w-full text-xs text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.1)]  border border-[hsl(var(--destructive)/0.35)]  rounded-md px-3 py-2"
                  data-testid="mi-form-error">{formError}</div>
              )}
              {detail.status === 'draft' && (
                <Button variant="outline" onClick={saveDetailItems} disabled={saving} data-testid="mi-save-items-btn">
                  {saving ? 'Menyimpan…' : 'Simpan Qty, Satuan & Lokasi'}
                </Button>
              )}
              <div className="flex items-center gap-2 ml-auto">
                {detail.status === 'draft' && (
                  <>
                    <Button variant="ghost" onClick={() => cancelMI(detail)} className="text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.1)] "><XCircle className="w-4 h-4 mr-1.5" /> Batalkan</Button>
                    {/* PROD-01: tombol legacy "Konfirmasi & Kurangi Stok" (tanpa approval) DIMATIKAN — satu jalur: Ajukan Approval → Approve */}
                    <Button onClick={() => submitMI(detail)} data-testid="mi-submit-approval-btn"><Send className="w-4 h-4 mr-1.5" /> Ajukan Approval</Button>
                  </>
                )}
              </div>
            </div>
          </div>
        </Modal>
      )}

      {/* U3 — Barcode Scanner Modal (Sprint A.1: UniversalScanner SSOT) */}
      <UniversalScanner
        variant="modal"
        open={showScanner}
        onClose={() => { setShowScanner(false); setScanTarget(null); }}
        onScan={handleBarcodeScan}
        title="Scan Barcode Material"
      />
    </div>
  );
}
