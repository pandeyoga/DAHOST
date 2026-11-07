/**
 * Log Aktivitas (Administrasi Sistem) — rekam jejak aktivitas pengguna.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, daftar = tabel (kartu ringkas di HP),
 * detail = popup, unduh Excel/CSV, nama aksi & modul dalam bahasa staf (dulu tampil kode program seperti
 * `create_journal`, `rahaza.model`).
 * Perbaikan kartu angka: dulu menghitung aksi persis "Create"/"Update"/"Delete" (huruf besar) sehingga 56 aksi
 * `create` dan semua `create_journal`/`delete_account` tidak terhitung. Kini dihitung per golongan aksi dari daftar
 * yang tampil (mengikuti saringan).
 */
import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from './finance/PeriodPicker';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const BATAS = 500;

// ─── Nama modul & aksi dalam bahasa staf ─────────────────────────────────────
const NAMA_MODUL = {
  Auth: 'Masuk akun', journal: 'Jurnal', coa: 'Daftar akun (COA)', 'rahaza.model': 'Model produk', master: 'Data induk',
  marketing_account: 'Akun marketing', 'rahaza.employee': 'Karyawan', rahaza_suppliers: 'Pemasok', vendor_portal: 'Portal vendor',
  'sales.customer': 'Pelanggan penjualan', accruals: 'Akrual', 'rahaza.bom': 'BOM', 'rahaza.po': 'PO produksi',
  'dewi-maklon': 'Maklon', bank_transfer: 'Transfer bank', wh_opname3_sessions: 'Opname gudang', 'rahaza.customer': 'Pelanggan',
  'Production PO': 'PO produksi', 'cmt-permak': 'Permak CMT', 'cutting.order': 'Order potong', wh_building: 'Gedung gudang',
  wh_rack: 'Rak gudang', wh_zone: 'Zona gudang', marketing_livehost_script: 'Naskah live host',
  marketing_livehost_training: 'Pelatihan live host', 'rahaza.leave': 'Cuti', periods: 'Periode buku',
  posting_profile: 'Profil posting', petty_cash_txn: 'Kas kecil', hr_inbox: 'Kotak masuk SDM', 'Work Order': 'Perintah kerja',
  'Production Progress': 'Progres produksi', Garments: 'Garmen', Products: 'Produk', Invoice: 'Faktur', Payment: 'Pembayaran',
  'User Management': 'Pengguna',
};
const KATA = {
  create: 'buat', created: 'dibuat', add: 'tambah', update: 'ubah', edit: 'ubah', delete: 'hapus', remove: 'hapus', login: 'masuk',
  logout: 'keluar', approve: 'setujui', reject: 'tolak', submit: 'ajukan', cancel: 'batalkan', void: 'batalkan', archive: 'arsipkan',
  deactivate: 'nonaktifkan', activate: 'aktifkan', save: 'simpan', upload: 'unggah', image: 'gambar', journal: 'jurnal',
  account: 'akun', draft: 'draf', auto: 'otomatis', sync: 'sinkron', master: 'data induk', apply: 'terapkan', fill: 'isi',
  close: 'tutup', reopen: 'buka lagi', period: 'periode', post: 'posting', opening: 'awal', balance: 'saldo', bank: 'bank',
  transfer: 'transfer', posting: 'posting', profile: 'profil', vendor: 'vendor', partner: 'mitra', template: 'templat',
  lines: 'baris', copy: 'salin', missing: 'yang kurang', catalog: 'katalog', buyer: 'pembeli', generate: 'buat',
  variants: 'varian', discontinue: 'hentikan', employee: 'karyawan', advance: 'kasbon', petty: 'kas', cash: 'kecil',
  settle: 'selesaikan', dept: 'departemen', model: 'model', order: 'order', customer: 'pelanggan', supplier: 'pemasok',
  suppliers: 'pemasok', user: 'pengguna', users: 'pengguna', role: 'peran', settings: 'pengaturan', import: 'impor',
  export: 'unduh', payment: 'pembayaran', invoice: 'faktur', sop: 'SOP', coa: 'COA', bom: 'BOM', po: 'PO', cmt: 'CMT',
  wh: 'gudang', opname: 'opname', opname3: 'opname', sessions: 'sesi', building: 'gedung', rack: 'rak', zone: 'zona',
  rahaza: '', txn: 'transaksi', backfill: 'isi ulang', subledger: 'buku pembantu', vendor_portal: 'portal vendor', inbox: 'kotak masuk', hr: 'SDM', livehost: 'live host', script: 'naskah', training: 'pelatihan',
  marketing: 'marketing', sales: 'penjualan', leave: 'cuti', accruals: 'akrual', periods: 'periode', cutting: 'potong',
};
const ALIAS_AKSI = { 'ganti sandi': 'Ganti sandi', login: 'Masuk', employee_advance: 'Kasbon karyawan', petty_cash_advance_settle: 'Penyelesaian kas kecil' };

