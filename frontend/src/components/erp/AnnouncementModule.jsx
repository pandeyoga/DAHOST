/**
 * Papan Pengumuman (Portal SDM) — kelola pengumuman yang tampil di halaman pilih portal.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026): cetakan PageLayout, kepala tipis, penyaring satu baris,
 * daftar = tabel (kartu ringkas di HP), detail = popup, form = popup standar, pemilih tanggal seragam,
 * hapus lewat konfirmasi, bahasa Indonesia, tombol Simpan hijau / Hapus merah.
 *
 * Perbaikan data yang ikut (lihat routes/announcements.py):
 *  • tanggal dibaca sebagai WIB dari waktu berzona (dulu tampil mundur sehari & bergeser tiap disimpan);
 *  • tanggal berakhir = sampai akhir hari WIB (dulu berhenti pukul 07.00 WIB di hari itu);
 *  • tanggal bisa dikosongkan; hapus benar-benar menghapus; daftar tujuan berisi 16 portal (dulu 9).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, Power, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { cn } from '@/lib/utils';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import { NAMA_PORTAL } from './portalAccess';
import { instan, ymd, keadaanPengumuman, KEADAAN, labelPeriode, labelTujuan } from './pengumuman/aturan';
import { AnnouncementItem, JENIS_PENGUMUMAN } from './AnnouncementBoard';

const API = process.env.REACT_APP_BACKEND_URL;
function JenisBadge({ jenis }) {
  const j = JENIS_PENGUMUMAN[jenis] || JENIS_PENGUMUMAN.info;
  return <StatusBadge status={jenis} label={j.label} tone={j.tone} />;
}

async function panggil(path, { method = 'GET', body } = {}) {
  const token = localStorage.getItem('erp_token');
  const res = await fetch(`${API}/api/announcements${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let pesan = 'Permintaan gagal. Coba lagi.';
    try { const d = await res.json(); if (typeof d.detail === 'string') pesan = d.detail; } catch { /* abaikan */ }
    throw new Error(pesan);
  }
  return res.status === 204 ? null : res.json();
}

// ─── Form (popup standar) ────────────────────────────────────────────────────
const KOSONG = { title: '', content: '', type: 'info', priority: 0, target_portals: ['all'], is_active: true, mulai: '', akhir: '' };

