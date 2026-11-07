/**
 * Perawatan Data Keuangan — Portal Administrasi Sistem (admin/super_admin).
 *
 * 2026-11-04 (keputusan owner, audit Keuangan): tombol perawatan yang dulu tersebar di layar kerja
 * Keuangan (Kas & Bank, Umur Piutang, Nilai Persediaan, Pemetaan Akun, Profil Posting) dikumpulkan di sini.
 * Alasannya: tombol itu menulis massal (jurnal, akun, pemetaan) dan jarang dipakai — di layar kerja
 * mereka mudah tertekan dan membingungkan staf. Logika tetap di endpoint yang sama; layar ini hanya pintu.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout; 7 tugas = satu daftar berbaris di satu kartu (dulu 7 kartu
 * berserakan), akun pembantu = tabel, rincian hasil (kandidat jurnal, peringatan CV) dibuka di popup dengan
 * unduh Excel/CSV, konfirmasi tulis massal lewat confirmDialog. Endpoint & logika tidak berubah.
 */
import { useCallback, useEffect, useState } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Eye, List, Loader2, PlayCircle } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup from '@/components/ui/detail-popup';
import { toast } from 'sonner';
import PageLayout from '../layout/PageLayout';
import { StatusBadge } from '../moduleAtoms';
import CronJobCard from '../CronJobCard';
import { formatDateID, formatRupiah } from '@/lib/format';

const API = process.env.REACT_APP_BACKEND_URL || '';
const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('erp_token')}`, 'Content-Type': 'application/json' });
const fmt = formatRupiah;

async function post(path) {
  const r = await fetch(`${API}${path}`, { method: 'POST', headers: authH() });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Kode ${r.status}`);
  return d;
}

/** Satu baris tugas: judul + penjelasan di kiri, tombol + hasil di kanan (di HP bertumpuk). */
function Task({ title, desc, children, testId }) {
  return (
    <div className="grid gap-2 py-3 md:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] md:gap-4" data-testid={testId}>
      <div className="min-w-0">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">{desc}</p>
      </div>
      <div className="min-w-0 space-y-1">{children}</div>
    </div>
  );
}

function OneShot({ label, path, confirmText, describe, testId }) {
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState('');
  const run = async () => {
    if (confirmText && !(await confirmDialog(confirmText))) return;
    setBusy(true);
    try { const d = await post(path); const msg = describe(d); setOut(msg); toast.success(msg); }
    catch (e) { toast.error(e.message); setOut(`Gagal: ${e.message}`); }
    finally { setBusy(false); }
  };
  return (
    <>
      <Button size="sm" variant="outline" onClick={run} disabled={busy} data-testid={testId}>
        {busy ? <Loader2 className="animate-spin" /> : <PlayCircle />}{label}
      </Button>
      {out && <p className="text-xs text-muted-foreground">{out}</p>}
    </>
  );
}