const kalimat = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
function terjemah(kode) {
  const kata = String(kode || '').toLowerCase().split(/[._\-\s]+/).filter(Boolean).map((w) => (w in KATA ? KATA[w] : w));
  return kalimat(kata.filter(Boolean).join(' ').replace(/\s+/g, ' ').trim());
}
export function labelModul(m) {
  if (!m) return '—';
  return NAMA_MODUL[m] || terjemah(m) || m;
}
export function labelAksi(a) {
  if (!a) return '—';
  const [utama, ...sisa] = String(a).split(':');
  const kunci = utama.trim().toLowerCase();
  const dasar = ALIAS_AKSI[kunci] || terjemah(utama);
  return sisa.length ? `${dasar} · ${sisa.join(':')}` : dasar;
}

/** Golongan aksi untuk warna lencana dan kartu angka. */
export function golonganAksi(a) {
  const s = String(a || '').toLowerCase();
  if (s === 'login') return 'masuk';
  if (/^(delete|remove|void|cancel|deactivate|archive)/.test(s) || s.includes('delete')) return 'hapus';
  if (/^(create|add|auto_create|generate|opname_create|bom_add|post_opening)/.test(s) || s.startsWith('create')) return 'buat';
  if (/^(update|edit|save|fill|upload|bom_copy)/.test(s)) return 'ubah';
  return 'lain';
}
const NADA = { buat: 'success', ubah: 'primary', hapus: 'danger', masuk: 'info', lain: 'default' };

// Waktu dari server tersimpan UTC tetapi dikirim tanpa zona ("2026-11-07T22:19:14") → baca sebagai UTC,
// bukan jam perangkat (dulu tampil mundur 7 jam di perangkat WIB).
const instan = (ts) => (typeof ts === 'string' && /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(ts) ? `${ts}Z` : ts);
const waktu = (ts) => formatDateTimeID(instan(ts));
const tanggalWIB = (ts) => {
  const d = new Date(instan(ts));
  return Number.isNaN(d.getTime()) ? '' : new Date(d.getTime() + 7 * 3600 * 1000).toISOString().slice(0, 10);
};

