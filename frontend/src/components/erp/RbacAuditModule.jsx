/**
 * Audit RBAC — Persetujuan & Notifikasi (Portal Sysadmin, 2026-08-07).
 *
 * Permintaan owner: "pastikan approval & notifikasi terhubung RBAC — jangan
 * sampai role A menerima notifikasi role B", plus halaman audit agar bisa
 * dipantau sendiri ke depan.
 *
 * Sumber: GET /api/admin/rbac-audit (analisis statis kode + fakta data notifikasi).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, 4 kartu angka StatTile (dulu 11 kotak berwarna di 3 kartu),
 * daftar temuan = tabel dengan unduh Excel/CSV, jenis notifikasi dalam bahasa staf (dulu kode `low_stock`).
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

const JENIS_NOTIF = {
  low_stock: 'Stok menipis', expiring_discount: 'Diskon segera berakhir', ar_due: 'Piutang jatuh tempo',
  sla_breach: 'Lewat batas waktu layanan', stock: 'Stok', contract_expiry: 'Kontrak segera berakhir',
  content_today: 'Konten hari ini', upcoming_launch: 'Peluncuran mendatang', rnd_weekly_decisions: 'Keputusan R&D mingguan',
  negative_stock_daily: 'Stok minus harian', out_of_stock: 'Stok habis', approval: 'Persetujuan',
};
const labelJenis = (k) => JENIS_NOTIF[k]
  || (String(k || '').replace(/[_.-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) || '—');
const PENULIS = { notif_insert: 'Penulis notifikasi umum', publish_notification: 'Penerbit notifikasi' };

/** Satu bagian halaman: judul kecil + alat (unduh) di kanan, isi di bawah. */
function Bagian({ judul, keterangan, alat, children, testId }) {
  return (
    <GlassCard className="space-y-3 p-4" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-foreground">{judul}</h3>
          {keterangan && <p className="text-sm text-muted-foreground">{keterangan}</p>}
        </div>
        {alat && <div className="flex items-center gap-2">{alat}</div>}
      </div>
      {children}
    </GlassCard>
  );
}

const kode = (t) => <span className="break-all font-mono text-xs text-foreground/80">{t}</span>;