function SubledgerBackfill() {
  const [types, setTypes] = useState(null);
  const [res, setRes] = useState({});
  const [busy, setBusy] = useState('');
  useEffect(() => {
    fetch(`${API}/api/rahaza/coa-auto/settings`, { headers: authH() }).then(r => (r.ok ? r.json() : null))
      .then(d => setTypes(Object.entries(d?.entity_types || {}).filter(([k]) => k !== 'store_revenue')))
      .catch(() => setTypes([]));
  }, []);
  const run = async (key, commit) => {
    setBusy(`${key}:${commit}`);
    try { const d = await post(`/api/rahaza/coa-auto/backfill/${key}?commit=${commit}`); setRes(x => ({ ...x, [key]: d })); }
    catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };
  const hasil = (key) => {
    const r = res[key];
    if (!r) return '—';
    return `${r.total_entities} data · ${r.already_have_account} sudah punya akun · ${r.committed ? `${r.created} akun dibuat` : `${r.would_create} akan dibuat`}`
      + ((r.errors || []).length ? ` · ${r.errors.length} gagal` : '');
  };
  if (types === null) return <p className="text-sm text-muted-foreground">Memuat…</p>;
  if (!types.length) return <p className="text-sm text-muted-foreground">Tidak ada jenis akun pembantu yang diatur.</p>;
  const baris = types.map(([key, cfg]) => ({ key, ...cfg }));
  return (
    <>
    <div className="flex justify-end">
      <TombolUnduh namaBerkas="akun-pembantu-data-lama" namaLembar="Akun pembantu" baris={baris} testId="maint-subledger-unduh" kolom={[
        { label: 'Jenis akun pembantu', nilai: (t) => t.label || t.key }, { label: 'Status', nilai: (t) => (t.enabled ? 'Aktif' : 'Nonaktif') },
        { label: 'Hasil terakhir', nilai: (t) => (res[t.key] ? hasil(t.key) : '') },
      ]} />
    </div>
    <TabelData baris={baris} kunci={(t) => t.key} testId="maint-subledger-table" kolom={[
      { kunci: 'label', label: 'Jenis akun pembantu', hp: 'judul', isi: (t) => (
        <span className="font-medium" data-testid={`maint-subledger-${t.key}`}>{t.label || t.key}</span>) },
      { kunci: 'status', label: 'Status', isi: (t) => (
        <StatusBadge status={t.enabled ? 'aktif' : 'nonaktif'} label={t.enabled ? 'Aktif' : 'Nonaktif'} tone={t.enabled ? 'success' : 'muted'} />) },
      { kunci: 'hasil', label: 'Hasil terakhir', isi: (t) => (
        <span className={`text-sm ${(res[t.key]?.errors || []).length ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{hasil(t.key)}</span>) },
      { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (t) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run(t.key, false)}>
            <Eye />Pratinjau
          </Button>
          <Button size="sm" disabled={!!busy || !t.enabled} title={t.enabled ? 'Buat akun pembantu' : 'Aktifkan dulu di Pengaturan Keuangan › Pemetaan akun'}
            onClick={() => run(t.key, true)}>
            <PlayCircle />Buat akun
          </Button>
        </div>) },
    ]} />
    </>
  );
}

function WipFgBackfill() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rincian, setRincian] = useState(false);
  const run = useCallback(async (dryRun) => {
    if (!dryRun && !(await confirmDialog({
      title: 'Posting jurnal WIP → Barang Jadi?',
      body: 'Untuk semua Terima FG dari CMT (PO internal) yang belum berjurnal.', confirmLabel: 'Posting sekarang',
    }))) return;
    setBusy(true);
    try { setD(await post(`/api/prod/cmt-receipts/backfill-wip-fg?dry_run=${dryRun}`)); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }, []);
  const rows = d?.rows || [];
  return (
    <>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={busy} onClick={() => run(true)} data-testid="maint-wipfg-preview">Lihat kandidat</Button>
        <Button size="sm" disabled={busy || !(d?.dry_run && d?.candidates > 0)} onClick={() => run(false)} data-testid="maint-wipfg-run">Posting sekarang</Button>
      </div>
      {d && (
        <p className="text-xs text-muted-foreground" data-testid="maint-wipfg-result">
          {d.dry_run ? `${d.candidates} kandidat · ${fmt(d.total_value)}` : `${d.posted} jurnal diposting · ${fmt(d.total_value)}`}
          {rows.length > 0 && <Button variant="link" size="sm" className="ml-1 h-auto p-0 text-xs" onClick={() => setRincian(true)}><List />Lihat rincian</Button>}
        </p>
      )}
      {rincian && (
        <DetailPopup open onClose={() => setRincian(false)} judul="Jurnal WIP → Barang Jadi" testId="maint-wipfg-detail"
          keterangan={d?.dry_run ? 'Kandidat yang akan diposting.' : 'Hasil posting.'}
          aksi={<TombolUnduh namaBerkas="wip-barang-jadi" namaLembar="Kandidat" baris={rows} kolom={[
            { label: 'Terima FG', nilai: (r) => r.receipt_code }, { label: 'PO', nilai: (r) => r.po_number },
            { label: 'Nilai', nilai: (r) => r.value }, { label: 'Hasil', nilai: (r) => r.result },
            { label: 'Jurnal', nilai: (r) => r.je_number || '' }, { label: 'Galat', nilai: (r) => r.error || '' },
          ]} />}>
          <TabelData baris={rows} kunci={(r) => r.receipt_id} kolom={[
            { kunci: 'receipt_code', label: 'Terima FG', hp: 'judul', isi: (r) => <span className="font-mono text-sm">{r.receipt_code}</span> },
            { kunci: 'po', label: 'PO', isi: (r) => <span className="font-mono text-sm">{r.po_number}</span> },
            { kunci: 'value', label: 'Nilai', rata: 'kanan', isi: (r) => <span className="tabular-nums">{fmt(r.value)}</span> },
            { kunci: 'result', label: 'Hasil', isi: (r) => <span className="text-sm">{r.result}{r.je_number ? ` (${r.je_number})` : ''}{r.error ? ` — ${r.error}` : ''}</span> },
          ]} />
        </DetailPopup>
      )}
    </>
  );
}

/**
 * Tahap 8 (dua CV) — cek jurnal otomatis yang akun/rekeningnya tidak cocok dengan CV jurnal.
 * Jurnal otomatis tidak pernah ditolak karena CV; ketidakcocokan hanya ditandai di jurnalnya
 * (GET /api/rahaza/journals/entity-warnings) dan diperbaiki Keuangan lewat jurnal manual.
 */
function EntityWarnings() {
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [rincian, setRincian] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/rahaza/journals/entity-warnings?entity=ALL&limit=50`, { headers: authH() });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `Kode ${r.status}`);
      setData(d);
    } catch (e) { toast.error(e.message); }
    finally { setBusy(false); }
  };
  const items = data?.items || [];
  return (
    <>
      <Button size="sm" variant="outline" onClick={run} disabled={busy} data-testid="maint-cv-check-run">
        {busy ? <Loader2 className="animate-spin" /> : <Eye />}Periksa
      </Button>
      {data && (
        <p className="text-xs text-muted-foreground" data-testid="maint-cv-check-result">
          {data.total ? `${data.total} jurnal otomatis perlu diperiksa (${items.length} terbaru).`
            : 'Semua jurnal otomatis cocok dengan CV-nya.'}
          {items.length > 0 && <Button variant="link" size="sm" className="ml-1 h-auto p-0 text-xs" onClick={() => setRincian(true)}><List />Lihat rincian</Button>}
        </p>
      )}
      {rincian && (
        <DetailPopup open onClose={() => setRincian(false)} judul="Jurnal otomatis beda CV" testId="maint-cv-check-detail"
          keterangan="Jurnalnya tetap tersimpan; perbaiki lewat jurnal manual di Portal Keuangan."
          aksi={<TombolUnduh namaBerkas="jurnal-beda-cv" namaLembar="Jurnal" baris={items} kolom={[
            { label: 'Nomor jurnal', nilai: (it) => it.je_number }, { label: 'CV', nilai: (it) => it.entity_label },
            { label: 'Tanggal', nilai: (it) => formatDateID(it.date) }, { label: 'Peringatan', nilai: (it) => it.entity_warning },
          ]} />}>
          <TabelData baris={items} kunci={(it) => it.id} kolom={[
            { kunci: 'je', label: 'Nomor jurnal', hp: 'judul', isi: (it) => <span className="font-mono text-sm">{it.je_number}</span> },
            { kunci: 'cv', label: 'CV', isi: (it) => it.entity_label },
            { kunci: 'tgl', label: 'Tanggal', isi: (it) => <span className="whitespace-nowrap">{formatDateID(it.date)}</span> },
            { kunci: 'warn', label: 'Peringatan', isi: (it) => <span className="text-sm">{it.entity_warning}</span> },
          ]} />
        </DetailPopup>
      )}
    </>
  );
}

export default function FinanceMaintenanceModule({ onNavigate }) {
  return (
    <PageLayout testId="finance-maintenance" title="Perawatan data keuangan"
      subtitle="Tombol perbaikan & pengisian massal data keuangan. Jalankan hanya bila diminta Keuangan; semua aman diulang.">
      <GlassCard className="px-4 py-1" data-testid="maint-tasks" data-konten-utama="">
        <div className="divide-y divide-[var(--glass-border)]">
          <Task title="Sinkron rekening kas/bank dengan Bagan Akun"
            desc="Membuat rekening untuk akun kas/bank yang belum punya, menautkan rekening lama ke akun buku besarnya, dan menjurnal saldo awal yang belum terjurnal."
            testId="maint-sync-gl">
            <OneShot label="Sinkronkan" path="/api/rahaza/cash-accounts/sync-gl" testId="maint-sync-gl-run"
              describe={(d) => {
                const rep = d.report || [];
                return `${(d.sync?.cash_accounts_created || []).length} rekening baru · ${rep.filter(x => x.opening).length} jurnal saldo awal · ${rep.filter(x => x.error).length} gagal`;
              }} />
          </Task>
          <Task title="Pasang profil jurnal otomatis bawaan"
            desc="Menambah profil jurnal otomatis yang belum ada (faktur, pembayaran, gaji, persediaan…). Profil yang sudah diubah Keuangan tidak ditimpa."
            testId="maint-pp-seed">
            <OneShot label="Pasang bawaan" path="/api/rahaza/posting-profiles/seed" testId="maint-pp-seed-run"
              describe={(d) => `${d.inserted} profil baru · ${d.skipped} sudah ada`} />
          </Task>
          <Task title="Pasang pemetaan akun klaim karyawan bawaan"
            desc="Mengisi pemetaan kategori klaim karyawan → akun beban untuk kategori yang belum dipetakan."
            testId="maint-claims-seed">
            <OneShot label="Pasang bawaan" path="/api/hr/expenses/gl-mappings/seed-default" testId="maint-claims-seed-run"
              describe={(d) => d.message || 'Selesai'} />
          </Task>
          <Task title="Cek CV jurnal otomatis"
            desc="Jurnal otomatis yang akun atau rekeningnya milik CV lain (mis. bayar faktur CV Dewi Aditya ke rekening CV Sukma). Jurnalnya tetap tersimpan; perbaiki lewat jurnal manual."
            testId="maint-cv-check">
            <EntityWarnings />
          </Task>
          <Task title="Jurnal WIP → Barang Jadi yang tertinggal"
            desc="Terima FG dari CMT (PO internal) yang sudah lolos QC tetapi belum berjurnal Persediaan Barang Jadi / WIP."
            testId="maint-wipfg">
            <WipFgBackfill />
          </Task>
          <CronJobCard job="mark-overdue" title="Tandai faktur lewat jatuh tempo"
            description="otomatis tiap hari 00.15 WIB untuk faktur penjualan & tagihan pemasok."
            renderResult={(r) => `${r.ar_marked} faktur penjualan · ${r.ap_marked} tagihan pemasok ditandai`} />
          <CronJobCard job="fg-valuation-check" title="Cek nilai persediaan barang jadi vs buku besar"
            description="otomatis tiap hari 07.00 WIB; Keuangan diberi notifikasi bila selisih belum terjelaskan."
            renderResult={(r) => `selisih ${fmt(r.difference)} · belum terjelaskan ${fmt(r.unexplained_difference)}${r.notified ? ' · notifikasi terkirim' : ''}`} />
        </div>
      </GlassCard>

      <GlassCard className="space-y-3 p-4" data-testid="maint-subledger">
        <div>
          <h3 className="text-lg font-semibold text-foreground">Buat akun pembantu untuk data lama</h3>
          <p className="text-sm text-muted-foreground">
            Membuat akun turunan (per pemasok, pelanggan, dll.) untuk data yang dibuat sebelum fitur akun otomatis aktif.
            Pengaturannya tetap di Pengaturan Keuangan › Pemetaan akun.
          </p>
        </div>
        <SubledgerBackfill />
      </GlassCard>

      {onNavigate && (
        <p className="text-sm text-muted-foreground">
          Pemasangan awal untuk server baru (bagan akun, profil posting, kategori klaim):{' '}
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => onNavigate('admin-setup-panel')} data-testid="maint-open-setup">buka Setup Awal</Button>.
        </p>
      )}
    </PageLayout>
  );
}