export default function ActivityLogModule({ token }) {
  const [logs, setLogs] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [galat, setGalat] = useState('');
  const [semuaModul, setSemuaModul] = useState([]);
  const [filterModule, setFilterModule] = useState('');
  const [filterUser, setFilterUser] = useState('');
  const [filterAction, setFilterAction] = useState('');
  const [searchText, setSearchText] = useState('');
  const [periode, setPeriode] = useState(() => periodFromPreset('all'));
  const [detail, setDetail] = useState(null);

  // Modul & pengguna disaring di server (parameter API yang sudah ada); sisanya di layar.
  const fetchLogs = async () => {
    setLoading(true);
    setGalat('');
    try {
      const params = new URLSearchParams({ limit: String(BATAS) });
      if (filterModule) params.append('module', filterModule);
      if (filterUser) params.append('user_id', filterUser);
      const res = await fetch(`/api/activity-logs?${params}`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      const list = Array.isArray(data) ? data : [];
      setLogs(list);
      if (!res.ok) setGalat('Log aktivitas tidak bisa dimuat. Coba muat ulang.');
      // Daftar modul tetap lengkap walau sedang menyaring satu modul.
      setSemuaModul((prev) => [...new Set([...prev, ...list.map((l) => l.module).filter(Boolean)])]);
    } catch {
      setGalat('Log aktivitas tidak bisa dimuat. Coba muat ulang.');
    } finally {
      setLoading(false);
    }
  };

  const fetchUsers = async () => {
    try {
      const res = await fetch('/api/users', { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      setUsers(Array.isArray(data) ? data : []);
    } catch { /* pilihan pengguna kosong */ }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchUsers(); }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchLogs(); }, [filterModule, filterUser]);

  const actions = useMemo(() => [...new Set(logs.map((l) => l.action).filter(Boolean))]
    .sort((a, b) => labelAksi(a).localeCompare(labelAksi(b), 'id')), [logs]);

  const filtered = useMemo(() => logs.filter((l) => {
    if (filterAction && l.action !== filterAction) return false;
    if (searchText) {
      const q = searchText.toLowerCase();
      const teks = `${l.details || ''} ${l.user_name || ''} ${l.module || ''} ${labelModul(l.module)} ${labelAksi(l.action)}`;
      if (!teks.toLowerCase().includes(q)) return false;
    }
    const tgl = tanggalWIB(l.timestamp);
    if (periode.from && tgl && tgl < periode.from) return false;
    if (periode.to && tgl && tgl > periode.to) return false;
    return true;
  }), [logs, filterAction, searchText, periode]);

  const hitung = useMemo(() => {
    const h = { buat: 0, ubah: 0, hapus: 0, masuk: 0, lain: 0 };
    filtered.forEach((l) => { h[golonganAksi(l.action)] += 1; });
    return h;
  }, [filtered]);

  const adaSaringan = !!(searchText || filterAction || filterModule || filterUser || periode.preset !== 'all');
  const resetSaringan = () => {
    setSearchText(''); setFilterAction(''); setFilterModule(''); setFilterUser(''); setPeriode(periodFromPreset('all'));
  };

  const kolom = [
    { kunci: 'waktu', label: 'Waktu', hp: 'keterangan', isi: (l) => <span className="whitespace-nowrap text-sm tabular-nums">{waktu(l.timestamp)}</span> },
    { kunci: 'pengguna', label: 'Pengguna', hp: 'judul', isi: (l) => <span className="font-medium">{l.user_name || '—'}</span> },
    { kunci: 'aksi', label: 'Aksi', isi: (l) => <StatusBadge status={golonganAksi(l.action)} label={labelAksi(l.action)} tone={NADA[golonganAksi(l.action)]} className="max-w-[16rem] truncate" /> },
    { kunci: 'modul', label: 'Modul', isi: (l) => <span className="text-sm">{labelModul(l.module)}</span> },
    { kunci: 'rincian', label: 'Rincian', isi: (l) => <p className="line-clamp-2 text-sm text-muted-foreground md:max-w-[28rem]" title={l.details}>{l.details || '—'}</p> },
  ];

  const keteranganKartu = `Dari ${filtered.length} aktivitas di daftar (${BATAS} terbaru, mengikuti saringan).`;

  return (
    <PageLayout testId="activity-log-module" title="Log aktivitas"
      subtitle="Rekam jejak aktivitas pengguna: siapa, melakukan apa, di modul mana, dan kapan."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={searchText} onChange={(e) => setSearchText(e.target.value)} placeholder="Cari rincian, pengguna, modul"
            className="pl-8" data-testid="activity-log-search" />
        </div>
        <SmartNativeSelect value={filterModule} onChange={(e) => setFilterModule(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-48"
          aria-label="Modul" data-testid="activity-log-module-filter">
          <option value="">Semua modul</option>
          {semuaModul.map((m) => <option key={m} value={m}>{labelModul(m)}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterUser} onChange={(e) => setFilterUser(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-52"
          aria-label="Pengguna" data-testid="activity-log-user-filter">
          <option value="">Semua pengguna</option>
          {users.map((u) => <option key={u.id} value={u.id}>{`${u.name} - ${u.email}`}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterAction} onChange={(e) => setFilterAction(e.target.value)} className="w-full" wrapperClassName="w-full sm:w-44"
          aria-label="Aksi" data-testid="activity-log-action-filter">
          <option value="">Semua aksi</option>
          {actions.map((a) => <option key={a} value={a}>{labelAksi(a)}</option>)}
        </SmartNativeSelect>
        <PeriodPicker value={periode} onChange={setPeriode} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="activity-log-period" />
        {adaSaringan && (
          <Button variant="link" size="sm" onClick={resetSaringan} data-testid="activity-log-reset">Hapus saringan</Button>
        )}
      </>}
      tools={<>
        <TombolUnduh namaBerkas="log-aktivitas" namaLembar="Log aktivitas" baris={filtered} testId="activity-log-unduh"
          kolom={[
            { label: 'Waktu', nilai: (l) => waktu(l.timestamp) },
            { label: 'Pengguna', nilai: (l) => l.user_name || '' },
            { label: 'Aksi', nilai: (l) => labelAksi(l.action) },
            { label: 'Modul', nilai: (l) => labelModul(l.module) },
            { label: 'Rincian', nilai: (l) => l.details || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchLogs} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="activity-log-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={filtered.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="activity-log-stats">
          <StatTile label="Dibuat" value={hitung.buat} hint={keteranganKartu} testId="activity-stat-buat" />
          <StatTile label="Diubah" value={hitung.ubah} hint={keteranganKartu} testId="activity-stat-ubah" />
          <StatTile label="Dihapus / dibatalkan" value={hitung.hapus} hint={keteranganKartu} testId="activity-stat-hapus" />
          <StatTile label="Masuk akun" value={hitung.masuk} hint={keteranganKartu} testId="activity-stat-masuk" />
        </div>
      )}>
      {galat && <p className="text-sm text-[hsl(var(--danger-text))]" role="alert">{galat}</p>}
      {loading && logs.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat log aktivitas…</p>
      ) : (
        <>
          {filtered.length > 0 && (
            <p className="text-xs text-muted-foreground" data-testid="activity-log-count">
              {filtered.length} aktivitas tampil{logs.length >= BATAS ? ` · daftar memuat ${BATAS} aktivitas terbaru` : ''}.
            </p>
          )}
          <TabelData kolom={kolom} baris={filtered} onKlikBaris={setDetail} testId="activity-log-table"
            kosong={<EmptyState title={logs.length ? 'Tidak ada aktivitas yang cocok' : 'Belum ada aktivitas'}
              description={logs.length ? 'Ubah saringan atau kata pencarian.' : 'Aktivitas pengguna akan tercatat di sini.'}
              action={adaSaringan ? { label: 'Hapus saringan', onClick: resetSaringan } : undefined} />} />
        </>
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={labelAksi(detail.action)} testId="activity-log-detail"
          keterangan={waktu(detail.timestamp)}
          status={<StatusBadge status={golonganAksi(detail.action)} label={labelModul(detail.module)} tone={NADA[golonganAksi(detail.action)]} />}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Pengguna">{detail.user_name || '—'}</BarisDetail>
            <BarisDetail label="Aksi">{labelAksi(detail.action)}</BarisDetail>
            <BarisDetail label="Modul">{labelModul(detail.module)}</BarisDetail>
            <BarisDetail label="Waktu">{waktu(detail.timestamp)}</BarisDetail>
            <BarisDetail label="Rincian"><span className="whitespace-pre-wrap break-words">{detail.details || '—'}</span></BarisDetail>
          </dl>
        </DetailPopup>
      )}
    </PageLayout>
  );
}