export default function RbacAuditModule({ token }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/admin/rbac-audit`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `Kode ${res.status}`);
      setData(body);
    } catch (e) {
      toast.error('Gagal memuat audit akses', { description: e.message });
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const ap = data?.code?.approvals;
  const nw = data?.code?.notification_writers;
  const dt = data?.data;
  const tanpaIzin = ap?.unguarded_items || [];
  const tanpaTarget = nw?.untargeted_items || [];
  const jenis = dt?.top_subtypes || [];
  const sebaran = dt ? [
    { id: 'personal', label: 'Untuk satu orang', n: dt.personal_user_id },
    { id: 'role', label: 'Untuk peran tertentu', n: dt.role_targeted },
    { id: 'daftar', label: 'Untuk daftar orang', n: dt.user_list_targeted },
    { id: 'tanpa', label: 'Tanpa target (hanya admin/owner)', n: dt.untargeted },
  ] : [];
  const angka = (v) => (v === undefined || v === null ? '—' : v);

  return (
    <PageLayout testId="rbac-audit-module" title="Audit persetujuan & notifikasi"
      subtitle="Siapa boleh memutuskan dan siapa menerima notifikasi — diperiksa langsung dari kode dan data."
      tools={(
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Periksa ulang" aria-label="Periksa ulang"
          data-testid="rbac-audit-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Titik keputusan tanpa izin" value={angka(ap?.unguarded)} accent={ap?.unguarded ? 'danger' : 'default'}
            sub={`dari ${angka(ap?.total)} titik keputusan; ${angka(ap?.guarded)} dijaga izin`} testId="rbac-approvals-unguarded" />
          <StatTile label="Penulis notifikasi tanpa target" value={angka(nw?.untargeted)} accent={nw?.untargeted ? 'warning' : 'default'}
            sub={`dari ${angka(nw?.total)} tempat penulisan di kode`} testId="rbac-writers-untargeted" />
          <StatTile label="Notifikasi tersimpan" value={angka(dt?.total)}
            sub={`${angka(dt?.role_targeted)} per peran · ${angka(dt?.personal_user_id)} perorangan`} testId="rbac-data-total" />
          <StatTile label="Notifikasi tanpa target" value={angka(dt?.untargeted)} accent={dt?.untargeted ? 'danger' : 'default'}
            sub="Hanya terlihat oleh admin/owner" testId="rbac-data-untargeted" />
        </div>
      )}>
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memeriksa kode dan data…</p>
      ) : !data ? (
        <EmptyState title="Audit belum bisa dimuat" description="Coba periksa ulang beberapa saat lagi."
          action={{ label: 'Periksa ulang', onClick: load }} />
      ) : (
        <>
          <Notice tone="info" title="Aturan penerima notifikasi" testId="rbac-audit-rule">{data.audience_rule}</Notice>

          {(data.findings || []).length > 0 && (
            <div className="space-y-2" data-testid="rbac-audit-findings">
              {data.findings.map((f, i) => (
                <Notice key={i} tone={f.level === 'ok' ? 'success' : f.level === 'warning' ? 'warning' : 'info'} title={f.title}>
                  {f.detail}
                </Notice>
              ))}
            </div>
          )}

          <Bagian testId="rbac-audit-approvals" judul="Titik keputusan tanpa gerbang izin"
            keterangan={`Setujui, tolak, dan konfirmasi yang hanya butuh "sudah masuk akun". ${angka(ap?.guarded)} dari ${angka(ap?.total)} sudah dijaga izin.`}
            alat={tanpaIzin.length > 0 && (
              <TombolUnduh namaBerkas="audit-keputusan-tanpa-izin" namaLembar="Tanpa izin" baris={tanpaIzin} testId="rbac-unguarded-unduh"
                kolom={[
                  { label: 'Metode', nilai: (r) => r.method }, { label: 'Alamat', nilai: (r) => r.route },
                  { label: 'Fungsi', nilai: (r) => r.func }, { label: 'Berkas', nilai: (r) => `${r.file}:${r.line}` },
                ]} />
            )}>
            <TabelData testId="rbac-unguarded-table" baris={tanpaIzin} kunci={(r) => `${r.file}-${r.line}-${r.func}`}
              kosong={<p className="text-sm text-muted-foreground">Semua titik keputusan sudah dijaga izin.</p>}
              kolom={[
                { kunci: 'route', label: 'Alamat', hp: 'judul', isi: (r) => kode(r.route) },
                { kunci: 'method', label: 'Metode', isi: (r) => <span className="text-xs">{r.method}</span> },
                { kunci: 'func', label: 'Fungsi', isi: (r) => kode(r.func) },
                { kunci: 'file', label: 'Berkas', isi: (r) => kode(`${r.file}:${r.line}`) },
              ]} />
          </Bagian>

          <Bagian testId="rbac-audit-writers" judul="Penulisan notifikasi tanpa target penerima"
            keterangan={`Tanpa target, notifikasi hanya sampai ke admin/owner. ${angka(nw?.targeted)} dari ${angka(nw?.total)} sudah bertarget.`}
            alat={tanpaTarget.length > 0 && (
              <TombolUnduh namaBerkas="audit-notifikasi-tanpa-target" namaLembar="Tanpa target" baris={tanpaTarget} testId="rbac-untargeted-unduh"
                kolom={[
                  { label: 'Penulis', nilai: (r) => PENULIS[r.writer] || r.writer }, { label: 'Berkas', nilai: (r) => `${r.file}:${r.line}` },
                  { label: 'Potongan kode', nilai: (r) => r.snippet },
                ]} />
            )}>
            <TabelData testId="rbac-untargeted-list" baris={tanpaTarget} kunci={(r) => `${r.file}-${r.line}`}
              kosong={<p className="text-sm text-muted-foreground">Semua penulisan notifikasi sudah punya target penerima.</p>}
              kolom={[
                { kunci: 'file', label: 'Berkas', hp: 'judul', isi: (r) => kode(`${r.file}:${r.line}`) },
                { kunci: 'writer', label: 'Penulis', isi: (r) => <span className="text-sm">{PENULIS[r.writer] || r.writer}</span> },
                { kunci: 'snippet', label: 'Potongan kode', isi: (r) => <p className="line-clamp-2 font-mono text-xs text-muted-foreground md:max-w-[32rem]" title={r.snippet}>{r.snippet}</p> },
              ]} />
          </Bagian>

          <div className="grid gap-4 lg:grid-cols-2">
            <Bagian testId="rbac-audit-data" judul="Notifikasi tersimpan menurut target"
              alat={<TombolUnduh namaBerkas="notifikasi-menurut-target" namaLembar="Target" baris={sebaran} testId="rbac-data-unduh"
                kolom={[{ label: 'Target', nilai: (r) => r.label }, { label: 'Jumlah', nilai: (r) => r.n ?? 0 }]} />}>
              <TabelData testId="rbac-data-target" baris={sebaran} kolom={[
                { kunci: 'label', label: 'Target', hp: 'judul' },
                { kunci: 'n', label: 'Jumlah', rata: 'kanan', isi: (r) => <span className="tabular-nums">{angka(r.n)}</span> },
              ]} />
            </Bagian>
            <Bagian testId="rbac-data-subtypes" judul="Jenis notifikasi terbanyak"
              alat={jenis.length > 0 && <TombolUnduh namaBerkas="jenis-notifikasi" namaLembar="Jenis" baris={jenis} testId="rbac-subtypes-unduh"
                kolom={[{ label: 'Jenis', nilai: (s) => labelJenis(s.subtype) }, { label: 'Jumlah', nilai: (s) => s.count }]} />}>
              <TabelData baris={jenis} kunci={(s) => s.subtype}
                kosong={<p className="text-sm text-muted-foreground">Belum ada notifikasi tersimpan.</p>}
                kolom={[
                  { kunci: 'subtype', label: 'Jenis', hp: 'judul', isi: (s) => labelJenis(s.subtype) },
                  { kunci: 'count', label: 'Jumlah', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.count}</span> },
                ]} />
            </Bagian>
          </div>
        </>
      )}
    </PageLayout>
  );
}
