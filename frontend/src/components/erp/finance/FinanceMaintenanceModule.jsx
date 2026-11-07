/**
 * Perawatan Data Keuangan — Portal Administrasi Sistem (admin/super_admin).
 *
 * 2026-11-04 (keputusan owner, audit Keuangan): tombol perawatan yang dulu tersebar di layar kerja
 * Keuangan (Kas & Bank, Umur Piutang, Nilai Persediaan, Pemetaan Akun, Profil Posting) dikumpulkan di sini.
 * Alasannya: tombol itu menulis massal (jurnal, akun, pemetaan) dan jarang dipakai — di layar kerja
 * mereka mudah tertekan dan membingungkan staf. Logika tetap di endpoint yang sama; layar ini hanya pintu.
 */
import { useCallback, useEffect, useState } from 'react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { BookOpen, Database, Landmark, Loader2, PlayCircle, Eye, Sparkles, Boxes, Settings2 } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { PageHeader } from '../moduleAtoms';
import CronJobCard from '../CronJobCard';
import { formatRupiah } from '@/lib/format';

const API = process.env.REACT_APP_BACKEND_URL || '';
const authH = () => ({ Authorization: `Bearer ${localStorage.getItem('erp_token')}`, 'Content-Type': 'application/json' });
const fmt = formatRupiah;

async function post(path) {
  const r = await fetch(`${API}${path}`, { method: 'POST', headers: authH() });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
  return d;
}