function FormPengumuman({ open, awal, onClose, onTersimpan }) {
  const ubah = !!awal?.id;
  const [f, setF] = useState(KOSONG);
  const [galat, setGalat] = useState({});
  const [menyimpan, setMenyimpan] = useState(false);

  useEffect(() => {
    if (!open) return;
    setGalat({});
    setF(awal?.id ? {
      title: awal.title || '', content: awal.content || '', type: awal.type || 'info',
      priority: awal.priority ?? 0, target_portals: awal.target_portals?.length ? awal.target_portals : ['all'],
      is_active: awal.is_active ?? true, mulai: ymd(awal.start_date), akhir: ymd(awal.end_date),
    } : KOSONG);
  }, [open, awal]);

  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }));
  const pilihPortal = (id) => setF((s) => {
    if (id === 'all') return { ...s, target_portals: ['all'] };
    const kini = s.target_portals.filter((p) => p !== 'all');
    const baru = kini.includes(id) ? kini.filter((p) => p !== id) : [...kini, id];
    return { ...s, target_portals: baru.length ? baru : ['all'] };
  });

  const simpan = async () => {
    const g = {};
    if (!f.title.trim()) g.title = 'Judul wajib diisi.';
    if (!f.content.trim()) g.content = 'Isi pengumuman wajib diisi.';
    if (f.mulai && f.akhir && f.akhir < f.mulai) g.akhir = 'Tanggal berakhir tidak boleh sebelum tanggal mulai.';
    setGalat(g);
    if (Object.keys(g).length) return;
    setMenyimpan(true);
    try {
      const body = {
        title: f.title.trim(), content: f.content.trim(), type: f.type, priority: Number(f.priority) || 0,
        target_portals: f.target_portals, is_active: f.is_active,
        // Tanggal kalender WIB: mulai pukul 00.00, berakhir sampai 23.59.59 di hari itu.
        start_date: f.mulai ? `${f.mulai}T00:00:00+07:00` : null,
        end_date: f.akhir ? `${f.akhir}T23:59:59+07:00` : null,
      };
      await panggil(ubah ? `/${awal.id}` : '/', { method: ubah ? 'PUT' : 'POST', body });
      toast.success(ubah ? 'Pengumuman disimpan.' : 'Pengumuman dibuat.');
      onTersimpan();
      onClose();
    } catch (e) {
      setGalat({ umum: e.message });
    } finally {
      setMenyimpan(false);
    }
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" onSimpan={simpan} menyimpan={menyimpan}
      judul={ubah ? 'Ubah pengumuman' : 'Buat pengumuman'}
      keterangan="Tampil di halaman pilih portal bagi orang yang bisa membuka portal tujuan."
      labelSimpan={ubah ? 'Simpan perubahan' : 'Buat pengumuman'} galat={galat.umum} testId="form-pengumuman">
      <Isian label="Judul" wajib htmlFor="png-judul" galat={galat.title}>
        <Input id="png-judul" value={f.title} maxLength={200} onChange={(e) => set('title')(e.target.value)}
          placeholder="Contoh: Libur nasional 10 November" data-testid="announcement-title-input" />
      </Isian>
      <Isian label="Isi pengumuman" wajib htmlFor="png-isi" galat={galat.content}>
        <Textarea id="png-isi" rows={4} value={f.content} onChange={(e) => set('content')(e.target.value)}
          placeholder="Tulis informasinya dengan jelas: apa, kapan, siapa yang terkena." data-testid="announcement-content-input" />
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Jenis" htmlFor="png-jenis" petunjuk="Menentukan warna di papan.">
          <SmartNativeSelect id="png-jenis" value={f.type} onChange={(e) => set('type')(e.target.value)}
            data-testid="announcement-type-select">
            {Object.entries(JENIS_PENGUMUMAN).map(([k, j]) => <option key={k} value={k}>{j.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Prioritas" htmlFor="png-prioritas" petunjuk="0–10. Angka lebih besar tampil lebih atas.">
          <Input id="png-prioritas" type="number" inputMode="numeric" min={0} max={10} value={f.priority}
            onChange={(e) => set('priority')(Math.max(0, Math.min(10, parseInt(e.target.value, 10) || 0)))}
            data-testid="announcement-priority-input" />
        </Isian>
        <Isian label="Mulai tampil" petunjuk="Kosong = tampil sejak disimpan.">
          <DatePicker value={f.mulai} onChange={set('mulai')} placeholder="Langsung" testId="announcement-start-date" />
        </Isian>
        <Isian label="Berhenti tampil" galat={galat.akhir} petunjuk="Tampil sampai akhir hari itu (WIB). Kosong = tanpa batas.">
          <DatePicker value={f.akhir} onChange={set('akhir')} min={f.mulai || undefined} placeholder="Tanpa batas"
            testId="announcement-end-date" />
        </Isian>
      </div>
      <Isian label="Tampil untuk" petunjuk="Hanya orang yang bisa membuka portal terpilih yang melihat pengumuman ini.">
        <div className="flex flex-wrap gap-1.5" data-testid="announcement-portals">
          {[{ id: 'all', nama: 'Semua portal' }, ...NAMA_PORTAL].map((p) => {
            const aktif = f.target_portals.includes(p.id);
            return (
              <button key={p.id} type="button" onClick={() => pilihPortal(p.id)} aria-pressed={aktif}
                data-testid={`portal-toggle-${p.id}`}
                className={cn('rounded-full border px-3 py-1 text-sm transition-colors',
                  aktif ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-[var(--glass-border)] bg-[var(--card-surface)] text-foreground hover:border-[hsl(var(--primary)/0.4)]')}>
                {p.nama}
              </button>
            );
          })}
        </div>
      </Isian>
      <label className="flex items-center gap-3 text-sm" htmlFor="png-aktif">
        <Switch id="png-aktif" checked={f.is_active} onCheckedChange={set('is_active')} data-testid="announcement-active-checkbox" />
        <span>Aktif — tampil di papan sesuai periode</span>
      </label>
    </FormPopup>
  );
}

// ─── Halaman ─────────────────────────────────────────────────────────────────
export default function AnnouncementModule() {
  const [data, setData] = useState([]);
  const [memuat, setMemuat] = useState(true);
  const [saring, setSaring] = useState('');
  const [cari, setCari] = useState('');
  const [form, setForm] = useState(null);        // null | {} (baru) | pengumuman (ubah)
  const [detail, setDetail] = useState(null);

  const muat = useCallback(async () => {
    setMemuat(true);
    try {
      setData(await panggil('/all?limit=200'));
    } catch (e) {
      toast.error(e.message || 'Gagal memuat pengumuman.');
    } finally {
      setMemuat(false);
    }
  }, []);
  useEffect(() => { muat(); }, [muat]);

  const denganKeadaan = useMemo(() => data.map((a) => ({ ...a, keadaan: keadaanPengumuman(a) })), [data]);
  const hitung = (k) => denganKeadaan.filter((a) => a.keadaan === k).length;
  const opsi = [
    { key: '', label: 'Semua', count: denganKeadaan.length },
    { key: 'tampil', label: 'Sedang tampil', count: hitung('tampil') },
    { key: 'terjadwal', label: 'Terjadwal', count: hitung('terjadwal') },
    { key: 'berakhir', label: 'Berakhir', count: hitung('berakhir') },
    { key: 'nonaktif', label: 'Nonaktif', count: hitung('nonaktif') },
  ];
  const q = cari.trim().toLowerCase();
  const baris = denganKeadaan
    .filter((a) => !saring || a.keadaan === saring)
    .filter((a) => !q || `${a.title} ${a.content}`.toLowerCase().includes(q));

  const alihAktif = async (a) => {
    try {
      await panggil(`/${a.id}/toggle`, { method: 'POST' });
      toast.success(a.is_active ? 'Pengumuman dinonaktifkan.' : 'Pengumuman diaktifkan.');
      setDetail(null);
      muat();
    } catch (e) { toast.error(e.message); }
  };
  const hapus = async (a) => {
    const ok = await confirmDialog({
      title: 'Hapus pengumuman ini?', body: `"${a.title}" hilang dari papan dan dari daftar ini.`,
      confirmLabel: 'Hapus', danger: true,
    });
    if (!ok) return;
    try {
      await panggil(`/${a.id}`, { method: 'DELETE' });
      toast.success('Pengumuman dihapus.');
      setDetail(null);
      muat();
    } catch (e) { toast.error(e.message); }
  };

  const kolom = [
    { kunci: 'judul', label: 'Pengumuman', hp: 'judul', isi: (a) => (
      <div className="min-w-0 md:max-w-[22rem]">
        <p className="truncate font-medium text-foreground" title={a.title}>{a.title}</p>
        <p className="hidden truncate text-xs text-muted-foreground md:block" title={a.content}>{a.content}</p>
      </div>) },
    { kunci: 'jenis', label: 'Jenis', isi: (a) => <JenisBadge jenis={a.type} /> },
    { kunci: 'tujuan', label: 'Tampil untuk', isi: (a) => <span className="text-sm">{labelTujuan(a.target_portals)}</span> },
    { kunci: 'periode', label: 'Periode', isi: (a) => <span className="text-sm md:whitespace-nowrap">{labelPeriode(a)}</span> },
    { kunci: 'prioritas', label: 'Prioritas', rata: 'kanan', isi: (a) => <span className="tabular-nums">{a.priority}</span> },
    { kunci: 'keadaan', label: 'Status', isi: (a) => <StatusBadge status={a.keadaan} label={KEADAAN[a.keadaan].label} tone={KEADAAN[a.keadaan].tone} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (a) => (
      <Button size="sm" variant="outline" onClick={() => setForm(a)} data-testid={`edit-btn-${a.id}`}>
        <Pencil />Ubah
      </Button>) },
  ];

  return (
    <PageLayout testId="announcement-module" title="Papan pengumuman"
      subtitle="Pengumuman di halaman pilih portal, untuk portal yang bisa dibuka tiap orang."
      actions={<Button onClick={() => setForm({})} data-testid="create-announcement-btn"><Plus />Buat pengumuman</Button>}
      filters={<>
        <FilterChips options={opsi} value={saring} onChange={setSaring} hideWhenEmpty={false} testId="announcement-filter" />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari judul atau isi"
            className="pl-8" data-testid="announcement-search" />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="papan-pengumuman" namaLembar="Pengumuman" baris={baris} testId="announcement-unduh"
          kolom={[
            { label: 'Judul', nilai: (a) => a.title },
            { label: 'Isi', nilai: (a) => a.content },
            { label: 'Jenis', nilai: (a) => (JENIS_PENGUMUMAN[a.type] || JENIS_PENGUMUMAN.info).label },
            { label: 'Tampil untuk', nilai: (a) => labelTujuan(a.target_portals, 99) },
            { label: 'Periode', nilai: (a) => labelPeriode(a) },
            { label: 'Prioritas', nilai: (a) => a.priority },
            { label: 'Status', nilai: (a) => KEADAAN[a.keadaan].label },
            { label: 'Dibuat oleh', nilai: (a) => a.created_by_name || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={muat} disabled={memuat} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {memuat && data.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat pengumuman…</p>
      ) : (
        <TabelData kolom={kolom} baris={baris} onKlikBaris={setDetail} testId="announcement-table"
          kosong={<EmptyState title={data.length ? 'Tidak ada pengumuman yang cocok' : 'Belum ada pengumuman'}
            description={data.length ? 'Ubah saringan atau kata pencarian.' : 'Buat pengumuman pertama untuk ditampilkan di halaman pilih portal.'}
            action={!data.length && <Button onClick={() => setForm({})}><Plus />Buat pengumuman</Button>} />} />
      )}

      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.title} testId="announcement-detail"
          status={<><JenisBadge jenis={detail.type} />
            <StatusBadge status={detail.keadaan} label={KEADAAN[detail.keadaan].label} tone={KEADAAN[detail.keadaan].tone} /></>}
          aksi={<>
            <Button size="sm" variant="outline" onClick={() => { setForm(detail); setDetail(null); }}><Pencil />Ubah</Button>
            <Button size="sm" variant="outline" onClick={() => alihAktif(detail)} data-testid="announcement-toggle"><Power />{detail.is_active ? 'Nonaktifkan' : 'Aktifkan'}</Button>
            <Button size="sm" variant="destructive" onClick={() => hapus(detail)} data-testid="announcement-delete"><Trash2 />Hapus</Button>
          </>}>
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">Tampilan di papan</p>
            <AnnouncementItem announcement={detail} />
          </div>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Tampil untuk">{labelTujuan(detail.target_portals, 99)}</BarisDetail>
            <BarisDetail label="Periode">{labelPeriode(detail)}</BarisDetail>
            <BarisDetail label="Prioritas">{detail.priority} <span className="text-muted-foreground">(lebih besar = lebih atas)</span></BarisDetail>
            <BarisDetail label="Dibuat">{formatDateTimeID(instan(detail.created_at))}{detail.created_by_name ? ` · ${detail.created_by_name}` : ''}</BarisDetail>
            {detail.updated_at && <BarisDetail label="Terakhir diubah">{formatDateTimeID(instan(detail.updated_at))}</BarisDetail>}
          </dl>
        </DetailPopup>
      )}

      <FormPengumuman open={form !== null} awal={form} onClose={() => setForm(null)} onTersimpan={muat} />
    </PageLayout>
  );
}