function Task({ icon: Icon, title, desc, children, testId }) {
  return (
    <GlassCard className="p-4 space-y-2" data-testid={testId}>
      <div className="flex items-start gap-3">
        <Icon className="w-4 h-4 mt-0.5 text-primary shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-sm text-foreground">{title}</div>
          <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
        </div>
      </div>
      {children}
    </GlassCard>
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
    <div className="flex items-center gap-3 flex-wrap">
      <Button size="sm" onClick={run} disabled={busy} data-testid={testId}>
        {busy ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5 mr-1.5" />}{label}
      </Button>
      {out && <span className="text-xs text-muted-foreground">{out}</span>}
    </div>
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
  if (types === null) return <p className="text-xs text-muted-foreground">Memuat…</p>;
  if (!types.length) return <p className="text-xs text-muted-foreground">Tidak ada jenis akun pembantu yang diatur.</p>;
  return (
    <div className="divide-y divide-[var(--glass-border)]">
      {types.map(([key, cfg]) => {
        const r = res[key];
        return (
          <div key={key} className="py-2 flex items-center gap-3 flex-wrap text-xs" data-testid={`maint-subledger-${key}`}>
            <span className="font-medium text-foreground min-w-[180px]">{cfg.label || key}</span>
            <span className={cfg.enabled ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}>{cfg.enabled ? 'aktif' : 'nonaktif'}</span>
            <div className="ml-auto flex gap-2">
              <Button size="sm" variant="ghost" className="h-8 border border-[var(--glass-border)]" disabled={!!busy} onClick={() => run(key, false)}>
                <Eye className="w-3.5 h-3.5 mr-1" />Pratinjau
              </Button>
              <Button size="sm" className="h-8" disabled={!!busy || !cfg.enabled} title={cfg.enabled ? '' : 'Aktifkan dulu di Pengaturan Keuangan › Pemetaan akun'} onClick={() => run(key, true)}>
                <PlayCircle className="w-3.5 h-3.5 mr-1" />Buat akun
              </Button>
            </div>
            {r && (
              <div className="w-full text-muted-foreground">
                {r.total_entities} data · {r.already_have_account} sudah punya akun · {r.committed ? `${r.created} akun dibuat` : `${r.would_create} akan dibuat`}
                {(r.errors || []).length > 0 && <span className="text-red-500"> · {r.errors.length} gagal</span>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function WipFgBackfill() {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (dryRun) => {
    if (!dryRun && !(await confirmDialog('Posting jurnal WIP → Barang Jadi untuk semua Terima FG dari CMT (PO internal) yang belum berjurnal?'))) return;
    setBusy(true);
    try { setD(await post(`/api/prod/cmt-receipts/backfill-wip-fg?dry_run=${dryRun}`)); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }, []);
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Button size="sm" variant="ghost" className="border border-[var(--glass-border)]" disabled={busy} onClick={() => run(true)} data-testid="maint-wipfg-preview">Lihat kandidat</Button>
        <Button size="sm" disabled={busy || !(d?.dry_run && d?.candidates > 0)} onClick={() => run(false)} data-testid="maint-wipfg-run">Posting sekarang</Button>
      </div>
      {d && (
        <div className="text-xs text-muted-foreground" data-testid="maint-wipfg-result">
          {d.dry_run ? `${d.candidates} kandidat · ${fmt(d.total_value)}` : `${d.posted} jurnal diposting · ${fmt(d.total_value)}`}
          {(d.rows || []).slice(0, 10).map(r => (
            <div key={r.receipt_id} className="font-mono">{r.receipt_code} · {r.po_number} · {fmt(r.value)} → {r.result}{r.je_number ? ` (${r.je_number})` : ''}{r.error ? ` — ${r.error}` : ''}</div>
          ))}
        </div>
      )}
    </div>
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
  const run = async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/rahaza/journals/entity-warnings?entity=ALL&limit=50`, { headers: authH() });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      setData(d);
    } catch (e) { toast.error(e.message); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-2">
      <Button size="sm" variant="outline" onClick={run} disabled={busy} data-testid="maint-cv-check-run">
        {busy ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Eye className="w-3.5 h-3.5 mr-1.5" />}Periksa
      </Button>
      {data && (
        <div className="text-xs space-y-1" data-testid="maint-cv-check-result">
          <p className="text-muted-foreground">
            {data.total ? `${data.total} jurnal otomatis perlu diperiksa (${(data.items || []).length} terbaru ditampilkan).`
              : 'Semua jurnal otomatis cocok dengan CV-nya.'}
          </p>
          {(data.items || []).map((it) => (
            <p key={it.id} className="text-foreground">
              <span className="font-mono">{it.je_number}</span> · {it.entity_label} · {it.date} — {it.entity_warning}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export default function FinanceMaintenanceModule({ onNavigate }) {
  return (
    <div className="space-y-4" data-testid="finance-maintenance">
      <PageHeader
        icon={Settings2}
        title="Perawatan Data Keuangan"
        subtitle="Tombol perbaikan & pengisian massal untuk data keuangan. Jalankan hanya bila diminta Keuangan; semua aman diulang."
      />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Task icon={Landmark} title="Sinkron rekening kas/bank dengan Bagan Akun"
          desc="Membuat rekening untuk akun kas/bank yang belum punya, menautkan rekening lama ke akun buku besarnya, dan menjurnal saldo awal yang belum terjurnal."
          testId="maint-sync-gl">
          <OneShot label="Sinkronkan" path="/api/rahaza/cash-accounts/sync-gl" testId="maint-sync-gl-run"
            describe={(d) => {
              const rep = d.report || [];
              return `${(d.sync?.cash_accounts_created || []).length} rekening baru · ${rep.filter(x => x.opening).length} jurnal saldo awal · ${rep.filter(x => x.error).length} gagal`;
            }} />
        </Task>
        <Task icon={Sparkles} title="Pasang profil jurnal otomatis bawaan"
          desc="Menambah profil jurnal otomatis yang belum ada (faktur, pembayaran, gaji, persediaan…). Profil yang sudah diubah Keuangan tidak ditimpa."
          testId="maint-pp-seed">
          <OneShot label="Pasang bawaan" path="/api/rahaza/posting-profiles/seed" testId="maint-pp-seed-run"
            describe={(d) => `${d.inserted} profil baru · ${d.skipped} sudah ada`} />
        </Task>
        <Task icon={BookOpen} title="Pasang pemetaan akun klaim karyawan bawaan"
          desc="Mengisi pemetaan kategori klaim karyawan → akun beban untuk kategori yang belum dipetakan."
          testId="maint-claims-seed">
          <OneShot label="Pasang bawaan" path="/api/hr/expenses/gl-mappings/seed-default" testId="maint-claims-seed-run"
            describe={(d) => d.message || 'Selesai'} />
        </Task>
        <Task icon={Eye} title="Cek CV jurnal otomatis"
          desc="Jurnal otomatis yang akun atau rekeningnya milik CV lain (mis. bayar faktur CV Dewi Aditya ke rekening CV Sukma). Jurnalnya tetap tersimpan; perbaiki lewat jurnal manual."
          testId="maint-cv-check">
          <EntityWarnings />
        </Task>
        <Task icon={Boxes} title="Jurnal WIP → Barang Jadi yang tertinggal"
          desc="Terima FG dari CMT (PO internal) yang sudah lolos QC tetapi belum berjurnal Persediaan Barang Jadi / WIP."
          testId="maint-wipfg">
          <WipFgBackfill />
        </Task>
      </div>
      <Task icon={Database} title="Buat akun pembantu untuk data lama"
        desc="Membuat akun turunan (per pemasok, pelanggan, dll.) untuk data yang dibuat sebelum fitur akun otomatis aktif. Pengaturannya tetap di Pengaturan Keuangan › Pemetaan akun."
        testId="maint-subledger">
        <SubledgerBackfill />
      </Task>
      <CronJobCard job="mark-overdue" title="Tandai faktur lewat jatuh tempo"
        description="otomatis tiap hari 00:15 WIB untuk faktur penjualan & tagihan pemasok"
        renderResult={(r) => `${r.ar_marked} faktur penjualan · ${r.ap_marked} tagihan pemasok ditandai`} />
      <CronJobCard job="fg-valuation-check" title="Cek nilai persediaan barang jadi vs buku besar"
        description="otomatis tiap hari 07:00 WIB; Keuangan diberi notifikasi bila selisih belum terjelaskan"
        renderResult={(r) => `selisih ${fmt(r.difference)} · belum terjelaskan ${fmt(r.unexplained_difference)}${r.notified ? ' · notifikasi terkirim' : ''}`} />
      {onNavigate && (
        <p className="text-xs text-muted-foreground">
          Pemasangan awal untuk server baru (bagan akun, profil posting, kategori klaim):{' '}
          <button type="button" className="text-primary hover:underline" onClick={() => onNavigate('admin-setup-panel')} data-testid="maint-open-setup">buka Setup Awal</button>.
        </p>
      )}
    </div>
  );
}
